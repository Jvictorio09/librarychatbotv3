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

# ☁️ Upload to Drive (supports PDF and other file types)
def upload_to_gdrive_folder(file_data, filename, folder_name, root_folder="thesis_uploads"):
    service = load_drive_service()

    # Decide whether to nest under thesis_uploads or root
    parent_id = None if root_folder == "root" else find_or_create_folder(service, root_folder)
    target_folder_id = find_or_create_folder(service, folder_name, parent_id=parent_id)

    # Save to temporary file
    temp_path = os.path.join(tempfile.gettempdir(), filename)
    with open(temp_path, "wb") as f:
        f.write(file_data)

    # Determine MIME type
    mimetype = "application/pdf" if filename.endswith(".pdf") else "application/octet-stream"

    metadata = {
        "name": filename,
        "parents": [target_folder_id],
    }

    media = MediaFileUpload(temp_path, resumable=True, mimetype=mimetype)
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()

    # Make public
    service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()

    file_link = f"https://drive.google.com/file/d/{file['id']}/view"
    print(f"✅ Uploaded: {filename} → {file_link}")
    return file_link

# 🔄 Download a file from Drive using file ID
def download_drive_file(service, file_id, suffix=".faiss"):
    request = service.files().get_media(fileId=file_id)
    file_stream = io.BytesIO()
    downloader = MediaIoBaseDownload(file_stream, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    file_stream.seek(0)
    temp_path = f"/tmp/temp_vector_{datetime.now().timestamp()}{suffix}"
    with open(temp_path, "wb") as f:
        f.write(file_stream.read())
    return temp_path

# 🔍 Find the latest version of a file by prefix (used in semantic search)
def get_latest_file_by_prefix(service, folder_name, prefix):
    try:
        response = service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
            spaces="drive",
            fields="files(id, name)"
        ).execute()

        folders = response.get("files", [])
        if not folders:
            raise Exception(f"❌ Folder '{folder_name}' not found in Drive.")
        folder_id = folders[0]["id"]

        query = f"'{folder_id}' in parents and name contains '{prefix}'"
        files = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name, createdTime)"
        ).execute().get("files", [])

        if not files:
            raise Exception(f"❌ No files found in '{folder_name}' with prefix '{prefix}'.")

        latest = sorted(files, key=lambda x: x["createdTime"], reverse=True)[0]
        print(f"📄 Found latest '{prefix}': {latest['name']}")
        return latest["id"], latest["name"]

    except Exception as e:
        print(f"❌ Error in get_latest_file_by_prefix: {e}")
        return None, None


def delete_drive_file_by_name(service, filename, folder_name):
    print(f"🔍 Looking for '{filename}' in Google Drive folder '{folder_name}'")
    folder_id = find_or_create_folder(service, folder_name)
    query = f"'{folder_id}' in parents and name='{filename}'"
    files = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute().get('files', [])

    if not files:
        print(f"❌ File '{filename}' not found in folder '{folder_name}'")
    for file in files:
        service.files().delete(fileId=file['id']).execute()
        print(f"🗑 Deleted '{file['name']}' from Google Drive (ID: {file['id']})")
