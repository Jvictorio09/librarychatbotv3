# myApp/admin.py

from django.contrib import admin
from django.utils.html import format_html
from .models import Program, Thesis

from myApp.scripts.vector_cache import upload_to_gdrive_folder


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
        # Save to DB first so we can access the file
        super().save_model(request, obj, form, change)

        try:
            if obj.document:
                # Read the file and upload it to Google Drive
                file_data = obj.document.read()
                filename = f"{obj.title}.pdf"
                drive_url = upload_to_gdrive_folder(file_data, filename, obj.program.name)

                # Save the generated Drive link
                obj.gdrive_url = drive_url
                obj.save(update_fields=["gdrive_url"])

                # Trigger background embedding
                process_thesis_async.delay(obj.id)

                self.message_user(
                    request,
                    "✅ Upload saved and sent to Google Drive. Background embedding is processing."
                )
            else:
                self.message_user(request, "⚠️ No file uploaded with this record.", level='warning')

        except Exception as e:
            print(f"❌ Admin Upload Error: {e}")
            self.message_user(request, f"❌ Error during upload or processing: {e}", level='error')

    def has_add_permission(self, request):
        return True  # Toggle this if you want to restrict uploads via the admin
