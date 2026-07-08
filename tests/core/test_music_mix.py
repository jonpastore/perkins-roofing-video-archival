"""100% line-coverage tests for core.music_mix (A8).

Covers:
  - MusicTrack dataclass fields
  - MusicCatalog: add, lookup (found + not found), filter_by_genre, all_genres
  - build_music_mix_filter: duck=True, duck=False, custom gain, custom LUFS,
    custom stream specifiers, output label present
  - build_music_mix_cmd: list type, elements are strings, both paths present,
    filter_complex present, video passthrough map, mixout map, no shell string
"""
from __future__ import annotations

import core.music_mix as mm


# ---------------------------------------------------------------------------
# MusicTrack
# ---------------------------------------------------------------------------


class TestMusicTrack:
    def test_fields_stored(self) -> None:
        t = mm.MusicTrack(
            track_id="upbeat_01",
            genre="upbeat",
            path="/assets/music/upbeat_01.mp3",
            duration=120.5,
            title="Rise Up",
        )
        assert t.track_id == "upbeat_01"
        assert t.genre == "upbeat"
        assert t.path == "/assets/music/upbeat_01.mp3"
        assert t.duration == 120.5
        assert t.title == "Rise Up"

    def test_default_duration_and_title(self) -> None:
        t = mm.MusicTrack(track_id="x", genre="calm", path="/a/b.mp3")
        assert t.duration == 0.0
        assert t.title == ""


# ---------------------------------------------------------------------------
# MusicCatalog
# ---------------------------------------------------------------------------


class TestMusicCatalog:
    def _catalog(self) -> mm.MusicCatalog:
        cat = mm.MusicCatalog()
        cat.add(mm.MusicTrack("t1", "upbeat", "/a.mp3", 60.0, "Track 1"))
        cat.add(mm.MusicTrack("t2", "calm", "/b.mp3", 90.0, "Track 2"))
        cat.add(mm.MusicTrack("t3", "upbeat", "/c.mp3", 45.0, "Track 3"))
        return cat

    def test_add_and_lookup_found(self) -> None:
        cat = self._catalog()
        t = cat.lookup("t2")
        assert t is not None
        assert t.track_id == "t2"
        assert t.genre == "calm"

    def test_lookup_not_found_returns_none(self) -> None:
        cat = self._catalog()
        assert cat.lookup("nonexistent") is None

    def test_filter_by_genre_returns_matching(self) -> None:
        cat = self._catalog()
        results = cat.filter_by_genre("upbeat")
        assert len(results) == 2
        ids = {r.track_id for r in results}
        assert ids == {"t1", "t3"}

    def test_filter_by_genre_no_match_returns_empty(self) -> None:
        cat = self._catalog()
        assert cat.filter_by_genre("cinematic") == []

    def test_all_genres_sorted_deduplicated(self) -> None:
        cat = self._catalog()
        genres = cat.all_genres()
        assert genres == ["calm", "upbeat"]

    def test_all_genres_empty_catalog(self) -> None:
        cat = mm.MusicCatalog()
        assert cat.all_genres() == []

    def test_catalog_starts_empty(self) -> None:
        cat = mm.MusicCatalog()
        assert cat.tracks == []


# ---------------------------------------------------------------------------
# build_music_mix_filter — duck=True (default)
# ---------------------------------------------------------------------------


