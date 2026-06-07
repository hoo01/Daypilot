import os
from dotenv import load_dotenv

load_dotenv()

# ADK expects GOOGLE_API_KEY, map from our GEMINI_API_KEY
if not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

# Ensure HTTPS_PROXY is visible to the process (falls back to .env setting)
if not os.environ.get("HTTPS_PROXY"):
    from config import settings
    if settings.https_proxy:
        os.environ["HTTPS_PROXY"] = settings.https_proxy
        os.environ.setdefault("HTTP_PROXY", settings.https_proxy)

# --- httpx proxy fix ---
# google-genai auto-creates an ssl.SSLContext and passes it to httpx.AsyncClient.
# httpx 0.28 bug: trust_env=True (reads HTTPS_PROXY) + custom SSLContext = timeout.
# Fix 1: force google-genai to use httpx, not aiohttp (aiohttp has TLS-in-TLS issues in Py3.13).
import google.genai._api_client as _genai_api_client
_genai_api_client.has_aiohttp = False

# Fix 2: patch google-adk's GoogleLLM.api_client to inject our shared httpx client
# (explicit proxy= arg, no custom SSLContext → bypasses the bug entirely).
from functools import cached_property as _cached_property
from google.adk.models.google_llm import Gemini as _GoogleLLM
from google.genai import types as _genai_types
from google.genai import Client as _GenaiClient
import http_client as _http_client


def _patched_api_client(self):
    base_url, api_version = self._base_url_and_api_version
    http_opts: dict = {
        "headers": self._tracking_headers(),
        "retry_options": self.retry_options,
        "base_url": base_url,
        "httpx_async_client": _http_client.shared_async_client(),
    }
    if api_version:
        http_opts["api_version"] = api_version
    kwargs: dict = {"http_options": _genai_types.HttpOptions(**http_opts)}
    if self.model.startswith("projects/"):
        kwargs["vertexai"] = True
    return _GenaiClient(**kwargs)


_prop = _cached_property(_patched_api_client)
_prop.__set_name__(_GoogleLLM, "api_client")
_GoogleLLM.api_client = _prop

import uvicorn
from api.app import app

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
