#!/usr/bin/env python3
"""Write experiment configs (base config.yaml + chain_specs). Run from ~/poem-loop."""
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
base = yaml.safe_load((HERE.parent / "config.yaml").read_text())
start = lambda n: (HERE / "starts" / f"{n}.txt").read_text()
ITERS, SEEDS = 60, [101, 202, 303]

# A. Temperature sweep: same start poem, temperature is the only knob (applies to judge and rewriter).
temp = dict(base, iterations=ITERS, workers=2, out_dir="runs/temp_sweep/")
temp["chain_specs"] = [{"label": f"T={t}", "temperature": t, "seed": s, "start": start("quiet_engine")}
                       for t in [0.0, 0.3, 0.6, 0.8, 1.0, 1.2] for s in SEEDS]

# B. Basin mapping: very different starts at the original T=0.8, two twin seeds each.
basin = dict(base, iterations=ITERS, workers=2, out_dir="runs/basin/")
basin["chain_specs"] = [{"label": n, "temperature": 0.8, "seed": s, "start": start(n)}
                        for n in ["limerick", "nursery", "prose", "random_words", "sonnet", "end_state"]
                        for s in SEEDS[:2]]

for name, cfg in [("temp_sweep", temp), ("basin", basin)]:
    (HERE / f"{name}.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print(name, len(cfg["chain_specs"]), "chains x", ITERS)
