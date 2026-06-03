# Health-Agent Integration Plan

## Goal

Fold the health-agent into the root monolith as a first-class ADK component —
the same pattern as the goal-agent hierarchy. The microservice (server.py, api/)
is deleted. The 4-node ADK Workflow pipeline is untouched in logic; only its
import paths and wiring change.

The system runs against bundled scenario datasets (HealthKit + Strava JSON files
checked into the repo). At startup, `analyze_health()` picks a scenario randomly
once per app lifetime and uses the scenario's date range to resolve `target_date`.
This gives any user a realistic, deterministic-for-the-session health profile
without requiring real wearable data.

---

## Decision Log (do not re-litigate)

| Decision | Rationale |
|---|---|
| Move to in-process ADK | One deployment, shared Python path, no HTTP round-trip |
| Rename `health-agent/` → `health_agent/` | Hyphen is illegal in Python package names |
| Delete `server.py`, `api/`, `config.py` | Dead code once in-process |
| Merge settings into root `config.py` | Nodes do `from config import settings`; resolves to root after merge |
| Datasets bundled in repo under `agents/health_agent/datasets/` | Deployable; no filesystem config needed. Scenarios are already checked in |
| Single scenario assigned randomly at startup, reused for session lifetime | Simulates one real user; avoids per-request randomness; predictable within a session |
| `target_date` resolved from scenario's manifest, not from `date.today()` | Scenario data has fixed date ranges (2026-05-27 to 2026-06-26). We pick the latest available date in the scenario that is ≤ today, falling back to the last date in the manifest |
| `focus_window` read from MongoDB user preferences | Coordinator already has user_id; `MemoryAgent.get_preferences()` is canonical |
| Rename `HealthOutput` fields to match `root.md` | `energy_score`, `focus_windows` (list[str]), `cognitive_load`. Drop `avoid_tasks` |
| Drop `avoid_tasks` | Schedule prescription, not health signal. `plan_schedule` Gemini derives this naturally from `cognitive_load` + classification |

---

## Datasets

The bundled scenarios live at `agents/health_agent/datasets/` (after rename):

| Scenario dir | Date range | Character |
|---|---|---|
| `healthy_baseline` | 2026-05-28 – 2026-06-26 | All verdicts NONE; low PSI/PLI |
| `training_overreach` | 2026-05-28 – 2026-06-26 | High PLI; PHYSICAL verdicts |
| `emotional_volatility` | 2026-05-28 – 2026-06-26 | Elevated PSI; PSYCHOLOGICAL verdicts |
| `progressive_work_burnout_sim` | 2026-05-27 – 2026-06-25 | Rising PSI over time; AMBIGUOUS → PSYCHOLOGICAL arc |
| `progressive_work_burnout` | 2025-01-01 – 2025-01-30 | Hand-crafted; older dates |

For the app integration, use only the four simulator scenarios with 2026 dates:
`healthy_baseline`, `training_overreach`, `emotional_volatility`,
`progressive_work_burnout_sim`. The `progressive_work_burnout` (2025 dates)
is retained for CLI testing only.

---

## Files: What Gets Deleted

```
agents/health-agent/server.py
agents/health-agent/api/__init__.py
agents/health-agent/api/app.py
agents/health-agent/api/routes/__init__.py
agents/health-agent/api/routes/health.py
agents/health-agent/config.py
```

---

## Step 1 — Rename Directory

Rename `agents/health-agent/` → `agents/health_agent/`.

All files inside move with the rename. The datasets move too:
`agents/health_agent/datasets/` is their new location.

Verify (create if absent):
- `agents/health_agent/__init__.py`
- `agents/health_agent/agents/__init__.py`
- `agents/health_agent/agents/nodes/__init__.py`
- `agents/health_agent/agents/tools/__init__.py`

---

## Step 2 — Root `config.py` Additions

File: `/config.py`

Add to `Settings` class. Do not remove any existing fields.

```python
# Health-agent (previously in agents/health_agent/config.py)
node4_model: str = "gemini-2.5-flash"
memory_backend: str = "jsonl"   # "jsonl" | "bigquery"
```

