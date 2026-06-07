# Health Agent — PsychoBio Pipeline

> **Psychobiological monitoring integrated as a first-class ADK component in the DayPilot monolith**

---

## What happened to this agent

This agent was originally a standalone FastAPI microservice (`server.py`, `api/`, its own `config.py`). It has been **fully integrated into the DayPilot monolith** as an in-process ADK component — the same pattern as the goal agent.

**What was deleted:** `server.py`, `api/`, `config.py`, `HealthPipelineInput`

**What was added:** `scenario_selector.py`, a rewritten `schemas.py`, and `agents/tools/health_tools.py` as the coordinator's entry point

**What did not change:** the 4 pipeline nodes, `run_pipeline()`, `PsychobioState`, `DataRepository`, `MemoryRepository`, all PSI/PLI formulas, the Node 4 Gemini system prompt and 8-class taxonomy

The directory was also renamed from `health-agent/` to `health_agent/` (hyphen is illegal in Python package names). All import paths are now absolute from the monolith root.

---

## How it fits into DayPilot

```
POST /chat/
  ↓
before_agent_callback (_preload_user_context)
  ├── read_user_context(user_id)        ─┐
  ├── track_goals(user_id)               │  asyncio.gather — all 4 in parallel
  ├── get_relationship_context(user_id)  │
  └── analyze_health(user_id)           ─┘
            ↓
    agents/tools/health_tools.py
            ↓
    scenario_selector  →  picks run_dir + target_date
            ↓
    agents/health_agent/agents/graph_orchestrator.py
            ↓
    ┌── Node 1: HealthKit Sentinel (parallel) ──┐
    └── Node 2: Strava Contextualizer (parallel)─┘
                    ↓  fan-in
           Node 3: Autonomic Decoupler
           (PSI, PLI, verdict)
                    ↓  unconditional
           Node 4: Insights Engine (Gemini)
           (classification, final_insight)
                    ↓
    HealthPipelineOutput.from_state(state, ...)
                    ↓
    Returns dict: energy_score, focus_windows, cognitive_load,
                  node3_verdict, node4_classification, final_insight,
                  psi, pli, scenario, target_date
```

The coordinator receives health context **before the LLM generates its first token**. No tool call needed — it is already in the `{user_context}` template variable the coordinator reads. The coordinator can still call `analyze_health` explicitly (e.g. when the user asks "how am I doing today?") — that is also wired in the tools list.

---

## Data source: bundled simulation scenarios

There is no live HealthKit or Strava integration. The agent uses **four bundled simulation scenarios** stored under `agents/health_agent/datasets/`:

| Scenario | Date range | Character |
|---|---|---|
| `healthy_baseline` | 2026-05-28 – 2026-06-26 | All verdicts NONE; low PSI/PLI |
| `training_overreach` | 2026-05-28 – 2026-06-26 | High PLI; PHYSICAL verdicts |
| `emotional_volatility` | 2026-05-28 – 2026-06-26 | Elevated PSI; PSYCHOLOGICAL verdicts |
| `progressive_work_burnout_sim` | 2026-05-27 – 2026-06-25 | Rising PSI; AMBIGUOUS → PSYCHOLOGICAL arc |

A fifth scenario (`progressive_work_burnout`, 2025 dates) exists under `datasets/` for CLI-only testing.

**At process startup**, `scenario_selector.py` picks one of the four 2026 scenarios randomly and fixes it for the lifetime of the process — every call to `analyze_health` within the same server process uses the same scenario. This simulates a single real user without per-request randomness.

---

## New files introduced by the integration

### `agents/health_agent/scenario_selector.py`

The single source of truth for scenario selection and date resolution. All other code calls this — nothing else picks paths.

```python
from agents.health_agent.scenario_selector import (
    get_active_scenario,  # → "training_overreach" (fixed at startup)
    get_run_dir,          # → "/abs/path/to/datasets/training_overreach"
    get_target_date,      # → "2026-06-02" (latest manifest date ≤ today)
)
```

**How `get_target_date()` works:** picks the latest date in the scenario's `manifest.json` that is ≤ today's real calendar date. If today is past the scenario's end date, it falls back to the last manifest entry. This keeps the health signal "current" relative to today even though the data is synthetic.

**How to change the active scenario for testing:** at import time, the module picks randomly. To force a specific scenario for a test, monkeypatch `_active_scenario` before the first import:

