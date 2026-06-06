# Dynatrace Observability for DayPilot

> Full-stack OpenTelemetry instrumentation with Dynatrace as the backend. Every agent call, every LLM invocation, every health pipeline node, and every HTTP request is traced, metered, and logged.

---

## Why Dynatrace?

DayPilot is an agentic system — a coordinator agent that orchestrates tools, sub-agents, and LLM calls across multiple turns. When something is slow or broken, you can't just check a single endpoint. You need distributed traces that show:

- Which tool took 4 seconds inside a 6-second chat response?
- Is the health pipeline's LLM call retrying due to malformed JSON?
- How often does the relationship context cache miss?
- What's the P95 latency of `plan_schedule` across all users?

Dynatrace provides this via native OTLP ingest — we export OpenTelemetry traces, metrics, and logs directly to the Dynatrace platform with zero proprietary agents.

---

## Architecture Overview

```
                        ┌─────────────────────────────────┐
                        │         Dynatrace Tenant        │
                        │  (Traces / Metrics / Logs)      │
                        └──────────────▲──────────────────┘
                                       │ OTLP/HTTP
                                       │
┌──────────────────────────────────────┴───────────────────────────────────┐
│                          DayPilot Application                           │
│                                                                         │
│  main.py                                                                │
│    └── import telemetry  ← initializes OTel SDK globally                │
│                                                                         │
│  telemetry/                                                             │
│    ├── setup.py          ← TracerProvider, MeterProvider, LoggerProvider │
│    ├── instrument.py     ← @traced_tool, @traced_llm, @traced_node      │
│    ├── middleware.py      ← FastAPI HTTP middleware                      │
│    └── __init__.py        ← public API: tracer, meter, get_logger       │
│                                                                         │
│  agents/dynatrace_mcp.py ← MCP server for self-monitoring              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## What Gets Instrumented

### 1. HTTP Layer (`telemetry/middleware.py`)

Every incoming FastAPI request (except `/health`) is automatically traced.

| What | How |
|---|---|
| **Span** | One span per request with `SpanKind.SERVER` |
| **Attributes** | `http.method`, `http.route`, `http.url`, `http.status_code` |
| **Metrics** | `http.server.request.duration` (histogram, ms), `http.server.request.count` (counter), `http.server.error.count` (counter, 4xx/5xx only) |
| **Logs** | `GET /chat → 200 (342ms)` pattern for every request |

### 2. Agent Tools (`telemetry/instrument.py` — `@traced_tool`)

Every tool the coordinator can call is wrapped with `@traced_tool("tool_name")`. This decorator:

- Creates a span: `tool.{name}` (e.g., `tool.plan_schedule`)
- Extracts `user_id` from function arguments for attribution
- Captures the tool's return value (first 4 KB) as a span event
- Records duration, call count, and error count as metrics

**Instrumented tools:**

| Tool | Span Name | What It Does |
|---|---|---|
| `read_user_context` | `tool.read_user_context` | Loads preferences, goals, events from MongoDB |
| `write_entity_to_memory` | `tool.write_entity_to_memory` | Persists extracted entities to Knowledge Graph |
| `clear_pending_reschedule` | `tool.clear_pending_reschedule` | Clears rescheduled task flags |
| `store_conversation_memory` | `tool.store_conversation_memory` | Embeds and stores conversation insights |
| `retrieve_relevant_memories` | `tool.retrieve_relevant_memories` | Semantic vector search over past conversations |
| `get_relationship_context` | `tool.get_relationship_context` | Surfaces upcoming important dates |
| `plan_schedule` | `tool.plan_schedule` | Generates 3 daily schedule strategies |
| `adjust_schedule` | `tool.adjust_schedule` | Real-time schedule replanning |
| `track_goals` | `tool.track_goals` | Goal progress assessment via Gemini |
| `get_geo_info` | `tool.get_geo_info` | Multi-segment commute via Google Routes API |

**Metrics emitted per tool call:**

| Metric | Type | Description |
|---|---|---|
| `agent.tool.duration` | Histogram (ms) | Execution time per tool |
| `agent.tool.calls` | Counter | Total invocations (labeled by tool name, status) |
| `agent.tool.errors` | Counter | Error count by tool name |

### 3. LLM Calls (`telemetry/instrument.py` — `@traced_llm`)

Every Gemini invocation is wrapped with `@traced_llm(model, operation)`. This follows the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

| What | How |
|---|---|
| **Span** | `genai.{operation}` (e.g., `genai.generate`) |
| **Attributes** | `gen_ai.system` = "gemini", `gen_ai.request.model`, `gen_ai.operation.name` |
| **Metrics** | `genai.request.duration` (histogram, ms), `genai.requests` (counter) |
| **Events** | LLM response text (first 4 KB) captured as span event |

### 4. Health Pipeline Nodes (`telemetry/instrument.py` — `@traced_node`)

The PsychoBio health pipeline has 4 nodes executed in sequence. Each is instrumented:

#### Node 1 — HealthKit Sentinel (`healthkit_sentinel.py`)

Detects biometric anomalies from HealthKit data (HRV suppression, sleep fragmentation, resting HR spikes).

| What | Details |
|---|---|
| **Span** | `health.node1.healthkit_sentinel` |
| **Attributes** | `pipeline.node`, `health.target_date`, `node1.cold_start`, `node1.hrv_suppressed`, `node1.sleep_fragmented`, `node1.duration_ms` |
| **Events** | Flag summary (which biometric flags were raised) |

#### Node 2 — Strava Contextualizer (`strava_contextualizer.py`)

Analyzes training load (ATL/CTL/TSB), identifies sport types, and detects affective fatigue keywords.

| What | Details |
|---|---|
| **Logging** | Structured logs via `get_logger("health.node2")` |
| **Tracing** | Wrapped by graph orchestrator |

#### Node 3 — Autonomic Decoupler (`autonomic_decoupler.py`)

Deterministic rule engine (no LLM) that classifies fatigue as PSYCHOLOGICAL, PHYSICAL, NONE, or AMBIGUOUS based on PSI/PLI scores.

| What | Details |
|---|---|
| **Metrics** | `health.psi` (histogram) — Psychological Strain Index values |
| | `health.pli` (histogram) — Physical Load Index values |
| | `health.verdict` (counter) — Verdict distribution across classifications |
| **Logging** | Structured logs via `get_logger("health.node3")` |

#### Node 4 — Insights Engine (`insights_engine.py`)

Generates the final psychobiological assessment via Gemini LLM.

| What | Details |
|---|---|
| **Metrics** | `health.node4.duration` (histogram, ms) — LLM call latency |
| | `health.node4.retries` (counter) — JSON parsing retry count |
| **Logging** | Structured logs via `get_logger("health.node4")` |

#### Pipeline Orchestrator (`graph_orchestrator.py`)

Runs the full Node 1 → 2 → 3 → 4 pipeline.

| What | Details |
|---|---|
| **Span** | `health.pipeline.execute` |
| **Attributes** | `user.id`, `health.target_date`, `health.pipeline.events`, `health.pipeline.duration_ms`, `health.pipeline.verdict` |
| **Metrics** | `health.pipeline.duration` (histogram, ms) |
| **Events** | Final state: verdict, classification, insight summary, PSI, PLI |

### 5. Coordinator Context Preload (`coordinator.py`)

Before every chat turn, the coordinator pre-loads user context in parallel via `asyncio.gather`. This preload is fully traced:

| What | Details |
|---|---|
| **Span** | `coordinator.preload_context` |
| **Attributes** | `user.id`, `context.parts_count`, `context.{component}.error` (per-component failure flags) |
| **Metrics** | `coordinator.context_load.duration` (histogram, ms), `coordinator.context_load.errors` (counter) |
| **Events** | Final assembled context snapshot |

### 6. Chat Endpoint (`api/routes/chat.py`)

The main `/chat/` endpoint has dedicated instrumentation beyond the HTTP middleware:

| What | Details |
|---|---|
| **Span** | `chat.handle_request` |
| **Attributes** | `user.id`, `session.id`, `chat.message_length`, `session.is_new` |
| **Metrics** | `chat.duration` (histogram, ms), `chat.llm.duration` (histogram, ms), `chat.memory_consolidation` (counter) |
| **Background** | Memory consolidation runs as a background task with its own span `chat.memory_consolidation` |

### 7. Health Tool Entry Point (`agents/tools/health_tools.py`)

The `analyze_health()` tool (called during preload) has its own instrumentation layer on top of the pipeline:

| What | Details |
|---|---|
| **Span** | `health.run_pipeline` |
| **Attributes** | `user.id`, `health.scenario`, `health.target_date`, `health.verdict`, `health.psi`, `health.pli`, `health.duration_ms` |
| **Metrics** | `health.duration` (histogram, ms), `health.cache_hits` (counter), `health.pipeline_errors` (counter) |

---

## Dynatrace MCP — Self-Monitoring Agent

Beyond passive telemetry export, DayPilot's coordinator agent can **actively query Dynatrace** about its own performance using the [Dynatrace MCP Server](https://github.com/dynatrace-oss/dynatrace-mcp-server).

### What Is It?

The Dynatrace MCP server (`@dynatrace-oss/dynatrace-mcp-server`) is loaded as an MCP toolset inside the coordinator. This gives the AI agent direct access to:

- **DQL query generation** — natural language → Dynatrace Query Language
- **DQL execution** — run queries against traces, metrics, and logs
- **Problem detection** — list active Dynatrace problems
- **Entity search** — find monitored entities by name
- **Davis AI** — invoke Davis Copilot for root cause analysis

### How It Works

```python
# agents/dynatrace_mcp.py
async def get_dynatrace_mcp() -> MCPToolset | None:
    """Load Dynatrace MCP server for coordinator self-monitoring."""
    tools, exit_stack = await MCPToolset.from_server(
        connection_params=StdioServerParameters(
            command="npx",
            args=["-y", "@dynatrace-oss/dynatrace-mcp-server@latest"],
            env={...}  # DT_ENVIRONMENT, OAUTH credentials
        )
    )
    return tools
