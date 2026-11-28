"""Render the chat latency benchmark (scripts/bench_chat_latency.py output) as an SVG dot plot.

One row per conversation step, one lane per version. Every measured turn is a dot
(hollow = the turn did not do its job), the median is a vertical tick, and the
right-hand columns give both medians and the change. No third-party dependencies.

Usage:
  python scripts/plot_bench_latency.py docs/benchmarks/2026-11-15_chat_latency.csv \
      --out docs/benchmarks/chat_latency.svg
"""
from __future__ import annotations

import argparse
import csv
import html
import statistics

STEPS = [
    ("chat", "Ask for advice", "“What should I focus on today?”"),
    ("plan", "Plan the day", "“Plan my day”"),
    ("confirm_plan", "Confirm a plan", "“Let's go with the most relaxed plan”"),
    ("adjust", "Adjust the plan", "“Add a team meeting at 4pm today”"),
    ("confirm_adjust", "Confirm the change", "“Yes, apply that change”"),
]
VERSIONS = [("before", "Before refactor"), ("after", "After refactor")]

# Layout (px)
W = 980
LEFT = 270          # step labels
PLOT_W = 450
RIGHT_X = LEFT + PLOT_W + 36
TOP = 128
ROW_H = 64
LANE_OFF = 12       # lane centre offset from row centre


