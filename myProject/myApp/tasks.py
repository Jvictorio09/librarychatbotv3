import os
import json
import tempfile
import numpy as np
import faiss
from pathlib import Path
from celery import shared_task
from openai import OpenAI
from dotenv import load_dotenv

from myApp.models import Thesis
from myApp.scripts.extract_text import extract_text_from_pdf
from myApp.scripts.vector_cache import (
    load_drive_service,
    upload_to_gdrive_folder,
    get_latest_file_by_prefix,
    download_drive_file,  # ✅ Use this name (matches your recent vector_cache)
)

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

# 🔐 Load env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TMP_DIR = Path(tempfile.gettempdir())

def notify_librarians(message):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "librarian_notify", {
            "type": "notify_upload_complete",
            "message": message
        }
    )

@shared_task
def process_thesis_task(thesis_id, version="v2"):
    try:
        thesis = Thesis.objects.get(id=thesis_id)
        print(f"📘 [v{version}] Processing: {thesis.title}")

        if not thesis.gdrive_url:
            print(f"❌ No gdrive_url found for thesis {thesis.title}")
            return

        # ✅ Download the actual PDF from the gdrive_url
        pdf_path = download_drive_file(thesis.gdrive_url, suffix=".pdf")
        if not os.path.exists(pdf_path):
            print(f"❌ Failed to download PDF from gdrive_url")
            return

        # 📄 Extract text and chunk
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

        # 🧠 Save index + metadata locally
        index_path = TMP_DIR / "thesis_index.faiss"
        metadata_path = TMP_DIR / "metadata.json"
        dim = len(vectors[0])

        # 🔄 Load existing index or create new
        try:
            if not index_path.exists() or not metadata_path.exists():
                print("🔄 Pulling index and metadata from Drive...")
                service = load_drive_service()
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

                if faiss_id and meta_id:
                    faiss_url = f"https://drive.google.com/file/d/{faiss_id}/view"
                    meta_url = f"https://drive.google.com/file/d/{meta_id}/view"
                    faiss_path = download_drive_file(faiss_url, suffix=".faiss")
                    meta_path = download_drive_file(meta_url, suffix=".json")
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
            print(f"⚠️ Error loading existing vector store: {e}")
            index = faiss.IndexFlatL2(dim)
            existing_metadata = []

        # ➕ Update vector store
        index.add(np.array(vectors))
        faiss.write_index(index, str(index_path))

        new_metadata = [m for m in metadata if m["id"] not in {x["id"] for x in existing_metadata}]
        all_metadata = existing_metadata + new_metadata

        with open(metadata_path, "w") as f:
            json.dump(all_metadata, f, indent=2)

        # ☁️ Upload everything to Drive
        upload_to_gdrive_folder(index_path.read_bytes(), "thesis_index.faiss", "ja_vector_store")
        upload_to_gdrive_folder(metadata_path.read_bytes(), "metadata.json", "ja_vector_store")

        notify_librarians(f"📘 Thesis uploaded & processed: {thesis.title}")
        print(f"✅ Done processing: {thesis.title}")

    except Thesis.DoesNotExist:
        print(f"❌ Thesis with ID {thesis_id} not found.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