```

The coordinator's system instruction includes guidance to use these tools for self-monitoring — checking its own latency, error rates, and token usage.

### DT_MODE Control

The `DT_MODE` environment variable controls MCP behavior:

| Mode | Behavior |
|---|---|
| `off` | Dynatrace MCP tools are not loaded. Passive telemetry (OTLP export) still works. |
| `on_demand` | MCP tools are loaded. Coordinator can query Dynatrace when relevant. **(Default)** |
| `always` | MCP tools are loaded. Coordinator checks Dynatrace health on every turn. |

---

## Setting Up the Dynatrace MCP Server

The Dynatrace MCP server is what allows both Claude Code and the coordinator agent to query Dynatrace using natural language. There are two places it's configured: `.mcp.json` (for Claude Code) and `.env` (for the coordinator agent). Here's how to set up both from scratch.

### Prerequisites

- **Node.js 18+** — the MCP server runs via `npx`
- **A Dynatrace tenant** — SaaS or Managed (e.g., `https://abc12345.apps.dynatrace.com`)
- **An OAuth client** in Dynatrace with the required scopes

### Step 1: Create an OAuth Client in Dynatrace

1. Go to your Dynatrace tenant → **Account Management** → **Identity & access management** → **OAuth clients**
2. Click **Create client**
3. Give it a name (e.g., `daypilot-mcp`)
4. Select the following scopes:
   - `storage:logs:read`
   - `storage:metrics:read`
   - `storage:spans:read`
   - `storage:buckets:read`
   - `storage:bizevents:read`
   - `storage:events:read`
   - `storage:entities:read`
   - `environment-api:problems:read`
   - `app-engine:apps:run`
   - `automation:workflows:read`
   - `automation:workflows:write`
   - `Davis Analyzers` (all davis scopes if you want Davis Copilot)
