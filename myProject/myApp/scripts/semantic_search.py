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
def answer_query(query, session_history, uploaded_text=None, uploaded_file_path=None, gdrive_url=None):
    chunks = []
    file_scanned = False
    debug_source = "unknown"

    try:
        # Step 1: Classify intent
        classification_prompt = f"What type of question is this: '{query}'?\nOptions: author_lookup, topic_search, method_question, general_info"
        messages = [
            {"role": "system", "content": "Classify the query type. Respond with just one of the given options."},
            {"role": "user", "content": classification_prompt}
        ]
        classification_response = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        query_type = classification_response.choices[0].message.content.strip()
        print(f"🔍 Detected query type: {query_type}")

        # Step 2: Normalize title from question
        lowered = query.lower()
        cleaned_title = re.sub(r"(who\s+is\s+the\s+author\s+of|who\s+are\s+the\s+authors\s+of|authors?\s+of|can you give me the authors?\s+of)", "", lowered).strip().strip("?\"“”'")
        print(f"🔍 Normalized search title: {cleaned_title}")

        # Step 3: Exact match for author lookup
        if query_type == "author_lookup":
            for thesis in Thesis.objects.all():
                if normalize_title(thesis.title) == normalize_title(cleaned_title):
                    debug_source = "database_exact"
                    return (
                        f'The author(s) of "{thesis.title}" is **{thesis.authors}**. '
                        f'📁 Found in {thesis.program.name} ({thesis.year})'
                        + (f'. [📄 View File]({thesis.gdrive_url})' if thesis.gdrive_url else "")
                        + f"\n\n🧠 Source: {debug_source}",
                        session_history,
                        file_scanned
                    )

        # Step 4: Smart keyword topic/title match
        if query_type in ["topic_search", "general_info"]:
            print("📁 Performing keyword-based search in DB...")
            matches = Thesis.objects.filter(
                models.Q(title__icontains=query) |
                models.Q(abstract__icontains=query)
            ).values("title", "authors", "program__name", "year", "gdrive_url")[:50]

            if matches:
                debug_source = "database_fuzzy"
                formatted = "\n".join([
                    f'📁 Title: "{m["title"]}"<br>🖋️ by {m["authors"]}<br>📚 {m["program__name"]} ({m["year"]})'
                    + (f'<br>🔗 [View File]({m["gdrive_url"]})' if m["gdrive_url"] else "")
                    for m in matches
                ])
                return formatted + f"\n\n🧠 Source: {debug_source}", session_history, file_scanned

        # Step 5: Lazy load metadata.json from Drive
        if not chunks and not uploaded_file_path:
            print("🔄 Trying metadata.json from GDrive...")
            metadata_path = download_drive_file("thesis_index", ".json")
            if metadata_path:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                keywords = re.findall(r'\w+', query.lower())
                for item in metadata:
                    searchable = f"{item.get('title', '')} {item.get('text', '')}".lower()
                    if any(word in searchable for word in keywords):
                        chunks.append(item)
                if chunks:
                    debug_source = "metadata"

        # Step 6: Lazy load FAISS from Drive
        if not chunks and not uploaded_file_path:
            print("🔍 Trying FAISS search from Drive...")
            faiss_path = download_drive_file("thesis_index", ".faiss")
            if faiss_path and metadata_path:
                query_vector = embed_text(query)
                index = faiss.read_index(str(faiss_path))
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                for i in index.search(np.array([query_vector]), 10)[1][0]:
                    if i < len(metadata):
                        chunks.append(metadata[i])
                if chunks:
                    debug_source = "faiss"

        # Step 7: Build final prompt and respond
        chunks = chunks[:10]
        prompt = build_prompt(chunks, query) if chunks else f"Answer this academic question: {query}"

        messages = [
            {"role": "system", "content": "You are an academic AI assistant. Help students using thesis data only."},
            {"role": "user", "content": prompt}
        ]

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()

        return reply + f"\n\n🧠 Source: {debug_source}", session_history, file_scanned

    except Exception as e:
        print(f"❌ Error in answer_query: {e}")
        return "⚠️ Something went wrong. Please try again.", session_history, False



import json
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
from openai import OpenAI

# 🔐 Load OpenAI key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@csrf_exempt
def basic_ai_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed."}, status=405)

    try:
        data = json.loads(request.body)
        message = data.get("message", "").strip()
    except Exception as e:
        return JsonResponse({"error": f"Invalid JSON: {e}"}, status=400)

    if not message:
        return JsonResponse({"error": "Message is required."}, status=400)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful academic assistant."},
                {"role": "user", "content": message}
            ],
            temperature=0.5,
            max_tokens=600
        )
        answer = response.choices[0].message.content.strip()
        return JsonResponse({"answer": answer})
    except Exception as e:
        return JsonResponse({"error": f"OpenAI error: {e}"}, status=500)