```python
import agents.health_agent.scenario_selector as sel
sel._active_scenario = "emotional_volatility"
```

Or set a fixed random seed before importing:

```python
import random
random.seed(42)
from agents.health_agent.scenario_selector import get_active_scenario
```

---

### `agents/tools/health_tools.py`

The coordinator's only entry point to the pipeline. Replace this file to change how health data is sourced (e.g. switch to live HealthKit when ready).

```python
async def analyze_health(user_id: str) -> dict:
    """
    Returns:
        energy_score:         "low" | "medium" | "high"
        focus_windows:        list[str]   e.g. ["9PM-1AM"] or ["7PM-10PM"] if PSI >= 65
        cognitive_load:       float       0.0–1.0 (PSI / 100)
        node3_verdict:        "NONE" | "PHYSICAL" | "PSYCHOLOGICAL" | "AMBIGUOUS"
        node4_classification: str | None  one of 8 taxonomy labels
        final_insight:        str | None  2–4 sentence Gemini-grounded insight
        psi:                  float       0–100
        pli:                  float       0–100
        scenario:             str         which scenario was active
        target_date:          str | None  YYYY-MM-DD
    """
```

**Fallback behaviour:** if MongoDB is unreachable (preference fetch fails), it falls back to `"9PM-1AM"` as the preferred focus window and continues the pipeline. If the pipeline itself throws, `_fallback()` returns a neutral dict (`energy_score="medium"`, `cognitive_load=0.5`) so the coordinator always gets a usable result.

---

### `agents/health_agent/schemas.py` (rewritten)

Defines `HealthPipelineOutput` — a typed bridge between raw ADK state and the root `HealthOutput` shape. Key logic:

- `from_state(state, preferred_focus_window, scenario)` — maps the ADK final-state dict to typed fields
- `_derive_focus_windows(preferred, psi)` — shifts the focus window 2 hours earlier when PSI ≥ 65 (low energy state)

**Focus window shift map** (PSI ≥ 65 only):

| Preferred | Shifted |
|---|---|
| `9PM-1AM` | `7PM-10PM` |
| `10PM-2AM` | `8PM-11PM` |
| `8PM-12AM` | `6PM-9PM` |
| `9AM-1PM` | `7AM-10AM` |
| `10AM-2PM` | `8AM-11AM` |
| `8AM-12PM` | `6AM-9AM` |

To add more shift mappings, edit `_SHIFT_MAP` in `schemas.py`. Unknown windows pass through unchanged.

---

## Root schemas that changed

### `schemas/health.py`

The root `HealthOutput` model fields were renamed to match what `analyze_health()` returns and what `plan_schedule` consumes:

| Old field | New field |
|---|---|
| `energy_level` | `energy_score` |
| `focus_window` (str) | `focus_windows` (list[str]) |
| `cognitive_load_score` | `cognitive_load` |
| `avoid_tasks` (list[str]) | *(removed)* |

If you are consuming `HealthOutput` anywhere in the codebase, use the new field names. `avoid_tasks` is gone — the schedule Gemini call derives this naturally from `cognitive_load` + task classification.

---

## CLI harness (unchanged logic, updated paths)

The CLI script is useful for testing the pipeline directly against any scenario without starting the server.

```bash
# Always run from the monolith root
cd /path/to/Daypilot

python agents/health_agent/agents/psychobio_engine_adk.py \
    --scenario <SCENARIO_NAME> \
    [--date YYYY-MM-DD] \
    [--model gemini-2.5-flash|gemini-2.5-pro]
```

| Argument | Required | Description |
|---|---|---|
| `--scenario` | Yes | One of: `healthy_baseline`, `training_overreach`, `emotional_volatility`, `progressive_work_burnout_sim`, `progressive_work_burnout` |
| `--date` | No | Target date. Defaults to last date in HealthKit data. |
| `--model` | No | Overrides `node4_model` in root `config.py` for this run only. |

**Must be run from the monolith root** — `config.py` and `agents/` are resolved relative to that directory.

---

## Configuration

All config now lives in the root `config.py` (pydantic_settings). No separate `.env` per-agent.

