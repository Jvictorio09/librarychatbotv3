import os
import tempfile
import time
import json
import numpy as np
import cloudinary.uploader
import faiss

from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from myApp.scripts.extract_text import extract_text_from_pdf

# Load .env and OpenAI client
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Constants
VECTOR_STORE_DIR = Path("vector_store")
INDEX_PATH = VECTOR_STORE_DIR / "thesis_index.faiss"
METADATA_PATH = VECTOR_STORE_DIR / "metadata.json"
EMBEDDING_MODEL = "text-embedding-ada-002"

def chunk_text(text, max_tokens=500):
    paragraphs = text.split("\n")
    chunks, current = [], []
    for p in paragraphs:
        if len(" ".join(current + [p])) < max_tokens * 4:
            current.append(p)
        else:
            chunks.append(" ".join(current))
            current = [p]
    if current:
        chunks.append(" ".join(current))
    return chunks

def embed_text(text: str):
    response = client.embeddings.create(input=[text], model=EMBEDDING_MODEL)
    return response.data[0].embedding

def upload_to_google_drive(local_path, filename, program_name):
    raw_json = os.getenv("GDRIVE_SERVICE_JSON")
    if not raw_json:
        raise Exception("GDRIVE_SERVICE_JSON not found in environment")

    creds_dir = os.path.join(os.getcwd(), 'credentials')
    os.makedirs(creds_dir, exist_ok=True)
    creds_path = os.path.join(creds_dir, 'gdrive_service.json')

    with open(creds_path, 'w') as f:
        f.write(raw_json)

    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/drive"]
    )
    service = build("drive", "v3", credentials=credentials)

    # Step 1: Find or create root and program folder
    root_folder_id = find_or_create_folder(service, "thesis_uploads")
    program_folder_id = find_or_create_folder(service, program_name, parent_id=root_folder_id)

    # Step 2: Upload the file
    file_metadata = {
        "name": filename,
        "parents": [program_folder_id]
    }
    media = MediaFileUpload(local_path, mimetype="application/pdf")

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    file_id = uploaded.get("id")

    # ✅ Step 3: Make it publicly accessible
    service.permissions().create(
        fileId=file_id,
        body={
            "type": "anyone",
            "role": "reader"
        }
    ).execute()

    return f"https://drive.google.com/file/d/{file_id}/view"


def find_or_create_folder(service, folder_name, parent_id=None):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, spaces='drive', fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # If not found, create it
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder.get("id")


def process_thesis_locally(thesis_instance):
    print(f"\U0001F4C4 Processing (local-only): {thesis_instance.title}")

    if not thesis_instance.document or not hasattr(thesis_instance.document, 'file'):
        print("❌ No valid uploaded document found.")
        return

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(thesis_instance.document.file.read())
            local_path = temp_file.name
    except Exception as e:
        print(f"❌ Failed to save file locally: {e}")
        return

    # ☁️ Upload to Google Drive
    try:
        print("☁️ Uploading to Google Drive...")
        drive_url = upload_to_google_drive(local_path, thesis_instance.title + ".pdf", thesis_instance.program.name)
        thesis_instance.gdrive_url = drive_url
        thesis_instance.save(update_fields=['gdrive_url'])
        print(f"✅ Google Drive URL saved: {drive_url}")
    except Exception as e:
        print(f"❌ Google Drive upload failed: {e}")

    try:
        raw_text = extract_text_from_pdf(local_path)
        chunks = chunk_text(raw_text)
        print(f"🔍 Extracted {len(chunks)} chunks from: {thesis_instance.title}")

        embeddings, metadata = [], []
        for i, chunk in enumerate(chunks):
            try:
                vector = embed_text(chunk)
                embeddings.append(np.array(vector, dtype=np.float32))
                metadata.append({
                    "id": f"{thesis_instance.id}_{i}",
                    "title": thesis_instance.title,
                    "program": thesis_instance.program.name,
                    "year": thesis_instance.year,
                    "chunk": chunk
                })
            except Exception as e:
                print(f"❌ Failed to embed chunk {i}: {e}")

        if not embeddings:
            print("⚠️ No embeddings generated.")
            return

        VECTOR_STORE_DIR.mkdir(exist_ok=True)
        dim = len(embeddings[0])
        if INDEX_PATH.exists():
            index = faiss.read_index(str(INDEX_PATH))
        else:
            index = faiss.IndexFlatL2(dim)
        index.add(np.array(embeddings))
        faiss.write_index(index, str(INDEX_PATH))

        existing_metadata = []
        if METADATA_PATH.exists():
            with open(METADATA_PATH, "r") as f:
                existing_metadata = json.load(f)

        existing_ids = {item["id"] for item in existing_metadata}
        new_metadata = [item for item in metadata if item["id"] not in existing_ids]
        existing_metadata.extend(new_metadata)

        with open(METADATA_PATH, "w") as f:
            json.dump(existing_metadata, f, indent=2)

        print(f"✅ Thesis processed and chunks embedded: {thesis_instance.title}")

    except Exception as e:
        print(f"❌ Error during embedding: {e}")

    finally:
        try:
            os.remove(local_path)
            print(f"🧹 Temp file deleted: {local_path}")
        except Exception as e:
            print(f"⚠️ Could not delete temp file: {e}")
