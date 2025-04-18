import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

# 🌱 Load environment variables
load_dotenv()

GDRIVE_JSON = os.getenv("GDRIVE_SERVICE_JSON")

if not GDRIVE_JSON:
    raise Exception("❌ GDRIVE_SERVICE_JSON is missing in environment!")

# 💾 Temporarily save JSON credentials to disk
creds_path = "credentials/gdrive_service.json"
os.makedirs("credentials", exist_ok=True)

with open(creds_path, "w") as f:
    f.write(GDRIVE_JSON)

# 🔐 Authenticate and build Drive service
creds = service_account.Credentials.from_service_account_file(
    creds_path, scopes=["https://www.googleapis.com/auth/drive"]
)
service = build("drive", "v3", credentials=creds)


def list_files_in_folder(folder_name):
    """List and count files inside a Google Drive folder by name."""
    # 📁 Find folder ID by name
    folder_query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
    folder_result = service.files().list(q=folder_query, spaces="drive", fields="files(id, name)").execute()
    folders = folder_result.get("files", [])

    if not folders:
        print(f"❌ Folder '{folder_name}' not found.")
        return []

    folder_id = folders[0]['id']
    print(f"\n📁 Folder: {folder_name} (ID: {folder_id})")

    # 📄 List files in the folder
    file_query = f"'{folder_id}' in parents"
    files_result = service.files().list(
        q=file_query,
        spaces="drive",
        fields="files(id, name, mimeType, createdTime)"
    ).execute()

    files = files_result.get("files", [])

    if not files:
        print("📂 (Empty folder)")
        return []

    for file in files:
        print(f"  📄 {file['name']} — {file['mimeType']} — Created: {file['createdTime']}")

    print(f"📦 Total files in '{folder_name}': {len(files)}")
    return files


# 🔍 Check and count important folders
list_files_in_folder("ja_vector_store")
list_files_in_folder("thesis_uploads")
