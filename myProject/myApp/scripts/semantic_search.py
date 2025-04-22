import os, json, tempfile, faiss, fitz, re
import numpy as np
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv
from myApp.scripts.vector_cache import load_drive_service, download_drive_file, get_latest_file_by_prefix
from myApp.scripts.embedding_utils import embed_text
from myApp.models import Thesis

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Temporary file paths
TMP_DIR = Path(tempfile.gettempdir())
INDEX_PATH = TMP_DIR / "thesis_index.faiss"
METADATA_PATH = TMP_DIR / "metadata.json"

# Extract text from PDF
def extract_text_from_pdf(file_path):
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text.strip()

# Extract reference info
def extract_reference(text):
    match = re.search(r"(?:titled|paper)\s[\"']?(.+?)[\"']?\sby\s(.+?)(?:\.|,|\s|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, None

# FAISS search
def search_similar_chunks(index_path, metadata_path, question_vector, top_k=8):
    index = faiss.read_index(str(index_path))
    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    D, I = index.search(np.array([question_vector]), top_k)
    results = []

    for dist, idx in zip(D[0], I[0]):
        if idx < len(metadata):
            chunk = metadata[idx]
            text = chunk.get("text", "")
            title = chunk.get("title")
            author = chunk.get("author")
            if not (title and author):
                title_from_text, author_from_text = extract_reference(text)
                title = title or title_from_text
                author = author or author_from_text

            thesis_obj = Thesis.objects.filter(title__iexact=title.strip() if title else None, year=chunk.get("year")).first()

            results.append({
                "text": text,
                "source": chunk.get("source", "library"),
                "distance": float(dist),
                "title": title,
                "author": author,
                "program": chunk.get("program"),
                "year": chunk.get("year"),
                "gdrive_url": getattr(thesis_obj, 'gdrive_url', None) if thesis_obj else None,
                "hash": hash(text.strip())
            })

    return results

def build_prompt(chunks, query):
    joined = "\n\n".join(chunk["text"] if isinstance(chunk, dict) else str(chunk) for chunk in chunks)
    return (
        f"You are a helpful academic assistant. Infer meaning beyond literal words. "
        f"Think conceptually and semantically. Use thesis excerpts even if they are only loosely related to the user’s query."
        f"\n\nContext:\n{joined}\n\nQuestion: {query}"
    )

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

def chunk_text(text, chunk_size=500, overlap=50):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks

from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def is_followup_question_llm(query, session_history):
    if not session_history:
        return False

    # Extract last user and assistant messages to give GPT full context
    last_user = next((m["content"] for m in reversed(session_history) if m["role"] == "user"), "")
    last_assistant = next((m["content"] for m in reversed(session_history) if m["role"] == "assistant"), "")

    prompt = [
        {
            "role": "system",
            "content": (
                "You're a smart classifier. Your task is to detect whether a user's new question is a follow-up to the ongoing topic. "
                "Only answer 'yes' or 'no'. A follow-up continues the same subject, refers to a previous reply, or asks for elaboration."
            )
        },
        {"role": "user", "content": f"Previous user message: {last_user}"},
        {"role": "assistant", "content": f"AI reply: {last_assistant}"},
        {"role": "user", "content": f"New message: {query}"}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=prompt,
            temperature=0
        )
        result = response.choices[0].message.content.strip().lower()
        return result.startswith("yes")
    except Exception as e:
        print(f"⚠️ Follow-up classifier failed: {e}")
        return False


def get_last_cited_thesis(session_history):
    for msg in reversed(session_history):
        if isinstance(msg, dict) and msg.get("title"):
            return msg
    return None

def sanitize_title(title):
    import re
    return re.sub(r'[^\w\s]', '', title or "").strip().lower()
def answer_query(query, session_history, uploaded_text=None, uploaded_file_path=None, gdrive_url=None):
    global INDEX_PATH, METADATA_PATH
    chunks = []
    file_scanned = False

    try:
        # 🎯 Load directly from Drive if "Load this File" was clicked
        if gdrive_url:
            print(f"📄 Downloading and scanning from Drive: {gdrive_url}")
            downloaded_path = download_drive_file(gdrive_url, suffix=".pdf")
            uploaded_file_path = downloaded_path
            uploaded_text = extract_text_from_pdf(downloaded_path)
            print("📎 Extracted text from GDrive PDF.")

        if uploaded_file_path and uploaded_file_path.endswith(".pdf"):
            uploaded_text = extract_text_from_pdf(uploaded_file_path)
            print("📎 Extracted text from uploaded PDF.")

        if uploaded_text:
            temp_chunks = chunk_text(uploaded_text)
            temp_embeddings = [embed_text(c) for c in temp_chunks]
            query_vector = embed_text(query)
            similarities = sorted(
                [(i, np.dot(query_vector, vec)) for i, vec in enumerate(temp_embeddings)],
                key=lambda x: x[1], reverse=True
            )
            top_matches = similarities[:5]
            chunks = [{"text": temp_chunks[i], "source": "uploaded"} for i, _ in top_matches]

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

    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")

    if session_history is None:
        session_history = []

    is_followup = is_followup_question_llm(query, session_history)
    last_cited = get_last_cited_thesis(session_history)

    # 🧠 Check if the follow-up is still relevant
    if is_followup and last_cited:
        related = is_question_still_related(query, last_cited.get("title"))
        if not related:
            print("🔄 Topic has changed — moving on from previously loaded thesis.")
            last_cited = None
            is_followup = False

    # 🔁 Load previous thesis if still relevant
    if is_followup and last_cited:
        gdrive_url = last_cited.get("gdrive_url")
        if gdrive_url:
            try:
                pdf_path = download_drive_file(gdrive_url, suffix=".pdf")
                full_text = extract_text_from_pdf(pdf_path)
                temp_chunks = chunk_text(full_text)
                chunks = [{"text": c, "title": last_cited["title"]} for c in temp_chunks]
                file_scanned = True
                print(f"📖 Loaded {len(temp_chunks)} chunks from thesis PDF")
            except Exception as e:
                print(f"⚠️ Failed to scan thesis from Drive: {e}")

    # 🧠 Prompting logic
    prompt = (
        f"You are continuing the discussion based on the thesis titled '{last_cited['title']}'. "
        f"Use only the information from that thesis. If something is not directly mentioned, explain so and offer a likely possibility.\n\nQuestion: {query}"
        if is_followup and last_cited else
        build_prompt(chunks, query) if chunks else
        f"Answer this question:\n\n{query}"
    )

    messages = [{"role": "system", "content": (
        "You are a helpful academic mentor. Respond with relevant insights, infer missing details only when needed, and cite specific sources when possible."
    )}] + session_history + [{"role": "user", "content": prompt}]

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    reply = response.choices[0].message.content.strip()

    # 🔁 Append session memory with updated context
    if is_followup and last_cited:
        session_history.append({
            "role": "assistant",
            "content": reply,
            "title": last_cited.get("title"),
            "year": last_cited.get("year"),
            "program": last_cited.get("program"),
            "gdrive_url": last_cited.get("gdrive_url"),
        })
    else:
        seen = set()
        citations = []
        for c in chunks:
            key = (c.get("title"), c.get("year"))
            if key in seen or not c.get("title"):
                continue
            seen.add(key)
            title = c["title"]
            author = c.get("author", "Unknown")
            program = c.get("program", "Unknown Program")
            year = c.get("year", "Unknown Year")
            gdrive_url = c.get("gdrive_url")
            drive_link = f"\n🔗 [View File]({gdrive_url})" if gdrive_url else ""
            button = f"\n<button class='load-file-btn' data-url='{gdrive_url}'>📥 Load this file</button>" if gdrive_url else ""
            citations.append(f"📁 Title: \"{title}\"\n📚 {program} ({year}){drive_link}{button}")

        if citations:
            reply += (
                "\n\n🔍 Here are some projects that might inspire you:\n\n" +
                "\n\n".join(citations[:3])
            )
        if chunks:
            reply += "\n\n💬 Would you like to explore more?"

        session_history.append({"role": "assistant", "content": reply})
        session_history.append({"role": "user", "content": query})

    # 🧼 Summarize long sessions
    if len(session_history) >= 8:
        summary = summarize_messages(session_history[-8:])
        session_history = session_history[:-8] + [{"role": "system", "content": f"Summary: {summary}"}]

    return reply, session_history, file_scanned