| Field in `Settings` | Env var | Default | Purpose |
|---|---|---|---|
| `gemini_api_key` | `GEMINI_API_KEY` | required | Node 4 Gemini calls |
| `node4_model` | `NODE4_MODEL` | `gemini-2.5-flash` | Gemini model for Node 4 |
| `memory_backend` | `MEMORY_BACKEND` | `jsonl` | `jsonl` (active) or `bigquery` (stub) |

The CLI `--model` flag overrides `node4_model` at runtime via `os.environ["NODE4_MODEL"]`.

---

## Pipeline topology

```
                     ┌──────────────────────────┐
                     │          START            │
                     └─────────┬────────────────┘
                               │  fan-out
              ┌────────────────┴────────────────┐
              ▼                                  ▼
   ┌──────────────────┐              ┌─────────────────────┐
   │  Node 1           │              │  Node 2              │
   │  HealthKit        │              │  Strava              │
   │  Sentinel         │              │  Contextualizer      │
   │  (FunctionNode)   │              │  (FunctionNode)      │
   │  → node1_flags    │              │  → node2_metrics     │
   └────────┬──────────┘              └──────────┬───────────┘
            └────────────────┬───────────────────┘
                             │  fan-in (JoinNode)
                             ▼
                  ┌──────────────────────┐
                  │  Node 3              │
                  │  Autonomic Decoupler  │
                  │  (FunctionNode)       │
                  │  → PSI, PLI, verdict  │
                  └──────────┬───────────┘
                             │  unconditional edge
                             ▼
                  ┌──────────────────────┐
                  │  Node 4              │
                  │  Insights Engine     │
                  │  (FunctionNode)      │
                  │  + Gemini API call   │
                  │  → classification,   │
                  │    final_insight     │
                  └──────────┬───────────┘
                             ▼
                           END
```

Node 4 **always runs** — the edge from Node 3 to Node 4 is unconditional. `ctx.route` is set to the verdict but there are no conditional edges matching it in the current wiring.

---

## Node reference

All nodes are in `agents/health_agent/agents/nodes/`. Import paths from monolith root:

```
agents.health_agent.agents.nodes.healthkit_sentinel
agents.health_agent.agents.nodes.strava_contextualizer
agents.health_agent.agents.nodes.autonomic_decoupler
agents.health_agent.agents.nodes.insights_engine
```

### Node 1 — HealthKit Sentinel

**File:** `agents/health_agent/agents/nodes/healthkit_sentinel.py`
**Type:** `FunctionNode` (no LLM, deterministic)
**Runs in parallel with:** Node 2

Reads today's HealthKit biometrics, computes a 14-day rolling baseline, and emits boolean deviation flags plus sleep latency triangulation flags.

**Writes to `ctx.state["node1_flags"]`:**

| Key | Type | Description |
|---|---|---|
| `cold_start` | `bool` | True when baseline supplementation was needed (see below) |
| `today_values` | `dict` | Raw biometrics: hrv, rhr, sleep efficiency, deep sleep, awake hours, resp. rate, latency metrics |
| `baseline_stats` | `dict` | Per-metric `{"mean": float, "std": float}` over 14 days |
| `hrv_suppressed` | `bool` | today HRV < (mean − 1.5 σ) |
| `rhr_elevated` | `bool` | today RHR > (mean + 1.5 σ) |
| `sleep_fragmented` | `bool` | sleep efficiency < 80% OR awake hours > 1.5 h |
| `deep_sleep_reduced` | `bool` | today deep sleep < (mean − 1.0 σ) |
| `late_night_awake_flag` | `bool \| None` | ≥ 2 awake windows between 02:00–06:00 |
| `deep_sleep_latency_flag` | `str \| None` | `RAPID_ONSET` (<20 min) / `NORMAL` / `DELAYED_ONSET` (>60 min) |
| `rem_latency_flag` | `str \| None` | `DELAYED` (>120 min) / `NORMAL` |

**Key thresholds** (all `UNVALIDATED_HEURISTIC`):

| Signal | Threshold |
|---|---|
| HRV suppression | −1.5 σ from 14d mean |
| RHR elevation | +1.5 σ from 14d mean |
| Sleep fragmentation | efficiency < 80% OR awake > 1.5 h |
| Deep sleep reduction | −1.0 σ from 14d mean |
| Deep latency — rapid onset | < 20 min |
| Deep latency — delayed onset | > 60 min |
| REM latency — delayed | > 120 min |
| Late-night awake flag | ≥ 2 windows between 02:00–06:00 |

