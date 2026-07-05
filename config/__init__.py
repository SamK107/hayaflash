# Expose the Celery app so that `celery -A config` works.
from .celery import app as celery_app

__all__ = ["celery_app"]
