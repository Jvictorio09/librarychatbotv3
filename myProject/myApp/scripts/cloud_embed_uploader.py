import os
import tempfile
import json
import numpy as np
import faiss

from openai import OpenAI
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv
from myApp.scripts.extract_text import extract_text_from_pdf

# Load .env and OpenAI client
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
EMBEDDING_MODEL = "text-embedding-ada-002"

# -------------------- DRIVE HELPERS --------------------
def load_drive_service():
    raw_json = os.getenv("GDRIVE_SERVICE_JSON")
    if not raw_json:
        raise Exception("❌ GDRIVE_SERVICE_JSON missing in .env")

    creds_dir = os.path.join(os.getcwd(), 'credentials')
    os.makedirs(creds_dir, exist_ok=True)
    creds_path = os.path.join(creds_dir, 'gdrive_service.json')
    with open(creds_path, 'w') as f:
        f.write(raw_json)

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def find_or_create_folder(service, folder_name, parent_id=None):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    result = service.files().list(q=query, spaces='drive', fields="files(id)").execute()
    files = result.get("files", [])
    if files:
        return files[0]['id']

    metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]

def upload_or_replace(service, folder_id, file_path, filename):
    # Try to replace if exists
    query = f"name='{filename}' and '{folder_id}' in parents"
    existing = service.files().list(q=query, spaces='drive', fields="files(id)").execute().get("files", [])

    media = MediaFileUpload(file_path, resumable=True)
    if existing:
        file_id = existing[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"🔄 Replaced: {filename}")
    else:
        service.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id"
        ).execute()
        print(f"✅ Uploaded: {filename}")

# -------------------- MAIN FUNCTION --------------------
def process_thesis_cloud(thesis_instance, version="v1"):
    print(f"📘 Processing: {thesis_instance.title}")

    if not thesis_instance.document or not hasattr(thesis_instance.document, 'file'):
        print("❌ No valid uploaded document.")
        return

    # Save uploaded PDF to temp
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(thesis_instance.document.file.read())
            pdf_path = temp_pdf.name
    except Exception as e:
        print(f"❌ Failed to save PDF locally: {e}")
        return

    try:
        # Setup Drive
        service = load_drive_service()
        root_id = find_or_create_folder(service, "thesis_uploads")
        vector_id = find_or_create_folder(service, "vector_store", parent_id=root_id)

        # Get existing files from Drive (if they exist)
        def get_file_id_by_name(name):
            query = f"'{vector_id}' in parents and name='{name}'"
            results = service.files().list(q=query, spaces='drive', fields="files(id)").execute().get("files", [])
            return results[0]["id"] if results else None

        faiss_id = get_file_id_by_name(f"thesis_index_{version}.faiss")
        json_id = get_file_id_by_name(f"metadata_{version}.json")

        existing_index = None
        existing_metadata = []

        if faiss_id and json_id:
            print("📥 Downloading existing FAISS and metadata...")
            existing_faiss_path = download_drive_file(service, faiss_id, ".faiss")
            existing_json_path = download_drive_file(service, json_id, ".json")

            existing_index = faiss.read_index(existing_faiss_path)
            with open(existing_json_path, "r") as f:
                existing_metadata = json.load(f)

        # Extract and chunk new file
        raw_text = extract_text_from_pdf(pdf_path)
        paragraphs = raw_text.split("\n")
        chunks, current = [], []
        for p in paragraphs:
            if len(" ".join(current + [p])) < 2000:
                current.append(p)
            else:
                chunks.append(" ".join(current))
                current = [p]
        if current:
            chunks.append(" ".join(current))

        print(f"🔍 Chunks extracted: {len(chunks)}")

        # Embed new chunks
        embeddings, metadata = [], []
        for i, chunk in enumerate(chunks):
            try:
                vector = client.embeddings.create(input=[chunk], model=EMBEDDING_MODEL)
                embeddings.append(np.array(vector.data[0].embedding, dtype=np.float32))
                metadata.append({
                    "id": f"{thesis_instance.id}_{i}",
                    "title": thesis_instance.title,
                    "program": thesis_instance.program.name,
                    "year": thesis_instance.year,
                    "chunk": chunk
                })
            except Exception as e:
                print(f"⚠️ Skipping chunk {i}: {e}")

        if not embeddings:
            print("⚠️ No embeddings generated.")
            return

        # Combine old + new vectors
        dim = len(embeddings[0])
        if existing_index:
            print("🧠 Appending to existing FAISS index...")
            existing_index.add(np.array(embeddings))
            index = existing_index
        else:
            index = faiss.IndexFlatL2(dim)
            index.add(np.array(embeddings))

        # Combine metadata
        all_metadata = existing_metadata + metadata

        # Save updated files to temp
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{version}.faiss") as faiss_file:
            faiss.write_index(index, faiss_file.name)
            faiss_path = faiss_file.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{version}.json", mode='w') as meta_file:
            json.dump(all_metadata, meta_file, indent=2)
            meta_path = meta_file.name

        # Upload updated versions
        upload_or_replace(service, vector_id, faiss_path, f"thesis_index_{version}.faiss")
        upload_or_replace(service, vector_id, meta_path, f"metadata_{version}.json")

        thesis_instance.gdrive_url = f"https://drive.google.com/file/d/{thesis_instance.id}/view"
        thesis_instance.save(update_fields=["gdrive_url"])

    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    finally:
        for path in [pdf_path, faiss_path, meta_path]:
            try:
                os.remove(path)
            except Exception as e:
                print(f"⚠️ Cleanup failed: {e}")
