from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

def make_file_public(service, file_id):
    try:
        permission = {
            'type': 'anyone',
            'role': 'reader',
        }
        service.permissions().create(
            fileId=file_id,
            body=permission
        ).execute()
    except HttpError as e:
        print(f"❌ Error making file public: {e}")