5. Click **Create** — you'll get:
   - **Client ID** (e.g., `dt0s02.XXXXXXXX`)
   - **Client Secret** (e.g., `dt0s02.XXXXXXXX.YYYYYYYY...`)
6. Note your **Account URN** from the top of the Account Management page (e.g., `urn:dtaccount:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

### Step 2: Create an API Token for OTLP Ingest

This is separate from the OAuth client — it's for exporting traces/metrics/logs.

1. Go to your Dynatrace tenant → **Access Tokens** (or **Settings** → **Integration** → **Access tokens**)
2. Click **Generate new token**
3. Name it (e.g., `daypilot-otlp-ingest`)
4. Select scopes:
   - `metrics.ingest`
   - `traces.ingest`
   - `logs.ingest`
5. Click **Generate** and copy the token

### Step 3: Configure `.env` for the DayPilot Server

Add these to your `.env` file:

```bash
# Dynatrace tenant URL
DT_ENVIRONMENT=https://abc12345.apps.dynatrace.com

# API token (from Step 2) — for OTLP export
DT_API_TOKEN=dt0c01.XXXXXXXX.YYYYYYYY...

# OAuth credentials (from Step 1) — for MCP server
OAUTH_CLIENT_ID=dt0s02.XXXXXXXX
OAUTH_CLIENT_SECRET=dt0s02.XXXXXXXX.YYYYYYYY...
OAUTH_ACCOUNT_URN=urn:dtaccount:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Mode: "on_demand" (default), "always", or "off"
DT_MODE=on_demand
```

This enables two things:
- **OTLP export** — traces, metrics, and logs flow to Dynatrace automatically
- **Coordinator MCP** — the AI agent can query Dynatrace about its own performance

### Step 4: Configure `.mcp.json` for Claude Code

Create or update `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "dynatrace": {
      "command": "npx",
      "args": ["-y", "@dynatrace-oss/dynatrace-mcp-server@latest"],
      "env": {
        "DT_ENVIRONMENT": "https://abc12345.apps.dynatrace.com",
        "OAUTH_CLIENT_ID": "dt0s02.XXXXXXXX",
        "OAUTH_CLIENT_SECRET": "dt0s02.XXXXXXXX.YYYYYYYY...",
        "OAUTH_ACCOUNT_URN": "urn:dtaccount:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      }
    }
  }
}
```

> **Important:** Use the same OAuth credentials from Step 1. The `.mcp.json` file is gitignored — never commit real credentials.

### Step 5: Verify the Setup

**Verify OTLP export:**
```bash
python main.py
# Send a chat request, then check Dynatrace → Distributed Traces
# You should see spans like "chat.handle_request", "tool.plan_schedule", etc.
```

**Verify Claude Code MCP:**
```bash
# Open Claude Code in the project directory
# The MCP server auto-connects. Ask:
"List any active Dynatrace problems"
"What's the average latency of tool.plan_schedule in the last hour?"
```

**Verify coordinator self-monitoring:**
```bash
# With DT_MODE=on_demand in .env, send a chat message:
"How's your performance looking?"
# The coordinator should query Dynatrace and report its own metrics
```

### Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `Dynatrace MCP credentials incomplete — skipping` | Missing `DT_ENVIRONMENT`, `OAUTH_CLIENT_ID`, or `OAUTH_CLIENT_SECRET` in `.env` | Check all three are set |
| MCP server fails to start | Node.js not installed or `npx` not in PATH | Install Node.js 18+ and ensure `npx` is available |
| OTLP export silently fails | Wrong `DT_API_TOKEN` or missing ingest scopes | Regenerate token with `metrics.ingest`, `traces.ingest`, `logs.ingest` |
| OAuth 403 errors in MCP | OAuth client missing required scopes | Re-create the OAuth client with all scopes from Step 1 |
| `npm ERR! could not determine executable to run` | npx cache issue | Run `npx -y @dynatrace-oss/dynatrace-mcp-server@latest` manually to debug |
| No traces in Dynatrace | Tenant URL format wrong | Must be `https://xxxxx.apps.dynatrace.com` (not `.live.`) — the code converts it automatically |