No `health_data_root` field — scenario path is computed at runtime from the
bundled datasets directory relative to the health_agent package (see Step 6).

---

## Step 3 — Root `schemas/health.py` Changes

File: `/schemas/health.py`

Rename fields to match `agents/goal/prompts/root.md` (which is the contract and
must not be changed).

**Replace the entire file content with:**

```python
from pydantic import BaseModel


class HealthInput(BaseModel):
    """Legacy input model — not used by the pipeline path."""
    sleep_duration_hours: float
    sleep_quality: str
    user_reported_energy: str
    previous_workload: str
    wearable_summary: str | None = None


class HealthOutput(BaseModel):
    energy_score: str          # "low" | "medium" | "high"
    focus_windows: list[str]   # primary first; e.g. ["9PM-1AM"]
    cognitive_load: float      # 0.0–1.0  (PSI / 100)
```

`HealthInput` is kept to avoid breaking any import that references it, but it
is not used by the pipeline.

---

## Step 4 — New Module: `agents/health_agent/scenario_selector.py`

Create this new file. It is the single place that owns scenario selection and
`target_date` resolution. All other code calls it.

```python
"""
scenario_selector.py — Bundled scenario selection for the health pipeline.

At import time, one scenario is chosen randomly from the four 2026 simulator
scenarios. That choice is fixed for the lifetime of the process (module-level
singleton). All calls to get_active_scenario() return the same scenario.

target_date resolution:
    Pick the latest date in the scenario manifest that is <= today.
    If today is beyond all manifest dates, use the last manifest date.
    This keeps the health signal "current" relative to today even though
    the data is synthetic.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

# The four simulator scenarios with 2026 dates (deployable)
_SCENARIO_NAMES = [
    "healthy_baseline",
    "training_overreach",
    "emotional_volatility",
    "progressive_work_burnout_sim",
]

_DATASETS_DIR = Path(__file__).parent / "datasets"


def _load_manifest(scenario_name: str) -> list[dict]:
    manifest_path = _DATASETS_DIR / scenario_name / "manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def _pick_scenario() -> str:
    """Pick one scenario randomly. Called once at module import."""
    return random.choice(_SCENARIO_NAMES)


# Module-level singleton: fixed for the lifetime of the process
_active_scenario: str = _pick_scenario()


def get_active_scenario() -> str:
    """Return the scenario name chosen at startup."""
    return _active_scenario


def get_run_dir() -> str:
    """Return the absolute path to the active scenario's dataset directory."""
    return str(_DATASETS_DIR / _active_scenario)


def get_target_date() -> str:
    """
    Return the best target date for today within the active scenario.

    Picks the latest manifest date that is <= today (real calendar date).
    Falls back to the last manifest date if today is beyond the scenario range.
    """
    today_str = date.today().isoformat()
    manifest = _load_manifest(_active_scenario)
    manifest_dates = sorted(r["date"] for r in manifest)

    # Latest manifest date <= today
    eligible = [d for d in manifest_dates if d <= today_str]
    if eligible:
        return eligible[-1]
    # today is before the scenario start — use the first date
    return manifest_dates[0]
```

---

## Step 5 — Health-Agent `schemas.py` Changes

File: `agents/health_agent/schemas.py`

**Replace the entire file content with:**

