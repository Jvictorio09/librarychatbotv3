import os
import io
import json
import time
import tempfile
import requests
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.errors import HttpError
from pathlib import Path


# 🔐 Load Drive service from embedded JSON in environment
def load_drive_service():
    raw_json = os.getenv("GDRIVE_SERVICE_JSON")
    if not raw_json:
        raise Exception("❌ GDRIVE_SERVICE_JSON not found in environment.")

    creds_path = os.path.join(os.getcwd(), "credentials", "gdrive_service.json")
    os.makedirs(os.path.dirname(creds_path), exist_ok=True)

    # Only write file if not already created
    if not os.path.exists(creds_path):
        with open(creds_path, "w") as f:
            f.write(raw_json)

    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)

# 🛡 Retry permission creation with exponential backoff
def create_permission_with_retry(service, file_id, retries=3, delay=2):
    for attempt in range(retries):
        try:
            return service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"}
            ).execute()
        except HttpError as e:
            if e.resp.status in [500, 503]:
                print(f"⚠️ Retry {attempt+1}/{retries} - Google error {e.resp.status}. Waiting {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                raise e
    raise Exception("❌ Failed to set permission after retries.")

# 📁 Find or create folder inside Google Drive
def find_or_create_folder(service, name, parent_id=None):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(q=query, spaces="drive", fields="files(id)").execute()
    folders = results.get("files", [])
    if folders:
        return folders[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder.get("id")

# ☁️ Upload file to a specific Drive folder (with optional cleanup)
def upload_to_gdrive_folder(file_data, filename, folder_name, root_folder="thesis_uploads", cleanup=True):
    service = load_drive_service()

    parent_id = None if root_folder == "root" else find_or_create_folder(service, root_folder)
    folder_id = find_or_create_folder(service, folder_name, parent_id=parent_id)

    # Save file to temporary path
    temp_path = os.path.join(tempfile.gettempdir(), filename)
    with open(temp_path, "wb") as f:
        f.write(file_data)

    mimetype = "application/pdf" if filename.endswith(".pdf") else "application/octet-stream"

    metadata = {
        "name": filename,
        "parents": [folder_id],
    }

    media = MediaFileUpload(temp_path, resumable=True, mimetype=mimetype)
    uploaded = service.files().create(body=metadata, media_body=media, fields="id").execute()

    # Set file as public
    create_permission_with_retry(service, uploaded["id"])

    # Remove temp file if flag is set
    if cleanup:
        try:
            os.remove(temp_path)
        except Exception as e:
            print(f"⚠️ Could not delete temp file: {e}")

    file_link = f"https://drive.google.com/file/d/{uploaded['id']}/view"
    print(f"✅ Uploaded: {filename} → {file_link}")
    return file_link

def download_drive_file(gdrive_url, suffix=".pdf", output_path=None):
    import requests
    import tempfile
    import re

    match = re.search(r"/d/([a-zA-Z0-9_-]+)", gdrive_url)
    file_id = match.group(1) if match else None
    if not file_id:
        raise ValueError("Invalid Google Drive URL")

    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(download_url)

    if response.status_code != 200:
        raise Exception(f"Failed to download file: {response.status_code}")

    # 📦 Choose where to save the file
    if output_path:
        path = Path(output_path)
    else:
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        path = Path(tmp_file.name)

    with open(path, "wb") as f:
        f.write(response.content)

    print(f"✅ Downloaded file to: {path}")
    return str(path)


# 🔍 Find the latest file in Drive folder by prefix
def get_latest_file_by_prefix(service, folder_name, prefix):
    try:
        folder_id = find_or_create_folder(service, folder_name)
        query = f"'{folder_id}' in parents and name contains '{prefix}'"
        files = service.files().list(
            q=query, spaces="drive", fields="files(id, name, createdTime)"
        ).execute().get("files", [])

        if not files:
            raise Exception(f"❌ No files found in '{folder_name}' with prefix '{prefix}'")

        latest = sorted(files, key=lambda x: x["createdTime"], reverse=True)[0]
        return latest["id"], latest["name"]

    except Exception as e:
        print(f"❌ Error in get_latest_file_by_prefix: {e}")
        return None, None

# 🗑 Delete specific file by name inside a folder
def delete_drive_file_by_name(service, filename, folder_name):
    folder_id = find_or_create_folder(service, folder_name)
    query = f"'{folder_id}' in parents and name='{filename}'"
    files = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute().get('files', [])

    for file in files:
        service.files().delete(fileId=file['id']).execute()
        print(f"🗑 Deleted: {file['name']} (ID: {file['id']}) from Drive")
