"""Pure segment→chunk windowing — ported from app/ingest embed stage.
Groups consecutive segments into fixed-size windows for embedding."""


def chunk_segments(segments, chunk_size):
    """Window ``segments`` (objects with .text/.start/.end) into groups of ``chunk_size``.
    Returns [(joined_text, start, end)] preserving the first/last timecodes of each window."""
    chunks = []
    for i in range(0, len(segments), chunk_size):
        grp = segments[i:i + chunk_size]
        chunks.append((" ".join(x.text for x in grp), grp[0].start, grp[-1].end))
    return chunks