def load(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    data = {(v, s): [] for v, _ in VERSIONS for s, *_ in STEPS}
    for r in rows:
        key = (r["target"], r["step"])
        if key in data:
            data[key].append((int(r["ms"]) / 1000, r["ok"] == "1", int(r["round"])))
    return data


def fmt_s(x):
    return f"{x:.1f} s"


def pct(x):
    return f"{x:+.0f}%".replace("-", "\u2212")


def render(data, title_note, theme="auto"):
    xmax = max(t for pts in data.values() for t, _, _ in pts)
    xmax = (int(xmax // 2) + 1) * 2                      # round up to an even second
    sx = lambda t: LEFT + t / xmax * PLOT_W

    all_ms = {v: [t for (vv, _), pts in data.items() if vv == v for t, _, _ in pts] for v, _ in VERSIONS}
    ok = {v: sum(o for (vv, _), pts in data.items() if vv == v for _, o, _ in pts) for v, _ in VERSIONS}
    n = {v: len(all_ms[v]) for v, _ in VERSIONS}
    med = {v: statistics.median(all_ms[v]) for v, _ in VERSIONS}
    change_all = (med["after"] - med["before"]) / med["before"] * 100

    H = TOP + ROW_H * len(STEPS) + 108
    out = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
      f'role="img" aria-labelledby="t d" class="viz">')
    style = """<style>
  .viz { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#8a8984; --grid:#e8e7e3;
         --before:#eb6834; --after:#2a78d6; font-family:-apple-system,"Segoe UI","Helvetica Neue",Arial,sans-serif; }
  @media (prefers-color-scheme: dark) {
    .viz { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#8f8e86; --grid:#2e2e2c;
           --before:#d95926; --after:#3987e5; }
  }
  .bg { fill:var(--surface); }
  .title { font-size:20px; font-weight:650; fill:var(--ink); }
  .sub { font-size:13px; fill:var(--ink2); }
  .step { font-size:14px; font-weight:600; fill:var(--ink); }
  .quote { font-size:11.5px; fill:var(--muted); }
  .lane { font-size:11.5px; fill:var(--ink2); }
  .tick { font-size:11px; fill:var(--muted); }
  .colh { font-size:11px; fill:var(--muted); font-weight:600; letter-spacing:.04em; text-transform:uppercase; }
  .num { font-size:13px; fill:var(--ink); font-variant-numeric:tabular-nums; }
  .delta { font-size:13px; font-weight:650; fill:var(--ink); font-variant-numeric:tabular-nums; }
  .foot { font-size:11px; fill:var(--muted); }
  .grid { stroke:var(--grid); stroke-width:1; }
  .sep { stroke:var(--grid); stroke-width:1; }
  .med { stroke:var(--ink); stroke-width:2; stroke-linecap:round; }
  .dot-before { fill:var(--before); stroke:var(--surface); stroke-width:2; }
  .dot-after  { fill:var(--after);  stroke:var(--surface); stroke-width:2; }
  .miss-before { fill:var(--surface); stroke:var(--before); stroke-width:2; }
  .miss-after  { fill:var(--surface); stroke:var(--after);  stroke-width:2; }
  .dot-before:hover, .dot-after:hover, .miss-before:hover, .miss-after:hover { stroke:var(--ink); }
</style>"""
    if theme == "light":
        style = style[:style.index("  @media")] + style[style.index("  .bg {"):]
    elif theme == "dark":
        start = style.index("  @media (prefers-color-scheme: dark) {\n") + len("  @media (prefers-color-scheme: dark) {\n")
        dark = style[start:style.index("  }\n", start)]
        style = style.replace("  .bg {", dark + "  .bg {", 1)
    a(style)
    a(f'<rect class="bg" x="0" y="0" width="{W}" height="{H}"/>')
    title = (f"Median reply time {fmt_s(med['before'])} → {fmt_s(med['after'])} "
             f"({pct(change_all)}), and every turn completed")
    a(f'<text id="t" class="title" x="24" y="38">{html.escape(title)}</text>')
    desc = (f"Completed turns: {ok['before']}/{n['before']} before, {ok['after']}/{n['after']} after. "
            f"{title_note}")
    a(f'<text id="d" class="sub" x="24" y="62">{html.escape(desc)}</text>')

    # legend
    ly = 92
    lx = 24
    for v, label in VERSIONS:
        a(f'<circle class="dot-{v}" cx="{lx + 6}" cy="{ly - 4}" r="6"/>')
        a(f'<text class="lane" x="{lx + 18}" y="{ly}">{label}</text>')
        lx += 150
    a(f'<circle class="miss-before" cx="{lx + 6}" cy="{ly - 4}" r="5"/>')
    a(f'<text class="lane" x="{lx + 18}" y="{ly}">hollow = turn didn’t do its job (no reply / not saved)</text>')
    a(f'<line class="med" x1="{lx + 400}" y1="{ly - 11}" x2="{lx + 400}" y2="{ly + 3}"/>')
    a(f'<text class="lane" x="{lx + 410}" y="{ly}">median</text>')

    # grid + x ticks
    plot_top, plot_bot = TOP - 8, TOP + ROW_H * len(STEPS)
    for s in range(0, xmax + 1, 2):
        x = sx(s)
        a(f'<line class="grid" x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_bot}"/>')
        a(f'<text class="tick" x="{x:.1f}" y="{plot_bot + 18}" text-anchor="middle">{s}s</text>')
    a(f'<text class="tick" x="{LEFT + PLOT_W / 2}" y="{plot_bot + 36}" text-anchor="middle">'
      f'reply time per turn (seconds, client-measured)</text>')

    # right-hand columns
    cx_b, cx_a, cx_d = RIGHT_X + 50, RIGHT_X + 130, RIGHT_X + 205
    a(f'<text class="colh" x="{cx_b}" y="{TOP - 16}" text-anchor="end">Before</text>')
    a(f'<text class="colh" x="{cx_a}" y="{TOP - 16}" text-anchor="end">After</text>')
    a(f'<text class="colh" x="{cx_d}" y="{TOP - 16}" text-anchor="end">Change</text>')

    for i, (step, label, quote) in enumerate(STEPS):
        cy = TOP + ROW_H * i + ROW_H / 2
        if i:
            a(f'<line class="sep" x1="24" y1="{TOP + ROW_H * i}" x2="{W - 24}" y2="{TOP + ROW_H * i}"/>')
        a(f'<text class="step" x="24" y="{cy - 2}">{html.escape(label)}</text>')
        a(f'<text class="quote" x="24" y="{cy + 15}">{html.escape(quote)}</text>')
        meds = {}
        for j, (v, vlabel) in enumerate(VERSIONS):
            lane_y = cy - LANE_OFF if j == 0 else cy + LANE_OFF
            pts = data[(v, step)]
            ts = [t for t, _, _ in pts]
            meds[v] = statistics.median(ts)
            for t, ok_, rnd in sorted(pts, key=lambda p: -p[0]):
                cls = f"dot-{v}" if ok_ else f"miss-{v}"
                r = 6 if ok_ else 5
                tip = f"{vlabel} · {label} · round {rnd}: {t:.2f} s" + ("" if ok_ else " · did not complete")
                a(f'<circle class="{cls}" cx="{sx(t):.1f}" cy="{lane_y}" r="{r}">'
                  f'<title>{html.escape(tip)}</title></circle>')
            mx = sx(meds[v])
            a(f'<line class="med" x1="{mx:.1f}" y1="{lane_y - 9}" x2="{mx:.1f}" y2="{lane_y + 9}"/>')
            fails = sum(1 for _, o, _ in pts if not o)
            suffix = f"  {len(pts) - fails}/{len(pts)} ok" if fails else ""
            a(f'<text class="num" x="{cx_b if j == 0 else cx_a}" y="{cy + 5}" text-anchor="end">'
              f'{meds[v]:.1f} s</text>')
            if suffix:
                a(f'<text class="tick" x="{cx_b + 4 if j == 0 else cx_a + 4}" y="{cy + 5}">'
                  f'{html.escape(suffix.strip())}</text>')
        change = (meds["after"] - meds["before"]) / meds["before"] * 100
        a(f'<text class="delta" x="{cx_d}" y="{cy + 5}" text-anchor="end">{pct(change)}</text>')

    foot = ["Same scripted conversation, 5 interleaved rounds per version. Both backends ran on the same local MongoDB,",
            "seed data and .env (Gemini 2.5 Flash / Flash-Lite). Raw data: docs/benchmarks/2026-11-15_chat_latency.csv"]
    for k, line in enumerate(foot):
        a(f'<text class="foot" x="24" y="{H - 34 + k * 15}">{html.escape(line)}</text>')
    a("</svg>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out", default="chat_latency.svg")
    ap.add_argument("--note", default="Each dot is one measured turn.")
    ap.add_argument("--theme", choices=["auto", "light", "dark"], default="auto",
                    help="auto follows prefers-color-scheme (good for README); light/dark for slides")
    args = ap.parse_args()
    svg = render(load(args.csv), args.note, args.theme)
    with open(args.out, "w") as f:
        f.write(svg)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
