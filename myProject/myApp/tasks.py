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
    download_drive_file,
    get_latest_file_by_prefix,
)
from myApp.scripts.embedding_utils import embed_text, chunk_text

# 🔄 Channels
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

# 🔐 Env + Client
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TMP_DIR = Path(tempfile.gettempdir())

# 📢 WebSocket Notifier
def notify_librarians(message):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "librarian_notify",
        {
            "type": "notify_upload_complete",
            "message": message,
        }
    )

@shared_task
def process_thesis_task(thesis_id, version="v1"):
    try:
        thesis = Thesis.objects.get(id=thesis_id)
        print(f"📘 [v{version}] Starting async processing for: {thesis.title}")
        process_thesis_async(thesis_id)
        print(f"✅ [v{version}] Processing complete for: {thesis.title}")
    except Thesis.DoesNotExist:
        print(f"❌ Thesis with ID {thesis_id} does not exist.")
    except Exception as e:
        print(f"❌ Error in process_thesis_task: {e}")

@shared_task
def process_thesis_async(thesis_id):
    try:
        thesis = Thesis.objects.get(pk=thesis_id)
        print(f"📚 Processing thesis: {thesis.title}")

        if not thesis.document:
            print("❌ No document found.")
            return

        # 👇 Safely read the uploaded file from wherever it's stored
        with default_storage.open(thesis.document.name, 'rb') as doc_file:
            file_data = doc_file.read()

        # 💾 Save to temporary path
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(file_data)
            tmp_path = tmp_file.name

        # 📄 Extract text and chunk it
        text = extract_text_from_pdf(tmp_path)
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
                print(f"❌ Chunk {i} failed: {e}")

        if not vectors:
            print("⚠️ No embeddings created. Stopping.")
            return

        # 🧠 FAISS and metadata paths
        index_path = TMP_DIR / "thesis_index.faiss"
        metadata_path = TMP_DIR / "metadata.json"
        dim = len(vectors[0])

        # 🔄 Load or create index
        try:
            if not index_path.exists() or not metadata_path.exists():
                print("🔄 Pulling from Drive...")
                service = load_drive_service()
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

                if faiss_id and meta_id:
                    faiss_path = download_drive_file(service, faiss_id, ".faiss")
                    meta_path = download_drive_file(service, meta_id, ".json")
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
            print(f"⚠️ Starting fresh index: {e}")
            index = faiss.IndexFlatL2(dim)
            existing_metadata = []

        # ➕ Add new vectors
        index.add(np.array(vectors))
        faiss.write_index(index, str(index_path))

        # 📝 Merge metadata safely
        existing_ids = {item["id"] for item in existing_metadata}
        new_metadata = [m for m in metadata if m["id"] not in existing_ids]
        all_metadata = existing_metadata + new_metadata

        with open(metadata_path, "w") as f:
            json.dump(all_metadata, f, indent=2)

        # ☁️ Upload vector files to Drive
        upload_to_gdrive_folder(index_path.read_bytes(), "thesis_index.faiss", "ja_vector_store")
        upload_to_gdrive_folder(metadata_path.read_bytes(), "metadata.json", "ja_vector_store")

        # ☁️ Upload original PDF
        gdrive_url = upload_to_gdrive_folder(file_data, f"{thesis.title}.pdf", thesis.program.name)
        thesis.gdrive_url = gdrive_url
        thesis.save(update_fields=["gdrive_url"])

        print(f"✅ Completed upload and embedding for: {thesis.title}")
        notify_librarians(f"📘 Thesis uploaded & processed: {thesis.title}")
        print(f"📢 Notifying librarians: {thesis.title}")

    except Thesis.DoesNotExist:
        print(f"❌ Thesis with ID {thesis_id} does not exist.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        if 'tmp_path' in locals():
            try:
                os.remove(tmp_path)
                print(f"🧹 Temp file cleaned up: {tmp_path}")
            except Exception as e:
                print(f"⚠️ Failed to delete temp file: {e}")
