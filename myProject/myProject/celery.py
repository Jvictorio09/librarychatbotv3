# myProject/celery.py

import os
from celery import Celery
from dotenv import load_dotenv

# Load environment variables from .env manually
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Set default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myProject.settings')

app = Celery('myProject', broker='redis://localhost:6379/0')

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
