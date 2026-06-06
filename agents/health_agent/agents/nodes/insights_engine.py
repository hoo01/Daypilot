"""
insights_engine.py — Node 4: Insights Engine (ADK FunctionNode + Gemini).

Implemented as a FunctionNode wrapping a direct google-genai SDK call.
This gives full control over JSON schema validation and retry-on-parse-failure.

Always runs — every execution produces AI insights and a psychobiological
assessment regardless of Node 3 verdict (NONE, PHYSICAL, PSYCHOLOGICAL, AMBIGUOUS).

Config is loaded from config.py (pydantic_settings), aligning with the root
monolith's config pattern. NODE4_MODEL env var is still supported as a
runtime override (e.g. from the CLI --model flag).

Reads:  ctx.state (all node 1/2/3 outputs)
Writes: ctx.state["node4_classification"], ctx.state["final_insight"]
Also:   writes a longitudinal record to MemoryRepository after a successful run.
"""

from __future__ import annotations

import json
import os
from typing import Any

from google.adk.workflow import FunctionNode


SYSTEM_PROMPT = """You are a precision psychobiological analyst. You always produce a full assessment — every run gets AI insights and a classification, regardless of whether strain signals are elevated or nominal.

STRICT RULES — violating any rule makes your response invalid:
1. Every claim MUST cite a specific number from the provided data (e.g. "HRV at 42 ms, 22% below your 14-day mean of 54 ms").
2. FORBIDDEN words: "burnout" as a standalone noun-diagnosis, "anxiety", "depression", "condition", "medical", "clinical", "diagnose", "disorder".
3. PERMITTED trajectory language: "early burnout trajectory pattern", "cognitive fatigue signal", "autonomic suppression pattern", "recovery trajectory", "well-recovered state", "balanced load profile", "healthy adaptation".
4. Select EXACTLY ONE classification tag from:
   ACUTE_COGNITIVE_LOAD | CHRONIC_COGNITIVE_FATIGUE | EARLY_BURNOUT_TRAJECTORY |
   EMOTIONAL_VOLATILITY | WELL_RECOVERED | OPTIMAL_LOAD | PHYSICAL_OVERREACH | RECOVERY_IN_PROGRESS
   — Use WELL_RECOVERED when biometrics are within or above baseline and load is moderate.
   — Use OPTIMAL_LOAD when training load is elevated but biometrics remain stable.
   — Use PHYSICAL_OVERREACH when PLI is high and physical degradation signals dominate.
   — Use RECOVERY_IN_PROGRESS when signals are improving but not yet at baseline.
5. insight_text must be 2-4 sentences, grounded entirely in the numbers provided.
6. If the athlete's own words are provided and relevant, reference them.
7. Return ONLY valid JSON with exactly two keys: "classification" and "insight_text". No markdown fences."""


