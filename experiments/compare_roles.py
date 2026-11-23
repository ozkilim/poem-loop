#!/usr/bin/env python3
"""Compare runs on the style measures at matched rounds. Run from ~/poem-loop.
  python experiments/compare_roles.py NAME=runs/x[:filter] ...   (filter = substring of the chain label)
"""
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from physics import load_chains, centroid, chain_metrics, bow  # noqa

REF = "runs/2026-11-07_210935"
ref = load_chains(REF)
dark = centroid([p for c in ref for p in c["poems"][-10:]])
light = centroid([p for c in ref for p in c["poems"][:5]])
ROUNDS = [0, 5, 10, 20, 40, 60]


def summarize(name, chains, maxn):
    ms = []
    for c in chains:
        c = dict(c, poems=c["poems"][:maxn + 1], fb=c["fb"][:maxn + 1])
        ms.append(chain_metrics(c, dark, light))
    print(f"\n== {name}: {len(ms)} chains")
    for key in ["words", "rhyme", "human", "attr", "step"]:
        cells = []
        for t in ROUNDS:
            xs = [m["rows"][t][key] for m in ms if t < len(m["rows"]) and m["rows"][t][key] is not None]
            cells.append(f"{t:>3}:{sum(xs)/len(xs):6.2f}" if xs else f"{t:>3}:   -  ")
        print(f"  {key:6s}", " ".join(cells))
    end = Counter()
    for m in ms:
        end.update(bow(m["last"]))
    print("  top end words:", ", ".join(w for w, _ in end.most_common(15)))
    print("  end titles:", " | ".join(m["last_title"][:28] for m in ms))
    return ms


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        name, spec = arg.split("=", 1)
        run, _, filt = spec.partition(":")
        maxn = 60
        if "@" in run:
            run, maxn = run.split("@"); maxn = int(maxn)
        ch = [c for c in load_chains(run) if not filt or filt in str(c["label"])]
        summarize(name, ch, maxn)
