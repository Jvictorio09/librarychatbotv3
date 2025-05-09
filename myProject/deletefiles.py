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


def delete_folder_and_contents(folder_name):
    """Delete all files inside a Google Drive folder by name, then delete the folder itself."""
    # 📁 Find folder ID by name
    folder_query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
    folder_result = service.files().list(q=folder_query, spaces="drive", fields="files(id, name)").execute()
    folders = folder_result.get("files", [])

    if not folders:
        print(f"❌ Folder '{folder_name}' not found.")
        return

    folder_id = folders[0]['id']
    print(f"\n🗑️ Deleting contents of folder: {folder_name} (ID: {folder_id})")

    # 📄 List and delete files in the folder
    file_query = f"'{folder_id}' in parents"
    files_result = service.files().list(
        q=file_query,
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    files = files_result.get("files", [])

    for file in files:
        file_id = file['id']
        file_name = file['name']
        try:
            service.files().delete(fileId=file_id).execute()
            print(f"✅ Deleted file: {file_name}")
        except Exception as e:
            print(f"❌ Failed to delete file {file_name}: {e}")

    # 🧨 Delete the folder itself
    try:
        service.files().delete(fileId=folder_id).execute()
        print(f"✅ Deleted folder: {folder_name}")
    except Exception as e:
        print(f"❌ Failed to delete folder {folder_name}: {e}")


# 🚮 Clean up these folders
delete_folder_and_contents("ja_vector_store")
delete_folder_and_contents("thesis_uploads")
