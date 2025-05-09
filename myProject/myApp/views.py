import os
import json
import tempfile
from pathlib import Path

from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.utils.safestring import mark_safe

from myApp.scripts.semantic_search import answer_query
from myApp.scripts.vector_cache import (
    load_drive_service,
    get_latest_file_by_prefix,
    download_drive_file
)

# 🧠 Simple in-memory chat session (for dev/demo)
chat_memory = {}

# 🎨 Render the chatbot page
def chat_page(request):
    return render(request, "chatbot_app/chat.html")

@csrf_exempt
def chat_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are allowed.'}, status=405)

    try:
        message = None
        uploaded_text = None
        uploaded_file_path = None
        uploaded_file = None
        current_file_name = None
        gdrive_url = None
        file_scanned = False

        # 📦 Handle JSON or multipart
        if request.content_type.startswith('application/json'):
            data = json.loads(request.body)
            message = data.get('message', '').strip()
            gdrive_url = data.get('gdrive_url', '').strip()
        else:
            message = request.POST.get('message', '').strip()
            gdrive_url = request.POST.get('gdrive_url', '').strip()
            uploaded_file = request.FILES.get('file')

            if uploaded_file:
                current_file_name = uploaded_file.name
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(current_file_name)[1]) as tmp_file:
                    for chunk in uploaded_file.chunks():
                        tmp_file.write(chunk)
                    uploaded_file_path = tmp_file.name

                if not current_file_name.lower().endswith('.pdf'):
                    try:
                        uploaded_text = open(uploaded_file_path, 'r', encoding='utf-8', errors='ignore').read()
                    except Exception as e:
                        print(f"⚠️ Could not read uploaded file: {e}")
                        uploaded_text = None

        # 🧠 Manage session memory
        session_id = request.session.session_key or request.COOKIES.get('sessionid') or 'default'
        if session_id not in chat_memory:
            chat_memory[session_id] = []
            # ⏬ Refresh vector store from Drive
            try:
                service = load_drive_service()
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                meta_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")
                if faiss_id and meta_id:
                    download_drive_file(f"https://drive.google.com/file/d/{faiss_id}/view", suffix=".faiss")
                    download_drive_file(f"https://drive.google.com/file/d/{meta_id}/view", suffix=".json")
                    print("✅ Vector store refreshed for session.")
            except Exception as e:
                print(f"❌ Failed to update vector store: {e}")

        # 🔁 Reset session if file changes
        last_file_name = request.session.get('last_uploaded_filename')
        if current_file_name and current_file_name != last_file_name:
            chat_memory[session_id] = []
            request.session['last_uploaded_filename'] = current_file_name
            print(f"🔄 Memory cleared due to new file: {current_file_name}")

        # 💬 Ask KaAI
        reply, updated_history, file_scanned = answer_query(
            query=message or "[User uploaded a file]",
            session_history=chat_memory[session_id],
            uploaded_text=uploaded_text,
            uploaded_file_path=uploaded_file_path,
            gdrive_url=gdrive_url
        )

        chat_memory[session_id] = updated_history

        # 🧼 Clean up temp
        if uploaded_file_path and os.path.exists(uploaded_file_path):
            os.remove(uploaded_file_path)

        return JsonResponse({
            'reply': mark_safe(reply),
            'file_scanned': file_scanned
        })

    except Exception as e:
        print(f"❌ Chat API Error: {e}")
        return JsonResponse({'reply': '⚠️ Something went wrong. Please try again.'}, status=500)

from django.contrib.auth.models import User
from django.contrib.auth import login
from django.shortcuts import render, redirect

def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            return render(request, 'partials/signup.html', {'error': 'Passwords do not match.'})

        if User.objects.filter(username=username).exists():
            return render(request, 'partials/signup.html', {'error': 'Username already exists.'})

        if User.objects.filter(email=email).exists():
            return render(request, 'partials/signup.html', {'error': 'Email is already registered.'})

        user = User.objects.create_user(username=username, email=email, password=password1)
        login(request, user)  # Optional: log in user after signup
        return redirect('chat_page')  # or 'dashboard' if you want to skip login

    return render(request, 'partials/signup.html')



# app_name/views.py
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect

def signin_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('chat_page')  # Or any page you want to land on
        else:
            return render(request, 'partials/login.html', {
                'error': 'Invalid username or password.'
            })
    return render(request, 'partials/login.html')


from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.shortcuts import render, redirect
from django.urls import reverse
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.urls import reverse
from django.template.loader import render_to_string
from django.contrib.auth import logout
from django.contrib.auth import login
from django.contrib.auth.forms import SetPasswordForm


from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.shortcuts import render, redirect
from django.urls import reverse
from django.template.loader import render_to_string
from django.conf import settings

# 🔐 Step 1: Password Reset Request Form (User enters email)
def password_reset_request(request):
    context = {}

    if request.method == "POST":
        email = request.POST.get("email", "").strip()

        if not email:
            context['error'] = "Please enter your email address."
            return render(request, 'partials/password_reset.html', context)

        user = User.objects.filter(email__iexact=email).first()

        if user:
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            reset_url = request.build_absolute_uri(
                reverse('password_reset_confirm_custom', kwargs={'uidb64': uid, 'token': token})
            )

            subject = "KaAI Password Reset"
            from_email = settings.DEFAULT_FROM_EMAIL
            to_email = user.email
            text_content = f"Hi {user.username},\n\nClick the link below to reset your password:\n{reset_url}"
            html_content = render_to_string('partials/password_reset_email.html', {
                'user': user,
                'reset_url': reset_url,
            })

            try:
                email_msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
                email_msg.attach_alternative(html_content, "text/html")
                email_msg.send()
                print(f"✅ Password reset email sent to {to_email}")
            except Exception as e:
                print(f"❌ Error sending email: {e}")

            return redirect('password_reset_done_custom')
        else:
            context['error'] = "Sorry, we couldn’t find an account with that email."

    return render(request, 'partials/password_reset.html', context)



