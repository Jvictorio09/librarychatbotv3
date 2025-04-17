import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load your service account credentials from env or .env
import json
from dotenv import load_dotenv
load_dotenv()

GDRIVE_JSON = os.getenv("GDRIVE_SERVICE_JSON")

if not GDRIVE_JSON:
    raise Exception("❌ GDRIVE_SERVICE_JSON is missing in environment!")

# Save it temporarily to access as a file
creds_path = "credentials/gdrive_service.json"
os.makedirs("credentials", exist_ok=True)

with open(creds_path, "w") as f:
    f.write(GDRIVE_JSON)

creds = service_account.Credentials.from_service_account_file(
    creds_path, scopes=["https://www.googleapis.com/auth/drive"]
)
service = build("drive", "v3", credentials=creds)


def list_files_in_folder(folder_name):
    # Get the folder ID
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
    folder_result = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    folders = folder_result.get("files", [])

    if not folders:
        print(f"❌ Folder '{folder_name}' not found.")
        return

    folder_id = folders[0]['id']
    print(f"📁 Folder: {folder_name} (ID: {folder_id})\n")

    # List files inside that folder
    file_query = f"'{folder_id}' in parents"
    files_result = service.files().list(q=file_query, spaces="drive", fields="files(id, name, mimeType, createdTime)").execute()
    files = files_result.get("files", [])

    if not files:
        print("📂 (Empty folder)")
        return

    for file in files:
        print(f"📄 {file['name']} — {file['mimeType']} — Created: {file['createdTime']}")
    print("\n")


# 🔍 Check important folders
list_files_in_folder("ja_vector_store")
list_files_in_folder("thesis_uploads")
