"""Pure hybrid-retrieval scoring — ported verbatim from app/retrieval.hybrid_search.
No DB/embedding I/O here; callers fetch rows then hand them to rank()."""


def link(video_id, start):
    """Deep-link into a YouTube video at a timecode (the AIO-critical citation field)."""
    return f"https://youtu.be/{video_id}?t={int(start)}"


def rank(vec_hits, lex_chunks, graph_video_ids, k=8):
    """Merge vector + lexical + Content-Graph signals into a ranked list.

    vec_hits:          list of (chunk, similarity) from the vector store.
    lex_chunks:        list of chunks whose text matched the query (lexical).
    graph_video_ids:   set of video_ids that had a matching Content-Graph node.
    Returns the top-k [(chunk, score)] descending. Chunks need .id and .video_id.
    """
    scored = {}
    for ch, sim in vec_hits:
        scored[ch.id] = [ch, sim]
    for ch in lex_chunks:                       # lexical boost (keyword match)
        if ch.id in scored:
            scored[ch.id][1] += 0.15
        else:
            scored[ch.id] = [ch, 0.5]
    for entry in scored.values():               # graph boost (video has a matching key point)
        if entry[0].video_id in graph_video_ids:
            entry[1] += 0.1
    ranked = sorted(scored.values(), key=lambda x: -x[1])[:k]
    return [(c, sc) for c, sc in ranked]
