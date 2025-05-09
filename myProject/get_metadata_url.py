import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 🔐 Load credentials
load_dotenv()
SERVICE_ACCOUNT_FILE = "credentials/gdrive_service.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=credentials)

FOLDER_NAME = "ja_vector_store"

def get_folder_id(name):
    results = drive_service.files().list(
        q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces="drive",
        fields="files(id)"
    ).execute()
    folders = results.get("files", [])
    return folders[0]["id"] if folders else None

def get_file_url(filename, folder_id):
    results = drive_service.files().list(
        q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
        fields="files(id, name)",
        spaces="drive"
    ).execute()
    files = results.get("files", [])
    if not files:
        return None
    file_id = files[0]["id"]
    return f"https://drive.google.com/file/d/{file_id}/view"

def main():
    folder_id = get_folder_id(FOLDER_NAME)
    if not folder_id:
        print("❌ Folder not found.")
        return

    url = get_file_url("metadata.json", folder_id)
    if url:
        print(f"🌐 metadata.json URL: {url}")
    else:
        print("❌ metadata.json not found in ja_vector_store.")

if __name__ == "__main__":
    main()
