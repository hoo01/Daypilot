# PsychoBio Engine — Health Agent

> **Psychobiological monitoring pipeline for athlete well-being using Google ADK + Gemini**

---

## SECTION 1 — OVERVIEW
*For: non-technical readers, product stakeholders, coaches*

### What this agent does

The PsychoBio Engine continuously monitors an athlete's physical and psychological well-being by examining two data streams in parallel: biometric readings from Apple HealthKit (heart rate variability, resting heart rate, sleep architecture) and training load data from Strava (workout effort, pace, cadence). It fuses these signals through a deterministic scoring engine and, when strain is detected, calls a Gemini language model to produce a plain-language insight grounded entirely in the athlete's own numbers.

### Why it exists

Overtraining, burnout, and cognitive fatigue are difficult to detect in real time because their signals are distributed across physiology and psychology. HRV suppression might indicate physical stress or psychological stress — and they require different interventions. This agent exists to make that distinction early, before cumulative strain becomes injury or burnout. It is designed as a first-line triage layer that routes athletes to the appropriate specialist agent or human coach.

### What it outputs

Every run produces:

1. **A Node 3 verdict** — a four-way classification of the dominant strain pattern:
   - `NONE` — no elevated strain detected
   - `PHYSICAL` — training load is the primary driver
   - `PSYCHOLOGICAL` — autonomic and sleep signals indicate mental/cognitive strain
   - `AMBIGUOUS` — both physical and psychological signals are elevated simultaneously

2. **A Node 4 classification** (when verdict is `PSYCHOLOGICAL` or `AMBIGUOUS`) — one of 8 fine-grained taxonomy labels:

   | Classification | Meaning |
   |---|---|
   | `ACUTE_COGNITIVE_LOAD` | Short-term cognitive overload, likely transient |
   | `CHRONIC_COGNITIVE_FATIGUE` | Sustained cognitive strain pattern |
   | `EARLY_BURNOUT_TRAJECTORY` | Pattern consistent with pre-burnout autonomic profile |
   | `EMOTIONAL_VOLATILITY` | High RPE–output discrepancy suggesting emotional loading |
   | `WELL_RECOVERED` | Biometrics at or above baseline, moderate load |
   | `OPTIMAL_LOAD` | Elevated training load with stable biometrics |
   | `PHYSICAL_OVERREACH` | High PLI with dominant physical degradation signals |
   | `RECOVERY_IN_PROGRESS` | Signals improving but not yet back to baseline |

3. **A 2–4 sentence insight** grounded in the athlete's specific numbers (e.g. "HRV at 42 ms, 22% below your 14-day mean of 54 ms"), with no clinical diagnoses and no invented language.

### What data it consumes

All data is pre-exported JSON — there is no live API integration in the current version.

- **HealthKit biometrics** (`raw_healthkit_daily_summary.json`, `raw_healthkit_samples.json`): daily summaries of HRV (SDNN), resting heart rate, sleep efficiency, deep sleep hours, awake hours, respiratory rate; plus raw sleep-stage samples for latency analysis.
- **Strava training data** (`strava_summary_activities.json`, `strava_detailed_activities.json`): activity-level metrics including relative effort, perceived exertion (RPE), speed, cadence, heart rate, watts, lap splits, and the athlete's own written description of the workout.

---

## SECTION 2 — QUICK START
*For: engineers setting up or running the pipeline*

### Prerequisites

- Python >= 3.11
- A `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/app/apikey)

### Setup

```bash
# 1. Install dependencies from pyproject.toml
pip install -e ".[dev]"

# 2. Copy and populate environment variables
cp .env.example .env   # or edit .env directly
# Set GEMINI_API_KEY=<your key>
```

The `.env` file is loaded automatically at startup. Do not commit it to version control.

### Run command

```bash
python -m agents.psychobio_engine_adk \
    --scenario <SCENARIO> \
    [--date YYYY-MM-DD] \
    [--model gemini-2.5-flash|gemini-2.5-pro]
```

| Argument | Required | Description |
|---|---|---|
| `--scenario` | Yes | One of 5 scenario names (see Section 8) |
| `--date` | No | Target date in `YYYY-MM-DD`. Defaults to last date in dataset. |
| `--model` | No | Overrides `NODE4_MODEL` env var for this run only. |

**Example:**

```bash
python -m agents.psychobio_engine_adk --scenario training_overreach --date 2026-06-08
```

### Sample output

```
Running scenario 'training_overreach' for date 2026-06-08 [ADK]
Run dir: /path/to/health-agent/datasets/training_overreach
Node 4 model: gemini-2.5-flash

======================================================================
  PSYCHOBIO ENGINE (ADK) — 2026-06-08
======================================================================

── NODE 1: HealthKit Sentinel ──
  Flags raised:
    hrv_suppressed: True
    rhr_elevated: False
    sleep_fragmented: False
    deep_sleep_reduced: True
  Sleep latency flags:
    late_night_awake_flag:   False (count=1)
    deep_sleep_latency_flag: RAPID_ONSET (14.0 min)
    rem_latency_flag:        NORMAL (88.0 min)
  Today values vs 14d baseline:
    hrv_sdnn_ms:  today=38.20  mean=52.10  std=4.80
    resting_hr_bpm: today=62.00  mean=59.40  std=2.10
    ...

── NODE 2: Strava Contextualizer ──
  ATL=68.45  CTL=52.10  TSB=-16.35
  Physical Load Score: 85.6/100
  Week effort current: 520  prior: 310
  Activity: sport=Run  effort=95  RPE=7.8  speed=2.71 m/s
  Fatigue type: NEUROMUSCULAR  Primary degradation: 8.3%
  Discrepancy flag: False  Affective score: 0.45
  Description: "Dead legs from the start. Dug deep to finish."

── NODE 3: Autonomic Decoupler ──
  PSI = 32.10/100
    HRV=26.83  Awake=2.10  Deep=1.80  RPE-dissoc=1.35  RHR=0.45  Latency=0.00
  PLI = 71.40/100
    ATL=34.23  WoW=35.00  Degradation=8.33  SleepEff=2.10
  Verdict: PHYSICAL

── EVALUATION ──
  Expected verdict:        PHYSICAL
  Actual verdict:          PHYSICAL
  Expected classification: None
  Actual classification:   None
  Verdict Match: ✓ PASS