---

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# === Required for OTLP export (traces, metrics, logs) ===
DT_ENVIRONMENT=https://your-env.apps.dynatrace.com
DT_API_TOKEN=your_dynatrace_api_token
# Token scopes needed: metrics.ingest, traces.ingest, logs.ingest

# === Required for MCP self-monitoring ===
OAUTH_CLIENT_ID=your_dynatrace_oauth_client_id
OAUTH_CLIENT_SECRET=your_dynatrace_oauth_client_secret
OAUTH_ACCOUNT_URN=urn:dtaccount:your-account-urn  # optional, for multi-tenant

# === Mode control ===
DT_MODE=on_demand   # "always" | "on_demand" | "off"

# === Optional ===
OTEL_SERVICE_NAME=daypilot   # Override service name (default: "daypilot")
APP_ENV=development          # "development" → DEBUG logs, anything else → INFO
```

### How the OTLP Endpoint Is Derived

The setup automatically converts your Dynatrace environment URL:

```
Input:  https://abc12345.apps.dynatrace.com
Output: https://abc12345.live.dynatrace.com/api/v2/otlp
```

No manual OTLP endpoint configuration needed.

### Dependencies

```
opentelemetry-api>=1.25.0
opentelemetry-sdk>=1.25.0
opentelemetry-exporter-otlp-proto-http>=1.25.0
opentelemetry-semantic-conventions>=0.46b0
```

Already included in `requirements.txt`.

---

## Testing It Out

### Option 1: Via the Web UI (Dynatrace Platform)

1. **Set up credentials** — add `DT_ENVIRONMENT` and `DT_API_TOKEN` to your `.env`
2. **Start the server** — `python main.py`
3. **Send a chat request** — `POST /chat/` with any message
4. **Open Dynatrace** → navigate to your tenant URL

**Where to find your data:**

| Dynatrace Section | What You'll See |
|---|---|
| **Distributed Traces** | Full request traces from HTTP → coordinator → tools → LLM calls |
| **Metrics** | `agent.tool.duration`, `genai.request.duration`, `health.pipeline.duration`, etc. |
| **Logs** | Structured logs from every component, correlated with traces |
| **Notebooks** | Create DQL queries to analyze patterns (e.g., `fetch spans \| filter span.name == "tool.plan_schedule"`) |

**Example DQL queries to try:**

```dql
// Tool call latency breakdown
fetch spans
| filter matchesPhrase(span.name, "tool.")
| summarize avg(duration), p95=percentile(duration, 95) by span.name

