import os
import json
import tempfile
import faiss
import requests
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from myApp.scripts.embed_and_store import embed_text  # or wherever your embed logic lives

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
EMBEDDING_MODEL = "text-embedding-ada-002"

# === Google Drive Setup ===
GDRIVE_JSON = os.getenv("GDRIVE_SERVICE_JSON")
GDRIVE_VECTOR_FOLDER_NAME = "ja_vector_store"

def load_drive_service():
    if not GDRIVE_JSON:
        raise Exception("GDRIVE_SERVICE_JSON not found in environment.")
    creds_dir = os.path.join(os.getcwd(), 'credentials')
    os.makedirs(creds_dir, exist_ok=True)
    creds_path = os.path.join(creds_dir, 'gdrive_service.json')
    with open(creds_path, 'w') as f:
        f.write(GDRIVE_JSON)

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def get_latest_file_by_prefix(service, folder_name, prefix):
    try:
        # Step 1: Find the target folder
        response = service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
            spaces='drive',
            fields="files(id, name)"
        ).execute()

        folders = response.get("files", [])
        if not folders:
            raise Exception(f"❌ Folder '{folder_name}' not found in service account Drive. "
                            f"Make sure it's created or shared with this account.")

        folder_id = folders[0]['id']
        print(f"📂 Found folder '{folder_name}' with ID: {folder_id}")

        # Step 2: Find the latest file by prefix
        query = f"'{folder_id}' in parents and name contains '{prefix}'"
        files = service.files().list(
            q=query,
            spaces='drive',
            fields="files(id, name, createdTime)"
        ).execute().get("files", [])

        if not files:
            raise Exception(f"❌ No file found in '{folder_name}' with prefix '{prefix}'. "
                            f"Please check naming or upload first.")

        # Step 3: Sort by created time and return the latest
        latest_file = sorted(files, key=lambda x: x["createdTime"], reverse=True)[0]
        print(f"📄 Found latest file for prefix '{prefix}': {latest_file['name']}")

        return latest_file["id"], latest_file["name"]

    except Exception as e:
        print(f"❌ Error in get_latest_file_by_prefix: {e}")
        return None, None


def download_drive_file(service, file_id, suffix):
    request = service.files().get_media(fileId=file_id)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    downloader = MediaIoBaseDownload(temp_file, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            print(f"⬇️ Downloading {suffix}: {int(status.progress() * 100)}%")

    return temp_file.name

def embed_question(question):
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[question]
    )
    return np.array(response.data[0].embedding, dtype=np.float32)

def search_similar_chunks(index_path, metadata_path, question_vector, top_k=5):
    index = faiss.read_index(index_path)
    with open(metadata_path, "r") as f:
        metadata = json.load(f)

    D, I = index.search(np.array([question_vector]), top_k)
    return [metadata[i] for i in I[0] if i < len(metadata)]

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

def answer_query(query):
    print(f"🤖 Received query: {query}")
    try:
        question_vector = embed_question(query)
    except Exception as e:
        print(f"❌ Failed to embed question: {e}")
        return "Sorry, I couldn't understand the question at the moment."

    try:
        service = load_drive_service()

        # Get latest versioned FAISS and metadata from Drive
        faiss_id, faiss_name = get_latest_file_by_prefix(service, GDRIVE_VECTOR_FOLDER_NAME, "thesis_index")
        json_id, json_name = get_latest_file_by_prefix(service, GDRIVE_VECTOR_FOLDER_NAME, "metadata")

        # Download them to temp
        faiss_path = download_drive_file(service, faiss_id, ".faiss")
        json_path = download_drive_file(service, json_id, ".json")

        similar_chunks = search_similar_chunks(faiss_path, json_path, question_vector, top_k=5)
        prompt = build_prompt(similar_chunks, query) if similar_chunks else f"Answer the question to the best of your knowledge:\n\n{query}"

    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")
        prompt = f"Answer the question to the best of your knowledge:\n\n{query}"

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly and witty academic mentor helping students with their thesis. "
                        "Speak in a clear, encouraging, and casual tone—like a wise professor who’s easy to talk to. "
                        "Avoid deep academic words unless writing research content like significance or background. "
                        "Always guide with follow-up questions, suggestions, or tips. Keep it practical, kind, and never abrupt."
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
        return "Oops, something went wrong while trying to answer. Please try again later."
