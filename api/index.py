"""Vercel entrypoint for the Brand OS FastAPI application."""
from apps.api.app.main import app

__all__ = ["app"]