# 📧 Step 2: Confirmation screen after sending the email
def password_reset_done(request):
    return render(request, 'partials/password_reset_done.html')


from django.contrib.auth.forms import SetPasswordForm
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator

# 🔁 Step 3: Password Reset Link — Set new password
def password_reset_confirm(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "✅ Your password has been successfully changed. You may now log in.")
                return redirect('login')
            else:
                messages.error(request, "⚠️ Please correct the errors below.")
        else:
            form = SetPasswordForm(user)
        return render(request, 'partials/password_reset_confirm.html', {'form': form})
    else:
        messages.error(request, "❌ The password reset link is invalid or has expired.")
        return render(request, 'partials/password_reset_invalid.html')


# myApp/views.py
from django.core.paginator import Paginator
from myApp.models import Thesis, Program

def thesis_library(request):
    program_id = request.GET.get('program')
    search_query = request.GET.get('search', '')
    theses = Thesis.objects.all().order_by('-uploaded_at')

    if program_id:
        theses = theses.filter(program_id=program_id)

    if search_query:
        theses = theses.filter(title__icontains=search_query) | theses.filter(authors__icontains=search_query)

    paginator = Paginator(theses, 20)  # 20 per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'theses': page_obj,  # paginated result
        'programs': Program.objects.all(),
        'selected_program': Program.objects.filter(id=program_id).first() if program_id else None,
        'page_obj': page_obj,
    }
    return render(request, 'librarian/library_view.html', context)


from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from myApp.models import Program, Thesis
from myApp.scripts.cloud_embed_uploader import process_thesis_cloud



@login_required
def librarian_home(request):
    programs = Program.objects.all()
    return render(request, 'librarian/landing.html', {'programs': programs})

from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from myApp.models import Program, Thesis
from myApp.tasks import process_thesis_task  # ✅ Celery task for async processing

@login_required
def upload_thesis_view(request):
    if request.method == "POST":
        title = request.POST.get("title")
        authors = request.POST.get("authors")
        year = request.POST.get("year")
        program_id = request.POST.get("program")
        document = request.FILES.get("document")

        if not document:
            return HttpResponse("❌ No file uploaded.", status=400)

        try:
            program = Program.objects.get(id=program_id)

            thesis = Thesis.objects.create(
                title=title,
                authors=authors,
                year=year,
                program=program,
                document=document
            )

            # 🔁 Offload background processing
            process_thesis_task.delay(thesis.id, version="v1")

            return redirect("librarian_home")

        except Program.DoesNotExist:
            return HttpResponse("❌ Selected program does not exist.", status=404)
        except Exception as e:
            return HttpResponse(f"❌ Upload failed: {e}", status=500)

    return redirect("librarian_home")



@login_required
def create_librarian_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if not User.objects.filter(username=username).exists():
            user = User.objects.create_user(username=username, password=password)
            user.is_staff = True  # Mark as staff so they can access admin/librarian features
            user.save()
            return redirect('librarian_home')
        else:
            return HttpResponse("❌ Username already exists", status=400)

    return redirect('librarian_home')

from django.shortcuts import redirect
from django.contrib import messages
from myApp.models import Thesis
from myApp.scripts.vector_cache import (
    load_drive_service,
    get_latest_file_by_prefix,
    download_drive_file,
    upload_to_gdrive_folder,
    delete_drive_file_by_name
)
import json, faiss
from pathlib import Path
import tempfile
from django.contrib import messages
from django.shortcuts import redirect
from pathlib import Path
import tempfile, json, faiss

from myApp.models import Thesis
from myApp.scripts.vector_cache import (
    load_drive_service,
    get_latest_file_by_prefix,
    download_drive_file,
    upload_to_gdrive_folder,
    delete_drive_file_by_name
)

