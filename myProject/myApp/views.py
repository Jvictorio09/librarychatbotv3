# myApp/views.py

import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from myApp.models import Thesis

from myApp.scripts.semantic_search import answer_query

def chat_page(request):
    return render(request, "chatbot_app/chat.html")

@csrf_exempt
def chat_api(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST requests are allowed.")

    try:
        data = json.loads(request.body)
        user_question = data.get("message")

        if not user_question:
            return JsonResponse({"reply": "❗Please enter a message before sending."}, status=400)

        print(f"📩 Incoming message: {user_question}")
        response = answer_query(user_question)
        return JsonResponse({"reply": response})

    except json.JSONDecodeError:
        return JsonResponse({"reply": "⚠️ Invalid request format."}, status=400)
    except Exception as e:
        print(f"❌ Chat API Error: {e}")
        return JsonResponse({"reply": "Sorry, something went wrong. Please try again."}, status=500)


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
                return redirect('login')
        else:
            form = SetPasswordForm(user)
        return render(request, 'partials/password_reset_confirm.html', {'form': form})
    else:
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


def extract_metadata_from_text(text):
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    title, authors, abstract = "", "", ""

    for i, line in enumerate(lines):
        if not title and len(line.split()) > 4:
            title = line
        if not authors and ("By" in line or "Author" in line):
            authors = lines[i + 1] if i + 1 < len(lines) else line
        if "ABSTRACT" in line.upper():
            abstract = "\n".join(lines[i + 1:i + 5])
            break

    return title[:255], authors[:255], abstract


def bulk_upload_single(request):
    if request.method == 'POST' and request.FILES.get("documents"):
        uploaded_file = request.FILES["documents"]
        file_data = uploaded_file.read()

        try:
            program_id = request.POST.get("program_id")
            program = Program.objects.get(id=program_id)

            # Save temp, extract metadata
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(file_data)

            text = extract_text_from_pdf(temp_path)
            title, authors, abstract = extract_metadata_from_text(text)
            year_match = re.search(r"(19|20)\d{2}", uploaded_file.name)
            year = int(year_match.group()) if year_match else 0

            gdrive_url = upload_to_gdrive_folder(file_data, uploaded_file.name, program.name)

            thesis = Thesis.objects.create(
                title=title or uploaded_file.name,
                authors=authors or "Unknown",
                abstract=abstract or "",
                year=year,
                program=program,
                document=uploaded_file.name,  # 👈 Store just name
                gdrive_url=gdrive_url
            )

            process_thesis_task.delay(thesis.id)
            return JsonResponse({"status": "✅ Queued", "success": True})

        except Exception as e:
            return JsonResponse({"status": f"❌ {e}", "success": False}, status=500)

    return JsonResponse({"status": "❌ Invalid Request", "success": False}, status=400)
