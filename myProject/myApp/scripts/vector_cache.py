import os
import io
import json
import tempfile
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

# 🔐 Load Drive service from embedded JSON in env
def load_drive_service():
    raw_json = os.getenv("GDRIVE_SERVICE_JSON")
    if not raw_json:
        raise Exception("❌ GDRIVE_SERVICE_JSON not found in environment.")

    creds_path = os.path.join(os.getcwd(), "credentials", "gdrive_service.json")
    os.makedirs(os.path.dirname(creds_path), exist_ok=True)

    with open(creds_path, "w") as f:
        f.write(raw_json)

    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)

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

# ☁️ Upload file to Google Drive
def upload_to_gdrive_folder(file_data, filename, folder_name, root_folder="thesis_uploads"):
    service = load_drive_service()

    parent_id = None if root_folder == "root" else find_or_create_folder(service, root_folder)
    folder_id = find_or_create_folder(service, folder_name, parent_id=parent_id)

    # Save to temp
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

    # Make it public
    service.permissions().create(fileId=uploaded["id"], body={"type": "anyone", "role": "reader"}).execute()
    file_link = f"https://drive.google.com/file/d/{uploaded['id']}/view"
    print(f"✅ Uploaded: {filename} → {file_link}")
    return file_link

# ⬇️ Download file by name (from a folder)
import requests

def download_drive_file(url, suffix=".pdf"):
    try:
        file_id = None

        # 🕵️ Extract file ID from shared GDrive URL
        if "drive.google.com" in url:
            if "id=" in url:
                file_id = url.split("id=")[-1].split("&")[0]
            elif "/d/" in url:
                file_id = url.split("/d/")[-1].split("/")[0]

        if not file_id:
            raise Exception("❌ Invalid Google Drive URL.")

        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        # 📥 Fetch the file
        response = requests.get(download_url)
        response.raise_for_status()

        # 💾 Save to /tmp/
        temp_path = os.path.join(tempfile.gettempdir(), f"downloaded_{file_id}{suffix}")
        with open(temp_path, "wb") as f:
            f.write(response.content)

        print(f"✅ Downloaded file to: {temp_path}")
        return temp_path

    except Exception as e:
        print(f"❌ Failed to download from Drive URL: {e}")
        return ""


# 🔍 Find latest file by prefix (Drive vector logic)
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

# 🗑 Delete Drive file by exact name in folder
def delete_drive_file_by_name(service, filename, folder_name):
    folder_id = find_or_create_folder(service, folder_name)
    query = f"'{folder_id}' in parents and name='{filename}'"
    files = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute().get('files', [])

    for file in files:
        service.files().delete(fileId=file['id']).execute()
        print(f"🗑 Deleted: {file['name']} (ID: {file['id']}) from Drive")