def delete_theses(request):
    if request.method == 'POST':
        ids = request.POST.getlist('thesis_ids')
        theses = Thesis.objects.filter(id__in=ids)
        TMP_DIR = Path(tempfile.gettempdir())

        try:
            service = load_drive_service()

            # 🔍 Try loading existing vector index and metadata
            try:
                faiss_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "thesis_index")
                json_id, _ = get_latest_file_by_prefix(service, "ja_vector_store", "metadata")

                if faiss_id and json_id:
                    faiss_path = download_drive_file(service, faiss_id, ".faiss")
                    meta_path = download_drive_file(service, json_id, ".json")

                    index = faiss.read_index(faiss_path)
                    with open(meta_path, "r") as f:
                        metadata = json.load(f)

                    # 🧠 Rebuild metadata
                    thesis_ids = {str(thesis.id) for thesis in theses}
                    new_metadata = [m for m in metadata if not any(tid in m["id"] for tid in thesis_ids)]

                    # 💾 Save & upload updated metadata
                    new_meta_path = TMP_DIR / "metadata.json"
                    with open(new_meta_path, "w") as f:
                        json.dump(new_metadata, f, indent=2)

                    upload_to_gdrive_folder(new_meta_path.read_bytes(), "metadata.json", "ja_vector_store")
                else:
                    print("⚠️ No index or metadata found. Skipping FAISS cleanup.")

            except Exception as e:
                print(f"⚠️ Failed to update FAISS/metadata: {e}")

            # 🗑 Delete files from Drive (if any)
            for thesis in theses:
                try:
                    if thesis.title:
                        delete_drive_file_by_name(service, f"{thesis.title}.pdf", thesis.program.name)
                except Exception as e:
                    print(f"⚠️ Could not delete Drive file for {thesis.title}: {e}")

        except Exception as e:
            print(f"⚠️ Drive service error: {e}")

        # ✅ Always delete from DB
        try:
            deleted_count, _ = theses.delete()
            messages.success(request, f"✅ Deleted {deleted_count} thesis record(s) successfully.")
        except Exception as e:
            messages.error(request, f"❌ Failed to delete thesis from database: {e}")

        return redirect(request.META.get('HTTP_REFERER', 'thesis_library'))

from django.shortcuts import redirect, get_object_or_404
from .models import Thesis, Program

from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from .models import Thesis, Program

def edit_thesis(request):
    if request.method == 'POST':
        thesis_id = request.POST.get('id')
        title = request.POST.get('title')
        authors = request.POST.get('authors')
        program_id = request.POST.get('program')
        year = request.POST.get('year')

        thesis = get_object_or_404(Thesis, id=thesis_id)

        thesis.title = title
        thesis.authors = authors

        if program_id:
            thesis.program = get_object_or_404(Program, id=program_id)

        thesis.year = year
        thesis.save()

        messages.success(request, "✅ Thesis updated successfully.")
        return redirect('thesis_library')  # replace with your URL name if different


from django.http import JsonResponse
from django.db.models import Q
from myApp.models import Thesis

def search_theses(request):
    query = request.GET.get("q", "")
    results = Thesis.objects.filter(
        Q(title__icontains=query) | Q(authors__icontains=query)
    ).values("id", "title", "authors", "program__name", "year", "gdrive_url")[:10]

    return JsonResponse(list(results), safe=False)


from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_staff)
def librarian_users(request):
    users = User.objects.all().order_by('username')
    return render(request, 'librarian_users.html', {'users': users})

@user_passes_test(lambda u: u.is_staff)
def revoke_user(request, user_id):
    if request.method == 'POST':
        user = User.objects.get(pk=user_id)
        user.is_active = False
        user.save()
    return redirect('librarian_users')

from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_staff)
def librarian_users(request):
    users = User.objects.all().order_by('username')
    return render(request, 'librarian/librarian_users.html', {'users': users})

@user_passes_test(lambda u: u.is_staff)
def revoke_user(request, user_id):
    if request.method == 'POST':
        user = User.objects.get(pk=user_id)
        user.is_active = False
        user.save()
    return redirect('librarian_users')

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

@csrf_exempt
@login_required
def ajax_change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Keep user logged in
            return JsonResponse({"success": True})
        else:
            errors = form.errors.as_json()
            return JsonResponse({"success": False, "errors": errors}, status=400)
    return JsonResponse({"error": "Invalid request"}, status=400)

import re
from django.shortcuts import render
from django.http import JsonResponse
from .models import Thesis, Program
from .scripts.extract_text import extract_text_from_pdf
from django.core.files.base import ContentFile
from .tasks import process_thesis_task

def bulk_upload_page(request):
    programs = Program.objects.all()
    return render(request, "librarian/bulk_upload.html", {"programs": programs})

import re
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from .models import Program, Thesis
from .tasks import process_thesis_task
from .scripts.extract_text import extract_text_from_pdf
from .scripts.vector_cache import upload_to_gdrive_folder

@login_required
def upload_thesis_view(request):
    if request.method == "POST":
        title = request.POST.get("title")
        authors = request.POST.get("authors")
        year = request.POST.get("year")
        program_id = request.POST.get("program")
        document = request.FILES.get("document")

        if not document:
            return HttpResponse("❌ No file uploaded.", status=400)

        try:
            program = Program.objects.get(id=program_id)
            file_data = document.read()

            # Upload to Drive FIRST
            gdrive_url = upload_to_gdrive_folder(file_data, document.name, program.name)

            thesis = Thesis.objects.create(
                title=title,
                authors=authors,
                year=year,
                program=program,
                document=document.name,  # ⛔ We only save the name!
                gdrive_url=gdrive_url
            )

            process_thesis_task.delay(thesis.id)
            return redirect("librarian_home")

        except Program.DoesNotExist:
            return HttpResponse("❌ Program not found", status=400)
        except Exception as e:
            return HttpResponse(f"❌ Error: {e}", status=500)

    return redirect("librarian_home")


import os
import json
import tempfile
import datetime
import traceback
import re

from django.http import JsonResponse
from .models import Program, Thesis
from .scripts.extract_text import extract_text_from_pdf
from .scripts.vector_cache import upload_to_gdrive_folder
from .tasks import process_thesis_task
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 🔍 Extract year from filename (e.g. "BSIT_Project_2022_Final.pdf")
import re
import json
import datetime

# 🎯 Extract year from filename
def extract_year_from_filename(filename):
    match = re.search(r"(20\d{2})", filename)
    if match:
        return int(match.group(1))
    return datetime.datetime.now().year

