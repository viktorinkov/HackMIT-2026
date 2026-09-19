_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 150
_MIN_CHUNK_CHARS = 80


def chunk_markdown(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    if len(cleaned) < _MIN_CHUNK_CHARS:
        return []
    if len(cleaned) <= _CHUNK_SIZE:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + _CHUNK_SIZE, len(cleaned))
        piece = cleaned[start:end].strip()
        if len(piece) >= _MIN_CHUNK_CHARS:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start = end - _CHUNK_OVERLAP
    return chunks
