import os
import django
import re

# 🧠 Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myProject.settings")
django.setup()

from myApp.models import Thesis, Program
from myApp.scripts.vector_cache import load_drive_service, find_or_create_folder
from googleapiclient.errors import HttpError

def clean_filename(name):
    return re.sub(r'[^\w\s-]', '', name).strip().lower()

def make_files_public_and_update_links(root_folder="thesis_uploads"):
    service = load_drive_service()

    # Get ID of the root folder
    root_folder_id = find_or_create_folder(service, root_folder)

    # Get all subfolders (each representing a Program)
    subfolders = service.files().list(
        q=f"'{root_folder_id}' in parents and mimeType='application/vnd.google-apps.folder'",
        spaces="drive",
        fields="files(id, name)"
    ).execute().get("files", [])

    print(f"📁 Found {len(subfolders)} program folders in '{root_folder}'")

    for folder in subfolders:
        folder_name = folder["name"]
        folder_id = folder["id"]

        try:
            program = Program.objects.get(name__iexact=folder_name)
        except Program.DoesNotExist:
            print(f"❌ No matching program found for folder '{folder_name}'")
            continue

        # List all files in this program's folder
        files = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces="drive",
            fields="files(id, name, webViewLink)"
        ).execute().get("files", [])

        print(f"🔍 {folder_name}: Checking {len(files)} files")

        for file in files:
            filename = clean_filename(file['name'])
            # Try to find a Thesis record by document name
            match = Thesis.objects.filter(
                program=program,
                document__icontains=file['name']
            ).first()

            if match:
                # Make sure the file is public
                try:
                    service.permissions().create(
                        fileId=file['id'],
                        body={"type": "anyone", "role": "reader"},
                        fields="id"
                    ).execute()
                except HttpError as e:
                    print(f"⚠️ Sharing error on {file['name']}: {e}")

                # Update thesis if URL is not set
                if not match.gdrive_url:
                    link = f"https://drive.google.com/file/d/{file['id']}/view"
                    match.gdrive_url = link
                    match.save(update_fields=["gdrive_url"])
                    print(f"✅ Updated gdrive_url for: {match.title}")
                else:
                    print(f"☑️ Already has Drive URL: {match.title}")
            else:
                print(f"❌ No DB match for: {file['name']} in {folder_name}")

if __name__ == "__main__":
    make_files_public_and_update_links()