```python
"""
schemas.py — Output model for the Health Agent pipeline.

HealthPipelineOutput bridges ADK pipeline state to the root HealthOutput shape.
HealthPipelineInput is removed — run_pipeline() is called directly with positional args.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


# ── Focus window shift lookup ────────────────────────────────────────────────
# Applied only when PSI >= 65 (LOW energy). Maps preferred window → shifted window.
# Keys are the most common stored preference values.
_SHIFT_MAP = {
    "9PM-1AM":  "7PM-10PM",
    "10PM-2AM": "8PM-11PM",
    "8PM-12AM": "6PM-9PM",
    "9AM-1PM":  "7AM-10AM",
    "10AM-2PM": "8AM-11AM",
    "8AM-12PM": "6AM-9AM",
}


def _derive_focus_windows(preferred: str, psi: float) -> list[str]:
    """
    Return focus windows adjusted for current PSI.
    PSI >= 65 (low energy): shift 2h earlier and shorten.
    PSI < 65: return preferred unchanged.
    """
    if psi >= 65:
        return [_SHIFT_MAP.get(preferred, preferred)]
    return [preferred]


class HealthPipelineOutput(BaseModel):
    """
    Response model for the health pipeline.

    Core psychobio fields mirror PsychobioState.
    Compatibility fields (energy_score, focus_windows, cognitive_load) match
    the root HealthOutput schema so the coordinator consumes this directly.
    """

    user_id: str
    target_date: str
    scenario: str    # which scenario was active — useful for debugging

    # Core psychobio outputs
    psychological_strain_index: float
    physical_load_index: float
    node3_verdict: str
    node4_classification: Optional[str] = None
    final_insight: Optional[str] = None

    # Root HealthOutput compatibility fields
    energy_score: str          # "low" | "medium" | "high"
    focus_windows: list[str]
    cognitive_load: float

    @classmethod
    def from_state(
        cls,
        state: dict,
        preferred_focus_window: str = "9PM-1AM",
        scenario: str = "unknown",
    ) -> "HealthPipelineOutput":
        """Map a raw ADK final-state dict to a typed HealthPipelineOutput."""
        psi = state.get("psychological_strain_index", 0.0)

        if psi >= 65:
            energy = "low"
        elif psi >= 35:
            energy = "medium"
        else:
            energy = "high"

        return cls(
            user_id=state.get("user_id", ""),
            target_date=state.get("target_date", ""),
            scenario=scenario,
            psychological_strain_index=round(psi, 2),
            physical_load_index=round(state.get("physical_load_index", 0.0), 2),
            node3_verdict=state.get("node3_verdict", "NONE"),
            node4_classification=state.get("node4_classification"),
            final_insight=state.get("final_insight"),
            energy_score=energy,
            focus_windows=_derive_focus_windows(preferred_focus_window, psi),
            cognitive_load=round(psi / 100, 3),
        )
```

---

## Step 6 — Update Import Paths Inside `health_agent`

After the rename, all intra-health-agent imports must be absolute from the
monolith root. Go through each file:

### `agents/health_agent/agents/graph_orchestrator.py`

```python
# Before
from agents.nodes.healthkit_sentinel    import healthkit_sentinel
from agents.nodes.strava_contextualizer import strava_contextualizer
from agents.nodes.autonomic_decoupler   import autonomic_decoupler
from agents.nodes.insights_engine       import insights_engine
from agents.graph_state                 import PsychobioState

# After
from agents.health_agent.agents.nodes.healthkit_sentinel    import healthkit_sentinel
from agents.health_agent.agents.nodes.strava_contextualizer import strava_contextualizer
from agents.health_agent.agents.nodes.autonomic_decoupler   import autonomic_decoupler
from agents.health_agent.agents.nodes.insights_engine       import insights_engine
from agents.health_agent.agents.graph_state                 import PsychobioState
```

### `agents/health_agent/agents/nodes/healthkit_sentinel.py`

```python
# Before
from agents.tools.data_tools import DataRepository

# After
from agents.health_agent.agents.tools.data_tools import DataRepository
```

### `agents/health_agent/agents/nodes/strava_contextualizer.py`

```python
# Before
from agents.tools.data_tools import DataRepository

# After
from agents.health_agent.agents.tools.data_tools import DataRepository
```

### `agents/health_agent/agents/nodes/insights_engine.py`

Two imports inside function bodies:
```python
# Before (inside _write_memory)
from agents.memory_repository import MemoryRepository
from config import settings

# After
from agents.health_agent.agents.memory_repository import MemoryRepository
from config import settings   # unchanged — now resolves to root config.py
```

Also inside `_insights_engine_fn`:
```python
# Before
from config import settings

# After
from config import settings   # unchanged
```

`settings.gemini_api_key`, `settings.node4_model`, `settings.memory_backend`
must all exist on root Settings after Step 2. They do.

### `agents/health_agent/agents/memory_repository.py`

Read this file. If it imports `from config import settings`, that import
stays the same — it will resolve to root config after Step 2. Verify no other
internal imports need updating.