class TestBuildMusicMixFilterDuck:
    def test_returns_string(self) -> None:
        f = mm.build_music_mix_filter()
        assert isinstance(f, str)

    def test_contains_volume_attenuation(self) -> None:
        f = mm.build_music_mix_filter(music_gain_db=-12.0)
        assert "volume=-12.0dB" in f

    def test_contains_sidechaincompress_when_duck_true(self) -> None:
        f = mm.build_music_mix_filter(duck=True)
        assert "sidechaincompress" in f

    def test_sidechaincompress_not_present_when_duck_false(self) -> None:
        f = mm.build_music_mix_filter(duck=False)
        assert "sidechaincompress" not in f

    def test_amix_present(self) -> None:
        f = mm.build_music_mix_filter()
        assert "amix" in f

    def test_loudnorm_present(self) -> None:
        f = mm.build_music_mix_filter()
        assert "loudnorm" in f

    def test_loudnorm_default_lufs(self) -> None:
        f = mm.build_music_mix_filter(target_lufs=-14.0)
        assert "I=-14.0" in f

    def test_loudnorm_custom_lufs(self) -> None:
        f = mm.build_music_mix_filter(target_lufs=-16.0)
        assert "I=-16.0" in f

    def test_mixout_label_present(self) -> None:
        f = mm.build_music_mix_filter()
        assert "[mixout]" in f

    def test_custom_gain(self) -> None:
        f = mm.build_music_mix_filter(music_gain_db=-6.0)
        assert "volume=-6.0dB" in f

    def test_lra_and_tp(self) -> None:
        f = mm.build_music_mix_filter()
        assert "LRA=11" in f
        assert "TP=-1.5" in f

    def test_custom_stream_specifiers(self) -> None:
        f = mm.build_music_mix_filter(primary_stream="0:a:0", music_stream="2:a")
        assert "2:a" in f
        assert "0:a:0" in f

    def test_semicolon_separated_parts(self) -> None:
        f = mm.build_music_mix_filter()
        # Multiple filter nodes separated by semicolons
        assert ";" in f


# ---------------------------------------------------------------------------
# build_music_mix_filter — duck=False
# ---------------------------------------------------------------------------


class TestBuildMusicMixFilterNoDuck:
    def test_music_att_label_used_in_amix(self) -> None:
        f = mm.build_music_mix_filter(duck=False)
        # music_att goes directly into amix — music_ducked should not appear
        assert "music_ducked" not in f
        assert "music_att" in f

    def test_amix_inputs_two(self) -> None:
        f = mm.build_music_mix_filter(duck=False)
        assert "amix=inputs=2" in f


# ---------------------------------------------------------------------------
# build_music_mix_cmd
# ---------------------------------------------------------------------------


class TestBuildMusicMixCmd:
    def test_returns_list(self) -> None:
        cmd = mm.build_music_mix_cmd("primary.mp4", "music.mp3", "out.mp4")
        assert isinstance(cmd, list)

    def test_all_elements_strings(self) -> None:
        cmd = mm.build_music_mix_cmd("primary.mp4", "music.mp3", "out.mp4")
        assert all(isinstance(x, str) for x in cmd)

    def test_primary_path_in_cmd(self) -> None:
        cmd = mm.build_music_mix_cmd("/a/primary.mp4", "/b/music.mp3", "/c/out.mp4")
        assert "/a/primary.mp4" in cmd

    def test_music_path_in_cmd(self) -> None:
        cmd = mm.build_music_mix_cmd("/a/primary.mp4", "/b/music.mp3", "/c/out.mp4")
        assert "/b/music.mp3" in cmd

    def test_out_path_is_last(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4")
        assert cmd[-1] == "out.mp4"

    def test_filter_complex_flag(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4")
        assert "-filter_complex" in cmd

    def test_mixout_map(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4")
        assert "[mixout]" in cmd

    def test_video_passthrough_map(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4")
        assert "0:v?" in cmd

    def test_overwrite_flag(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4")
        assert "-y" in cmd

    def test_no_shell_injection(self) -> None:
        """Paths with shell metacharacters appear as a single token."""
        cmd = mm.build_music_mix_cmd("p.mp4 && rm -rf /", "m.mp3", "out.mp4")
        assert "p.mp4 && rm -rf /" in cmd

    def test_duck_false_propagated(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4", duck=False)
        fc_idx = cmd.index("-filter_complex")
        fc_val = cmd[fc_idx + 1]
        assert "sidechaincompress" not in fc_val

    def test_custom_gain_propagated(self) -> None:
        cmd = mm.build_music_mix_cmd("p.mp4", "m.mp3", "out.mp4", music_gain_db=-6.0)
        fc_idx = cmd.index("-filter_complex")
        fc_val = cmd[fc_idx + 1]
        assert "volume=-6.0dB" in fc_val
