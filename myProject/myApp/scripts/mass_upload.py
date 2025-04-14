import os
import re
import datetime
from django.core.files import File
from myApp.models import Thesis, Program
from myApp.scripts.extract_text import extract_text_from_pdf
from myApp.scripts.embed_and_store import process_thesis_locally
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Setup Google Drive API
SERVICE_ACCOUNT_FILE = 'credentials/gdrive_service.json'
SCOPES = ['https://www.googleapis.com/auth/drive']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

def extract_metadata(text, filename):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    # YEAR from filename or text
    year_match = re.search(r"20\d{2}", filename)
    if not year_match:
        for line in lines[:20]:
            match = re.search(r"\b(20\d{2})\b", line)
            if match:
                year_match = match
                break
    year = int(year_match.group()) if year_match else datetime.datetime.now().year

    # TITLE - First long enough line
    title = next((line for line in lines if len(line.split()) > 6), "Untitled")
    title = title.title()[:255]

    # AUTHORS - Look for emails or name-like pattern
    authors = "Unknown"
    for line in lines:
        if '@' in line or re.search(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', line):
            authors = line.title()
            break
    authors = authors[:255]

    # ABSTRACT block
    abstract_lines = []
    abstract_started = False
    for line in lines:
        if 'abstract' in line.lower():
            abstract_started = True
            continue
        if abstract_started:
            if line.lower().startswith("keywords") or len(line) < 5:
                break
            abstract_lines.append(line)
    abstract = " ".join(abstract_lines).strip()[:5000] or "No abstract found."

    return title, authors, year, abstract

def upload_to_gdrive_and_share(file_path, filename):
    file_metadata = {'name': filename}
    media = MediaFileUpload(file_path, mimetype='application/pdf')
    file = drive_service.files().create(
        body=file_metadata, media_body=media, fields='id'
    ).execute()

    drive_service.permissions().create(
        fileId=file['id'],
        body={'type': 'anyone', 'role': 'reader'},
    ).execute()

    return f"https://drive.google.com/file/d/{file['id']}/view"

def mass_upload_from_folder(folder_path, program_name):
    program, _ = Program.objects.get_or_create(name=program_name)
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    total = len(files)

    for i, filename in enumerate(files, 1):
        file_path = os.path.join(folder_path, filename)
        print(f"📦 Uploading {i} of {total}: {filename}")
        try:
            text = extract_text_from_pdf(file_path)
            title, authors, year, abstract = extract_metadata(text, filename)
        except Exception as e:
            print(f"⚠️ Extraction error in {filename}: {e}")
            title = filename
            authors = "Unknown"
            year = datetime.datetime.now().year
            abstract = "No abstract available."

        thesis = Thesis(
            title=title,
            authors=authors,
            year=year,
            abstract=abstract,
            program=program
        )

        with open(file_path, "rb") as f:
            thesis.document.save(filename, File(f), save=True)

        try:
            gdrive_url = upload_to_gdrive_and_share(file_path, filename)
            thesis.gdrive_url = gdrive_url
            thesis.save()
        except Exception as e:
            print(f"❌ Failed to upload to Drive: {e}")
            continue

        process_thesis_locally(thesis)

        try:
            os.remove(file_path)
        except:
            print(f"⚠️ Couldn't delete: {file_path}")

        print(f"✅ Done: {title}")