def _build_user_prompt(state) -> str:
    """Accept either a plain dict or an ADK State object via .get()."""
    flags   = state.get("node1_flags", {})
    metrics = state.get("node2_metrics", {})
    bs      = flags.get("baseline_stats", {})
    tv      = flags.get("today_values", {})
    psi_bd  = flags.get("psi_breakdown", {})
    pli_bd  = flags.get("pli_breakdown", {})

    def _fmt(v: Any, spec: str) -> str:
        return format(v, spec) if isinstance(v, (int, float)) else str(v)

    hrv_mean        = bs.get("hrv_sdnn_ms", {}).get("mean", "N/A")
    hrv_today       = tv.get("hrv_sdnn_ms", "N/A")
    rhr_mean        = bs.get("resting_hr_bpm", {}).get("mean", "N/A")
    rhr_today       = tv.get("resting_hr_bpm", "N/A")
    sleep_eff_mean  = bs.get("sleep_efficiency_pct", {}).get("mean", "N/A")
    sleep_eff_today = tv.get("sleep_efficiency_pct", "N/A")
    deep_mean       = bs.get("sleep_deep_hours", {}).get("mean", "N/A")
    deep_today      = tv.get("sleep_deep_hours", "N/A")
    awake_mean      = bs.get("sleep_awake_hours", {}).get("mean", "N/A")
    awake_today     = tv.get("sleep_awake_hours", "N/A")

    # Sleep latency signals
    late_night_awake_flag   = flags.get("late_night_awake_flag")
    deep_sleep_latency_flag = flags.get("deep_sleep_latency_flag")
    rem_latency_flag        = flags.get("rem_latency_flag")
    deep_latency_min        = tv.get("deep_sleep_latency_minutes", "N/A")
    rem_latency_min         = tv.get("rem_sleep_latency_minutes", "N/A")
    late_night_count        = tv.get("late_night_awake_windows_count", "N/A")

    fatigue_type_flag = metrics.get("fatigue_type_flag", "NOMINAL")
    discrepancy_flag  = metrics.get("discrepancy_flag", False)
    description_raw   = metrics.get("description_raw")

    activity_summary = "No activity today (rest day)."
    if metrics.get("has_activity"):
        activity_summary = (
            f"Sport: {metrics.get('sport_type', 'Unknown')}, "
            f"Relative Effort: {metrics.get('relative_effort_today')}, "
            f"RPE: {metrics.get('rpe_today')}, "
            f"Avg Speed: {metrics.get('average_speed_today')} m/s, "
            f"Fatigue type: {fatigue_type_flag}, "
            f"Primary degradation: {metrics.get('primary_degradation_pct')}%"
        )

    flags_triggered = [
        f for f in ["hrv_suppressed", "rhr_elevated", "sleep_fragmented", "deep_sleep_reduced"]
        if flags.get(f)
    ]

    athlete_words_section = ""
    if description_raw:
        athlete_words_section = f"\nATHLETE'S OWN WORDS:\n- Activity description: \"{description_raw}\"\n"

    return f"""Date: {state.get("target_date")}
Node 3 Verdict: {state.get("node3_verdict")}
Flags triggered: {", ".join(flags_triggered) if flags_triggered else "none"}

BIOMETRICS vs 14-day baseline:
- HRV (SDNN): today={hrv_today} ms, 14d mean={_fmt(hrv_mean, ".1f")} ms
- Resting HR: today={rhr_today} bpm, 14d mean={_fmt(rhr_mean, ".1f")} bpm
- Sleep efficiency: today={sleep_eff_today}%, 14d mean={_fmt(sleep_eff_mean, ".1f")}%
- Deep sleep: today={deep_today} h, 14d mean={_fmt(deep_mean, ".2f")} h
- Awake hours: today={awake_today} h, 14d mean={_fmt(awake_mean, ".2f")} h

SLEEP ARCHITECTURE (latency flags):
- Late-night awake windows (02:00\u201306:00): {late_night_count} (flag={late_night_awake_flag})
- Deep sleep latency: {deep_latency_min} min (flag={deep_sleep_latency_flag})
- REM sleep latency: {rem_latency_min} min (flag={rem_latency_flag})

TRAINING LOAD:
- ATL: {metrics.get("atl", 0):.1f}, CTL: {metrics.get("ctl", 0):.1f}, TSB: {metrics.get("tsb", 0):.1f}
- Activity today: {activity_summary}
- Week effort current: {metrics.get("week_effort_current", 0):.0f}, prior week: {metrics.get("week_effort_prior", 0):.0f}

PSYCHOLOGICAL LOAD SIGNALS:
- RPE\u2013output discrepancy flag: {discrepancy_flag}
- Affective fatigue score (keyword NLP): {metrics.get("affective_fatigue_score", 0.0):.2f}
{athlete_words_section}
SCORES:
- PSI (Psychological Strain Index): {state.get("psychological_strain_index", 0):.1f}/100
  Components: HRV={psi_bd.get("hrv_component", 0):.1f}, Awake={psi_bd.get("awake_component", 0):.1f}, Deep={psi_bd.get("deep_component", 0):.1f}, RPE-dissociation={psi_bd.get("dissociation_component", 0):.1f}, RHR={psi_bd.get("rhr_component", 0):.1f}, Latency={psi_bd.get("latency_component", 0):.1f}
- PLI (Physical Load Index): {state.get("physical_load_index", 0):.1f}/100
  Components: ATL={pli_bd.get("atl_component", 0):.1f}, WoW={pli_bd.get("wow_component", 0):.1f}, Degradation={pli_bd.get("degradation_component", 0):.1f}, SleepEff={pli_bd.get("eff_component", 0):.1f}
"""


