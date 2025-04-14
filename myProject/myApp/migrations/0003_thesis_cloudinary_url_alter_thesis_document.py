# Generated by Django 5.1.2 on 2025-04-10 10:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myApp', '0002_alter_thesis_document'),
    ]

    operations = [
        migrations.AddField(
            model_name='thesis',
            name='cloudinary_url',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='thesis',
            name='document',
            field=models.FileField(blank=True, null=True, upload_to='uploads/'),
        ),
    ]
