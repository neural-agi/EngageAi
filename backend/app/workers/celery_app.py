"""Celery application skeleton."""

from celery import Celery


celery_app = Celery("engageai")

# TODO: configure broker, backend, and task routing.