### `agents/health_agent/agents/nodes/autonomic_decoupler.py`

No external imports. No changes needed.

### `agents/health_agent/agents/graph_state.py`

No external imports. No changes needed.

### `agents/health_agent/agents/tools/data_tools.py`

No internal imports. No changes needed.

### `agents/health_agent/agents/psychobio_engine_adk.py`

This is the CLI harness. Update its imports:

```python
# Before
REPO_ROOT = Path(__file__).parent.parent

# After — point to the health_agent package root for dataset resolution
# (datasets now live at agents/health_agent/datasets/ relative to monolith root,
#  but the CLI harness can still use SCENARIO_DATA_DIRS with absolute paths)
```

The `SCENARIO_DATA_DIRS` dict uses paths relative to `REPO_ROOT`. After the rename,
`REPO_ROOT` should point to the monolith root (three levels up from the nodes dir),
not the health_agent package root. Update:

```python
# Before
REPO_ROOT = Path(__file__).parent.parent  # was health-agent root

# After
REPO_ROOT = Path(__file__).parent.parent.parent.parent  # monolith root
```

And update SCENARIO_DATA_DIRS paths to start with `agents/health_agent/datasets/`:

```python
SCENARIO_DATA_DIRS = {
    "progressive_work_burnout":     "agents/health_agent/datasets/progressive_work_burnout/user_001/20260526T021707Z",
    "progressive_work_burnout_sim": "agents/health_agent/datasets/progressive_work_burnout_sim",
    "training_overreach":           "agents/health_agent/datasets/training_overreach",
    "healthy_baseline":             "agents/health_agent/datasets/healthy_baseline",
    "emotional_volatility":         "agents/health_agent/datasets/emotional_volatility",
}
```

Also update these two imports in the `main()` body:

```python
# Before
from agents.tools.data_tools import DataRepository
from agents.graph_orchestrator import run_pipeline

# After
from agents.health_agent.agents.tools.data_tools import DataRepository
from agents.health_agent.agents.graph_orchestrator import run_pipeline
```

And:
```python
# Before (inside main, from config import settings)
from config import settings

# After — stays the same; add sys.path so root config resolves when running CLI
```

The CLI harness is run as a script from the monolith root
(`python agents/health_agent/agents/psychobio_engine_adk.py`), so the working
directory is the monolith root and `from config import settings` resolves
correctly without sys.path manipulation.

---

## Step 7 — Implement `analyze_health()` Tool

File: `agents/tools/health_tools.py`

Replace the entire file:

```python
"""
Health tool — Owner: Vatsal

analyze_health() is the coordinator's entry point to the PsychoBio pipeline.

Data source: bundled scenario datasets under agents/health_agent/datasets/.
At process startup, scenario_selector.py picks one scenario randomly and fixes
it for the session. analyze_health() always uses that scenario.

Preference: reads user's preferred focus window from MongoDB (via MemoryAgent).
Falls back to "9PM-1AM" if no preference is stored.

Returns a dict shaped like HealthOutput (energy_score, focus_windows,
cognitive_load) plus enriched fields (node3_verdict, node4_classification,
final_insight, psi, pli) for optional use by the coordinator prompt.
"""

from db import get_db
from agents.memory import MemoryAgent
from agents.health_agent.agents.graph_orchestrator import run_pipeline
from agents.health_agent.scenario_selector import (
    get_active_scenario,
    get_run_dir,
    get_target_date,
)
from agents.health_agent.schemas import HealthPipelineOutput


async def analyze_health(user_id: str) -> dict:
    """
    Run the PsychoBio pipeline for the user and return their health context.

    The scenario (data source) is fixed for the process lifetime by
    scenario_selector. The target date is resolved from the scenario manifest
    relative to today.

    Returns keys: energy_score, focus_windows, cognitive_load, node3_verdict,
    node4_classification, final_insight, psi, pli, scenario.

    Falls back to neutral values if the pipeline errors.
    """
    # Fetch user's preferred focus window from MongoDB
    mem = MemoryAgent(get_db())
    prefs = await mem.get_preferences(user_id)
    preferred_focus_window = prefs.get("focus_window", "9PM-1AM")

    scenario = get_active_scenario()
    run_dir = get_run_dir()
    target_date = get_target_date()

    try:
        state = await run_pipeline(user_id, target_date, run_dir)
        output = HealthPipelineOutput.from_state(
            state,
            preferred_focus_window=preferred_focus_window,
            scenario=scenario,
        )
        return {
            "energy_score":         output.energy_score,
            "focus_windows":        output.focus_windows,
            "cognitive_load":       output.cognitive_load,
            "node3_verdict":        output.node3_verdict,
            "node4_classification": output.node4_classification,
            "final_insight":        output.final_insight,
            "psi":                  output.psychological_strain_index,
            "pli":                  output.physical_load_index,
            "scenario":             output.scenario,
            "target_date":          output.target_date,
        }
    except Exception as e:
        print(f"[analyze_health] Pipeline error for {user_id} (scenario={scenario}): {e}")
        return _fallback(preferred_focus_window, scenario)


def _fallback(preferred_focus_window: str, scenario: str) -> dict:
    """Neutral health context when pipeline cannot run."""
    return {
        "energy_score":         "medium",
        "focus_windows":        [preferred_focus_window],
        "cognitive_load":       0.5,
        "node3_verdict":        "NONE",
        "node4_classification": None,
        "final_insight":        None,
        "psi":                  50.0,
        "pli":                  0.0,
        "scenario":             scenario,
        "target_date":          None,
    }
```

