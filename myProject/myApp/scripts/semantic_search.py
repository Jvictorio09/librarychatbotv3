import os
import json
import tempfile
import faiss
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

from myApp.scripts.vector_cache import (
    load_drive_service,
    download_drive_file,
    get_latest_file_by_prefix  # ✅ Make sure this exists in vector_cache.py
)
from myApp.scripts.embedding_utils import embed_text, build_prompt

# 🔄 Load environment
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 📁 Temp paths
TMP_DIR = Path(tempfile.gettempdir())
INDEX_PATH = TMP_DIR / "thesis_index.faiss"
METADATA_PATH = TMP_DIR / "metadata.json"

# 🔍 FAISS Search
def search_similar_chunks(index_path, metadata_path, question_vector, top_k=5):
    index = faiss.read_index(str(index_path))
    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    D, I = index.search(np.array([question_vector]), top_k)
    return [metadata[i] for i in I[0] if i < len(metadata)]

def answer_query(query: str) -> str:
    print(f"🤖 Received query: {query}")
    try:
        question_vector = np.array(embed_text(query), dtype=np.float32)

        # Download vector files if missing
        if not INDEX_PATH.exists() or not METADATA_PATH.exists():
            print("⬇️ Vector store not found. Downloading from Drive...")
            service = load_drive_service()

            faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
            json_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

            if not faiss_id or not json_id:
                raise Exception("Missing required vector or metadata file from Google Drive.")

            faiss_path = download_drive_file(service, faiss_id, ".faiss")
            metadata_path = download_drive_file(service, json_id, ".json")
        else:
            faiss_path = INDEX_PATH
            metadata_path = METADATA_PATH

        # Search for relevant chunks
        similar_chunks = search_similar_chunks(faiss_path, metadata_path, question_vector, top_k=5)
        prompt = build_prompt(similar_chunks, query) if similar_chunks else f"Answer this question:\n\n{query}"

    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")
        prompt = f"Answer this question as best as you can:\n\n{query}"

    # Call OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful, smart academic mentor. Keep your tone practical and warm. "
                        "Avoid academic jargon unless needed. Always aim to guide the student forward."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"❌ OpenAI API error: {e}")
        return "Oops, I couldn’t process your question right now. Please try again soon."