# 🧠 GPT-powered metadata extractor (no year)
def smart_metadata_extraction(text_excerpt, fallback_filename="Untitled.pdf"):
    prompt = f"""
You are an assistant that extracts metadata from academic research papers.

Given the following text excerpt from the first page of a PDF, extract:
- Title
- Authors
- Abstract

Respond ONLY in raw JSON like this:

{{
    "title": "...",
    "authors": "...",
    "abstract": "..."
}}

Text:
\"\"\"
{text_excerpt}
\"\"\"
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You extract metadata from academic research PDFs."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )

        content = response.choices[0].message.content.strip()

        # 🧼 Remove markdown formatting if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as err:
            print(f"⚠️ JSON parse error: {err} — attempting regex fallback.")
            parsed = {}
            for field in ["title", "authors", "abstract"]:
                match = re.search(rf'"{field}"\s*:\s*"([^"]+)"', content)
                if match:
                    parsed[field] = match.group(1)

        # 🛠️ Final fallback values
        title = parsed.get("title") or fallback_filename.replace(".pdf", "").replace("_", " ").strip().title()
        authors = parsed.get("authors", "Unknown Authors")
        if isinstance(authors, list):
            authors = ", ".join(authors)
        abstract = parsed.get("abstract", "No abstract found.")

        return {
            "title": title[:255],
            "authors": authors[:255],
            "abstract": abstract[:5000],
            "year": extract_year_from_filename(fallback_filename)
        }

    except Exception as e:
        print("❌ OpenAI extraction error:", e)
        raise



def bulk_upload_single(request):
    if request.method != 'POST' or not request.FILES.get("documents"):
        return JsonResponse({"status": "❌ Invalid Request", "success": False}, status=400)

    uploaded_file = request.FILES["documents"]
    file_data = uploaded_file.read()

    try:
        program_id = request.POST.get("program_id")
        if not program_id:
            return JsonResponse({"status": "❌ Missing Program ID", "success": False}, status=400)

        program = Program.objects.get(id=program_id)

        thesis = Thesis.objects.create(
            title="Processing...",
            authors="Processing...",
            abstract="Processing...",
            year=2000,
            program=program,
            document=uploaded_file.name,
            gdrive_url="pending",
            embedding_status="pending"
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            tmp_pdf.write(file_data)
            temp_pdf_path = tmp_pdf.name

        # ✅ Queue async metadata extraction + drive upload + embedding
        prepare_thesis_upload_task.delay(thesis.id, temp_pdf_path)

        return JsonResponse({
            "status": f"✅ Queued for processing: {uploaded_file.name}",
            "success": True,
            "thesis_id": thesis.id
        })

    except Program.DoesNotExist:
        return JsonResponse({"status": "❌ Program not found", "success": False}, status=404)
    except Exception:
        print("❌ Unexpected error:", traceback.format_exc())
        return JsonResponse({
            "status": f"❌ Unexpected error during upload: {uploaded_file.name}",
            "success": False
        }, status=500)


from django.http import JsonResponse
from .models import Thesis

def check_thesis_status(request, thesis_id):
    try:
        thesis = Thesis.objects.get(id=thesis_id)
        return JsonResponse({"status": thesis.embedding_status})
    except Thesis.DoesNotExist:
        return JsonResponse({"status": "not_found"}, status=404)



import os
import io
import json
import time
import faiss
import tempfile
import numpy as np
from pathlib import Path
from datetime import datetime
from django.http import JsonResponse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import os
import json
import tempfile
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Set your Google Drive API scopes
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Create a temporary directory
TMP_DIR = Path(tempfile.gettempdir())

# Load the service account JSON from environment variable
service_account_info = json.loads(os.environ["GDRIVE_SERVICE_JSON"])

# Write it to a temp file for Google API compatibility
with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as temp_file:
    json.dump(service_account_info, temp_file)
    temp_file.flush()  # Make sure the file is written
    SERVICE_ACCOUNT_FILE = temp_file.name

# Initialize credentials and the Drive API client
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=credentials)


VECTOR_FOLDER_NAME = "ja_vector_store"
FILES = {
    "metadata": "metadata.json",
    "index": "thesis_index.faiss",
}


def get_or_create_drive_folder(name):
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
    results = drive_service.files().list(q=query, spaces="drive", fields="files(id)").execute().get("files", [])
    return results[0]["id"] if results else None


def find_drive_file_id(filename, parent_id):
    query = f"name='{filename}' and '{parent_id}' in parents and trashed=false"
    response = drive_service.files().list(q=query, spaces="drive", fields="files(id, modifiedTime)").execute()
    return response.get("files", [None])[0]


def download_file_from_drive(file_id, local_path):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    with open(local_path, "wb") as f:
        f.write(fh.read())
    return local_path


def check_and_download_latest_files():
    parent_id = get_or_create_drive_folder(VECTOR_FOLDER_NAME)
    updated = False

    for key, filename in FILES.items():
        drive_file = find_drive_file_id(filename, parent_id)
        if not drive_file:
            print(f"❌ {filename} not found on Drive.")
            continue

        drive_time = datetime.strptime(drive_file['modifiedTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
        local_path = TMP_DIR / filename

        if not local_path.exists() or datetime.fromtimestamp(local_path.stat().st_mtime) < drive_time:
            print(f"⬇️ Downloading latest {filename} from Drive...")
            download_file_from_drive(drive_file["id"], local_path)
            updated = True
        else:
            print(f"✅ Using cached {filename}")

    return updated


# === MAIN VIEW ===

from django.views.decorators.csrf import csrf_exempt
from django.views import View
from django.http import HttpRequest

@csrf_exempt
def ensure_vector_files(request: HttpRequest):
    """Ensure metadata.json and thesis_index.faiss are available for AI processing."""
    try:
        updated = check_and_download_latest_files()
        return JsonResponse({
            "status": "ok",
            "updated": updated,
            "message": "Vector store and metadata ready."
        })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)

def classify_thesis_query(user_question, thesis_titles):
    prompt = f"""
