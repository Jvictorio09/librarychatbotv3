import os, json, tempfile, faiss
import numpy as np
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv
from myApp.scripts.vector_cache import load_drive_service, download_drive_file, get_latest_file_by_prefix
from myApp.scripts.embedding_utils import embed_text, build_prompt

# 🔒 Load environment
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 🗂️ Temporary file paths
TMP_DIR = Path(tempfile.gettempdir())
INDEX_PATH = TMP_DIR / "thesis_index.faiss"
METADATA_PATH = TMP_DIR / "metadata.json"

# 🔍 Similarity search in FAISS index
def search_similar_chunks(index_path, metadata_path, question_vector, top_k=5):
    index = faiss.read_index(str(index_path))
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    D, I = index.search(np.array([question_vector]), top_k)
    return [metadata[i] for i in I[0] if i < len(metadata)]

# 🧠 Condensed memory summarization
def summarize_messages(messages):
    last_msgs = messages[-4:]
    combined = "\n\n".join([f"{m['role']}: {m['content']}" for m in last_msgs])
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Summarize the following conversation in 1 paragraph."},
            {"role": "user", "content": combined}
        ]
    )
    return response.choices[0].message.content.strip()

# 💬 Main query handler
def answer_query(query, session_history):
    global INDEX_PATH, METADATA_PATH  # 👈 Fix for scoping error

    try:
        # Convert user query to embedding
        question_vector = np.array(embed_text(query), dtype=np.float32)

        # Ensure index + metadata are loaded
        if not INDEX_PATH.exists() or not METADATA_PATH.exists():
            service = load_drive_service()
            faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
            meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

            if not faiss_id or not meta_id:
                raise Exception("❌ Required vector files not found on Drive.")

            INDEX_PATH = download_drive_file(f"https://drive.google.com/file/d/{faiss_id}/view", suffix=".faiss")
            METADATA_PATH = download_drive_file(f"https://drive.google.com/file/d/{meta_id}/view", suffix=".json")

        # Vector search
        chunks = search_similar_chunks(INDEX_PATH, METADATA_PATH, question_vector)
        prompt = build_prompt(chunks, query) if chunks else f"Answer this question:\n\n{query}"

    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")
        prompt = f"Answer this question as best as you can:\n\n{query}"

    # Initialize memory if needed
    if session_history is None:
        session_history = []

    messages = [{"role": "system", "content": "You are a helpful academic mentor."}] + session_history
    messages.append({"role": "user", "content": prompt})

    # ✨ OpenAI call
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    reply = response.choices[0].message.content.strip()

    # Update memory
    session_history.append({"role": "user", "content": query})
    session_history.append({"role": "assistant", "content": reply})

    # 🔄 Summarize if memory too long
    if len(session_history) >= 8:
        summary = summarize_messages(session_history[-8:])
        session_history = session_history[:-8] + [{"role": "system", "content": f"Summary: {summary}"}]

    return reply, session_history
