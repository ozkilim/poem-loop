#!/usr/bin/env python3
"""Dynamical-systems analysis of poem-loop experiments.

  python physics.py --ref runs/2026-11-07_210935 --runs runs/temp_sweep/<ts> runs/basin/<ts> [runs/t0_serial/<ts>] \
                    --json out.json

Per chain (text similarity = difflib ratio, 1 = identical):
  step      sim(x_t, x_t+1)                       how much each rewrite keeps
  frozen    share of late steps with step >= 0.95  "has it stopped moving?"
  repeats   exact repeats (any lag) and the first cycle found
  memory    C(lag) = mean sim(x_t, x_t+lag), late window  -> fading memory / aging
  origin    sim(x_0, x_t)
  style     rhyme share, people words, word count, and an attractor index:
            cos(BoW, dark centroid) - cos(BoW, start centroid), centroids from the reference run
            (its last 10 poems per chain vs its first 5).  > 0 = closer to where run 1 ended up.
Per twin pair (same label, different seed): sim(a_t, b_t) over t -> divergence of identical starts.
"""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import text_sim, rhyme_share, words, STOP  # noqa: E402

HUMAN = re.compile(r"\b(we|us|our|i|me|my|you|your|love|heart|soul|hand|hands)\b", re.I)
LATE = 0.5  # late window = second half of the chain


def load_chains(run):
    out = []
    for f in sorted(Path(run).glob("chain_*.jsonl"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1])):
        R = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        R = [r for r in R if r.get("poem")]
        if R:
            out.append({"id": int(re.findall(r"\d+", f.stem)[-1]), "label": R[0].get("label") or f.stem,
                        "temperature": R[0].get("temperature"), "seed": R[0].get("seed"),
                        "poems": [r["poem"] for r in R], "fb": [r.get("feedback") for r in R]})
    return out


def bow(t):
    return Counter(w for w in words(t) if w not in STOP and len(w) > 2)


def cosc(a, b):
    num = sum(a[k] * b.get(k, 0) for k in a)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def centroid(poems):
    c = Counter()
    for p in poems:
        b = bow(p)
        n = sum(b.values()) or 1
        for k, v in b.items():
            c[k] += v / n
    return c


def chain_metrics(ch, dark, light):
    P = ch["poems"]
    n = len(P)
    t0 = int((n - 1) * LATE)
    step = [text_sim(P[t], P[t + 1]) for t in range(n - 1)]
    late = step[t0:]
    seen, first_cycle, exact = {}, None, 0
    for t, p in enumerate(P):
        if p in seen:
            exact += 1
            if first_cycle is None:
                first_cycle = {"at": t, "lag": t - seen[p]}
        seen.setdefault(p, t)
    lags = [1, 2, 3, 5, 8, 12, 20]
    memory = {}
    for L in lags:
        xs = [text_sim(P[t], P[t + L]) for t in range(t0, n - L)]
        if len(xs) >= 3:
            memory[L] = round(sum(xs) / len(xs), 3)
    rows = []
    for t, p in enumerate(P):
        b = bow(p)
        rows.append({
            "step": round(step[t - 1], 3) if t else None,
            "origin": round(text_sim(P[0], p), 3),
            "words": len(words(p)),
            "rhyme": round(rhyme_share(p), 3),
            "human": len(HUMAN.findall(p)),
            "attr": round(cosc(b, dark) - cosc(b, light), 3),
        })
    tail = rows[max(0, n - 10):]
    return {
        "id": ch["id"], "label": ch["label"], "temperature": ch["temperature"], "seed": ch["seed"], "n": n,
        "late_step": round(sum(late) / len(late), 3) if late else None,
        "frozen": round(sum(s >= 0.95 for s in late) / len(late), 3) if late else None,
        "identical_steps": sum(s == 1.0 for s in step),
        "exact_repeats": exact, "first_cycle": first_cycle,
        "memory": memory,
        "end_attr": round(sum(r["attr"] for r in tail) / len(tail), 3),
        "end_rhyme": round(sum(r["rhyme"] for r in tail) / len(tail), 3),
        "end_human": round(sum(r["human"] for r in tail) / len(tail), 2),
        "rows": rows,
        "first": P[0], "last": P[-1], "last_title": P[-1].split("\n")[0].strip("*# "),
        "last_fb": ch["fb"][-2] if len(ch["fb"]) > 1 else None,
    }