You are a thesis assistant.

Classify the user's question into one of the following intent types:
- topic_search
- thesis_summary
- extract_section (e.g. abstract, conclusion, objectives)
- methodology_analysis
- author_info
- literature_review
- topic_suggestion
- writing_help
- translation
- citation_request
- critique
- comparison
- research_design
- other

Also return the title mentioned (if any), or keywords.

User Question: "{user_question}"

Available Thesis Titles:
{json.dumps(thesis_titles)}

Respond in JSON like:
{{
    "intent": "extract_section",
    "title": "Smart Irrigation System for Urban Farming",
    "section": "abstract",
    "keywords": ["irrigation", "urban farming"]
}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300
        )
        raw = response.choices[0].message.content.strip()

        # Strip code fence if wrapped in markdown
        if raw.startswith("```json"):
            raw = raw.replace("```json", "").replace("```", "").strip()

        if not raw.startswith("{"):
            print("⚠️ GPT returned non-JSON:", raw[:100])
            raise ValueError("Invalid response format from OpenAI")

        return json.loads(raw)

    except Exception as e:
        print("❌ classify_thesis_query failed:", e)
        return {
            "intent": "general_info",
            "title": "",
            "keywords": []
        }

@csrf_exempt
def ai_thesis_query_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only."}, status=405)

    try:
        if request.content_type == "application/json":
            data = json.loads(request.body)
            question = data.get("message") or data.get("question") or ""
        else:
            question = request.POST.get("message", "") or request.POST.get("question", "")
    except Exception as e:
        return JsonResponse({"error": f"Invalid request format: {e}"}, status=400)

    question = question.strip()
    if not question:
        return JsonResponse({"error": "Missing question."}, status=400)

    # Basic OpenAI response without database
    prompt = f"The user asked: '{question}'\nPlease respond helpfully as an academic research assistant."

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an academic assistant for thesis research."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=600
        )
        reply = response.choices[0].message.content.strip()
        print("✅ OPENAI REPLY:", repr(reply))

    except Exception as e:
        return JsonResponse({"error": f"OpenAI error: {e}"}, status=500)

    return JsonResponse({
        "answer": reply,
        "title_matched": None,
        "intent": "general_info",
        "loaded": False,
        "options": []
    })



import json
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
from openai import OpenAI

# 🔐 Load OpenAI key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

 
'''    
@csrf_exempt
def basic_ai_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed."}, status=405)

    try:
        data = json.loads(request.body)
        message = data.get("message", "").strip()
    except Exception as e:
        return JsonResponse({"error": f"Invalid JSON: {e}"}, status=400)

    if not message:
        return JsonResponse({"error": "Message is required."}, status=400)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful academic assistant."},
                {"role": "user", "content": message}
            ],
            temperature=0.5,
            max_tokens=600
        )
        answer = response.choices[0].message.content.strip()
        return JsonResponse({"answer": answer})
    except Exception as e:
        return JsonResponse({"error": f"OpenAI error: {e}"}, status=500)
'''


import json
import re
from openai import OpenAI
from dotenv import load_dotenv
import os
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import Thesis

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

INTENT_CATEGORIES = [
    "topic_search",
    "thesis_summary",
    "extract_section",
    "methodology_analysis",
    "author_info",
    "literature_review",
    "topic_suggestion",
    "writing_help",
    "translation",
    "citation_request",
    "critique",
    "comparison",
    "research_design",
    "general_info"

    "summary_request",
    "general_writing",
    "translation",
    "paraphrase",
]

