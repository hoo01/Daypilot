"""Chat latency benchmark: legacy coordinator (before) vs code-owned orchestrator (after).

Plays the same scripted conversation against one or more running backends, interleaving
rounds between targets so Gemini's latency drift hits both equally. Measures client-side
wall time per turn (what the user feels) and whether each turn actually did its job.

Usage
-----
  # run (each target = label=url[,db=<mongo db name to reset between rounds>])
  python scripts/bench_chat_latency.py run \
      --target before=http://127.0.0.1:8001,db=daypilot_bench_before \
      --target after=http://127.0.0.1:8000,db=daypilot_bench_after \
      --mongo mongodb://localhost:27017 --rounds 5 --out bench.csv

  # summarise a CSV (per step, per target; deltas if exactly two targets)
  python scripts/bench_chat_latency.py report bench.csv
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
import uuid
from datetime import date

import httpx

USER = "demo_user"   # seeded by scripts/seed_demo.py

# (step id, message, what "success" means)
SCRIPT = [
    ("chat",           "What should I focus on today?",            "reply"),
    ("plan",           "Plan my day",                              "proposal"),
    ("confirm_plan",   "Let's go with the most relaxed plan",      "active"),
    ("adjust",         "Add a team meeting at 4pm today",          "proposal"),
    ("confirm_adjust", "Yes, apply that change",                   "active_changed"),
]


def _proposal_present(body: dict) -> bool:
    if body.get("day_plan") is not None:                       # after
        return bool((body.get("day_plan") or {}).get("proposal"))
    return bool(body.get("pending_proposal"))                  # before


def _active_signature(client: httpx.Client, base: str) -> str | None:
    """Confirmed schedule as stored, via the same endpoint the Today page uses."""
    r = client.get(f"{base}/schedule/today", params={"user_id": USER})
    if r.status_code != 200:
        return None
    return "|".join(f"{t.get('title')}@{t.get('start_time')}" for t in r.json().get("tasks", []))


def _reset(mongo_uri: str | None, db_name: str | None) -> None:
    if not (mongo_uri and db_name):
        return
    from pymongo import MongoClient
    with MongoClient(mongo_uri) as mc:
        mc[db_name]["daily_schedules"].delete_many({"user_id": USER, "date": date.today().isoformat()})


def run(args) -> None:
    targets = []
    for spec in args.target:
        label, rest = spec.split("=", 1)
        url, *opts = rest.split(",")
        kv = dict(o.split("=", 1) for o in opts)
        targets.append({"label": label, "url": url.rstrip("/"), "db": kv.get("db")})

    rows = []
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for t in targets:   # warm caches (health pipeline, relationship context) — not recorded
            _reset(args.mongo, t["db"])
            print(f"[warmup] {t['label']} …", flush=True)
            client.post(f"{t['url']}/chat/", json={"user_id": USER, "message": "hi", "session_id": str(uuid.uuid4())})

        for rnd in range(1, args.rounds + 1):
            order = targets if rnd % 2 else list(reversed(targets))   # alternate who goes first
            for t in order:
                _reset(args.mongo, t["db"])
                session = str(uuid.uuid4())
                active_before = _active_signature(client, t["url"])
                for step, message, expect in SCRIPT:
                    start = time.perf_counter()
                    try:
                        r = client.post(f"{t['url']}/chat/",
                                        json={"user_id": USER, "message": message, "session_id": session})
                        ms = (time.perf_counter() - start) * 1000
                        status, body = r.status_code, (r.json() if r.status_code == 200 else {})
                    except httpx.HTTPError as e:
                        ms, status, body = (time.perf_counter() - start) * 1000, -1, {"reply": repr(e)}
                    reply = body.get("reply", "") or ""
                    active_now = _active_signature(client, t["url"]) if expect.startswith("active") else None
                    err = (body.get("error") or {}).get("code", "") if isinstance(body.get("error"), dict) else ""
                    if expect == "reply":
                        # an open question must be answered, not turned into a schedule (old MODE A)
                        ok = (status == 200 and bool(reply) and "trouble connecting" not in reply
                              and not _proposal_present(body))
                    elif expect == "proposal":
                        ok = status == 200 and not err and _proposal_present(body)
                    elif expect == "active":
                        ok = active_now is not None
                    else:  # active_changed
                        ok = active_now is not None and active_now != active_before
                    if expect.startswith("active"):
                        active_before = active_now
                    rows.append({"target": t["label"], "round": rnd, "step": step, "ms": round(ms),
                                 "status": status, "ok": int(ok), "error": err, "reply_chars": len(reply),
                                 "reply": reply[:160].replace("\n", " ")})
                    print(f"r{rnd} {t['label']:>7} {step:<15} {ms:7.0f} ms  ok={int(ok)} {err}", flush=True)

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} rows → {args.out}\n")
    report(argparse.Namespace(csv=args.out))


def _pct(values: list[float], p: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def report(args) -> None:
    with open(args.csv) as f:
        rows = list(csv.DictReader(f))
    targets = list(dict.fromkeys(r["target"] for r in rows))
    steps = list(dict.fromkeys(r["step"] for r in rows)) + ["ALL"]
    stats: dict[tuple[str, str], dict] = {}
    for t in targets:
        for s in steps:
            sel = [r for r in rows if r["target"] == t and (s == "ALL" or r["step"] == s)]
            if not sel:
                continue
            ms = [float(r["ms"]) for r in sel]
            stats[(t, s)] = {"n": len(sel), "mean": statistics.mean(ms), "p50": _pct(ms, .5),
                             "p90": _pct(ms, .9), "ok": sum(int(r["ok"]) for r in sel) / len(sel)}
    hdr = f"{'step':<15}" + "".join(f"{t + ' p50':>13}{t + ' p90':>13}{t + ' ok':>10}" for t in targets)
    if len(targets) == 2:
        hdr += f"{'Δp50':>9}"
    print(hdr)
    for s in steps:
        line = f"{s:<15}"
        for t in targets:
            st = stats.get((t, s))
            line += (f"{st['p50']:>11.0f}ms{st['p90']:>11.0f}ms{st['ok'] * 100:>9.0f}%" if st else " " * 36)
        if len(targets) == 2 and (targets[0], s) in stats and (targets[1], s) in stats:
            a, b = stats[(targets[0], s)]["p50"], stats[(targets[1], s)]["p50"]
            line += f"{(b - a) / a * 100:>+8.0f}%"
        print(line)
    print("\nΔp50 = (second target − first target) / first target.  ok = turn did its job "
          "(reply / proposal shown / schedule actually confirmed / confirmed schedule changed).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--target", action="append", required=True, help="label=url[,db=name]")
    r.add_argument("--mongo", help="Mongo URI used to reset today's daily_schedules between rounds")
    r.add_argument("--rounds", type=int, default=5)
    r.add_argument("--timeout", type=float, default=180)
    r.add_argument("--out", default="bench.csv")
    r.set_defaults(func=run)
    p = sub.add_parser("report")
    p.add_argument("csv")
    p.set_defaults(func=report)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
