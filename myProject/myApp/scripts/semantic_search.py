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
    download_drive_file,  # ✅ Updated import
    get_latest_file_by_prefix
)
from myApp.scripts.embedding_utils import embed_text, build_prompt

# 🔄 Load .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 📁 Temp paths (used at runtime)
TMP_DIR = Path(tempfile.gettempdir())
INDEX_PATH = TMP_DIR / "thesis_index.faiss"
METADATA_PATH = TMP_DIR / "metadata.json"

# 🔍 Semantic Search from FAISS + Metadata
def search_similar_chunks(index_path, metadata_path, question_vector, top_k=5):
    index = faiss.read_index(str(index_path))
    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    D, I = index.search(np.array([question_vector]), top_k)
    return [metadata[i] for i in I[0] if i < len(metadata)]

# 🤖 Main Query Handler
def answer_query(query: str) -> str:
    print(f"🤖 Received query: {query}")
    try:
        # ➕ Turn query into a vector
        question_vector = np.array(embed_text(query), dtype=np.float32)

        # ⬇ Download from Drive if not locally cached
        if not INDEX_PATH.exists() or not METADATA_PATH.exists():
            print("⬇️ Missing local vector files. Fetching from Drive...")
            service = load_drive_service()

            faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
            meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

            if not faiss_id or not meta_id:
                raise Exception("❌ Required vector files not found on Drive.")

            faiss_url = f"https://drive.google.com/file/d/{faiss_id}/view"
            meta_url = f"https://drive.google.com/file/d/{meta_id}/view"

            faiss_path = download_drive_file(faiss_url, suffix=".faiss")
            meta_path = download_drive_file(meta_url, suffix=".json")
        else:
            faiss_path = INDEX_PATH
            meta_path = METADATA_PATH

        # 🔍 Run search
        similar_chunks = search_similar_chunks(faiss_path, meta_path, question_vector, top_k=5)
        prompt = build_prompt(similar_chunks, query) if similar_chunks else f"Answer this question:\n\n{query}"

    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")
        prompt = f"Answer this question as best as you can:\n\n{query}"

    # 🧠 OpenAI Answer
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful academic mentor. Keep responses practical and student-friendly. "
                        "Avoid jargon unless necessary. Be clear, concise, and empowering."
                    )
                },
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"❌ OpenAI API error: {e}")
        return "Sorry, I couldn’t process that question right now. Please try again later."
