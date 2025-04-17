# myProject/celery.py

import os
from celery import Celery

# ✅ Set default Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myProject.settings")

# ✅ Create Celery app
app = Celery("myProject")

# ✅ Load config from Django settings with CELERY_ prefix
app.config_from_object("django.conf:settings", namespace="CELERY")

# ✅ Discover tasks from all registered apps
app.autodiscover_tasks()
