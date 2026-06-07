import os
import httpx
from typing import Optional

_client: Optional[httpx.AsyncClient] = None


def shared_async_client() -> Optional[httpx.AsyncClient]:
    """Return the process-wide httpx.AsyncClient with explicit proxy.

    Uses explicit proxy= arg instead of trust_env so that httpx 0.28's bug
    (trust_env + custom ssl.SSLContext → timeout through HTTPS CONNECT proxy)
    is avoided. Called lazily so the env vars are read after load_dotenv().
    """
    global _client
    if _client is None:
        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or ""
        )
        if proxy:
            _client = httpx.AsyncClient(
                proxy=proxy,
                follow_redirects=True,
                trust_env=False,
            )
        else:
            _client = httpx.AsyncClient(follow_redirects=True)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