======================================================================
```

---

## SECTION 3 — ARCHITECTURE
*For: engineers integrating with or extending the pipeline*

### Pipeline topology

```
                         ┌─────────────────────────┐
                         │          START           │
                         └────────────┬────────────┘
                                      │  fan-out
                     ┌────────────────┴─────────────────┐
                     ▼                                   ▼
          ┌──────────────────┐               ┌──────────────────────┐
          │  Node 1          │               │  Node 2              │
          │  HealthKit       │               │  Strava              │
          │  Sentinel        │               │  Contextualizer      │
          │  (FunctionNode)  │               │  (FunctionNode)      │
          └────────┬─────────┘               └──────────┬───────────┘
                   │                                     │
                   └──────────────┬──────────────────────┘
                                  │  fan-in
                                  ▼
                         ┌─────────────────┐
                         │  fan_in_join     │
                         │  (JoinNode)      │
                         └────────┬────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │  Node 3                │
                     │  Autonomic Decoupler   │
                     │  (FunctionNode)        │
                     │  sets ctx.route=       │
                     └────────────┬───────────┘
                                  │  unconditional edge
                                  ▼
                     ┌────────────────────────┐
                     │  Node 4                │
                     │  Insights Engine       │
                     │  (FunctionNode+Gemini) │
                     └────────────┬───────────┘
                                  │
                                  ▼
                               END
