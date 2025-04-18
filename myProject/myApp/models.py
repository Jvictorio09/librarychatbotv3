from django.db import models

class Program(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Thesis(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    title = models.CharField(max_length=255)
    authors = models.CharField(max_length=255)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    abstract = models.TextField(blank=True)
    document = models.FileField(upload_to='uploads/', blank=True, null=True)  # Local
    gdrive_url = models.URLField(blank=True, null=True)
    embedding_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.program} - {self.year})"