def classify_intent(question, thesis_titles=None):
    thesis_titles = thesis_titles or []

    # 🧠 Add few-shot examples to help the model understand "Tell me more" requests
    examples = """
Example 1:
User's Question: "Tell me more about 'Barangay Bolo Services Management Information System'"
Response:
{
  "intent": "thesis_summary",
  "title": "Barangay Bolo Services Management Information System",
  "keywords": []
}

Example 2:
User's Question: "Do you have titles that include 'pharmacy'?"
Response:
{
  "intent": "topic_search",
  "title": null,
  "keywords": ["pharmacy"]
}

Example 3:
User's Question: "How can I improve their study?"
Response:
{
  "intent": "improvement_suggestion",
  "title": null,
  "keywords": []
}


Example 4:
User's Question: "Summarize the findings in 'Student Portal for Lipa City Science Integrated National High School'"
Response:
{
  "intent": "extract_section",
  "title": "Student Portal for Lipa City Science Integrated National High School",
  "keywords": [],
  "subtype": "findings"
}

Example 5:
User's Question: "What are the weaknesses of the thesis 'Barangay Masaguitsit Integrated Information Management System'?"
Response:
{
  "intent": "critique",
  "title": "Barangay Masaguitsit Integrated Information Management System",
  "keywords": [],
  "subtype": "weaknesses"
}

Example 6:
User's Question: "Give me research problems about online learning"
Response:
{
  "intent": "topic_suggestion",
  "title": null,
  "keywords": ["online learning"]
}

Example 7:
User's Question: "Is this study qualitative or quantitative: 'Spartner: Web-Based Messaging App to Find Study Partner'?"
Response:
{
  "intent": "research_design",
  "title": "Spartner: Web-Based Messaging App to Find Study Partner",
  "keywords": [],
  "subtype": "type"
}

Example 8:
User's Question: "Do you have a thesis with this title: Student Portal for Lipa City Science Integrated National High School"
Response:
{
  "intent": "thesis_summary",
  "title": "Student Portal for Lipa City Science Integrated National High School",
  "keywords": [],
  "subtype": null
}

Example 9:
User's Question: "Can you give me 3 citations they have on their study?"
Response:
{
  "intent": "extract_section",
  "title": null,
  "keywords": [],
  "subtype": "references"
}

Example 10:
User's Question: "Can you summarize the research titled 'Effects of Microplastics on Marine Life'?"
Response:
{
  "intent": "summary_request",
  "title": "Effects of Microplastics on Marine Life",
  "keywords": []
}



"""

    prompt = f"""
You are a helpful academic assistant.

Your task is to classify the user's question into one of the following intents:
{', '.join(INTENT_CATEGORIES)}

Also, if the user mentions a thesis title, extract it.
If not, extract keywords instead.

Respond in this JSON format:
{{
  "intent": "one_of_{INTENT_CATEGORIES}",
  "title": "Title if clearly mentioned, else null",
  "keywords": ["relevant", "keywords"]
}}

{examples}

User's Question:
"{question}"

Known Thesis Titles:
{json.dumps(thesis_titles[:100])}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a thesis query classifier."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=300
        )

        content = response.choices[0].message.content.strip()

        # ✅ NEW: Clean triple backticks if model wraps output like ```json ... ```
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()

        print(f"[KaAI CLASSIFIER RAW OUTPUT] {content}")  # 🧾 Debug print
        return json.loads(content)

    except Exception as e:
        print(f"[KaAI DEBUG] JSON decode failed: {e}")
        return {
            "intent": "general_info",
            "title": None,
            "keywords": []
        }

@csrf_exempt
def kaai_thesis_lookup(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    try:
        data = json.loads(request.body)
        message = data.get("message", "").strip()
    except Exception as e:
        return JsonResponse({"error": f"Invalid request: {e}"}, status=400)

    if not message:
        return JsonResponse({"error": "Missing message."}, status=400)

    GREETING_ONLY = {"hi", "hello", "hey", "yo", "goodmorning", "goodafternoon", "good evening", "sup", "whats up"}
    if message.lower() in GREETING_ONLY:
        return JsonResponse({
            "answer": "👋 Hello! How can I assist you today? You can ask me for thesis topics, summaries, or help with writing. Just let me know!",
            "source": "greeting"
        })

    thesis_qs = Thesis.objects.all()
    thesis_titles = [t.title for t in thesis_qs]
    classification = classify_intent(message, thesis_titles=thesis_titles)

    intent = classification.get("intent")
    title = classification.get("title")
    keywords = classification.get("keywords")
    subtype = classification.get("subtype")
    keyword_matches = []

    # Check if there's a user-uploaded file
    user_uploaded_text = request.session.get("uploaded_file_text")
    uploaded_filename = request.session.get("uploaded_filename")
    if user_uploaded_text:
        prompt = f"""
    You are an academic assistant helping the user understand their uploaded document.

    Filename: {uploaded_filename}

    Full content:
    {user_uploaded_text}

    User's question: "{message}"
    """
        ai = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant analyzing the user's uploaded document."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=850
        )
        return JsonResponse({
            "answer": ai.choices[0].message.content.strip(),
            "source": "user_upload_analysis"
        })


    if intent == "topic_search" and keywords:
        keyword_matches = [t for t in thesis_qs if any(kw in t.title.lower() for kw in keywords)]
    if keyword_matches:
        request.session["last_matched_thesis_id"] = keyword_matches[0].id
        response_text = "Here are some theses that match your query:\n"
        for t in keyword_matches[:8]:
            response_text += f"\n📁 \"{t.title}\"\n🕋️ by {t.authors}\n📚 {t.program.name} ({t.year})\n<button class='quick-followup' data-title=\"{t.title}\">📄 Tell me more</button>\n"
        return JsonResponse({
            "answer": response_text.strip(),
            "source": "db_keyword_match",
            "title_matched": keyword_matches[0].title
        })

    # If title wasn't detected, fallback to the last known matched thesis
    if not title and "last_matched_thesis_id" in request.session:
        try:
            last_thesis = Thesis.objects.get(id=request.session["last_matched_thesis_id"])
            title = last_thesis.title
            print(f"[KaAI DEBUG] Fallback to last known title: {title}")
        except Thesis.DoesNotExist:
            print("[KaAI DEBUG] No valid last_matched_thesis_id in session.")



    print(f"[KaAI DEBUG] Intent: {intent}\nTitle: {title}\nKeywords: {keywords}")

    chat_history = request.session.get("chat_history", [])
    chat_history.append({"user": message})
    chat_history = chat_history[-5:]
    request.session["chat_history"] = chat_history

    # === If user mentioned exact or partial title ===
    if title:
        t = None
        try:
            t = Thesis.objects.get(title__iexact=title)
        except Thesis.DoesNotExist:
            candidates = Thesis.objects.filter(title__icontains=title)
            t = candidates.first() if candidates.exists() else None

        if t:
            request.session["last_matched_thesis_id"] = t.id

            # 🧠 Lazy load and cache the full thesis content
            if t.gdrive_url:
                cached_text = request.session.get("cached_pdf_text")
                if not cached_text:
                    pdf_path = download_pdf_to_temp(t.gdrive_url)
                    if pdf_path:
                        full_text = extract_text_from_pdf(pdf_path)
                        os.remove(pdf_path)
                        request.session["cached_pdf_text"] = full_text
                        print("[KaAI DEBUG] PDF cached for follow-up.")
                    else:
                        print("[KaAI DEBUG] Failed to download PDF for caching.")
                else:
                    print("[KaAI DEBUG] Using cached PDF content for follow-up.")

        followup_prompt = f"""
