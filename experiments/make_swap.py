#!/usr/bin/env python3
"""Critic/rewriter swap: whose taste sets the attractor? Run from ~/poem-loop.

Three arms x the same three starting poems (run 1's round-0 poems, chains 0-2), 40 rounds, T=0.8:
  G/G  Gemma critic + Gemma rewriter   (Gemma's own attractor)
  G/Q  Gemma critic + Qwen rewriter
  Q/G  Qwen critic  + Gemma rewriter
Q/Q is run 1 itself (same starts, same seeds 42-44).
"""
import json
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
base = yaml.safe_load((HERE.parent / "config.yaml").read_text())
R1 = HERE.parent / "runs/2026-11-07_210935"
starts = [json.loads((R1 / f"chain_{c}.jsonl").read_text().splitlines()[0])["poem"] for c in range(3)]
Q = {"model": base["model"]}
G = {"model": "gemma-3-12b-it", "base_url": "http://127.0.0.1:8081/v1"}
arms = {"G/G": {"judge": G, "rewriter": G}, "G/Q": {"judge": G, "rewriter": Q}, "Q/G": {"judge": Q, "rewriter": G}}
cfg = dict(base, iterations=40, workers=6, out_dir="runs/swap/")
cfg["chain_specs"] = [{"label": f"{a} start{i}", "arm": a, "seed": 42 + i, "temperature": 0.8, "start": starts[i], "role_models": r}
                      for a, r in arms.items() for i in range(3)]
(HERE / "swap.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
print(len(cfg["chain_specs"]), "chains")
