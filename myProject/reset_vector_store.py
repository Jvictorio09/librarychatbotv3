import os
import tempfile
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === Hardcoded path to your credentials ===
CREDENTIALS_PATH = "/Users/Julia/Downloads/librarychatbotv3/myProject/credentials/gdrive_service.json"

def load_drive_service():
    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)

# === Helper to find and delete files ===
def find_and_delete(service, filename, folder_name):
    from myApp.scripts.vector_cache import find_or_create_folder

    folder_id = find_or_create_folder(service, folder_name)
    query = f"'{folder_id}' in parents and name='{filename}'"
    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])

    for file in files:
        service.files().delete(fileId=file["id"]).execute()
        print(f"🗑 Deleted from Drive: {file['name']} (ID: {file['id']})")

def reset_vector_store():
    try:
        print("📦 Resetting FAISS vector store...")

        # Load Drive service
        service = load_drive_service()

        # Delete from Drive
        find_and_delete(service, "thesis_index.faiss", "ja_vector_store")
        find_and_delete(service, "metadata.json", "ja_vector_store")

        # Delete local files
        tmp_dir = Path(tempfile.gettempdir())
        local_faiss = tmp_dir / "thesis_index.faiss"
        local_meta = tmp_dir / "metadata.json"

        for file in [local_faiss, local_meta]:
            if file.exists():
                file.unlink()
                print(f"🧹 Deleted local file: {file}")

        print("✅ Vector store reset complete.")

    except Exception as e:
        print(f"❌ Error resetting vector store: {e}")

if __name__ == "__main__":
    reset_vector_store()
