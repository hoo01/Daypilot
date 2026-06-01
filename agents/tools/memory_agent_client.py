import httpx


async def write_weekly_summary(
    user_id: str,
    week_start: str,
    summary_text: str,
    memory_agent_url: str,
    http_client: httpx.AsyncClient,
) -> None:
    """
    Write a compressed weekly behavioral summary to the Memory Agent via HTTP POST.

    Raises httpx.HTTPStatusError on 4xx/5xx; callers log and record failed status.
    """
    response = await http_client.post(
        f"{memory_agent_url}/memory/weekly-summary",
        json={
            "user_id": user_id,
            "week_start": week_start,
            "summary_text": summary_text,
        },
    )
    response.raise_for_status()
