import logging

import httpx

logger = logging.getLogger(__name__)


async def write_weekly_summary(
    user_id: str,
    week_start: str,
    summary_text: str,
    memory_agent_url: str,
    http_client: httpx.AsyncClient,
) -> None:
    """Write a compressed weekly behavioral summary to the Memory Agent via HTTP POST.

    summary_text must be ≤500 chars.  Raises httpx.HTTPStatusError on failure;
    callers log the error and write a failed status to weekly_memory_writes.
    """
    if len(summary_text) > 500:
        summary_text = summary_text[:497] + "..."

    payload = {
        "user_id": user_id,
        "week_start": week_start,
        "summary": summary_text,
    }
    url = f"{memory_agent_url.rstrip('/')}/v1/memory/write-weekly"
    response = await http_client.post(url, json=payload, timeout=10.0)
    response.raise_for_status()
    logger.info("Weekly memory written for user %s week %s", user_id, week_start)