---

## Step 8 — Update `schedule_tools.py`

File: `agents/tools/schedule_tools.py`

Three lines at ~95-98 must change. Also remove the `health_avoid` variable and
the `Avoid:` line from the prompt.

**Reads (change these 4 lines):**

```python
# Before
health_energy    = health.energy_level if health else "medium"
health_focus     = health.focus_window if health else "9PM-1AM"
health_cognitive = health.cognitive_load_score if health else 0.65
health_avoid     = ", ".join(health.avoid_tasks) if health and health.avoid_tasks else "(none)"

# After
health_energy    = health.energy_score if health else "medium"
health_focus     = health.focus_windows[0] if health and health.focus_windows else "9PM-1AM"
health_cognitive = health.cognitive_load if health else 0.5
```

**Prompt string (in `_build_prompt`):**

Remove the entire `Avoid: {health_avoid}` line. The Health & Energy block becomes:

```
## Health & Energy
Energy level: {health_energy}
Best focus window: {health_focus}
Cognitive load score: {health_cognitive} (0=exhausted, 1=peak)
```

**No other changes in `schedule_tools.py`.**

---

## Step 9 — Update Coordinator Instruction

File: `agents/coordinator.py`

In the `INSTRUCTION` string, update the `analyze_health` bullet:

```
# Before
- analyze_health: for energy/sleep analysis

# After
- analyze_health: run the full psychobiological pipeline to get today's
  energy_score, focus_windows, cognitive_load, and a final_insight string.
  Always call this before plan_schedule so the schedule reflects the user's
  real psychobiological state. Pass only user_id.
```

---

## Step 10 — `_preload_user_context`: Add Health as 4th Gather Arm

File: `agents/coordinator.py`

The `_preload_user_context` callback currently gathers 3 things in parallel.
Add `analyze_health` as a 4th arm so the coordinator's opening message can
reference the user's health state without needing an explicit tool call.

**Before:**
```python
ctx, goals, rel = await asyncio.gather(
    read_user_context(user_id),
    track_goals(user_id),
    get_relationship_context(user_id),
    return_exceptions=True,
)
```

**After:**
```python
ctx, goals, rel, health = await asyncio.gather(
    read_user_context(user_id),
    track_goals(user_id),
    get_relationship_context(user_id),
    analyze_health(user_id),
    return_exceptions=True,
)
```

Then add a health context block to the `context_parts` assembly:

```python
if not isinstance(health, Exception) and health.get("node4_classification"):
    context_parts.append(
        f"Health: {health['node4_classification']} "
        f"(PSI={health['psi']:.0f}, energy={health['energy_score']}). "
        f"{health.get('final_insight', '')}"
    )
elif not isinstance(health, Exception):
    context_parts.append(
        f"Health: energy={health.get('energy_score', 'medium')}, "
        f"cognitive_load={health.get('cognitive_load', 0.5):.2f}"
    )
```