Please provide a detailed and helpful explanation about the following thesis:

Title: {t.title}
Authors: {t.authors}
Program: {t.program.name}
Year: {t.year}

Abstract:
{t.abstract}

The user asked: '{message}'
"""

        ai = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a research assistant helping summarize and explain thesis projects."},
                {"role": "user", "content": followup_prompt}
            ],
            temperature=0.5,
            max_tokens=900
        )
        return JsonResponse({
            "answer": ai.choices[0].message.content.strip(),
            "title_matched": t.title,
            "source": "openai_title_summary"
        })
    else:
        print(f"[KaAI DEBUG] No thesis matched for title: {title}")


    # === Keyword-based match ===
    keyword_matches = [t for t in thesis_qs if any(kw in t.title.lower() for kw in keywords)] if keywords else []
    if keyword_matches:
        request.session["last_matched_thesis_id"] = keyword_matches[0].id
        response_text = "Here are some theses that match your query:\n"
        for t in keyword_matches[:8]:
            response_text += f"\n📁 \"{t.title}\"\n🕋️ by {t.authors}\n📚 {t.program.name} ({t.year})\n<button class='quick-followup' data-title=\"{t.title}\">\ud83d\udcc4 Tell me more</button>\n"
        print(f"[KaAI DEBUG] Keyword-based matches: {len(keyword_matches)}")
        return JsonResponse({
            "answer": response_text.strip(),
            "source": "db_keyword_match",
            "title_matched": keyword_matches[0].title
        })

    # === Generic handler for intent-based follow-ups (summary, methodology, etc.) ===
    INTENT_PROMPTS = {
        "thesis_summary": "You are a research assistant. The user is asking for a summary of a specific thesis.",
        "methodology_analysis": "You are a research assistant. The user is asking about the methodology of a specific thesis. Only respond with methodology details.",
        "author_info": "You are a research assistant. The user is asking who the authors of a specific thesis are. Just return the authors and nothing else.",
        "tech_stack": "You are a research assistant. The user wants to know what technologies were used to develop this thesis project. Respond only with the tech stack or platform mentioned.",

        "extract_section::findings": "Extract and summarize the findings of the thesis below.",
        "extract_section::abstract": "Provide the abstract of the thesis below.",
        "extract_section::conclusion": "Return the conclusion of the thesis below.",
        "extract_section::objectives": "State the objectives of the thesis below.",
        "critique::weaknesses": "What are the weaknesses or limitations of this study?",
        "critique::strengths": "List the strengths or advantages of this research.",
        "research_design::type": "Identify whether the thesis is qualitative, quantitative, or mixed-method.",
        "improvement_suggestion": "Suggest improvements to strengthen the thesis below.",

        "critique:limitations": "You are a research assistant. The user is asking about the **limitations** of a specific thesis. Only extract and explain the limitations.",
        "extract_section:findings": "You are a research assistant. The user is asking for the **findings** section of a specific thesis. Respond with that section only.",
        "extract_section:abstract": "You are a research assistant. The user is asking for the abstract of a specific thesis. Respond with just the abstract.",
        "research_design:type": "You are a research assistant. The user wants to know if this is a qualitative, quantitative, or mixed-method study. Only say the type and give a brief justification.",

        "extract_section:significance": "The user is asking about the significance of a specific thesis. Extract the significance and explain its importance in the context of the community, education, or technology.",
        
    }

    GENERAL_HELPER_PROMPTS = {
    "summary_request": "You are a research assistant. Summarize the study title or topic provided.",
    "general_writing": "You are an academic coach. Help the user write or improve their research document.",
    "translation": "You are a language translator. Translate the content clearly and professionally.",
    "paraphrase": "You are a skilled paraphraser. Rewrite the given content in simpler or more professional terms.",
    "topic_suggestion": "You are a thesis coach. Suggest 5 research titles or problems related to the topic.",
}


    intent_key = f"{intent}::{subtype}" if subtype else intent

    DEEP_PDF_SUBTYPES = {
        "significance", "scope", "limitations", "references", "research_gap", "assumptions",
        "strengths", "weaknesses", "sampling", "statistical_tools", "variables",
        "research_questions", "framework", "main_theme", "concepts", "arguments",
        "hypotheses", "author_background", "respondents", "instruments", "process",
        "chapter_outline", "data_analysis_chapter"
    }

    if intent in GENERAL_HELPER_PROMPTS:
        followup_prompt = f"""
    {GENERAL_HELPER_PROMPTS[intent]}

    User message: '{message}'
    """
        ai = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GENERAL_HELPER_PROMPTS[intent]},
                {"role": "user", "content": followup_prompt}
            ],
            temperature=0.5,
            max_tokens=800
        )
        return JsonResponse({
            "answer": ai.choices[0].message.content.strip(),
            "source": f"general_{intent}"
        })



    if intent == "extract_section" or (intent in {"critique", "research_design", "citation_request"} and subtype in DEEP_PDF_SUBTYPES):
        try:
            t = Thesis.objects.get(id=request.session["last_matched_thesis_id"])
            if not t.gdrive_url:
                return JsonResponse({
                    "answer": "This thesis has no file available for content lookup.",
                    "source": "missing_file"
                })

            # ⛳️ ⬇️ INSERT THIS BLOCK HERE
            full_text = request.session.get("cached_pdf_text")

            if not full_text:
                pdf_path = download_pdf_to_temp(t.gdrive_url)
                if not pdf_path:
                    return JsonResponse({
                        "answer": "Sorry, I couldn't fetch the thesis document right now.",
                        "source": "download_failed"
                    })

                full_text = extract_text_from_pdf(pdf_path)
                os.remove(pdf_path)
                request.session["cached_pdf_text"] = full_text

            prompt = f"""