```

> **Note on the orchestrator comment vs. actual edges:** The `graph_orchestrator.py` docstring describes conditional routing (PHYSICAL/NONE → END, PSYCHOLOGICAL/AMBIGUOUS → Node 4), but the actual `edges=` list uses an **unconditional edge** from `autonomic_decoupler` to `insights_engine`. Node 4 therefore **always runs** regardless of verdict. `ctx.route` is set but has no matching conditional edges in the current wiring.

### Fan-out / fan-in

`START` fires `healthkit_sentinel` and `strava_contextualizer` simultaneously as independent ADK `FunctionNode`s. A `JoinNode` named `fan_in_join` waits for both to complete before passing control to `autonomic_decoupler`. Nodes 1 and 2 write to different keys in `ctx.state` (`node1_flags` and `node2_metrics` respectively), so they are safe to run concurrently without locking.

### ADK components used

| Component | Import path | Role |
|---|---|---|
| `Workflow` | `google.adk.workflow` | Defines the graph: nodes + edges |
| `FunctionNode` | `google.adk.workflow` | Wraps a plain `async def fn(ctx)` as a DAG node |
| `JoinNode` | `google.adk.workflow` | Synchronises parallel branches before proceeding |
| `START` | `google.adk.workflow` | Sentinel for the graph entry edge |
| `Runner` | `google.adk.runners` | Executes the workflow for a given session |
| `InMemorySessionService` | `google.adk.sessions` | Session storage (dev/test; swap for `VertexAiSessionService` in production) |

### PsychobioState — shared session state

Defined in [agents/graph_state.py](agents/graph_state.py). A Pydantic `BaseModel` passed as `state_schema=` to the `Workflow`. All nodes read and write via `ctx.state["field_name"]`.

**Fields grouped by writer:**

| Field | Type | Default | Written by |
|---|---|---|---|
| `user_id` | `str` | `""` | CLI harness (before graph starts) |
| `target_date` | `str` | `""` | CLI harness |
| `run_dir` | `str` | `""` | CLI harness |
| `node1_flags` | `dict[str, Any]` | `{}` | Node 1 (Node 3 also appends `psi_breakdown`, `pli_breakdown`) |
| `node2_metrics` | `dict[str, Any]` | `{}` | Node 2 |
| `psychological_strain_index` | `float` | `0.0` | Node 3 |
| `physical_load_index` | `float` | `0.0` | Node 3 |
| `node3_verdict` | `str` | `"NONE"` | Node 3 |
| `node4_classification` | `str \| None` | `None` | Node 4 |
| `final_insight` | `str \| None` | `None` | Node 4 |

### DataRepository — JSON abstraction layer

Defined in [agents/tools/data_tools.py](agents/tools/data_tools.py). Instantiated directly inside each `FunctionNode`. Nodes never open files directly. Cloud portability is achieved by replacing the `get_*` methods with BigQuery calls — no node code changes needed.

**Public methods:**

| Method | Signature | Returns |
|---|---|---|
| `get_daily_summary` | `(target_date: str) -> dict` | One merged row: daily summary fields + computed sleep latency fields from raw samples |
| `get_history_14d` | `(target_date: str) -> list[dict]` | Up to 14 daily summary rows strictly before `target_date`, sorted ascending |
| `get_baseline_stats` | `(target_date: str) -> dict` | Per-metric `{"mean": float, "std": float}` over up to 14 prior days; empty dict if < 7 days available; `cold_start: True` if 7–13 days |
| `get_activity_today` | `(target_date: str) -> dict \| None` | Merged summary + detailed activity with computed `biomechanical_cadence_degradation_pct`, `pace_degradation_pct`, `cardio_efficiency_index`; `None` if rest day |
| `compute_atl_ctl` | `(target_date: str) -> dict` | `{"atl": float, "ctl": float, "tsb": float}` using exponential moving average (τ_ATL=7d, τ_CTL=42d) |
| `get_manifest_entry` | `(target_date: str) -> dict` | Ground-truth manifest row for that date (for evaluation only) |

### MemoryRepository — longitudinal memory

Defined in [agents/memory_repository.py](agents/memory_repository.py). Stores one record per day per user in a JSONL file at `memory/{user_id}/memory_log.jsonl`. Backend is swappable via the `MEMORY_BACKEND` environment variable.

**Backends:**

| Backend | `MEMORY_BACKEND` value | Status |
|---|---|---|
| `JsonlBackend` | `jsonl` | Active — local JSONL files |
| `BigQueryBackend` | `bigquery` | Stub — raises `NotImplementedError` |

**Public methods:**

| Method | Returns |
|---|---|
| `read_history(user_id, n_days=14)` | `list[dict]` — up to `n_days` records, sorted oldest-first |
| `write_today(user_id, date, record)` | `None` — persists record, deduplicates by date, auto-computes `consecutive_psych_days` |

---

## SECTION 4 — NODE REFERENCE
*For: agents integrating with this system and engineers extending nodes*

---

### Node 1 — HealthKit Sentinel

**File:** [agents/nodes/healthkit_sentinel.py](agents/nodes/healthkit_sentinel.py)

**Purpose:** Read today's HealthKit biometrics, compute a 14-day rolling baseline, and emit boolean deviation flags plus sleep latency triangulation flags.

**Inputs:**

| Source | Field / Method |
|---|---|
| `ctx.state` | `run_dir`, `target_date` |
| `DataRepository.get_daily_summary(target_date)` | `hrv_sdnn_ms`, `resting_hr_bpm`, `sleep_efficiency_pct`, `sleep_awake_hours`, `sleep_deep_hours`, `avg_respiratory_rate_bpm`, `late_night_awake_windows_count`, `deep_sleep_latency_minutes`, `rem_sleep_latency_minutes` |
| `DataRepository.get_baseline_stats(target_date)` | per-metric `mean` and `std` over prior 14 days |
| `DataRepository.get_history_14d(target_date)` | (called internally by `get_baseline_stats`) |

**Outputs** — writes `ctx.state["node1_flags"]`:

| Key | Type | Description |
|---|---|---|
| `cold_start` | `bool` | True if < 7 days of history available |
| `today_values` | `dict` | Raw today metrics: `hrv_sdnn_ms`, `resting_hr_bpm`, `sleep_efficiency_pct`, `sleep_awake_hours`, `sleep_deep_hours`, `avg_respiratory_rate_bpm`, `late_night_awake_windows_count`, `deep_sleep_latency_minutes`, `rem_sleep_latency_minutes` |
| `baseline_stats` | `dict` | Per-metric `{"mean": float, "std": float}` for: `hrv_sdnn_ms`, `resting_hr_bpm`, `sleep_deep_hours`, `sleep_awake_hours`, `sleep_efficiency_pct`, `avg_respiratory_rate_bpm` |
| `hrv_suppressed` | `bool \| absent` | True when today's HRV < (mean − 1.5 × std) |
| `rhr_elevated` | `bool \| absent` | True when today's RHR > (mean + 1.5 × std) |
| `sleep_fragmented` | `bool \| absent` | True when sleep efficiency < 80% OR awake hours > 1.5 h |
| `deep_sleep_reduced` | `bool \| absent` | True when today's deep sleep < (mean − 1.0 × std) |
| `late_night_awake_flag` | `bool \| None` | True when ≥ 2 awake windows between 02:00–06:00 |
| `deep_sleep_latency_flag` | `"RAPID_ONSET" \| "NORMAL" \| "DELAYED_ONSET" \| None` | Categorical latency classification |
| `rem_latency_flag` | `"DELAYED" \| "NORMAL" \| None` | REM onset latency classification |

*The keys `hrv_suppressed` through `rem_latency_flag` are absent entirely when `cold_start=True`.*

**Algorithm:**

1. Instantiate `DataRepository(run_dir)`.
2. Call `get_baseline_stats(target_date)`. If result is empty (< 7 days), write `cold_start=True`, empty `today_values` and `baseline_stats`, then return early.
3. Call `get_daily_summary(target_date)` which merges the daily CSV row with computed sleep latency fields from raw samples.
4. Populate `today_values` dict from the summary.
5. Populate `baseline_stats` dict (exclude the `cold_start` key if present).
6. If `cold_start=True` (7–13 days of history), write state and return — no deviation flags computed.
7. **HRV suppression flag:** `today_hrv < (mean_hrv − 1.5 × std_hrv)` *(UNVALIDATED_HEURISTIC)*
8. **RHR elevation flag:** `today_rhr > (mean_rhr + 1.5 × std_rhr)` *(UNVALIDATED_HEURISTIC)*
9. **Sleep fragmentation flag:** `sleep_efficiency_pct < 80.0 OR sleep_awake_hours > 1.5` *(UNVALIDATED_HEURISTIC)*
10. **Deep sleep reduced flag:** `today_deep < (mean_deep − 1.0 × std_deep)` *(UNVALIDATED_HEURISTIC)*
11. **Late-night awake flag:** count awake windows with `start_timestamp` hour in [2, 6); flag = True if count ≥ 2 *(UNVALIDATED_HEURISTIC)*
12. **Deep sleep latency flag:**
    - < 20 min → `RAPID_ONSET` (skeletal muscle debt — body crashes into deep sleep)
    - > 60 min → `DELAYED_ONSET` (elevated arousal / psychological stress)
    - 20–60 min → `NORMAL`
    *(UNVALIDATED_HEURISTIC)*
13. **REM latency flag:** > 120 min → `DELAYED` (CNS hyperarousal); else `NORMAL` *(UNVALIDATED_HEURISTIC)*
14. Write `ctx.state["node1_flags"]`.

**Key thresholds (all UNVALIDATED_HEURISTIC — Phase 7 calibration pending):**

| Threshold | Value | Signal |
|---|---|---|
| HRV suppression z-score | −1.5 σ | `hrv_suppressed` |
| RHR elevation z-score | +1.5 σ | `rhr_elevated` |
| Sleep efficiency minimum | 80% | `sleep_fragmented` |
| Awake hours maximum | 1.5 h | `sleep_fragmented` |
| Deep sleep z-score | −1.0 σ | `deep_sleep_reduced` |
| Late-night awake windows | ≥ 2 | `late_night_awake_flag` |
| Deep sleep latency rapid | < 20 min | `RAPID_ONSET` |
| Deep sleep latency delayed | > 60 min | `DELAYED_ONSET` |
| REM latency delayed | > 120 min | `DELAYED` |

**What Node 1 does NOT do:** access any Strava data; compute PSI/PLI scores; call any LLM; fail on rest days (it uses HealthKit data regardless of training activity).

---

### Node 2 — Strava Contextualizer

**File:** [agents/nodes/strava_contextualizer.py](agents/nodes/strava_contextualizer.py)

**Purpose:** Compute training load metrics (ATL/CTL/TSB), weekly effort windows, sport-type-specific performance degradation, fatigue type classification, and affective fatigue score from activity description text.

**Inputs:**

| Source | Field / Method |
|---|---|
| `ctx.state` | `run_dir`, `target_date` |
| `DataRepository.compute_atl_ctl(target_date)` | `atl`, `ctl`, `tsb` |
| `DataRepository.get_activity_today(target_date)` | `relative_effort`, `perceived_exertion`, `average_speed`, `sport_type`, `description`, `name`, laps array |
| `repo._strava_summary` (internal) | all activities for weekly effort window sums |

**Outputs** — writes `ctx.state["node2_metrics"]`:

| Key | Type | Value range / notes |
|---|---|---|
| `atl` | `float` | Acute Training Load (7-day EMA of relative effort) |
| `ctl` | `float` | Chronic Training Load (42-day EMA of relative effort) |
| `tsb` | `float` | Training Stress Balance = CTL − ATL; negative = fatigue |
| `physical_load_score` | `float` | `clamp(atl / 80 * 100, 0, 100)` |
| `week_effort_current` | `float` | Sum of `relative_effort` over last 7 days |
| `week_effort_prior` | `float` | Sum of `relative_effort` over the 7 days before that |
| `has_activity` | `bool` | False on rest days |
| `relative_effort_today` | `float \| None` | Strava relative effort for today's activity |
| `rpe_today` | `float \| None` | `perceived_exertion` field (1–10 scale) |
| `average_speed_today` | `float \| None` | m/s |
| `sport_type` | `str \| None` | `"Run"`, `"Ride"`, `"VirtualRide"`, `"Swim"`, etc. |
| `primary_degradation_pct` | `float \| None` | Sport-type-specific primary degradation percentage |
| `secondary_degradation_value` | `float \| None` | Sport-type-specific secondary metric |
| `fatigue_type_flag` | `"NEUROMUSCULAR" \| "CARDIORESPIRATORY" \| "NOMINAL"` | Fatigue mechanism classification |
| `discrepancy_flag` | `bool` | True when RPE > 6.5 AND external output looks normal |
| `affective_fatigue_score` | `float` | 0.0–1.0; keyword NLP on description |
| `description_raw` | `str \| None` | Raw activity description or name |

**Algorithm:**

1. Instantiate `DataRepository(run_dir)`.
2. Call `compute_atl_ctl(target_date)` → `atl`, `ctl`, `tsb`.
3. Compute `physical_load_score = clamp(atl / 80 * 100, 0, 100)`.
4. Sum weekly relative effort for current 7-day window (target−6 to target) and prior 7-day window (target−13 to target−7) by iterating `repo._strava_summary`.
5. Call `get_activity_today(target_date)`. If `None`, set `has_activity=False` and skip steps 6–12.
6. Extract `relative_effort_today`, `rpe_today`, `average_speed_today`, `sport_type`, `description_raw` from the merged activity.
7. Read computed lap degradation fields: `biomechanical_cadence_degradation_pct` (cadence % drop first-half vs last-half), `pace_degradation_pct` (speed % drop).
8. **Sport-type branching** for primary/secondary degradation metric *(UNVALIDATED_HEURISTIC)*:
   - `Run` → primary = cadence degradation %, secondary = pace degradation %
   - `Ride` / `VirtualRide` → primary = pace degradation %, secondary = cardio efficiency index
   - `Swim` → primary = pace degradation %, secondary = `None`
   - Other → primary = pace degradation %, secondary = cardio efficiency index
9. **Fatigue-type classification** (requires both cadence and pace degradation available) *(UNVALIDATED_HEURISTIC)*:
   - `cadence_deg > 5` → `NEUROMUSCULAR`
   - `pace_deg > 8 AND cadence_deg < 3` → `CARDIORESPIRATORY`
   - else → `NOMINAL`
10. **Discrepancy flag:** `rpe_today > 6.5 AND primary_deg < 5 AND pace_deg < 8` *(UNVALIDATED_HEURISTIC)*
11. **Affective fatigue score:** keyword scan of description against 15 weighted terms (see table below). Score = `min(1.0, sum_of_weights / 2.0)`. Also sets `discrepancy_flag=True` if `affective_score > 0.5 AND high_perceived_cost`.
12. Write `ctx.state["node2_metrics"]`.

**Key thresholds (all UNVALIDATED_HEURISTIC):**

| Threshold | Value | Signal |
|---|---|---|
| ATL normalisation ceiling | 80 | `physical_load_score` |
| RPE threshold for discrepancy | > 6.5 | `discrepancy_flag` |
| Primary degradation normal ceiling | < 5% | `discrepancy_flag` external output check |
| Pace degradation normal ceiling | < 8% | `discrepancy_flag` external output check |
| Cadence degradation → NEUROMUSCULAR | > 5% | `fatigue_type_flag` |
| Pace degradation → CARDIORESPIRATORY | > 8% (with cadence < 3%) | `fatigue_type_flag` |
| Affective score → discrepancy | > 0.5 (with RPE > 6.5) | `discrepancy_flag` |
| Affective score normalisation | sum / 2.0, capped at 1.0 | `affective_fatigue_score` |

**Keyword weights for affective fatigue scoring:**

| Keyword | Weight |
|---|---|
| exhausted | 1.0 |
| dead legs | 0.9 |
| drained | 0.9 |
| nothing left | 0.9 |
| dead | 0.8 |
| no energy | 0.8 |
| dig deep | 0.8 |
| empty | 0.8 |
| flat | 0.7 |
| sluggish | 0.7 |
| struggled | 0.7 |
| heavy | 0.6 |
| tired | 0.6 |
| hard | 0.4 |
| tough | 0.4 |

**What Node 2 does NOT do:** access any HealthKit data; use an LLM (keyword NLP only); fail on rest days (it writes `has_activity=False` with zeroed metrics).

---

### Node 3 — Autonomic Decoupler

**File:** [agents/nodes/autonomic_decoupler.py](agents/nodes/autonomic_decoupler.py)

**Purpose:** Compute the Psychological Strain Index (PSI) and Physical Load Index (PLI) from Nodes 1 and 2 outputs, then emit a routing verdict. No LLM. No external I/O.

> **ADR-003:** This node MUST remain deterministic and auditable. Never add an LLM to this node.

**Inputs:**

| Source | Fields read |
|---|---|
| `ctx.state["node1_flags"]` | `cold_start`, `baseline_stats` (per-metric mean/std), `today_values` (hrv, rhr, sleep_efficiency, sleep_awake_hours, sleep_deep_hours, deep_sleep_latency_minutes, rem_sleep_latency_minutes, late_night_awake_windows_count) |
| `ctx.state["node2_metrics"]` | `has_activity`, `rpe_today`, `relative_effort_today`, `discrepancy_flag`, `affective_fatigue_score`, `atl`, `week_effort_current`, `week_effort_prior`, `fatigue_type_flag`, `primary_degradation_pct` |

**Outputs:**

| Field | Type | Range |
|---|---|---|
| `ctx.state["psychological_strain_index"]` | `float` | 0–100 |
| `ctx.state["physical_load_index"]` | `float` | 0–100 |
| `ctx.state["node3_verdict"]` | `str` | `NONE \| PHYSICAL \| PSYCHOLOGICAL \| AMBIGUOUS` |
| `ctx.state["node1_flags"]["psi_breakdown"]` | `dict` | Component scores (appended to existing flags) |
| `ctx.state["node1_flags"]["pli_breakdown"]` | `dict` | Component scores (appended to existing flags) |
| `ctx.route` | `str` | Same as verdict — used by ADK for conditional edge matching |

**Algorithm:**

1. If `cold_start=True`: PSI=0, PLI=0, verdict=`NONE`, return early.
2. **PSI components** (all UNVALIDATED_HEURISTIC):

   | Component | Weight | Formula |
   |---|---|---|
   | HRV suppression | 35% | `clamp((mean_hrv − today_hrv) / mean_hrv * 100 / 30 * 100, 0, 100) × 0.35` |
   | Excess awake time | 25% | `clamp(z_awake / 3 * 100, 0, 100) × 0.25` where z = (today − mean) / std |
   | Deep sleep deficit | 20% | `clamp(z_deep / 3 * 100, 0, 100) × 0.20` where z = (mean − today) / std |
   | RPE dissociation | 15% | `clamp(base_dissociation × multiplier / 3 * 100, 0, 100) × 0.15` — see below |
   | RHR elevation | 5% | `clamp(z_rhr / 3 * 100, 0, 100) × 0.05` |
   | Sleep latency | 8% combined | deep_latency_component + rem_latency_component + late_night_component |

   RPE dissociation details:
   - `base_dissociation = max(0, rpe_zscore − effort_zscore)` where `rpe_zscore = (rpe − 5.5) / 1.5` and `effort_zscore = (relative_effort − 30) / 15`
   - Multiplier: `1.3` if `discrepancy_flag`, `1.15` if `affective_score > 0.5`, else `1.0`
   - Zero if no activity or no RPE data

   Sleep latency PSI sub-components:
   - Deep latency > 60 min: `clamp((deep_lat − 60) / 90 * 100, 0, 100) × 0.03`
   - REM latency > 120 min: `clamp((rem_lat − 120) / 60 * 100, 0, 100) × 0.03`
   - Late-night count ≥ 2: `clamp((count − 1) / 3 * 100, 0, 100) × 0.02`

3. **PLI components** (all UNVALIDATED_HEURISTIC):

   | Component | Weight | Formula |
   |---|---|---|
   | ATL | 40% | `clamp(atl / 80 * 100, 0, 100) × 0.40` |
   | Week-over-week spike | 35% | `clamp(wow_pct / 50 * 100, 0, 100) × 0.35` where `wow_pct = max(0, (current − prior) / prior * 100)` |
   | Degradation-aware | 15% | `deg_score × 0.15` — see below |
   | Sleep efficiency deficit | 10% | `clamp(z_eff / 3 * 100, 0, 100) × 0.10` where z = (mean − today) / std |

   Degradation-aware PLI:
   - `NEUROMUSCULAR`: `deg_score = clamp(primary_deg / 15 * 100, 0, 100)`
   - `CARDIORESPIRATORY`: `deg_score = clamp(primary_deg / 12 * 100, 0, 100)`
   - `NOMINAL`: `deg_score = clamp(primary_deg / 10 * 100, 0, 100)`
   - Zero if no activity or no `primary_degradation_pct`

4. **Routing rules** (UNVALIDATED_HEURISTIC — Phase 7 for calibration):

   | Condition | Verdict |
   |---|---|
   | `PSI > 45 AND PLI < 45` | `PSYCHOLOGICAL` |
   | `PLI > 60 AND PSI < 35` | `PHYSICAL` |
   | `PSI > 45 AND PLI > 45` | `AMBIGUOUS` |
   | else | `NONE` |

5. Append `psi_breakdown` and `pli_breakdown` dicts to `ctx.state["node1_flags"]`.
6. Write `psychological_strain_index`, `physical_load_index`, `node3_verdict` to state.
7. Set `ctx.route = verdict`.

**What Node 3 does NOT do:** call any LLM (ADR-003); read any files; modify `node2_metrics`.

---

### Node 4 — Insights Engine

**File:** [agents/nodes/insights_engine.py](agents/nodes/insights_engine.py)

**Purpose:** Call Gemini to produce a fine-grained classification label and a 2–4 sentence insight grounded in the athlete's specific numbers.

**Inputs:** All fields in `ctx.state` (passed to `_build_user_prompt`):

| State fields used | Purpose |
|---|---|
| `node1_flags` (all subkeys) | Biometric flags, baseline stats, today values, latency flags, PSI/PLI breakdowns |
| `node2_metrics` (all subkeys) | Training load, activity details, fatigue type, discrepancy, affective score, description |
| `psychological_strain_index`, `physical_load_index` | Scores shown to model |
| `node3_verdict`, `target_date` | Context shown to model |

**Outputs:**

| State field | Type | Values |
|---|---|---|
| `node4_classification` | `str \| None` | One of 8 classes (see Section 1) |
| `final_insight` | `str \| None` | 2–4 sentence insight text |

**Algorithm:**

1. Read `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) from environment. Skip if missing.
2. Import `google.genai`. Skip if not installed.
3. Call `_build_user_prompt(ctx.state)` to construct a structured prompt containing: date, verdict, flags triggered, biometrics vs baseline table, sleep architecture latency flags, training load summary, psychological load signals, PSI/PLI scores with component breakdowns, and the athlete's own words (if `description_raw` is set).
4. Call `client.models.generate_content()` with:
   - `model`: `NODE4_MODEL` env var (default: `gemini-2.5-flash`)
   - `system_instruction`: the `SYSTEM_PROMPT` constant
   - `temperature`: `0.3`