Add the import at the top of coordinator.py:
```python
from agents.tools import analyze_health   # already imported via tools/__init__.py
```

(It is already in the tools list passed to `build_coordinator`. The import is
already there. Only the callback body changes.)

Also store health in callback state for potential use by sub-agents:
```python
if not isinstance(health, Exception):
    callback_context.state["health_context"] = health
```

---

## Step 11 — `api/app.py` — Log Active Scenario at Startup

File: `api/app.py`

Add a startup log line so it's clear which scenario is active when the server starts.
In the `lifespan` function, after the MongoDB setup and before `yield`:

```python
from agents.health_agent.scenario_selector import get_active_scenario, get_target_date
print(f"[Health] Active scenario: {get_active_scenario()}, target_date={get_target_date()}")
```

No structural changes to the lifespan.

---

## Complete File Change Summary

| File | Action |
|---|---|
| `agents/health-agent/` | **Rename** to `agents/health_agent/` |
| `agents/health_agent/server.py` | **Delete** |
| `agents/health_agent/api/` | **Delete** entire directory |
| `agents/health_agent/config.py` | **Delete** |
| `agents/health_agent/__init__.py` | **Create** empty if absent |
| `agents/health_agent/agents/__init__.py` | **Verify** exists |
| `agents/health_agent/agents/nodes/__init__.py` | **Verify** exists |
| `agents/health_agent/agents/tools/__init__.py` | **Verify** exists |
| **NEW** `agents/health_agent/scenario_selector.py` | **Create** (Step 4) |
| `config.py` | **Add** `node4_model`, `memory_backend` |
| `schemas/health.py` | **Rename** fields, **remove** `avoid_tasks` |
| `agents/health_agent/schemas.py` | **Rewrite** — new fields, `from_state()`, `_derive_focus_windows()`, drop `HealthPipelineInput` |
| `agents/health_agent/agents/graph_orchestrator.py` | **Update** 5 imports |
| `agents/health_agent/agents/nodes/healthkit_sentinel.py` | **Update** data_tools import |
| `agents/health_agent/agents/nodes/strava_contextualizer.py` | **Update** data_tools import |
| `agents/health_agent/agents/nodes/insights_engine.py` | **Update** memory_repository import (2 occurrences) |
| `agents/health_agent/agents/memory_repository.py` | **Verify** config import resolves |
| `agents/health_agent/agents/nodes/autonomic_decoupler.py` | **No change** |
| `agents/health_agent/agents/graph_state.py` | **No change** |
| `agents/health_agent/agents/tools/data_tools.py` | **No change** |
| `agents/health_agent/agents/psychobio_engine_adk.py` | **Update** REPO_ROOT, SCENARIO_DATA_DIRS, 2 imports in main() |
| `agents/tools/health_tools.py` | **Rewrite** with real implementation |
| `agents/tools/schedule_tools.py` | **Update** 3 field reads, **remove** avoid line from prompt |
| `agents/coordinator.py` | **Update** INSTRUCTION text + `_preload_user_context` gather |
| `api/app.py` | **Add** startup log line |

---

## Testing Plan

### Phase 1 — Import Smoke Test

Run each from the monolith root directory (`/Users/vatsalvatsyayan/code/Daypilot`):

```bash
python -c "from agents.health_agent.agents.graph_orchestrator import run_pipeline; print('orchestrator OK')"
python -c "from agents.health_agent.scenario_selector import get_active_scenario, get_run_dir, get_target_date; print(get_active_scenario(), get_target_date())"
python -c "from agents.tools.health_tools import analyze_health; print('health_tools OK')"
python -c "from agents.tools.schedule_tools import plan_schedule; print('schedule_tools OK')"
python -c "from schemas.health import HealthOutput; print(list(HealthOutput.model_fields.keys()))"
```

Expected last line output: `['energy_score', 'focus_windows', 'cognitive_load']`

### Phase 2 — Scenario Selector Unit Test

