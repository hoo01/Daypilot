"""
Dynatrace MCP integration for the Coordinator agent.

Provides the coordinator with self-monitoring capabilities:
- Query traces, metrics, and logs from Dynatrace
- Check for active problems/anomalies
- Generate DQL queries from natural language

Controlled by DT_MODE environment variable:
  - "always":    Agent checks Dynatrace every turn (in before_agent_callback)
  - "on_demand": Agent can query Dynatrace when user asks or when relevant
  - "off":       Dynatrace tools not loaded
"""

import os

from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters
from telemetry import get_logger

_logger = get_logger("dynatrace_mcp")


def get_dynatrace_mcp() -> MCPToolset | None:
    """
    Create the Dynatrace MCP toolset if DT_MODE is not 'off'.
    Returns None if Dynatrace is disabled or credentials are missing.
    """
    dt_mode = os.environ.get("DT_MODE", "on_demand")
    if dt_mode == "off":
        _logger.info("Dynatrace MCP disabled (DT_MODE=off)")
        return None

    dt_env = os.environ.get("DT_ENVIRONMENT")
    oauth_client_id = os.environ.get("OAUTH_CLIENT_ID")
    oauth_client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    oauth_account_urn = os.environ.get("OAUTH_ACCOUNT_URN")

    if not all([dt_env, oauth_client_id, oauth_client_secret]):
        _logger.warning("Dynatrace MCP credentials incomplete — skipping")
        return None

    env = {
        **os.environ,
        "DT_ENVIRONMENT": dt_env,
        "OAUTH_CLIENT_ID": oauth_client_id,
        "OAUTH_CLIENT_SECRET": oauth_client_secret,
    }
    if oauth_account_urn:
        env["OAUTH_ACCOUNT_URN"] = oauth_account_urn

    _logger.info(f"Initializing Dynatrace MCP (mode={dt_mode}, env={dt_env})")

    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@dynatrace-oss/dynatrace-mcp-server@latest"],
                env=env,
            ),
        )
    )