**To tune thresholds:** edit the numeric constants directly in `healthkit_sentinel.py`. They are inline in the flag-setting logic (search `1.5 *`, `1.0 *`, `80.0`, `1.5` for awake hours, etc.).

---

### Node 2 — Strava Contextualizer

**File:** `agents/health_agent/agents/nodes/strava_contextualizer.py`
**Type:** `FunctionNode` (no LLM, keyword NLP only)
**Runs in parallel with:** Node 1

Computes ATL/CTL/TSB, weekly effort windows, sport-type-specific degradation, and affective fatigue score from activity description text.

**Writes to `ctx.state["node2_metrics"]`:**

| Key | Type | Description |
|---|---|---|
| `atl` | `float` | Acute Training Load (7-day EMA) |
| `ctl` | `float` | Chronic Training Load (42-day EMA) |
| `tsb` | `float` | CTL − ATL; negative = fatigue |
| `physical_load_score` | `float` | `clamp(atl / 80 * 100, 0, 100)` |
| `week_effort_current` | `float` | Relative effort sum over last 7 days |
| `week_effort_prior` | `float` | Relative effort sum over the 7 days before that |
| `has_activity` | `bool` | False on rest days |
| `rpe_today` | `float \| None` | Perceived exertion 1–10 |
| `sport_type` | `str \| None` | `"Run"`, `"Ride"`, `"VirtualRide"`, `"Swim"`, etc. |
| `primary_degradation_pct` | `float \| None` | Sport-specific primary degradation % |
| `fatigue_type_flag` | `str` | `NEUROMUSCULAR` / `CARDIORESPIRATORY` / `NOMINAL` |
| `discrepancy_flag` | `bool` | High perceived cost + normal external output |
| `affective_fatigue_score` | `float` | 0.0–1.0; keyword scan of activity description |
| `description_raw` | `str \| None` | Raw athlete's workout description text |

**Sport-type degradation branching** (`UNVALIDATED_HEURISTIC`):
- `Run` → primary = cadence degradation %, secondary = pace degradation %
- `Ride` / `VirtualRide` → primary = pace %, secondary = cardio efficiency index
- `Swim` / other → primary = pace %, secondary = cardio efficiency index

**To add or adjust affective fatigue keywords:** edit `_FATIGUE_KEYWORDS` in `strava_contextualizer.py`. Each entry is a `(keyword_string, weight)` tuple. Score = `min(1.0, total_weight / 2.0)`.

---

### Node 3 — Autonomic Decoupler

**File:** `agents/health_agent/agents/nodes/autonomic_decoupler.py`
**Type:** `FunctionNode` (deterministic, **no LLM, ADR-003**)

Computes PSI and PLI from Nodes 1 + 2 outputs and emits a routing verdict. Must never have an LLM added to it.

**Writes to state:**

| Field | Range | Description |
|---|---|---|
| `psychological_strain_index` | 0–100 | Higher = more psychological strain |
| `physical_load_index` | 0–100 | Higher = more physical load |
| `node3_verdict` | enum | `NONE` / `PHYSICAL` / `PSYCHOLOGICAL` / `AMBIGUOUS` |

**Routing rules** (`UNVALIDATED_HEURISTIC` — awaiting Phase 7 calibration):

| Condition | Verdict |
|---|---|
| PSI > 45 AND PLI < 45 | `PSYCHOLOGICAL` |
| PLI > 60 AND PSI < 35 | `PHYSICAL` |
| PSI > 45 AND PLI > 45 | `AMBIGUOUS` |
| else | `NONE` |

**PSI components and weights** (`UNVALIDATED_HEURISTIC`):

| Component | Weight |
|---|---|
| HRV suppression | 35% |
| Excess awake time | 25% |
| Deep sleep deficit | 20% |
| RPE dissociation | 15% |
| RHR elevation | 5% |
| Sleep latency (3 sub-components) | 8% combined |

**PLI components and weights** (`UNVALIDATED_HEURISTIC`):

| Component | Weight |
|---|---|
| ATL (acute training load) | 40% |
| Week-over-week effort spike | 35% |
| Degradation-aware (sport-specific) | 15% |
| Sleep efficiency deficit | 10% |