```python
from agents.health_agent.scenario_selector import (
    get_active_scenario, get_run_dir, get_target_date, _SCENARIO_NAMES
)
import os, json

# Scenario is one of the four valid names
assert get_active_scenario() in _SCENARIO_NAMES, f"Bad scenario: {get_active_scenario()}"

# run_dir exists and has the required files
run_dir = get_run_dir()
assert os.path.isdir(run_dir), f"run_dir not found: {run_dir}"
for fname in ["raw_healthkit_daily_summary.json", "strava_summary_activities.json",
              "strava_detailed_activities.json", "manifest.json"]:
    assert os.path.exists(os.path.join(run_dir, fname)), f"Missing: {fname}"

# target_date is in the manifest
manifest = json.load(open(os.path.join(run_dir, "manifest.json")))
dates = [r["date"] for r in manifest]
assert get_target_date() in dates, f"target_date {get_target_date()} not in manifest"

print(f"Scenario selector OK: scenario={get_active_scenario()}, date={get_target_date()}")
```

### Phase 3 — Schema Consistency Test

```python
from schemas.health import HealthOutput
from agents.health_agent.schemas import HealthPipelineOutput, _derive_focus_windows

# _derive_focus_windows
assert _derive_focus_windows("9PM-1AM", 20.0) == ["9PM-1AM"]   # HIGH — no shift
assert _derive_focus_windows("9PM-1AM", 50.0) == ["9PM-1AM"]   # MEDIUM — no shift
assert _derive_focus_windows("9PM-1AM", 70.0) == ["7PM-10PM"]  # LOW — shifted
assert _derive_focus_windows("weird-window", 70.0) == ["weird-window"]  # unknown — fallback

# from_state
state = {
    "user_id": "u1", "target_date": "2026-06-02",
    "psychological_strain_index": 72.0, "physical_load_index": 30.0,
    "node3_verdict": "PSYCHOLOGICAL",
    "node4_classification": "CHRONIC_COGNITIVE_FATIGUE",
    "final_insight": "Test.",
}
out = HealthPipelineOutput.from_state(state, preferred_focus_window="9PM-1AM", scenario="test")
assert out.energy_score == "low"
assert out.focus_windows == ["7PM-10PM"]
assert out.cognitive_load == 0.72
assert out.scenario == "test"

# Dict from analyze_health maps to HealthOutput
h = HealthOutput(energy_score=out.energy_score, focus_windows=out.focus_windows, cognitive_load=out.cognitive_load)
assert h.energy_score == "low"
assert h.focus_windows[0] == "7PM-10PM"

print("Schema tests passed.")
```

### Phase 4 — Pipeline End-to-End Test (with real data)

```python
import asyncio
from agents.health_agent.scenario_selector import get_active_scenario, get_run_dir, get_target_date
from agents.health_agent.agents.graph_orchestrator import run_pipeline

scenario = get_active_scenario()
run_dir = get_run_dir()
target_date = get_target_date()
print(f"Testing scenario={scenario}, date={target_date}")

state = asyncio.run(run_pipeline("test_user", target_date, run_dir))

# Pipeline must produce all expected fields
assert "psychological_strain_index" in state, "Missing PSI"
assert "physical_load_index" in state, "Missing PLI"
assert "node3_verdict" in state, "Missing verdict"
assert state["node3_verdict"] in ("NONE", "PHYSICAL", "PSYCHOLOGICAL", "AMBIGUOUS")
assert 0.0 <= state["psychological_strain_index"] <= 100.0
assert 0.0 <= state["physical_load_index"] <= 100.0

print(f"Pipeline OK: PSI={state['psychological_strain_index']:.1f}, "
      f"PLI={state['physical_load_index']:.1f}, verdict={state['node3_verdict']}, "
      f"classification={state.get('node4_classification')}")
```

### Phase 5 — `analyze_health` Tool Test

Run this against the real app with MongoDB running:

