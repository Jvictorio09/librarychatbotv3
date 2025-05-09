import os, json, re, tempfile, faiss, fitz
import numpy as np
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from django.db.models import Q
from myApp.models import Thesis
from myApp.scripts.vector_cache import download_drive_file
from myApp.scripts.embedding_utils import embed_text

# 🔐 Load OpenAI key
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ⏳ Temp paths for FAISS/metadata
TMP_DIR = Path(tempfile.gettempdir())
INDEX_PATH = TMP_DIR / "thesis_index.faiss"
METADATA_PATH = TMP_DIR / "metadata.json"

# 📘 PDF Text Extractor
def extract_text_from_pdf(file_path):
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text.strip()

# 🔤 Normalize titles
def normalize_title(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())

# 📎 Keyword extractor
def extract_keywords(text):
    return re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())

# 🧠 Prompt builder
def build_prompt(chunks, query, max_tokens=3000):
    total_chars, limited_chunks = 0, []
    for c in chunks:
        text = c.get("text", "")
        if isinstance(c, dict) and text:
            total_chars += len(text)
            if total_chars > max_tokens * 4:
                break
            limited_chunks.append(text.strip())
    joined = "\n\n".join(f"Excerpt: {text}" for text in limited_chunks)
    return (
        f"You are KaAI, an academic assistant who helps students using thesis data. Use only the excerpts below.\n\n{joined}\n\nUser's Question: {query}"
    )

# 🧭 Smart classifier
def classify_query_type(query):
    prompt = f"What type of question is this: '{query}'?\nOptions: author_lookup, topic_search, method_question, general_info"
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# 🎯 Main Query Handler
def answer_query(query, session_history, uploaded_text=None, uploaded_file_path=None, gdrive_url=None):
    chunks = []
    file_scanned = False
    debug_source = "unknown"

    try:
        query_type = classify_query_type(query)
        print(f"🎯 Detected Query Type: {query_type}")

        # 1️⃣ Author Lookup
        if query_type == "author_lookup":
            cleaned = re.sub(r"(who\s+is\s+the\s+author\s+of|author\s+of)", "", query.lower()).strip()
            all_titles = Thesis.objects.values("title", "authors", "program__name", "year", "gdrive_url")
            for m in all_titles:
                if normalize_title(m["title"]) == normalize_title(cleaned):
                    debug_source = "database_exact"
                    return (
                        f'The author of "{m["title"]}" is **{m["authors"]}**. 📁 Found in {m["program__name"]} ({m["year"]})'
                        + (f'. [📄 View File]({m["gdrive_url"]})' if m.get("gdrive_url") else "")
                        + f"\n\n🧠 Source: {debug_source}",
                        session_history,
                        file_scanned
                    )

        # 2️⃣ Topic Lookup
        if query_type in ["topic_search", "general_info"]:
            matches = Thesis.objects.filter(
                Q(title__icontains=query) | Q(abstract__icontains=query)
            ).values("title", "authors", "program__name", "year", "gdrive_url")[:30]
            for m in matches:
                chunks.append({
                    "title": m["title"],
                    "author": m["authors"],
                    "program": m["program__name"],
                    "year": m["year"],
                    "gdrive_url": m["gdrive_url"],
                    "text": f"{m['title']} by {m['authors']} ({m['year']})"
                })
            if chunks:
                debug_source = "database_fuzzy"
                formatted = [
                    f'📁 Title: "{c["title"]}"<br>🖋️ by {c["author"]}<br>📚 {c["program"]} ({c["year"]})<br>🔗 [View File]({c["gdrive_url"]})'
                    for c in chunks
                ]
                return "\n\n".join(formatted) + f"\n\n🧠 Source: {debug_source}", session_history, file_scanned

        # 3️⃣ If user clicked "Load this file"
        if gdrive_url:
            print("📥 Scanning thesis PDF from GDrive...")
            local_path = download_drive_file(gdrive_url, TMP_DIR)
            full_text = extract_text_from_pdf(local_path)
            chunks = [{"text": full_text}]
            file_scanned = True
            debug_source = "gdrive_pdf"

        # 4️⃣ Fallback to metadata
        if not chunks and METADATA_PATH.exists():
            with open(METADATA_PATH, 'r') as f:
                metadata = json.load(f)
            for item in metadata:
                blob = f"{item.get('title', '')} {item.get('text', '')}".lower()
                if any(word in blob for word in extract_keywords(query)):
                    chunks.append(item)
            if chunks:
                debug_source = "metadata"

        # 5️⃣ Fallback to FAISS vector
        if not chunks and INDEX_PATH.exists():
            query_vector = embed_text(query)
            index = faiss.read_index(str(INDEX_PATH))
            with open(METADATA_PATH, 'r') as f:
                metadata = json.load(f)
            for i in index.search(np.array([query_vector]), 10)[1][0]:
                if i < len(metadata):
                    chunks.append(metadata[i])
            if chunks:
                debug_source = "faiss"

        # 6️⃣ Final reply using OpenAI
        prompt = build_prompt(chunks[:10], query) if chunks else f"Answer this academic question: {query}"
        messages = [
            {"role": "system", "content": "You are KaAI, a helpful academic assistant. Only use thesis context."},
            {"role": "user", "content": prompt}
        ]
        response = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        reply = response.choices[0].message.content.strip()
        return reply + f"\n\n🧠 Source: {debug_source}", session_history, file_scanned

    except Exception as e:
        print(f"❌ Error in answer_query: {e}")
        return "⚠️ Something went wrong. Please try again.", session_history, file_scanned
