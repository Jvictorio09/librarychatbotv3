from django.contrib import admin
from django.utils.html import format_html
from django.core.files.storage import default_storage
from .models import Program, Thesis
from myApp.scripts.vector_cache import upload_to_gdrive_folder
from myApp.tasks import process_thesis_task  # ✅ use the correct Celery task

@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Thesis)
class ThesisAdmin(admin.ModelAdmin):
    list_display = ("title", "program", "year", "authors", "view_file", "uploaded_at")
    list_filter = ("program", "year")
    search_fields = ("title", "authors", "abstract")
    readonly_fields = ("gdrive_url",)

    def view_file(self, obj):
        if obj.gdrive_url:
            return format_html('<a href="{}" target="_blank">☁️ Google Drive</a>', obj.gdrive_url)
        elif obj.document and obj.document.url:
            return format_html('<a href="{}" target="_blank">📄 Local PDF</a>', obj.document.url)
        return "❌ No file uploaded"
    view_file.short_description = "Thesis File"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        try:
            if obj.document and obj.document.name:
                # 🔄 Load file from storage (e.g. S3, local, etc.)
                with default_storage.open(obj.document.name, 'rb') as doc_file:
                    file_data = doc_file.read()

                filename = f"{obj.title}.pdf"
                drive_url = upload_to_gdrive_folder(file_data, filename, obj.program.name)

                obj.gdrive_url = drive_url
                obj.save(update_fields=["gdrive_url"])

                # ✅ Queue for async embedding
                process_thesis_task.delay(obj.id)

                self.message_user(
                    request,
                    "✅ Uploaded to Google Drive and queued for embedding."
                )
            else:
                self.message_user(request, "⚠️ No document attached.", level='warning')

        except Exception as e:
            print(f"❌ Admin Upload Error: {e}")
            self.message_user(request, f"❌ Error uploading to Drive or processing: {e}", level='error')

    def has_add_permission(self, request):
        return True