```python
import asyncio
from agents.tools.health_tools import analyze_health

result = asyncio.run(analyze_health("demo_user"))

assert result["energy_score"] in ("low", "medium", "high")
assert isinstance(result["focus_windows"], list)
assert len(result["focus_windows"]) >= 1
assert 0.0 <= result["cognitive_load"] <= 1.0
assert result["node3_verdict"] in ("NONE", "PHYSICAL", "PSYCHOLOGICAL", "AMBIGUOUS")
assert result["scenario"] in ("healthy_baseline", "training_overreach",
                               "emotional_volatility", "progressive_work_burnout_sim")

print(f"analyze_health OK: {result}")
```

If MongoDB is not running, the preference fetch will fail. The function must
still complete via fallback and return `energy_score: "medium"`. Test this
explicitly by calling with a user_id that has no stored preferences.

### Phase 6 — `plan_schedule` Prompt Test

```python
from schemas.health import HealthOutput
from agents.tools.schedule_tools import _build_prompt
from schemas.schedule import ScheduleInput, UserPreferences

health = HealthOutput(energy_score="low", focus_windows=["7PM-10PM"], cognitive_load=0.72)
inp = ScheduleInput(
    user_id="test", date="2026-06-02", health=health,
    user_preferences=UserPreferences(preferred_work_hours="late_night",
                                     commute_minutes=30, break_frequency=90),
    calendar_events=[],
)
prompt = _build_prompt(inp)
assert "Energy level: low" in prompt
assert "Best focus window: 7PM-10PM" in prompt
assert "Cognitive load score: 0.72" in prompt
assert "Avoid:" not in prompt

print("plan_schedule prompt test passed.")
```

### Phase 7 — CLI Harness Test (verifies backward compat)

From the monolith root:

```bash
python agents/health_agent/agents/psychobio_engine_adk.py \
  --scenario healthy_baseline \
  --date 2026-06-02
```

Expected: same diagnostic output format as before. No import errors. Verdict
and classification match the manifest's `expected_node3_verdict`.

Also test a high-PSI scenario:
```bash
python agents/health_agent/agents/psychobio_engine_adk.py \
  --scenario emotional_volatility \
  --date 2026-06-10
```

Expected: `node3_verdict` is PSYCHOLOGICAL.

### Phase 8 — Monolith Boot Test

```bash
python main.py
```

Expected:
1. No import errors
2. `[Health] Active scenario: <name>, target_date=<date>` printed at startup
3. Server running on port 8000
4. `server.py` for health-agent no longer exists / is not started

Send a chat message:
```bash
curl -X POST http://localhost:8000/chat/ \
  -H "Content-Type: application/json" \
  -d '{"user_id": "demo_user", "message": "plan my day"}'
```

Check server logs for:
- `[Health] Active scenario: ...` (startup)
- No `[analyze_health] Pipeline error` lines
- A valid JSON response with the coordinator's reply

The reply should reference health context if `final_insight` is non-null
(the coordinator's `_preload_user_context` injects it).

---

## What Does NOT Change

- The 4 pipeline nodes — zero logic changes
- PSI/PLI formulas
- Node 4 system prompt and 8-classification taxonomy
- `MemoryRepository` (JSONL backend)
- `DataRepository` and all JSON file reading
- ADK `Workflow` topology (fan-out, fan-in, JoinNode, unconditional Node 4)
- `PsychobioState` schema
- `run_pipeline()` signature and body
- All goal agents and their prompts
- All other coordinator tools
- MongoDB schema, indexes, all other routes

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Two ADK Runners in same process | They use separate `InMemorySessionService` instances with different `app_name`. ADK supports this. |
| `run_pipeline` is slow (~2-4s with Gemini) and blocks `_preload_user_context` | Acceptable for demo. The gather runs it in parallel with goals/relationship fetches. If it becomes a problem, wrap in `asyncio.wait_for` with a timeout and fall back. |
| Scenario date range ends before today (e.g., 2026-06-26 is last date) | `get_target_date()` returns last manifest date as fallback. Pipeline still runs. |
| `from config import settings` inside health_agent nodes fails at import | Only happens if the monolith root is not on sys.path. Running from monolith root (`python main.py`) ensures it is. |
| `raw_healthkit_samples.json` absent for a scenario | `DataRepository._load_optional()` already handles this — returns empty list. |
| Memory write fails (JSONL write error) | Node 4 already wraps `_write_memory` in try/except and prints a warning. Pipeline continues. |