// LLM call frequency and duration
fetch spans
| filter matchesPhrase(span.name, "genai.")
| summarize count(), avg(duration) by dt.entity.custom_device

// Health pipeline verdict distribution
fetch metrics
| filter metric.key == "health.verdict"
| summarize sum(value) by verdict

// Slowest chat requests
fetch spans
| filter span.name == "chat.handle_request"
| sort duration desc
| limit 20
```

### Option 2: Via Claude Code MCP

DayPilot's `.mcp.json` configures the Dynatrace MCP server for use directly in Claude Code.

1. **Open Claude Code** in the DayPilot project directory
2. The MCP server auto-connects using credentials in `.mcp.json`
3. **Ask natural language questions** about your telemetry:

```
"What are the slowest tool calls in the last hour?"
"Show me error rates for the health pipeline"
"Are there any active Dynatrace problems?"
"What's the P95 latency for the chat endpoint?"
"Generate a DQL query for LLM token usage by model"
```

Claude Code uses the Dynatrace MCP tools to:
- Generate DQL from your question
- Execute the query against your Dynatrace tenant
- Return formatted results

This means you can debug production issues from your terminal without opening the Dynatrace UI.

### Option 3: Coordinator Self-Monitoring (In-App)

When `DT_MODE` is set to `on_demand` or `always`, the coordinator agent itself can query Dynatrace. In the chat UI:

```
You: "How's your performance looking?"
DayPilot: "Checking... My average response time is 2.3s (P95: 4.1s).
           The health pipeline is the main contributor at 1.8s average.
           No errors in the last hour. Token usage is nominal."