**To retune routing thresholds:** edit the four routing conditions at the bottom of `autonomic_decoupler.py`. To reweight PSI/PLI components: find the `0.35`, `0.25`, `0.20` etc. multipliers in the function body. All are inline float constants labelled `# UNVALIDATED_HEURISTIC`.

---

### Node 4 — Insights Engine

**File:** `agents/health_agent/agents/nodes/insights_engine.py`
**Type:** `FunctionNode` + Gemini API call

Calls Gemini to produce a fine-grained classification and a 2–4 sentence grounded insight. Always runs (unconditional edge).

**Writes to state:**

| Field | Type | Description |
|---|---|---|
| `node4_classification` | `str \| None` | One of 8 taxonomy labels (see below) |
| `final_insight` | `str \| None` | 2–4 sentence plain-language insight |

**8-class taxonomy:**

| Classification | Meaning |
|---|---|
| `OPTIMAL_LOAD` | Elevated load with stable biometrics |
| `WELL_RECOVERED` | Biometrics at or above baseline, moderate load |
| `ACUTE_COGNITIVE_LOAD` | Short-term cognitive overload, likely transient |
| `CHRONIC_COGNITIVE_FATIGUE` | Sustained cognitive strain pattern |
| `EARLY_BURNOUT_TRAJECTORY` | Pre-burnout autonomic profile |
| `EMOTIONAL_VOLATILITY` | High RPE–output discrepancy suggesting emotional loading |
| `PHYSICAL_OVERREACH` | High PLI with dominant physical degradation |
| `RECOVERY_IN_PROGRESS` | Signals improving but not yet at baseline |

**To change the Node 4 model:** set `NODE4_MODEL` env var, or the `node4_model` field in root `config.py`, or use `--model` flag in CLI.

**To modify the system prompt or classification rules:** edit `SYSTEM_PROMPT` constant in `insights_engine.py`. It defines the strict JSON response format, forbidden words, permitted trajectory language, and the 8-class taxonomy the model must choose from.

**Retry behaviour:** 2 attempts total on `JSONDecodeError` or missing keys. After exhaustion, prints warning, leaves `node4_classification = None` and `final_insight = None` in state. Pipeline does not fail.

---

## DataRepository — simulation fallback for cold-start

**File:** `agents/health_agent/agents/tools/data_tools.py`

`get_history_14d(target_date)` was updated to eliminate cold-start for simulation scenarios. Previously it returned only records strictly before `target_date`, which caused cold-start when fewer than 7 prior-date records existed.

**Current behaviour:** if fewer than 14 prior-date records exist, the method supplements with the nearest available records from the full dataset (records on/after `target_date`, sorted ascending so the closest dates come first). For synthetic data, temporal direction relative to `target_date` does not affect the physiological signals being modelled.

**Result:** `n` is always 14 for any scenario with 14+ total records. `cold_start` in Node 1 / Node 3 is structurally impossible for all four 2026 simulation scenarios.

**When cold-start can still occur:** only if the scenario dataset itself has fewer than 14 total records. None of the bundled scenarios have this problem. If you add a new scenario with very few records, cold-start will still be triggered.

**`DataRepository` public interface** (used directly by nodes — nodes never open files):

| Method | Returns | Notes |
|---|---|---|
| `get_daily_summary(date)` | `dict` | Merged daily row + computed sleep latency |
| `get_history_14d(date)` | `list[dict]` | 14 records; supplements if needed |
| `get_baseline_stats(date)` | `dict` | Per-metric mean/std; empty if < 7 records total |
| `get_activity_today(date)` | `dict \| None` | Merged summary+detailed with degradation; `None` on rest days |
| `compute_atl_ctl(date)` | `dict` | `{atl, ctl, tsb}` via EMA (τ_ATL=7d, τ_CTL=42d) |
| `get_strava_summary()` | `list[dict]` | Full Strava summary list |
| `get_manifest_entry(date)` | `dict` | Ground-truth labels (evaluation only) |

---

## MemoryRepository — longitudinal memory

**File:** `agents/health_agent/agents/memory_repository.py`

Writes one record per day per user to `memory/{user_id}/memory_log.jsonl`. Backend is set via root `config.py`'s `memory_backend` field.

| Backend | Value | Status |
|---|---|---|
| `JsonlBackend` | `jsonl` | Active |
| `BigQueryBackend` | `bigquery` | Stub — `NotImplementedError` |

