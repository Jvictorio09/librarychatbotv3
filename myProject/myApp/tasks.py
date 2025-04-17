import os
import json
import tempfile
import numpy as np
import faiss
from pathlib import Path
from celery import shared_task
from openai import OpenAI
from dotenv import load_dotenv

from django.core.files.storage import default_storage
from myApp.models import Thesis
from myApp.scripts.extract_text import extract_text_from_pdf
from myApp.scripts.vector_cache import (
    load_drive_service,
    upload_to_gdrive_folder,
    get_latest_file_by_prefix,
    download_drive_file_by_url,  # ✅ NEW FUNCTION
)
from myApp.scripts.embedding_utils import embed_text, chunk_text

# 🔄 Channels
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

# 🔐 Env + Client
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TMP_DIR = Path(tempfile.gettempdir())

def notify_librarians(message):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "librarian_notify",
        {"type": "notify_upload_complete", "message": message}
    )

@shared_task
def process_thesis_task(thesis_id, version="v2"):
    try:
        thesis = Thesis.objects.get(id=thesis_id)
        print(f"📘 [v{version}] Processing: {thesis.title}")

        if not thesis.gdrive_url:
            print(f"❌ No gdrive_url found for thesis {thesis.title}")
            return

        # ✅ Download PDF using public Google Drive URL
        pdf_path = download_drive_file_by_url(thesis.gdrive_url)
        if not os.path.exists(pdf_path):
            print(f"❌ Failed to download PDF from gdrive_url")
            return

        # 📄 Extract & embed
        text = extract_text_from_pdf(pdf_path)
        chunks = chunk_text(text)

        vectors, metadata = [], []
        for i, chunk in enumerate(chunks):
            try:
                emb = embed_text(chunk)
                vectors.append(np.array(emb, dtype=np.float32))
                metadata.append({
                    "id": f"{thesis.id}_{i}",
                    "title": thesis.title,
                    "program": thesis.program.name,
                    "year": thesis.year,
                    "chunk": chunk
                })
            except Exception as e:
                print(f"❌ Embedding failed on chunk {i}: {e}")

        if not vectors:
            print("⚠️ No embeddings created.")
            return

        # 🧠 Save FAISS index and metadata locally
        index_path = TMP_DIR / "thesis_index.faiss"
        metadata_path = TMP_DIR / "metadata.json"
        dim = len(vectors[0])

        try:
            if not index_path.exists() or not metadata_path.exists():
                print("🔄 Pulling from Drive...")
                service = load_drive_service()
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

                if faiss_id and meta_id:
                    faiss_path = download_drive_file_by_url(f"https://drive.google.com/uc?id={faiss_id}")
                    meta_path = download_drive_file_by_url(f"https://drive.google.com/uc?id={meta_id}")
                    index = faiss.read_index(faiss_path)
                    with open(meta_path, "r") as f:
                        existing_metadata = json.load(f)
                else:
                    index = faiss.IndexFlatL2(dim)
                    existing_metadata = []
            else:
                index = faiss.read_index(str(index_path))
                with open(metadata_path, "r") as f:
                    existing_metadata = json.load(f)
        except Exception as e:
            print(f"⚠️ Couldn't load existing FAISS index: {e}")
            index = faiss.IndexFlatL2(dim)
            existing_metadata = []

        index.add(np.array(vectors))
        faiss.write_index(index, str(index_path))

        new_metadata = [m for m in metadata if m["id"] not in {x["id"] for x in existing_metadata}]
        with open(metadata_path, "w") as f:
            json.dump(existing_metadata + new_metadata, f, indent=2)

        # ☁ Upload FAISS + Metadata
        upload_to_gdrive_folder(index_path.read_bytes(), "thesis_index.faiss", "ja_vector_store")
        upload_to_gdrive_folder(metadata_path.read_bytes(), "metadata.json", "ja_vector_store")

        notify_librarians(f"📘 Thesis uploaded & processed: {thesis.title}")
        print(f"✅ {thesis.title} processed & stored.")

    except Thesis.DoesNotExist:
        print(f"❌ Thesis with ID {thesis_id} not found.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
