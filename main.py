import os
from dotenv import load_dotenv

load_dotenv()

# ADK expects GOOGLE_API_KEY — always use GEMINI_API_KEY from .env
os.environ["GOOGLE_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

import uvicorn
from api.app import app

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