| Method | Description |
|---|---|
| `read_history(user_id, n_days=14)` | Returns up to `n_days` records, oldest-first |
| `write_today(user_id, date, record)` | Persists record; deduplicates by date; auto-computes `consecutive_psych_days` |

`consecutive_psych_days` is computed automatically — do not set it manually in the record passed to `write_today`.

---

## How to swap in live data (replacing the simulation)

When real HealthKit/Strava data is available:

1. **Replace `agents/tools/health_tools.py`** — change `run_dir` and `target_date` to be derived from a live data ingestion layer rather than `scenario_selector`. The `run_pipeline(user_id, target_date, run_dir)` signature does not change.

2. **Or replace `scenario_selector.py`** — reimplement `get_run_dir()` and `get_target_date()` to point to the user's live data directory (e.g. from a per-user S3 path or a local sync folder). `get_active_scenario()` can return `"live"` or any string.

3. **No node code changes needed** — Nodes 1–4 read from `run_dir` via `DataRepository`. Swap the data source, everything else follows.

4. **For BigQuery data:** implement `BigQueryBackend` in `memory_repository.py` and switch `MEMORY_BACKEND=bigquery`. For BigQuery HealthKit/Strava reads: replace the `_load()` methods in `DataRepository` with BigQuery client calls that return the same list-of-dict structure.

---

## How to add a new pipeline node

1. Create `agents/health_agent/agents/nodes/my_node.py`:
   ```python
   from google.adk.workflow import FunctionNode

   async def _my_node_fn(ctx) -> None:
       # Read from state
       psi = ctx.state.get("psychological_strain_index", 0.0)
       # Do something
       ctx.state["my_output"] = ...

   my_node = FunctionNode(func=_my_node_fn, name="my_node")
   ```

2. Add a field for its output to `PsychobioState` in `agents/health_agent/agents/graph_state.py`.

3. Wire it into the graph in `agents/health_agent/agents/graph_orchestrator.py`:
   ```python
   from agents.health_agent.agents.nodes.my_node import my_node

   # In root_workflow edges:
   (insights_engine, my_node),  # runs after Node 4
   ```

4. If the node's output should reach the coordinator, add the relevant key to the `return` dict in `agents/tools/health_tools.py`.

---

## Adding a new simulation scenario

1. Create a directory under `agents/health_agent/datasets/<scenario_name>/`.

2. Populate the five required files:
   - `raw_healthkit_daily_summary.json`
   - `strava_summary_activities.json`
   - `strava_detailed_activities.json`
   - `manifest.json`
   - `raw_healthkit_samples.json` (optional — sleep latency analysis)

   See Section "Data formats" below for field schemas.

3. Add the scenario name to `_SCENARIO_NAMES` in `scenario_selector.py` if you want the app to pick it randomly at startup.

4. Add it to `SCENARIO_DATA_DIRS` in `agents/health_agent/agents/psychobio_engine_adk.py` for CLI access.

5. The dataset needs **at least 14 total records** in `raw_healthkit_daily_summary.json` to avoid cold-start supplementation. More records produce a more realistic baseline.

---

## Running the pipeline programmatically

```python
import asyncio
from agents.health_agent.agents.graph_orchestrator import run_pipeline

state = asyncio.run(run_pipeline(
    user_id="user_001",
    target_date="2026-06-10",
    run_dir="/abs/path/to/datasets/emotional_volatility",
))

# state is a dict with all session fields
print(state["psychological_strain_index"])   # float 0–100
print(state["node3_verdict"])                # "NONE" | "PHYSICAL" | "PSYCHOLOGICAL" | "AMBIGUOUS"
print(state["node4_classification"])         # e.g. "EARLY_BURNOUT_TRAJECTORY"
print(state["final_insight"])                # 2–4 sentence insight text
```

To build a typed `HealthPipelineOutput` from the state:

```python
from agents.health_agent.schemas import HealthPipelineOutput

output = HealthPipelineOutput.from_state(
    state,
    preferred_focus_window="9PM-1AM",
    scenario="emotional_volatility",
)
print(output.energy_score)     # "low" | "medium" | "high"
print(output.focus_windows)    # ["7PM-10PM"]  (shifted when PSI >= 65)
print(output.cognitive_load)   # 0.0–1.0
```

