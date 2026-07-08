"""Pure background-music mixer and catalog — no I/O, deterministic. Coverage target: 100%.

A8: Builds ffmpeg filtergraph strings that mix a background-music track under the
primary audio with sidechain ducking (sidechaincompress) or simple volume automation,
plus loudnorm normalisation to -14 LUFS.  Also provides a typed music catalog
interface for track lookup/filter by genre.

No subprocess calls here.  All execution lives in adapters/.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Music catalog
# ---------------------------------------------------------------------------


@dataclass
class MusicTrack:
    """A catalog entry for a background-music asset.

    Args:
        track_id: Unique string identifier (e.g. ``"upbeat_01"``).
        genre:    Genre tag (e.g. ``"upbeat"``, ``"calm"``, ``"cinematic"``).
        path:     Filesystem or GCS path to the audio file.  The file is an
                  external asset — this module never reads it.
        duration: Track duration in seconds (0.0 = unknown).
        title:    Optional human-readable title.
    """

    track_id: str
    genre: str
    path: str
    duration: float = 0.0
    title: str = ""


@dataclass
class MusicCatalog:
    """An in-memory catalog of :class:`MusicTrack` entries.

    Tracks are referenced by path/id at render time; actual audio files are
    external assets managed outside this module.
    """

    tracks: list[MusicTrack] = field(default_factory=list)

    def add(self, track: MusicTrack) -> None:
        """Add a track to the catalog."""
        self.tracks.append(track)

    def lookup(self, track_id: str) -> Optional[MusicTrack]:
        """Return the track with *track_id*, or ``None`` if not found."""
        for t in self.tracks:
            if t.track_id == track_id:
                return t
        return None

    def filter_by_genre(self, genre: str) -> list[MusicTrack]:
        """Return all tracks whose ``genre`` exactly matches *genre*."""
        return [t for t in self.tracks if t.genre == genre]

    def all_genres(self) -> list[str]:
        """Return a sorted, deduplicated list of genres in the catalog."""
        return sorted({t.genre for t in self.tracks})


# ---------------------------------------------------------------------------
# Filtergraph builders
# ---------------------------------------------------------------------------

# Default music input index when building a two-input (primary, music) graph.
_MUSIC_INPUT_IDX = 1
_PRIMARY_INPUT_IDX = 0


def build_music_mix_filter(
    *,
    music_gain_db: float = -12.0,
    duck: bool = True,
    target_lufs: float = -14.0,
    primary_stream: str = "0:a",
    music_stream: str = "1:a",
) -> str:
    """Return a ``-filter_complex`` value that mixes background music under primary audio.

    The filtergraph:

    1. Attenuates the music track by *music_gain_db* dB (negative = quieter).
    2. When *duck* is True, applies ``sidechaincompress`` so the music dips
       whenever the primary audio is present (the primary stream is the sidechain
       key; the attenuated music is the sidechain input).
    3. Mixes the (ducked or flat) music with the primary audio via ``amix``.
    4. Normalises the result to *target_lufs* LUFS via ``loudnorm``.

    The caller must pass the primary audio as ``-i primary.mp4`` (input 0) and
    the music file as ``-i music.mp3`` (input 1), then map ``[mixout]``.

    Args:
        music_gain_db:  Initial music attenuation in dB (default ``-12.0``).
        duck:           Apply sidechain ducking (default ``True``).
        target_lufs:    Final loudnorm target LUFS (default ``-14.0``).
        primary_stream: ffmpeg stream specifier for the primary audio (default ``"0:a"``).
        music_stream:   ffmpeg stream specifier for the music track (default ``"1:a"``).

    Returns:
        A ``-filter_complex`` string; pass it to ffmpeg as the value of
        ``-filter_complex``.
    """
    parts: list[str] = []

    # Step 1 — attenuate music
    parts.append(f"[{music_stream}]volume={music_gain_db:.1f}dB[music_att]")

    if duck:
        # Step 2 — sidechain compress: primary is the key; music_att is the input.
        # threshold=-20dB triggers ducking when vocals are present; ratio=4 is a
        # noticeable but not harsh duck; attack/release smooth the envelope.
        parts.append(
            f"[music_att][{primary_stream}]sidechaincompress="
            "threshold=-20dB:ratio=4:attack=200:release=1000[music_ducked]"
        )
        mix_music_label = "music_ducked"
    else:
        mix_music_label = "music_att"

    # Step 3 — mix primary + music; weights=1 1 keeps both at unity after step 1
    parts.append(
        f"[{primary_stream}][{mix_music_label}]amix=inputs=2:duration=first:weights=1 1[mixed]"
    )

    # Step 4 — loudnorm final mix
    parts.append(
        f"[mixed]loudnorm=I={target_lufs:.1f}:LRA=11:TP=-1.5[mixout]"
    )

    return ";".join(parts)


def build_music_mix_cmd(
    primary_path: str,
    music_path: str,
    out_path: str,
    *,
    music_gain_db: float = -12.0,
    duck: bool = True,
    target_lufs: float = -14.0,
) -> list[str]:
    """Return a full ffmpeg arg list for background-music mixing.

    Args:
        primary_path:  Path to the primary video/audio file (input 0).
        music_path:    Path to the music file (input 1).
        out_path:      Destination file path.
        music_gain_db: Music attenuation in dB.
        duck:          Apply sidechain ducking.
        target_lufs:   Final loudnorm target.

    Returns:
        A ``list[str]`` suitable for ``subprocess.run(..., shell=False)``.
    """
    import os  # noqa: PLC0415

    ffmpeg = os.getenv("FFMPEG_BIN", "ffmpeg")
    fc = build_music_mix_filter(
        music_gain_db=music_gain_db,
        duck=duck,
        target_lufs=target_lufs,
    )
    return [
        ffmpeg, "-y",
        "-i", primary_path,
        "-i", music_path,
        "-filter_complex", fc,
        "-map", "0:v?",         # pass through video if present
        "-map", "[mixout]",
        "-c:v", "copy",
        out_path,
    ]
