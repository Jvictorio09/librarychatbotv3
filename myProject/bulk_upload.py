import os
import re
import json
import time
import datetime
import traceback
import numpy as np
import faiss
import django
import tempfile
from pathlib import Path
from django.core.files import File
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from openai import OpenAI
import io

# Set up Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myProject.settings")
django.setup()

# Load environment
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Google Drive setup
SERVICE_ACCOUNT_FILE = "credentials/gdrive_service.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=credentials)

# Django imports
from myApp.models import Thesis, Program
from myApp.scripts.extract_text import extract_text_from_pdf
from myApp.scripts.embedding_utils import embed_text
from myApp.scripts.chunking import chunk_text

TMP_DIR = Path(tempfile.gettempdir())
BATCH_METADATA = []
BATCH_VECTORS = []
FAILED_FILES_PATH = TMP_DIR / "failed_files.txt"


def extract_year_from_filename(filename):
    match = re.search(r"(20\\d{2})", filename)
    return int(match.group(1)) if match else datetime.datetime.now().year


def smart_metadata_extraction(text_excerpt, fallback_filename="Untitled.pdf"):
    prompt = f"""You are an assistant that extracts metadata from academic research papers.

Given the following text excerpt from the first page of a PDF, extract:
- Title
- Authors
- Abstract

Respond ONLY in raw JSON like this:
{{
    \"title\": \"...\",
    \"authors\": \"...\",
    \"abstract\": \"...\"
}}

Text:
{text_excerpt}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You extract metadata from academic research PDFs."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=700
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()

        if not content.endswith("}"):
            last_brace = content.rfind("}")
            if last_brace != -1:
                content = content[:last_brace + 1]

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as json_err:
            print("⚠️ GPT response not valid JSON:", content[:300])
            raise ValueError("Invalid JSON returned by GPT") from json_err

        return {
            "title": parsed.get("title", fallback_filename.replace(".pdf", ""))[:255],
            "authors": parsed.get("authors", "Unknown Authors")[:255],
            "abstract": parsed.get("abstract", "No abstract found.")[:5000],
            "year": extract_year_from_filename(fallback_filename)
        }

    except Exception as e:
        print("❌ Metadata extraction failed:", e)
        return {
            "title": fallback_filename.replace(".pdf", "").title(),
            "authors": "Unknown",
            "abstract": "No abstract extracted.",
            "year": extract_year_from_filename(fallback_filename)
        }


def get_or_create_drive_folder(name):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
    results = drive_service.files().list(q=query, spaces="drive", fields="files(id)").execute().get("files", [])
    if results:
        return results[0]["id"]
    folder = drive_service.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder"}, fields="id"
    ).execute()
    return folder.get("id")


def find_drive_file_id(filename, parent_id):
    query = f"name='{filename}' and '{parent_id}' in parents and trashed=false"
    response = drive_service.files().list(q=query, spaces="drive", fields="files(id)").execute()
    files = response.get("files", [])
    return files[0]['id'] if files else None


def fetch_existing_metadata_json(folder_name="ja_vector_store"):
    try:
        parent_id = get_or_create_drive_folder(folder_name)
        file_id = find_drive_file_id("metadata.json", parent_id)
        if not file_id:
            return []

        request = drive_service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        return json.load(fh)
    except Exception as e:
        print("⚠️ Failed to fetch existing metadata.json:", e)
        return []


def upload_batch_to_gdrive(index_path, metadata_path, folder="ja_vector_store"):
    parent_id = get_or_create_drive_folder(folder)

    for fname, fpath in [("thesis_index.faiss", index_path), ("metadata.json", metadata_path)]:
        existing_file_id = find_drive_file_id(fname, parent_id)
        if existing_file_id:
            drive_service.files().delete(fileId=existing_file_id).execute()

        metadata = {"name": fname, "parents": [parent_id]}
        media = MediaFileUpload(fpath, mimetype="application/octet-stream")
        uploaded = drive_service.files().create(body=metadata, media_body=media, fields="id").execute()
        drive_service.permissions().create(fileId=uploaded['id'], body={"type": "anyone", "role": "reader"}).execute()
        print(f"☁️ Uploaded {fname} to Drive")

        if fname == "metadata.json":
            print(f"🌐 metadata.json URL: https://drive.google.com/file/d/{uploaded['id']}/view")


def upload_to_gdrive_and_share(file_path, filename, folder="thesis_uploads"):
    parent_id = get_or_create_drive_folder(folder)
    existing_file_id = find_drive_file_id(filename, parent_id)
    if existing_file_id:
        drive_service.files().delete(fileId=existing_file_id).execute()

    metadata = {"name": filename, "parents": [parent_id]}
    media = MediaFileUpload(file_path, mimetype="application/pdf")
    uploaded = drive_service.files().create(body=metadata, media_body=media, fields="id").execute()
    drive_service.permissions().create(fileId=uploaded['id'], body={"type": "anyone", "role": "reader"}).execute()
    return f"https://drive.google.com/file/d/{uploaded['id']}/view"


def log_failed_file(file_path):
    with open(FAILED_FILES_PATH, "a") as f:
        f.write(f"{file_path}\n")


def process_pdf(file_path, program):
    global BATCH_METADATA, BATCH_VECTORS

    try:
        with open(file_path, "rb") as f:
            file_data = f.read()

        text = extract_text_from_pdf(file_path)
        excerpt = " ".join(text.split()[:800])
        metadata = smart_metadata_extraction(excerpt, fallback_filename=os.path.basename(file_path))
        gdrive_url = upload_to_gdrive_and_share(file_path, os.path.basename(file_path), folder=program.name)

        thesis = Thesis.objects.create(
            title=metadata["title"],
            authors=metadata["authors"],
            abstract=metadata["abstract"],
            year=metadata["year"],
            program=program,
            gdrive_url=gdrive_url,
            embedding_status="processing"
        )

        with open(file_path, "rb") as f:
            thesis.document.save(os.path.basename(file_path), File(f), save=True)

        chunks = chunk_text(text)
        vectors = []
        for chunk in chunks:
            try:
                if chunk.strip():
                    vector = np.array(embed_text(chunk), dtype=np.float32)
                    vectors.append(vector)
            except Exception as embed_err:
                print(f"⚠️ Failed embedding a chunk: {embed_err}")

        chunk_metadata = [{
            "id": f"{thesis.id}_{i}",
            "title": thesis.title,
            "program": thesis.program.name,
            "year": thesis.year,
            "chunk": chunk
        } for i, chunk in enumerate(chunks)]

        BATCH_VECTORS.extend(vectors)
        BATCH_METADATA.extend(chunk_metadata)

        thesis.embedding_status = "done"
        thesis.save()

        print(f"✅ Done: {thesis.title}")

    except Exception as e:
        print(f"❌ Failed: {file_path} — {e}")
        traceback.print_exc()
        log_failed_file(file_path)
        if 'thesis' in locals():
            thesis.embedding_status = "failed"
            thesis.save()


def run(folder_path, program_name):
    global BATCH_METADATA, BATCH_VECTORS

    program, _ = Program.objects.get_or_create(name=program_name)
    files = [f for f in Path(folder_path).glob("*.pdf") if f.is_file()]
    print(f"📂 Found {len(files)} PDF files in '{folder_path}'")

    if FAILED_FILES_PATH.exists():
        FAILED_FILES_PATH.unlink()  # Clear old failed log

    for idx, file_path in enumerate(files, 1):
        print(f"[{idx}/{len(files)}] Uploading {file_path.name}...")
        process_pdf(file_path, program)
        time.sleep(1)

    if BATCH_VECTORS:
        index_path = TMP_DIR / "thesis_index.faiss"
        metadata_path = TMP_DIR / "metadata.json"
        dim = len(BATCH_VECTORS[0])
        index = faiss.IndexFlatL2(dim)
        index.add(np.array(BATCH_VECTORS))
        faiss.write_index(index, str(index_path))

        # Merge existing metadata before writing
        existing_metadata = fetch_existing_metadata_json()
        merged_metadata = existing_metadata + BATCH_METADATA

        with open(metadata_path, "w") as f:
            json.dump(merged_metadata, f, indent=2)

        upload_batch_to_gdrive(index_path, metadata_path)
        print("📦 Batch vector store and metadata uploaded!")
    else:
        print("⚠️ No vectors to upload.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch upload and process thesis PDFs with AI metadata.")
    parser.add_argument("folder", help="Path to folder containing PDF files")
    parser.add_argument("program", help="Program name (e.g., BSIT)")
    args = parser.parse_args()

    run(args.folder, args.program)
