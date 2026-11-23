#!/usr/bin/env python3
"""Does the loop make poems better? Blind evaluation by the same model, every call fresh.

  python judge_pairs.py            # runs everything not yet in runs/eval/, resumable

Pairwise: two poems from the same chain, labelled A and B, both orders (position bias cancels; if the
verdict flips with the order it counts as a tie). Rating: one poem, score 1-10. Temperature 0, thinking off.
Writes runs/eval/pairs.jsonl and runs/eval/ratings.jsonl.
"""
import glob
import json
import re
import sys
from pathlib import Path

import yaml

import llm

HERE = Path(__file__).resolve().parent
OUT = HERE / "runs/eval"

PAIR = """Here are two poems.

<poem_A>
{a}
</poem_A>

<poem_B>
{b}
</poem_B>

Which is the better poem? Answer with a single letter: A or B."""

RATE = """Here is a poem.

<poem>
{p}
</poem>

Rate this poem from 1 to 10, where 10 is a perfect poem. Reply with the number only."""


def latest(pattern):
    d = sorted(glob.glob(str(HERE / pattern)))
    return Path(d[-1]) if d else None


def poems(run):
    out = {}
    for f in sorted(Path(run).glob("chain_*.jsonl")):
        c = int(re.findall(r"\d+", f.stem)[-1])
        P = [json.loads(l)["poem"] for l in f.read_text().splitlines() if l.strip()]
        out[c] = [p for p in P if p]
    return out


def jobs():
    runs = {"run1": HERE / "runs/2026-11-07_210935", "sweep": latest("runs/temp_sweep/*"), "basin": latest("runs/basin/*")}
    pairs, rates = [], []
    for name, run in runs.items():
        if not run:
            continue
        for c, P in poems(run).items():
            n = len(P) - 1
            if name == "run1":
                cmp = [(0, k, "origin") for k in (10, 20, 40, 60, 80, 100)] + \
                      [(20, 100, "late"), (50, 100, "late"), (80, 100, "late")] + \
                      [(k, k + 1, "step") for k in range(5, 100, 10)]
                rk = list(range(0, 101, 10))
            else:
                cmp = [(0, n, "origin"), (n // 2, n, "late")] + ([(0, n // 3, "origin")] if name == "basin" else [])
                rk = [0, n // 2, n]
            for i, j, kind in cmp:
                if j <= n:
                    pairs.append({"run": name, "chain": c, "i": i, "j": j, "kind": kind, "pi": P[i], "pj": P[j]})
            for k in rk:
                if k <= n:
                    rates.append({"run": name, "chain": c, "k": k, "p": P[k]})
    return pairs, rates


def ask(prompt, max_tokens=4):
    _, raw, _ = llm.call(prompt, max_tokens, seed=0, kind="feedback", temperature=0.0)
    return raw.strip()


def main():
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    llm.health_check(cfg)
    llm.setup(cfg, system_prompt=None)
    OUT.mkdir(parents=True, exist_ok=True)
    pf, rf = OUT / "pairs.jsonl", OUT / "ratings.jsonl"
    done_p = {(r["run"], r["chain"], r["i"], r["j"], r["order"]) for r in map(json.loads, pf.read_text().splitlines())} if pf.exists() else set()
    done_r = {(r["run"], r["chain"], r["k"]) for r in map(json.loads, rf.read_text().splitlines())} if rf.exists() else set()
    pairs, rates = jobs()
    print(f"{len(pairs)} pairs x 2 orders, {len(rates)} ratings; already done {len(done_p)} / {len(done_r)}", flush=True)
    for n, p in enumerate(pairs):
        for order in ("ij", "ji"):
            key = (p["run"], p["chain"], p["i"], p["j"], order)
            if key in done_p:
                continue
            a, b = (p["pi"], p["pj"]) if order == "ij" else (p["pj"], p["pi"])
            ans = ask(PAIR.format(a=a, b=b))
            m = re.search(r"\b([AB])\b", ans.replace("*", ""))
            pick = m.group(1) if m else None
            later = None if pick is None else ((pick == "B") == (order == "ij"))  # True if the later poem (j) won
            with open(pf, "a") as f:
                f.write(json.dumps({"run": p["run"], "chain": p["chain"], "i": p["i"], "j": p["j"], "kind": p["kind"],
                                    "order": order, "answer": ans, "pick": pick, "later_won": later}) + "\n")
        if n % 10 == 0:
            print(f"pairs {n + 1}/{len(pairs)}", flush=True)
    for n, r in enumerate(rates):
        key = (r["run"], r["chain"], r["k"])
        if key in done_r:
            continue
        ans = ask(RATE.format(p=r["p"]), max_tokens=6)
        m = re.search(r"\d+(\.\d+)?", ans)
        with open(rf, "a") as f:
            f.write(json.dumps({"run": r["run"], "chain": r["chain"], "k": r["k"], "answer": ans,
                                "score": float(m.group(0)) if m else None}) + "\n")
        if n % 20 == 0:
            print(f"ratings {n + 1}/{len(rates)}", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
