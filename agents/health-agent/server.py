"""
server.py — uvicorn entrypoint for the Health Agent microservice.

Run with:
    python server.py

Or via uvicorn directly:
    uvicorn api.app:app --host 0.0.0.0 --port 8001 --reload
"""

import uvicorn
from config import settings
from api.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
    )
