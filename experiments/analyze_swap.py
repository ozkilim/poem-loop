#!/usr/bin/env python3
"""Matched comparison of the partial swap run vs run 1 (same 3 starts). Run from ~/poem-loop."""
import sys, re
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from physics import load_chains, centroid, chain_metrics, bow
from analyze import text_sim, words

REF = "runs/2026-11-07_210935"; SW = "runs/swap/2026-11-09_205748"
ref = load_chains(REF)
dark = centroid([p for c in ref for p in c["poems"][-10:]])
light = centroid([p for c in ref for p in c["poems"][:5]])
sw = load_chains(SW)
N = min(len(c["poems"]) for c in sw) - 1
arms = {"Q/Q (run 1)": [c for c in ref if c["id"] in (0, 1, 2)],
        "G/G": [c for c in sw if "G/G" in c["label"]],
        "G/Q": [c for c in sw if "G/Q" in c["label"]]}
ROUNDS = [0, 5, 10, 15, N]
print(f"matched horizon: round {N}")
M = {}
for name, chs in arms.items():
    ms = [chain_metrics(dict(c, poems=c["poems"][:N+1], fb=c["fb"][:N+1]), dark, light) for c in chs]
    M[name] = ms
    print(f"\n== {name}  ({len(ms)} chains)")
    for k in ["words", "rhyme", "human", "attr", "step"]:
        cells = []
        for t in ROUNDS:
            xs = [m["rows"][t][k] for m in ms if m["rows"][t][k] is not None]
            cells.append(f"{t:>3}:{sum(xs)/len(xs):6.2f}" if xs else f"{t:>3}:   -  ")
        print(f"  {k:6s}", " ".join(cells))
    print("  per-chain end (words/rhyme/attr):", "  ".join(f"{m['rows'][-1]['words']}/{m['rows'][-1]['rhyme']:.2f}/{m['rows'][-1]['attr']:+.2f}" for m in ms))
    end = Counter()
    for m in ms: end.update(bow(m["last"]))
    print("  top end words:", ", ".join(w for w, _ in end.most_common(15)))
    print("  end titles:", " | ".join(m["last_title"][:32] for m in ms))
    fbs = [f for c in chs for f in c["fb"][:N] if f]
    print(f"  critique length: {sum(len(words(f)) for f in fbs)/len(fbs):.0f} words")
    ctr = Counter()
    for f in fbs: ctr.update(set(w for w in re.findall(r"[a-z]+", f.lower()) if w in
        {"rhyme","rhymes","rhyming","meter","cliche","cliché","abstract","concrete","image","imagery","specific","sentimental","predictable","forced","tell","show","subvert","ending","surprise","sensory","detail","darker","tension"}))
    print("  critique themes (% of critiques):", ", ".join(f"{w} {100*v/len(fbs):.0f}" for w, v in ctr.most_common(10)))
# cross-arm: do G/Q end poems resemble Q/Q ends or G/G ends from the same start?
print("\n== end-poem similarity, same start (text_sim)")
for i in range(3):
    q, g, gq = (M[a][i]["last"] for a in ["Q/Q (run 1)", "G/G", "G/Q"])
    print(f"  start{i}: GQ~QQ {text_sim(gq,q):.2f}  GQ~GG {text_sim(gq,g):.2f}  GG~QQ {text_sim(g,q):.2f}")
