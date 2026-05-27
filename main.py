import os
from dotenv import load_dotenv

load_dotenv()

# ADK expects GOOGLE_API_KEY, map from our GEMINI_API_KEY
if not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

import uvicorn
from api.app import app

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
