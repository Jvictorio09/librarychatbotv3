import os
from google.oauth2 import service_account
from googleapiclient.discovery import build


def load_drive_service():
    creds_path = "/Users/Julia/Downloads/librarychatbotv3/myProject/credentials/gdrive_service.json"
    
    if not os.path.exists(creds_path):
        raise Exception(f"❌ Service account file not found at {creds_path}")

    credentials = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)


def get_public_links_from_folder(folder_name="ja_vector_store"):
    service = load_drive_service()

    # Find the folder by name
    folder_results = service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    folders = folder_results.get("files", [])
    if not folders:
        print(f"❌ Folder '{folder_name}' not found.")
        return []

    folder_id = folders[0]["id"]
    print(f"📁 Found folder '{folder_name}' with ID: {folder_id}")

    # List files inside the folder
    file_results = service.files().list(
        q=f"'{folder_id}' in parents",
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    files = file_results.get("files", [])
    if not files:
        print("⚠️ No files found in this folder.")
        return []

    public_links = []
    for file in files:
        # Make sure it's public
        service.permissions().create(
            fileId=file["id"],
            body={"type": "anyone", "role": "reader"},
            fields="id"
        ).execute()

        public_url = f"https://drive.google.com/file/d/{file['id']}/view"
        public_links.append((file["name"], public_url))

    return public_links

# 🔍 Run it directly
if __name__ == "__main__":
    links = get_public_links_from_folder()
    for name, url in links:
        print(f"{name} → {url}")
