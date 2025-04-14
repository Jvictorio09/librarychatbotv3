from django.contrib import admin
from django.utils.html import format_html
from .models import Program, Thesis
from myApp.scripts.embed_and_store import process_thesis_locally


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Thesis)
class ThesisAdmin(admin.ModelAdmin):
    list_display = ("title", "program", "year", "authors", "view_file", "uploaded_at")
    list_filter = ("program", "year")
    search_fields = ("title", "authors", "abstract")
    readonly_fields = ("gdrive_url",)  # Display the GDrive URL but not editable

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
            process_thesis_locally(obj)
        except Exception as e:
            print(f"❌ Error during processing thesis: {e}")

    def has_add_permission(self, request):
        # Optional: Disable manual add if mass upload is preferred
        return False