```

The agent uses the same Dynatrace MCP tools to introspect its own telemetry.

---

## Telemetry Module Reference

### `telemetry/setup.py`

Core initialization. Called once at import time via `telemetry/__init__.py`.

| Function | Purpose |
|---|---|
| `setup_telemetry()` | Creates and registers all three OTel providers (Tracer, Meter, Logger) |
| `_get_otlp_endpoint()` | Converts `apps.dynatrace.com` → `live.dynatrace.com/api/v2/otlp` |
| `_build_tracer_provider()` | BatchSpanProcessor → OTLP HTTP exporter |
| `_build_meter_provider()` | PeriodicExportingMetricReader (30s interval) → OTLP HTTP exporter |
| `_build_logger_provider()` | BatchLogRecordProcessor → OTLP HTTP exporter |
| `get_logger(name)` | Returns logger with dual output: console (StreamHandler) + Dynatrace (OTel handler) |
| `get_dt_mode()` | Returns `DT_MODE` env var value |

### `telemetry/instrument.py`

Decorators for zero-boilerplate instrumentation.

| Decorator | Use On | Span Pattern | Metrics |
|---|---|---|---|
| `@traced_tool(name)` | Tool functions | `tool.{name}` | `agent.tool.duration`, `agent.tool.calls`, `agent.tool.errors` |
| `@traced_llm(model, op)` | LLM calls | `genai.{op}` | `genai.request.duration`, `genai.requests` |
| `@traced_node(name)` | Pipeline nodes | `health.pipeline.{name}` | `health.pipeline.node.duration` |

### `telemetry/middleware.py`

FastAPI middleware. Add with `app.add_middleware(TelemetryMiddleware)`.

Automatically traces all HTTP requests, records latency/error metrics, and logs request summaries.

### `telemetry/__init__.py`

Public API exports:

```python
from telemetry import tracer, meter, get_logger, setup_telemetry
```

---

## Instrumentation Coverage Summary

| Component | Traces | Metrics | Logs |
|---|---|---|---|
| HTTP requests | Full (middleware) | Full | Full |
| Coordinator context preload | Full | Full | Full |
| Chat endpoint | Full | Full | Full |
| Memory consolidation | Full | Full | Full |
| All agent tools (10) | Full (@traced_tool) | Full | Full |
| LLM calls | Full (@traced_llm) | Full | Full |
| Health pipeline orchestrator | Full | Full | Full |
| Health Node 1 (HealthKit) | Full | Full | Full |
| Health Node 2 (Strava) | Via orchestrator | Via orchestrator | Full |
| Health Node 3 (Autonomic) | Via orchestrator | Full (PSI/PLI/verdict) | Full |
| Health Node 4 (Insights) | Via orchestrator | Full (duration/retries) | Full |
| Dynatrace self-monitoring | Via MCP | Via MCP | Via MCP |

---

## Graceful Degradation

If Dynatrace credentials are missing or the tenant is unreachable:

- **The application continues to work normally.** No crashes, no errors.
- OTLP exporters silently fail — logs still go to console via StreamHandler.
- MCP tools are not loaded if credentials are missing — coordinator operates without self-monitoring.
- Set `DT_MODE=off` to explicitly disable all Dynatrace features.

---

## File Map

```
telemetry/
├── __init__.py          # Public API: tracer, meter, get_logger, setup_telemetry
├── setup.py             # OTel SDK initialization, provider configuration
├── instrument.py        # @traced_tool, @traced_llm, @traced_node decorators
└── middleware.py         # FastAPI HTTP request tracing middleware

agents/
├── dynatrace_mcp.py     # Dynatrace MCP server loader for self-monitoring
├── coordinator.py        # Context preload tracing, MCP tool integration
└── tools/
    ├── health_tools.py   # Health pipeline entry point tracing
    ├── memory_tools.py   # @traced_tool on all 5 memory functions
    ├── relationship_tools.py  # @traced_tool
    ├── schedule_tools.py      # @traced_tool
    ├── goal_tools.py          # @traced_tool
    ├── geo_tools.py           # @traced_tool
    └── realtime_tools.py      # @traced_tool

agents/health_agent/agents/
├── graph_orchestrator.py           # Pipeline-level span + metrics
└── nodes/
    ├── healthkit_sentinel.py       # Node 1 span + biometric flag attributes
    ├── strava_contextualizer.py    # Node 2 logging
    ├── autonomic_decoupler.py      # Node 3 PSI/PLI/verdict metrics
    └── insights_engine.py          # Node 4 duration + retry metrics

api/
├── app.py               # TelemetryMiddleware registration, MCP init
└── routes/
    ├── chat.py           # chat.handle_request span, LLM duration metrics
    └── schedule.py       # Error logging via get_logger

.mcp.json                # Dynatrace MCP server config for Claude Code
.env.example             # Dynatrace env var template
config.py                # Settings class with DT fields
main.py                  # `import telemetry` triggers global init
```
