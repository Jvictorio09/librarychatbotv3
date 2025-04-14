# scripts/fix_gdrive_permissions.py

from myApp.models import Thesis
from google.oauth2 import service_account
from googleapiclient.discovery import build
from myApp.scripts.gdrive_utils import make_file_public
import re

def extract_file_id(url):
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    return match.group(1) if match else None

def fix_all_links():
    service_json = os.getenv("GDRIVE_SERVICE_JSON")
    credentials_dict = json.loads(service_json)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_dict,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    service = build("drive", "v3", credentials=credentials)

    for thesis in Thesis.objects.exclude(gdrive_url=None):
        file_id = extract_file_id(thesis.gdrive_url)
        if file_id:
            print(f"🔓 Making public: {thesis.title}")
            make_file_public(service, file_id)
