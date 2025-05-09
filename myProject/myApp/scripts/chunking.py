import textwrap

def chunk_text(text, max_tokens=500, overlap=50):
    """
    Splits text into overlapping chunks based on word count.
    This is not exact token count, but good enough for embeddings.
    """
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + max_tokens
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += max_tokens - overlap

    return [chunk.strip() for chunk in chunks if chunk.strip()]
