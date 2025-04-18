import os
from googleapiclient.errors import HttpError
from myApp.scripts.vector_cache import load_drive_service, find_or_create_folder

def make_files_public_in_folder(service, folder_id, folder_label):
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        spaces="drive",
        fields="files(id, name, webViewLink)"
    ).execute()

    files = results.get("files", [])
    print(f"📂 {folder_label} → Found {len(files)} files")

    for file in files:
        try:
            service.permissions().create(
                fileId=file['id'],
                body={"type": "anyone", "role": "reader"},
                fields="id"
            ).execute()
            print(f"✅ Shared: {file['name']} → {file['webViewLink']}")
        except HttpError as e:
            print(f"❌ {file['name']} → Sharing failed: {e}")
        except Exception as ex:
            print(f"⚠️ Unexpected error for {file['name']}: {ex}")

def make_all_thesis_files_public(root_folder="thesis_uploads"):
    service = load_drive_service()

    # Step 1: Locate the root folder (e.g., 'thesis_uploads')
    root_folder_id = find_or_create_folder(service, root_folder)

    # Step 2: Get all program folders inside the root
    folders = service.files().list(
        q=f"'{root_folder_id}' in parents and mimeType='application/vnd.google-apps.folder'",
        spaces="drive",
        fields="files(id, name)"
    ).execute().get("files", [])

    print(f"📁 Found {len(folders)} program subfolders inside '{root_folder}'")

    # Step 3: Loop over each subfolder and share files
    for folder in folders:
        make_files_public_in_folder(service, folder["id"], folder["name"])

if __name__ == "__main__":
    make_all_thesis_files_public("thesis_uploads")
