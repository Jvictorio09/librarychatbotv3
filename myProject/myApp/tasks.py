import os, json, tempfile, numpy as np, faiss
from pathlib import Path
from celery import shared_task
from openai import OpenAI
from dotenv import load_dotenv
from myApp.models import Thesis
from myApp.scripts.extract_text import extract_text_from_pdf
from myApp.scripts.vector_cache import (
    load_drive_service, upload_to_gdrive_folder,
    download_drive_file, get_latest_file_by_prefix
)
from myApp.scripts.embedding_utils import embed_text, chunk_text
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TMP_DIR = Path(tempfile.gettempdir())

def notify_librarians(message):
    async_to_sync(get_channel_layer().group_send)(
        "librarian_notify", {"type": "notify_upload_complete", "message": message}
    )

@shared_task
def process_thesis_task(thesis_id, version="v2"):
    try:
        thesis = Thesis.objects.get(pk=thesis_id)
        print(f"📘 [v{version}] Processing: {thesis.title}")

        # 📥 Download from Drive
        service = load_drive_service()
        pdf_path = download_drive_file(service, thesis.document, suffix=".pdf")

        # 🧠 Extract → Chunk → Embed
        text = extract_text_from_pdf(pdf_path)
        chunks = chunk_text(text)

        vectors, metadata = [], []
        for i, chunk in enumerate(chunks):
            emb = embed_text(chunk)
            vectors.append(np.array(emb, dtype=np.float32))
            metadata.append({
                "id": f"{thesis.id}_{i}",
                "title": thesis.title,
                "program": thesis.program.name,
                "year": thesis.year,
                "chunk": chunk
            })

        # 🧠 Index & Meta
        index_path = TMP_DIR / "thesis_index.faiss"
        meta_path = TMP_DIR / "metadata.json"
        dim = len(vectors[0])

        try:
            if not index_path.exists() or not meta_path.exists():
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

                if faiss_id and meta_id:
                    index = faiss.read_index(download_drive_file(service, faiss_id, ".faiss"))
                    with open(download_drive_file(service, meta_id, ".json")) as f:
                        existing_meta = json.load(f)
                else:
                    index = faiss.IndexFlatL2(dim)
                    existing_meta = []
            else:
                index = faiss.read_index(str(index_path))
                with open(meta_path, "r") as f:
                    existing_meta = json.load(f)

        except Exception as e:
            print(f"⚠️ Fresh index: {e}")
            index = faiss.IndexFlatL2(dim)
            existing_meta = []

        # ➕ Add vectors
        index.add(np.array(vectors))
        faiss.write_index(index, str(index_path))

        all_meta = existing_meta + [m for m in metadata if m["id"] not in {x["id"] for x in existing_meta}]
        with open(meta_path, "w") as f:
            json.dump(all_meta, f, indent=2)

        # ☁️ Upload vectors to Drive
        upload_to_gdrive_folder(index_path.read_bytes(), "thesis_index.faiss", "ja_vector_store")
        upload_to_gdrive_folder(meta_path.read_bytes(), "metadata.json", "ja_vector_store")

        # ✅ Notify
        notify_librarians(f"📘 Thesis processed: {thesis.title}")

        # 🧹 Cleanup
        os.remove(pdf_path)
        print(f"✅ Done for: {thesis.title}")

    except Exception as e:
        print(f"❌ Error processing thesis {thesis_id}: {e}")