You are a research assistant. Based on the full thesis content below, extract and explain the **{subtype}**.

Title: {t.title}
Authors: {t.authors}
Program: {t.program.name}
Year: {t.year}

--- FULL THESIS TEXT START ---
{full_text}
--- FULL THESIS TEXT END ---
"""
            ai = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=850
            )
            return JsonResponse({
                "answer": ai.choices[0].message.content.strip(),
                "source": f"lazy_pdf::{subtype}"
            })

        except Exception as e:
            print(f"[KaAI ERROR] Lazy PDF extract failed: {e}")
            return JsonResponse({
                "answer": "Something went wrong while reading the file.",
                "source": "pdf_parse_error"
            })

    if intent_key in INTENT_PROMPTS and "last_matched_thesis_id" in request.session:

        try:
            t = Thesis.objects.get(id=request.session["last_matched_thesis_id"])
            followup_prompt = f"""
{INTENT_PROMPTS[intent_key]}


Title: {t.title}
Authors: {t.authors}
Program: {t.program.name}
Year: {t.year}

Abstract:
{t.abstract}

User message: '{message}'
"""
            ai = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": INTENT_PROMPTS[intent_key]},
                    {"role": "user", "content": followup_prompt}
                ],
                temperature=0.4,
                max_tokens=900
            )
            return JsonResponse({
                "answer": ai.choices[0].message.content.strip(),
                "source": f"followup_openai_{intent}"
            })
        except Thesis.DoesNotExist:
            print(f"[KaAI DEBUG] Could not retrieve thesis for intent: {intent}")

    # === Fallback ===
    combined_context = "\n".join([f"User: {m['user']}" for m in chat_history])
    fallback_prompt = f"{combined_context}\nUser: {message}\nPlease answer helpfully as a research assistant."

    ai = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful academic assistant."},
            {"role": "user", "content": fallback_prompt}
        ],
        temperature=0.5,
        max_tokens=900
    )
    print("[KaAI DEBUG] Fallback triggered.")
    return JsonResponse({
        "answer": ai.choices[0].message.content.strip(),
        "source": "openai_fallback"
    })


import tempfile
import fitz  # PyMuPDF
import requests

def download_pdf_to_temp(gdrive_url):
    """Download the PDF from Google Drive link into a temp file and return its path."""
    try:
        response = requests.get(gdrive_url)
        if response.status_code == 200:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.write(response.content)
            temp_file.flush()
            return temp_file.name
        else:
            print(f"[KaAI DEBUG] Failed to download PDF: {response.status_code}")
            return None
    except Exception as e:
        print(f"[KaAI ERROR] Exception in download_pdf_to_temp: {e}")
        return None

def extract_text_from_pdf(pdf_path):
    """Extract plain text from the entire PDF using PyMuPDF."""
    text = ""
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        print(f"[KaAI ERROR] Failed to extract text: {e}")
        return ""


from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils.text import get_valid_filename

@csrf_exempt
def kaai_user_upload(request):
    if request.method == "POST" and request.FILES.get("file"):
        uploaded_file = request.FILES["file"]
        filename = get_valid_filename(uploaded_file.name)

        # Save temporarily
        temp_path = default_storage.save(f"temp_uploads/{filename}", ContentFile(uploaded_file.read()))
        full_path = os.path.join(default_storage.location, temp_path)

        # Extract text
        if filename.endswith(".pdf"):
            text = extract_text_from_pdf(full_path)
        elif filename.endswith(".txt"):
            text = open(full_path, "r", encoding="utf-8").read()
        elif filename.endswith(".docx"):
            from docx import Document
            doc = Document(full_path)
            text = "\n".join([para.text for para in doc.paragraphs])
        else:
            return JsonResponse({"error": "Unsupported file format"}, status=400)

        # Store in session
        request.session["uploaded_file_text"] = text
        request.session["uploaded_filename"] = filename
        return JsonResponse({"status": "ok", "filename": filename})
    
    return JsonResponse({"error": "No file received"}, status=400)