5. Strip markdown fences from response if present (` ```json ... ``` `).
6. Parse JSON. Validate that `classification` and `insight_text` keys are present.
7. On `JSONDecodeError` or missing keys: retry up to **2 attempts total**. After exhausting retries, print error and return without writing state.
8. Write `ctx.state["node4_classification"]` and `ctx.state["final_insight"]`.

**System prompt rules:**

- Every claim must cite a specific number from the provided data.
- Forbidden words: `burnout` (as standalone noun-diagnosis), `anxiety`, `depression`, `condition`, `medical`, `clinical`, `diagnose`, `disorder`.
- Permitted trajectory language: `early burnout trajectory pattern`, `cognitive fatigue signal`, `autonomic suppression pattern`, `recovery trajectory`, `well-recovered state`, `balanced load profile`, `healthy adaptation`.
- Must select exactly one classification from the 8-class taxonomy.
- `insight_text` must be 2–4 sentences.
- Response must be valid JSON with exactly two keys: `classification` and `insight_text`.

**Expected Gemini response format:**

```json
{
  "classification": "EARLY_BURNOUT_TRAJECTORY",
  "insight_text": "Your HRV has dropped to 38 ms, 27% below your 14-day mean of 52 ms, alongside 2.1 h of waking time versus your typical 0.9 h. This autonomic suppression pattern — combined with a PSI of 61/100 — is consistent with an early burnout trajectory pattern, likely driven by accumulated cognitive load rather than this week's moderate training stress (PLI 28/100)."
}
```

