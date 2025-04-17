import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
EMBEDDING_MODEL = "text-embedding-ada-002"

def embed_text(text: str):
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding

def chunk_text(text, max_tokens=500):
    paragraphs = text.split("\n")
    chunks, current = [], []
    for p in paragraphs:
        if len(" ".join(current + [p])) < max_tokens * 4:  # 1 token ≈ 4 chars
            current.append(p)
        else:
            chunks.append(" ".join(current))
            current = [p]
    if current:
        chunks.append(" ".join(current))
    return chunks

def build_prompt(context_chunks, question):
    context_texts = "\n\n".join(
        f"[{chunk['program']}, {chunk['year']} - {chunk['title']}]\n{chunk['chunk']}"
        for chunk in context_chunks
    )
    return (
        f"You are a helpful academic assistant. Use the following thesis excerpts to answer the student's question.\n\n"
        f"{context_texts}\n\n"
        f"Question: {question}\n\n"
        f"Answer:"
    )