def _write_memory(ctx, classification: str) -> None:
    """
    Write today's record to MemoryRepository after a successful Node 4 run.
    Errors are caught and printed — memory write failure never aborts the pipeline.
    """
    from agents.health_agent.agents.memory_repository import MemoryRepository
    from config import settings

    flags   = ctx.state.get("node1_flags", {})
    metrics = ctx.state.get("node2_metrics", {})
    bs      = flags.get("baseline_stats", {})
    tv      = flags.get("today_values", {})

    hrv_mean  = bs.get("hrv_sdnn_ms", {}).get("mean")
    hrv_today = tv.get("hrv_sdnn_ms")
    hrv_pct   = round((hrv_today - hrv_mean) / hrv_mean * 100, 1) if hrv_mean and hrv_today else None

    deep_mean  = bs.get("sleep_deep_hours", {}).get("mean")
    deep_today = tv.get("sleep_deep_hours")
    deep_pct   = round((deep_today - deep_mean) / deep_mean * 100, 1) if deep_mean and deep_today else None

    psi = ctx.state.get("psychological_strain_index", 0.0)
    pli = ctx.state.get("physical_load_index", 0.0)

    record = {
        "user_id":          ctx.state.get("user_id"),
        "date":             ctx.state.get("target_date"),
        "readiness_score":  round(100 - psi, 1),
        "mental_fatigue":   round(psi, 1),
        "physical_fatigue": round(pli, 1),
        "node3_verdict":    ctx.state.get("node3_verdict", "NONE"),
        "classification":   classification,
        "key_signals": {
            "hrv_pct_vs_baseline":        hrv_pct,
            "deep_sleep_pct_vs_baseline": deep_pct,
            "sleep_fragmented":           flags.get("sleep_fragmented", False),
            "hrv_suppressed":             flags.get("hrv_suppressed", False),
            "discrepancy_flag":           metrics.get("discrepancy_flag", False),
            "consecutive_psych_days":     0,  # computed by write_today()
        },
    }

    try:
        mem = MemoryRepository(backend=settings.memory_backend)
        mem.write_today(
            ctx.state.get("user_id", "unknown"),
            ctx.state.get("target_date", ""),
            record,
        )
        print(f"[Node 4] Memory write OK for {ctx.state.get('user_id')} on {ctx.state.get('target_date')}")
    except Exception as e:
        print(f"[Node 4] WARN: memory write failed: {e}")


async def _insights_engine_fn(ctx) -> None:
    """
    Node 4: Insights Engine.

    Calls Gemini to produce a classification and insight text.
    Uses settings.gemini_api_key (from config.py / .env).
    NODE4_MODEL env var is still honoured as a runtime override (e.g. CLI --model flag).
    Switch to ADC (google.auth.default()) for production.

    Always runs after Node 3 — every execution produces AI insights.
    After a successful Gemini response, writes a record to MemoryRepository.
    """
    from config import settings

    api_key = settings.gemini_api_key
    if not api_key:
        print("[Node 4] WARN: GEMINI_API_KEY not set — skipping Gemini analysis.")
        return

    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        print("[Node 4] ERROR: google-genai not installed.")
        return

    user_prompt = _build_user_prompt(ctx.state)
    # Runtime override (e.g. from CLI --model flag) takes precedence over settings
    model = os.environ.get("NODE4_MODEL") or settings.node4_model

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                ),
            )
            raw = response.text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            parsed = json.loads(raw.strip())
            classification = parsed.get("classification")
            insight_text   = parsed.get("insight_text")

            if not classification or not insight_text:
                raise ValueError(f"Missing keys in Gemini response: {parsed}")

            ctx.state["node4_classification"] = classification
            ctx.state["final_insight"]         = insight_text

            # Wire MemoryRepository: persist longitudinal record
            _write_memory(ctx, classification)
            return

        except json.JSONDecodeError as e:
            print(f"[Node 4] JSON parse error on attempt {attempt}: {e}")
            if attempt == max_retries:
                print(f"[Node 4] All retries exhausted. Raw response:\n{raw}")
        except Exception as e:
            print(f"[Node 4] ERROR on attempt {attempt}: {e}")
            if attempt == max_retries:
                print("[Node 4] All retries exhausted.")


# ADK FunctionNode — instantiated once, reused across runs
insights_engine = FunctionNode(
    func=_insights_engine_fn,
    name="insights_engine",
)