**What Node 4 does NOT do:** access files directly (all data comes through state); apply deterministic thresholds (that is Node 3's role); write to `node3_verdict` or any Node 1/2/3 state fields.

---

## SECTION 5 — DATA FORMATS
*For: agents reading or generating scenario data*

### File inventory per scenario directory

| File | Required | Purpose |
|---|---|---|
| `raw_healthkit_daily_summary.json` | Yes | One row per day of biometric summaries |
| `raw_healthkit_samples.json` | Optional | Raw granular samples for sleep-stage latency analysis |
| `strava_summary_activities.json` | Yes | Lightweight activity list (resource_state=2) |
| `strava_detailed_activities.json` | Yes | Full activity records with laps, description, perceived_exertion |
| `manifest.json` | Yes | Ground-truth labels for evaluation |

---

### `raw_healthkit_daily_summary.json`

Array of objects. One object per calendar day.

| Field | Type | Description |
|---|---|---|
| `summary_id` | `str` | UUID |
| `user_id` | `str` | e.g. `"user_001"` |
| `summary_date` | `str` | `YYYY-MM-DD` |
| `hrv_sdnn_ms` | `float` | HRV SDNN in milliseconds |
| `resting_hr_bpm` | `float` | Resting heart rate in bpm |
| `sleep_total_hours` | `float` | Total sleep duration |
| `sleep_efficiency_pct` | `float` | 0–100 |
| `sleep_deep_hours` | `float` | Deep (slow-wave) sleep hours |
| `sleep_rem_hours` | `float` | REM sleep hours |
| `sleep_core_hours` | `float` | Core (light) sleep hours |
| `sleep_awake_hours` | `float` | Waking time within sleep window |
| `avg_respiratory_rate_bpm` | `float` | Overnight average respiratory rate |
| `avg_spo2_pct` | `float` | Blood oxygen saturation % |

---

### `raw_healthkit_samples.json`

Array of objects. Each object is one granular HealthKit sample.

| Field | Type | Description |
|---|---|---|
| `sample_id` | `str` | UUID |
| `user_id` | `str` | |
| `sample_date` | `str` | `YYYY-MM-DD` — the calendar date this sample belongs to |
| `start_timestamp` | `str` | ISO 8601 datetime (with or without microseconds) |
| `end_timestamp` | `str` | ISO 8601 datetime |
| `sample_type` | `str` | HealthKit type identifier (see below) |
| `value` | `float \| null` | Quantitative value for quantity types |
| `unit` | `str \| null` | Unit string (e.g. `"ms"`) |
| `category_value` | `str \| null` | Category value for sleep analysis samples |
| `source_name` | `str` | e.g. `"Apple Watch"` |

**Sleep analysis category values used by Node 1:**

| `category_value` | Meaning |
|---|---|
| `HKCategoryValueSleepAnalysisAsleepCore` | Light (core) sleep |
| `HKCategoryValueSleepAnalysisAsleepDeep` | Deep (slow-wave) sleep |
| `HKCategoryValueSleepAnalysisAsleepREM` | REM sleep |
| `HKCategoryValueSleepAnalysisAwake` | Awake within sleep window |

Sleep onset is defined as the earliest `start_timestamp` among any asleep category record for that date. Latencies are measured in minutes from sleep onset to the first occurrence of each stage.

---

### `strava_summary_activities.json`

Array of objects. Each is a Strava resource_state=2 (summary) activity record.

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Strava activity ID |
| `name` | `str` | Activity name |
| `sport_type` | `str` | `"Run"`, `"Ride"`, `"VirtualRide"`, `"Swim"`, etc. |
| `start_date` | `str` | ISO 8601 datetime (UTC) — first 10 chars used as date key |
| `distance` | `float` | Metres |
| `moving_time` | `int` | Seconds |
| `average_speed` | `float` | m/s |
| `average_heartrate` | `float` | bpm |
| `relative_effort` | `int \| null` | Strava relative effort score |

---

### `strava_detailed_activities.json`

Array of objects. Each is a Strava resource_state=3 (detailed) activity record. Contains all fields from the summary plus:

| Field | Type | Description |
|---|---|---|
| `description` | `str \| null` | Athlete's written workout description |
| `perceived_exertion` | `float \| null` | RPE on a 1–10 scale |
| `average_cadence` | `float \| null` | Steps/min (Run) or RPM (Ride) |
| `average_watts` | `float \| null` | Power (Ride only) |
| `calories` | `float` | Estimated caloric expenditure |
| `laps` | `array` | Array of lap objects (see below) |

**Lap object fields used by `DataRepository._compute_activity_degradation()`:**

| Field | Type | Description |
|---|---|---|
| `average_cadence` | `float \| null` | Per-lap cadence |
| `average_speed` | `float \| null` | Per-lap speed in m/s |

Degradation is computed only when ≥ 4 laps are present. First-half mean vs. last-half mean.

---

### `manifest.json`

Array of objects. One per calendar day. Used only for evaluation (Node 4 correctness checking); not used in the pipeline computation.

| Field | Type | Description |
|---|---|---|
| `day_index` | `int` | 0-based sequential day index |
| `date` | `str` | `YYYY-MM-DD` |
| `psychological_load` | `float` | Generator-level psych load signal (0–1) |
| `physical_load` | `float` | Generator-level physical load signal (0–1) |
| `phase_label` | `str` | Narrative phase name (e.g. `"overreach_block"`, `"taper_recovery"`) |
| `is_rest_day` | `bool` | True if no training activity on this day |
| `expected_node3_verdict` | `str` | Ground-truth verdict: `"NONE"`, `"PHYSICAL"`, `"PSYCHOLOGICAL"`, `"AMBIGUOUS"` |
| `expected_node4_classification` | `str \| null` | Ground-truth classification label or `null` if not applicable |

---

### Memory record schema (JSONL)

Each line in `memory/{user_id}/memory_log.jsonl` is one JSON object:

```json
{
  "user_id": "user_001",
  "date": "2026-06-08",
  "readiness_score": 45.0,
  "mental_fatigue": 61.2,
  "physical_fatigue": 28.4,
  "node3_verdict": "PSYCHOLOGICAL",
  "classification": "EARLY_BURNOUT_TRAJECTORY",
  "key_signals": {
    "hrv_pct_vs_baseline": -22.5,
    "deep_sleep_pct_vs_baseline": -18.0,
    "sleep_fragmented": true,
    "hrv_suppressed": true,
    "discrepancy_flag": false,
    "consecutive_psych_days": 3
  }
}
```

| Field | Type | Description |
|---|---|---|
| `user_id` | `str` | User identifier |
| `date` | `str` | `YYYY-MM-DD` |
| `readiness_score` | `float` | 0–100, higher = better readiness |
| `mental_fatigue` | `float` | 0–100; maps to PSI (higher = more strain) |
| `physical_fatigue` | `float` | 0–100; maps to PLI (higher = more load) |
| `node3_verdict` | `str` | `NONE \| PHYSICAL \| PSYCHOLOGICAL \| AMBIGUOUS` |
| `classification` | `str \| null` | Node 4 taxonomy label |
| `key_signals.hrv_pct_vs_baseline` | `float` | % change from 14d mean; negative = suppressed |
| `key_signals.deep_sleep_pct_vs_baseline` | `float` | % change from 14d mean; negative = reduced |
| `key_signals.sleep_fragmented` | `bool` | |
| `key_signals.hrv_suppressed` | `bool` | |
| `key_signals.discrepancy_flag` | `bool` | |
| `key_signals.consecutive_psych_days` | `int` | Trailing days with `PSYCHOLOGICAL` or `AMBIGUOUS` verdict, including today |

`consecutive_psych_days` is computed automatically by `MemoryRepository.write_today()` from the existing history — do not set it manually in the record passed to `write_today`.

---

## SECTION 6 — MULTI-AGENT INTEGRATION
*For: agents invoking or downstream-routing from this pipeline*

### Programmatic invocation

```python
import asyncio
from agents.graph_orchestrator import run_pipeline

final_state = asyncio.run(
    run_pipeline(
        user_id="user_001",
        target_date="2026-06-08",
        run_dir="/absolute/path/to/datasets/training_overreach",
    )
)
```

`run_pipeline` is a coroutine. It returns a `dict` containing all session state fields after all nodes have run.

### Returned state dict keys

```python
{
    # Inputs (echoed back)
    "user_id":     str,
    "target_date": str,
    "run_dir":     str,

    # Node 1
    "node1_flags": {
        "cold_start": bool,
        "today_values": dict,
        "baseline_stats": dict,
        "hrv_suppressed": bool,
        "rhr_elevated": bool,
        "sleep_fragmented": bool,
        "deep_sleep_reduced": bool,
        "late_night_awake_flag": bool | None,
        "deep_sleep_latency_flag": str | None,
        "rem_latency_flag": str | None,
        # Added by Node 3:
        "psi_breakdown": dict,
        "pli_breakdown": dict,
    },

    # Node 2
    "node2_metrics": {
        "atl": float, "ctl": float, "tsb": float,
        "physical_load_score": float,
        "week_effort_current": float, "week_effort_prior": float,
        "has_activity": bool,
        "relative_effort_today": float | None,
        "rpe_today": float | None,
        "average_speed_today": float | None,
        "sport_type": str | None,
        "primary_degradation_pct": float | None,
        "secondary_degradation_value": float | None,
        "fatigue_type_flag": str,
        "discrepancy_flag": bool,
        "affective_fatigue_score": float,
        "description_raw": str | None,
    },

    # Node 3
    "psychological_strain_index": float,  # 0–100
    "physical_load_index": float,          # 0–100
    "node3_verdict": str,                  # NONE | PHYSICAL | PSYCHOLOGICAL | AMBIGUOUS

    # Node 4
    "node4_classification": str | None,
    "final_insight": str | None,
}
```

### Reading longitudinal memory

```python
from agents.memory_repository import MemoryRepository

mem = MemoryRepository()  # reads MEMORY_BACKEND env var; defaults to "jsonl"
history = mem.read_history("user_001", n_days=14)
# Returns list[dict], sorted oldest-first, up to 14 entries
```

### Suggested downstream routing

| `node3_verdict` | Suggested downstream action |
|---|---|
| `PSYCHOLOGICAL` | Route to cognitive health / mental performance agent; flag for coach review if `consecutive_psych_days >= 3` |
| `PHYSICAL` | Route to sports medicine / recovery planning agent; flag for coach review if `PLI > 80` |
| `AMBIGUOUS` | Route to a coordination agent that can invoke both; requires multi-modal assessment |
| `NONE` | No action required; log to memory and continue monitoring |

For PSYCHOLOGICAL/AMBIGUOUS routing, `final_insight` and `node4_classification` provide the LLM-generated context to pass to the downstream agent.

### How to extend — adding a new node

1. Write a new `async def _my_node_fn(ctx) -> None` that reads from and writes to `ctx.state`.
2. Wrap it: `my_node = FunctionNode(func=_my_node_fn, name="my_node")`.
3. Add a field for its outputs to `PsychobioState` in [agents/graph_state.py](agents/graph_state.py).
4. Add edges to `root_workflow` in [agents/graph_orchestrator.py](agents/graph_orchestrator.py):
   ```python
   (insights_engine, my_node),  # after Node 4
   ```

### Current limitations

- **No live API integration:** HealthKit and Strava data must be pre-exported to JSON before running. There is no live webhook, OAuth flow, or polling loop.
- **BigQuery backend is a stub:** `MemoryRepository(backend="bigquery")` raises `NotImplementedError`. Set `MEMORY_BACKEND=jsonl` for all current use.
- **All heuristic thresholds are unvalidated:** Phase 7 calibration against labelled athlete data is pending. Do not treat PSI/PLI absolute values or verdict boundaries as clinically validated.
- **Cold-start behaviour is partial:** When < 7 days of history exist, `cold_start=True` is set and all deviation flags are skipped. The agent produces `NONE` verdict. Behaviour for genuinely new users is not fully defined beyond this.
- **Node 4 always runs:** Despite orchestrator comments suggesting conditional routing, the actual ADK edge wiring is unconditional. Every run calls Gemini.

---

## SECTION 7 — CONFIGURATION REFERENCE
*For: DevOps, engineers deploying the system*

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes (local) | — | Google AI Studio API key for Node 4 Gemini calls. Also checked as `GOOGLE_API_KEY`. |
| `GOOGLE_CLOUD_PROJECT` | No | `""` | GCP project ID. Required when switching to ADC (`google.auth.default()`) for production. |
| `GOOGLE_CLOUD_LOCATION` | No | `us-central1` | GCP region for Vertex AI / Agent Engine deployments. |
| `NODE4_MODEL` | No | `gemini-2.5-flash` | Gemini model used by Node 4. Options: `gemini-2.5-flash`, `gemini-2.5-pro`. Overridable per-run via `--model` CLI flag. |
| `ADK_MEMORY_BACKEND` | No | `in_memory` | ADK session service backend. Current value `in_memory` uses `InMemorySessionService`. Set to `vertex` to use `VertexAiSessionService` (requires GCP credentials). |
| `MEMORY_BACKEND` | No | `jsonl` | PsychoBio memory layer backend. Values: `jsonl` (active), `bigquery` (stub — not implemented). |

The `.env` file in the repo root is loaded by `psychobio_engine_adk.py` without requiring `python-dotenv`. Keys already present in `os.environ` are not overwritten.

---

## SECTION 8 — TEST SCENARIOS
*For: engineers and agents running validation*

| Scenario name | CLI flag | Data directory | Date range | Expected verdict pattern | Signal tested |
|---|---|---|---|---|---|
| `progressive_work_burnout` | `--scenario progressive_work_burnout` | `datasets/progressive_work_burnout/user_001/20260526T021707Z` | 2025-01-01 onward | `NONE` → escalating `PSYCHOLOGICAL` → `AMBIGUOUS` | Gradual HRV suppression + sleep disruption without matching physical load |
| `progressive_work_burnout_sim` | `--scenario progressive_work_burnout_sim` | `datasets/progressive_work_burnout_sim` | 2026-05-27 onward | `NONE` → escalating `PSYCHOLOGICAL` → `AMBIGUOUS` | Same pattern, simulator-generated data with May–Jun 2026 dates for spot-checking |
| `training_overreach` | `--scenario training_overreach` | `datasets/training_overreach` | 2026-05-28 – 2026-06-26 | `NONE` (baseline_training_block) → `PHYSICAL` (overreach_block, days 7–15) → `NONE` (taper_recovery) | Week-over-week ATL spike + cadence/pace degradation without psychological signals |
| `healthy_baseline` | `--scenario healthy_baseline` | `datasets/healthy_baseline` | 2026-05-28 onward | `NONE` throughout | Stable biometrics + moderate load — no flags should trigger |
| `emotional_volatility` | `--scenario emotional_volatility` | `datasets/emotional_volatility` | 2026-05-28 onward | `NONE` → periodic `PSYCHOLOGICAL` spikes | High RPE–output discrepancy + affective language in descriptions + HRV perturbations without load spike |

---

## SECTION 9 — DESIGN DECISIONS & KNOWN LIMITATIONS
*For: engineers, researchers, and agents reasoning about system behaviour*

### Why Nodes 1–3 are deterministic (no LLM)

Nodes 1, 2, and 3 are pure Python with no LLM calls. This is a deliberate architectural choice:

- **Auditability:** Every flag and score can be traced to a specific formula and input value. There are no opaque probabilities.
- **Testability:** Deterministic nodes produce identical output for identical input, enabling unit testing without mocking.
- **No hallucination risk:** Biometric flags and PSI/PLI scores cannot be invented by a model. If `hrv_suppressed=True`, it means the HRV was measurably below the 1.5σ threshold.
- **Cost:** Nodes 1–3 run at zero API cost, making frequent per-day pipeline runs affordable.

Node 4 uses Gemini specifically for the synthesis task — translating numeric patterns into athlete-facing language — where a language model adds genuine value.

### Why Node 4 uses temperature=0.3

Temperature 0.3 is low enough to ensure the model consistently cites the numbers it was given rather than generating creative but ungrounded narrative. It is not zero because the model must select context-appropriate phrasing from the permitted taxonomy.

### Heuristic thresholds — UNVALIDATED_HEURISTIC

Every numerical threshold in this system is marked `UNVALIDATED_HEURISTIC` in the source code. This means:

- They were chosen based on physiological literature and engineering judgement, not calibrated against labelled athlete data.
- They have NOT been validated against actual athlete outcomes (injury, performance decline, subjective fatigue ratings).
- **Phase 7** of the project roadmap is dedicated to threshold calibration using a labelled dataset. Until that phase is complete, PSI/PLI absolute values and verdict classifications should be interpreted as directional signals, not clinical measurements.
- Downstream agents and coaches should treat `PSYCHOLOGICAL` and `AMBIGUOUS` verdicts as "worth investigating further" rather than definitive diagnoses.

### Cold-start behaviour

When a user has fewer than 7 days of prior history in `raw_healthkit_daily_summary.json`:
- `DataRepository.get_baseline_stats()` returns an empty dict `{}`.
- Node 1 sets `cold_start=True`, skips all deviation flags, and writes empty `today_values` and `baseline_stats`.
- Node 3 detects `cold_start=True`, sets PSI=0, PLI=0, verdict=`NONE`, and returns.
- Node 4 still runs (due to unconditional edge) but will produce a `WELL_RECOVERED` or `OPTIMAL_LOAD` classification based on limited data.

When a user has 7–13 days of history:
- `get_baseline_stats()` returns stats with `cold_start=True` embedded.
- Node 1 populates `today_values` and `baseline_stats` but **does not** compute deviation flags.
- This represents partial cold-start: some context is available but flags are suppressed.

Behaviour for truly new users (0 days) is identical to < 7 days.

### No live API integration

HealthKit data must be exported from the Apple Health app or a Health platform API and formatted as `raw_healthkit_daily_summary.json` and `raw_healthkit_samples.json`. Strava data must be exported via the Strava API and formatted as `strava_summary_activities.json` and `strava_detailed_activities.json`. The pipeline has no built-in OAuth, webhook, or polling mechanism. Adding live ingestion would require a new preprocessing layer upstream of `DataRepository`.
