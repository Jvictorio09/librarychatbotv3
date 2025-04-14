# Generated by Django 5.1.2 on 2025-04-03 10:27

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Program',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='Thesis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('authors', models.CharField(max_length=255)),
                ('year', models.PositiveIntegerField()),
                ('abstract', models.TextField(blank=True)),
                ('document', models.FileField(upload_to='theses/')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='myApp.program')),
            ],
        ),
    ]