---

## Data formats

### `raw_healthkit_daily_summary.json`

Array of objects — one per calendar day.

| Field | Type | Description |
|---|---|---|
| `summary_date` | `str` | `YYYY-MM-DD` |
| `hrv_sdnn_ms` | `float` | HRV SDNN in ms |
| `resting_hr_bpm` | `float` | Resting HR in bpm |
| `sleep_efficiency_pct` | `float` | 0–100 |
| `sleep_deep_hours` | `float` | Deep (slow-wave) sleep |
| `sleep_awake_hours` | `float` | Waking time within sleep window |
| `avg_respiratory_rate_bpm` | `float` | Overnight respiratory rate |
| `sleep_total_hours` | `float` | Total sleep |
| `sleep_rem_hours` | `float` | REM sleep |

### `strava_summary_activities.json`

Array of Strava resource_state=2 activity objects.

| Field | Type | Description |
|---|---|---|
| `start_date` | `str` | ISO 8601 datetime (first 10 chars used as date key) |
| `sport_type` | `str` | `"Run"`, `"Ride"`, `"VirtualRide"`, `"Swim"`, etc. |
| `relative_effort` | `int \| null` | Strava relative effort score |
| `average_speed` | `float` | m/s |
| `average_heartrate` | `float` | bpm |

### `strava_detailed_activities.json`

Array of Strava resource_state=3 objects (all summary fields plus):

| Field | Type | Description |
|---|---|---|
| `description` | `str \| null` | Athlete's written workout description |
| `perceived_exertion` | `float \| null` | RPE on 1–10 scale |
| `average_cadence` | `float \| null` | Steps/min (Run) or RPM (Ride) |
| `average_watts` | `float \| null` | Power output (Ride) |
| `laps` | `array` | Lap objects with `average_cadence`, `average_speed` |

### `manifest.json`

Array of objects — one per day. Used only for CLI evaluation output.

| Field | Type | Description |
|---|---|---|
| `date` | `str` | `YYYY-MM-DD` |
| `expected_node3_verdict` | `str` | Ground-truth verdict for evaluation |
| `expected_node4_classification` | `str \| null` | Ground-truth classification or `null` |
| `phase_label` | `str` | Narrative phase name e.g. `"overreach_block"` |
| `is_rest_day` | `bool` | True if no training activity on this day |

---

## Downstream routing suggestions

| `node3_verdict` | Action |
|---|---|
| `PSYCHOLOGICAL` | Surface `final_insight` to user; flag for coach if `consecutive_psych_days >= 3` |
| `PHYSICAL` | Recommend recovery; flag if `PLI > 80` |
| `AMBIGUOUS` | Both streams elevated; needs multi-modal assessment |
| `NONE` | No action; pipeline ran cleanly |

---

## Known limitations and design notes

**All heuristic thresholds are unvalidated.** Every numeric threshold in Nodes 1–3 is marked `UNVALIDATED_HEURISTIC` in source. They are based on physiological literature and engineering judgement, not calibrated against labelled athlete outcomes. Phase 7 calibration against labelled data is pending. Treat verdicts as directional signals, not clinical measurements.

**Node 4 always runs.** The graph wiring is unconditional (see topology diagram above). The orchestrator docstring mentions conditional routing for PHYSICAL/NONE → END, but the actual `edges=` list does not implement this. Every pipeline run calls Gemini.

**No live API integration.** HealthKit and Strava data is pre-exported JSON. Adding live ingestion requires a new upstream preprocessing layer — see "How to swap in live data" above.

**BigQuery backend is a stub.** `MEMORY_BACKEND=bigquery` raises `NotImplementedError`. Use `jsonl` for all current deployments.

**Two ADK Runners in the same process.** The health pipeline uses its own `InMemorySessionService` (app_name `"psychobio_engine"`) separate from the DayPilot coordinator runner (app_name `"daypilot"`). ADK supports this. Session state is not shared between them.

**Node 4 Gemini 503s are transient.** Under high API load, Node 4's 2-retry logic may exhaust without a result. The pipeline completes without writing `node4_classification` or `final_insight` (`None` in state). `analyze_health()` still returns a valid dict — `energy_score`, `focus_windows`, and `cognitive_load` are derived from PSI in `HealthPipelineOutput.from_state()` without needing Node 4.
