import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def embed_text(text):
    """
    Generate a text embedding using OpenAI.
    """
    try:
        response = client.embeddings.create(
            model="text-embedding-ada-002",
            input=[text]
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"⚠️ Embedding error: {e}")
        return [0.0] * 1536  # Safe fallback (zero vector)
