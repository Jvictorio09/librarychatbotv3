from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json

# Load your service account JSON from environment variable
service_json = os.getenv("GDRIVE_SERVICE_JSON")
credentials_dict = json.loads(service_json)
credentials = service_account.Credentials.from_service_account_info(credentials_dict, scopes=["https://www.googleapis.com/auth/drive"])

# Build the Google Drive service
service = build("drive", "v3", credentials=credentials)

# List the first 10 files
results = service.files().list(pageSize=10, fields="files(id, name, mimeType, size)").execute()
items = results.get('files', [])

if not items:
    print("📂 No files found.")
else:
    print("📄 Files in the service account's Drive:")
    for item in items:
        size_mb = int(item.get('size', 0)) / (1024 * 1024)
        print(f"- {item['name']} ({item['mimeType']}) - {size_mb:.2f} MB")


def count_all_gdrive_files():
    service_json = os.getenv("GDRIVE_SERVICE_JSON")
    credentials_dict = json.loads(service_json)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_dict,
        scopes=["https://www.googleapis.com/auth/drive"]
    )

    service = build("drive", "v3", credentials=credentials)

    total_files = 0
    total_size = 0
    page_token = None

    while True:
        response = service.files().list(
            fields="nextPageToken, files(id, name, size)",
            pageToken=page_token
        ).execute()

        files = response.get("files", [])
        total_files += len(files)
        total_size += sum(int(f.get("size", 0)) for f in files)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    total_size_mb = total_size / (1024 * 1024)
    print(f"\n📦 Total files: {total_files}")
    print(f"💾 Total size: {total_size_mb:.2f} MB")
