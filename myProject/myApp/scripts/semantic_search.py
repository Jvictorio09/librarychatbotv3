import os, json, tempfile, faiss, fitz
import numpy as np
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv
from myApp.scripts.vector_cache import load_drive_service, download_drive_file, get_latest_file_by_prefix
from myApp.scripts.embedding_utils import embed_text

# 🔒 Load environment
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 🗂️ Temporary file paths
TMP_DIR = Path(tempfile.gettempdir())
INDEX_PATH = TMP_DIR / "thesis_index.faiss"
METADATA_PATH = TMP_DIR / "metadata.json"

# 📄 PDF text extraction using PyMuPDF
def extract_text_from_pdf(file_path):
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text.strip()

# 🔍 Similarity search in FAISS index
def search_similar_chunks(index_path, metadata_path, question_vector, top_k=5):
    index = faiss.read_index(str(index_path))
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    D, I = index.search(np.array([question_vector]), top_k)
    return [metadata[i] for i in I[0] if i < len(metadata)]

# 📚 Chunk text into manageable pieces
def chunk_text(text, chunk_size=500, overlap=50):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks

# 📜 Flexible prompt builder (supports both string and dict chunks)
def build_prompt(chunks, query):
    if isinstance(chunks[0], dict) and "text" in chunks[0]:
        joined = "\n\n".join(chunk["text"] for chunk in chunks)
    else:
        joined = "\n\n".join(chunks)

    return f"You are a helpful academic assistant.\n\nContext:\n{joined}\n\nQuestion: {query}"

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

# 💬 Main query handler (now with optional uploaded_text OR file_path)
def answer_query(query, session_history, uploaded_text=None, uploaded_file_path=None):
    global INDEX_PATH, METADATA_PATH
    chunks = []

    try:
        # 🧠 Prioritize uploaded file
        if uploaded_file_path and uploaded_file_path.endswith(".pdf"):
            uploaded_text = extract_text_from_pdf(uploaded_file_path)

        if uploaded_text:
            temp_chunks = chunk_text(uploaded_text)
            temp_embeddings = [embed_text(c) for c in temp_chunks]
            query_vector = embed_text(query)

            # Cosine similarity ranking
            similarities = [
                (i, np.dot(query_vector, vec)) for i, vec in enumerate(temp_embeddings)
            ]
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_matches = similarities[:5]
            chunks = [temp_chunks[i] for i, _ in top_matches]

        # 📂 Fallback to shared FAISS index if no uploaded data
        if not chunks:
            if not INDEX_PATH.exists() or not METADATA_PATH.exists():
                service = load_drive_service()
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

                if not faiss_id or not meta_id:
                    raise Exception("❌ Required vector files not found on Drive.")

                INDEX_PATH = download_drive_file(f"https://drive.google.com/file/d/{faiss_id}/view", suffix=".faiss")
                METADATA_PATH = download_drive_file(f"https://drive.google.com/file/d/{meta_id}/view", suffix=".json")

            question_vector = np.array(embed_text(query), dtype=np.float32)
            chunks = search_similar_chunks(INDEX_PATH, METADATA_PATH, question_vector)

        # 🧠 Build prompt
        prompt = build_prompt(chunks, query) if chunks else f"Answer this question:\n\n{query}"

    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")
        prompt = f"Answer this question as best as you can:\n\n{query}"

    # 🧠 Maintain memory
    if session_history is None:
        session_history = []

    messages = [{"role": "system", "content": "You are a helpful academic mentor."}] + session_history
    messages.append({"role": "user", "content": prompt})

    # ✨ Generate response
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    reply = response.choices[0].message.content.strip()

    # 🧠 Update memory
    session_history.append({"role": "user", "content": query})
    session_history.append({"role": "assistant", "content": reply})

    # 🔄 Condense memory if needed
    if len(session_history) >= 8:
        summary = summarize_messages(session_history[-8:])
        session_history = session_history[:-8] + [{"role": "system", "content": f"Summary: {summary}"}]

    return reply, session_history