def twins(chains):
    by = {}
    for c in chains:
        by.setdefault(c["label"], []).append(c)
    out = []
    for lab, cs in by.items():
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = cs[i]["poems"], cs[j]["poems"]
                m = min(len(a), len(b))
                out.append({"label": lab, "temperature": cs[i]["temperature"], "a": cs[i]["id"], "b": cs[j]["id"],
                            "sim": [round(text_sim(a[t], b[t]), 3) for t in range(m)],
                            "identical_until": next((t for t in range(m) if a[t] != b[t]), m)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--html", help="also render physics_template.html to this path")
    ap.add_argument("--findings", help="HTML snippet of finding cards to insert")
    a = ap.parse_args()

    ref = load_chains(a.ref)
    dark = centroid([p for c in ref for p in c["poems"][-10:]])
    light = centroid([p for c in ref for p in c["poems"][:5]])
    ref_m = [chain_metrics(c, dark, light) for c in ref]

    exps = {}
    for run in a.runs:
        run = Path(run)
        chains = load_chains(run)
        name = run.parent.name if run.parent.name != "runs" else run.name
        ms = [chain_metrics(c, dark, light) for c in chains]
        exps[name] = {"run": str(run), "chains": ms, "twins": twins(chains)}
        print(f"\n== {name} ({run.name}): {len(ms)} chains")
        print(f"{'label':14s} seed  n  late_step frozen ident exact cycle      mem@5  mem@12 end_attr rhyme human  last title")
        for m in ms:
            cyc = f"{m['first_cycle']['at']}/lag{m['first_cycle']['lag']}" if m["first_cycle"] else "-"
            print(f"{m['label']:14s} {m['seed']:4d} {m['n']:3d}  {m['late_step']:.3f}   {m['frozen']:.2f}  {m['identical_steps']:3d}  "
                  f"{m['exact_repeats']:3d}  {cyc:10s} {m['memory'].get(5, float('nan')):.2f}   {m['memory'].get(12, float('nan')):.2f}   "
                  f"{m['end_attr']:+.3f}  {m['end_rhyme']:.2f}  {m['end_human']:4.1f}  {m['last_title'][:30]}")
        for tw in exps[name]["twins"]:
            s = tw["sim"]
            print(f"  twins {tw['label']:14s} {tw['a']}-{tw['b']}: identical until {tw['identical_until']}, "
                  f"sim t=1 {s[1] if len(s) > 1 else '-'}  t=10 {s[10] if len(s) > 10 else '-'}  end {s[-1]}")
    ref_attr = [m["end_attr"] for m in ref_m]
    start_attr = [m["rows"][0]["attr"] for m in ref_m]
    print(f"\nreference run: attractor index start {sum(start_attr)/len(start_attr):+.3f} -> end {sum(ref_attr)/len(ref_attr):+.3f}")
    Path(a.json).write_text(json.dumps({"ref": {"run": a.ref, "chains": ref_m}, "exps": exps}, ensure_ascii=False))
    print("wrote", a.json)
    if a.html:
        render(exps, ref_m, a)


def t0_note(exp):
    if not exp:
        return None
    cs, tw = exp["chains"], (exp["twins"] or [None])[0]
    parts = []
    for c in cs:
        cyc = c["first_cycle"]
        parts.append(f"seed {c['seed']}: {c['n'] - 1} rounds, " +
                     (f"first exact repeat at round {cyc['at']} (cycle length {cyc['lag']}), " if cyc else "no exact repeats, ") +
                     f"{c['identical_steps']} steps that changed nothing, late step similarity {c['late_step']:.2f}")
    if tw:
        same = tw["identical_until"] >= len(tw["sim"])
        parts.append("the two chains are identical all the way through: the map is deterministic" if same else
                     f"the two chains are identical until round {tw['identical_until']}, then differ (end similarity {tw['sim'][-1]:.2f})")
    return "<p>" + "; ".join(parts) + ".</p>"


def render(exps, ref_m, a):
    import datetime as dt
    here = Path(__file__).resolve().parent
    tpl = (here / "physics_template.html").read_text()
    strip = lambda e: {"chains": [{k: v for k, v in c.items() if k != "last_fb"} for c in e["chains"]], "twins": e["twins"]} if e else None
    start = sum(m["rows"][0]["attr"] for m in ref_m) / len(ref_m)
    end = sum(m["end_attr"] for m in ref_m) / len(ref_m)
    runs = ", ".join(f"{k}/{Path(v['run']).name}" for k, v in exps.items())
    data = {
        "meta": {"line": f"Model Qwen3.6-35B-A3B (local) · runs {runs} · built {dt.datetime.now():%-d %b %Y, %H:%M}",
                 "foot": "Built by physics.py from the chain_*.jsonl logs. Reference run for the attractor index: " + Path(a.ref).name + ".",
                 "refBand": [round(start, 3), round(end, 3)]},
        "sweep": strip(exps.get("temp_sweep")), "basin": strip(exps.get("basin")),
        "t0note": t0_note(exps.get("t0_serial")),
    }
    findings = Path(a.findings).read_text() if a.findings and Path(a.findings).exists() else \
        '<div class="finding"><b>Still running</b><p>Findings are written once all chains finish.</p></div>'
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    Path(a.html).write_text(tpl.replace("__FINDINGS__", findings).replace("__DATA__", blob))
    print("wrote", a.html)


if __name__ == "__main__":
    main()
