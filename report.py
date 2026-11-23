#!/usr/bin/env python3
"""Build a shareable visual report (single HTML) from a run.  python report.py runs/<ts> out.html"""
import difflib
import json
import re
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import drift_row, word_diff, text_sim  # noqa: E402

HUMAN = re.compile(r"\b(we|us|our|i|me|my|you|your|love|heart|soul|hand|hands)\b", re.I)


def main():
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    cfg_iters = 100
    for line in (run / "config.yaml").read_text().splitlines():
        if line.startswith("iterations:"):
            cfg_iters = int(line.split(":")[1].split("#")[0])
    n_chains = 5
    for line in (run / "config.yaml").read_text().splitlines():
        if line.startswith("chains:"):
            n_chains = int(line.split(":")[1].split("#")[0])
    chains = []
    for f in sorted(run.glob("chain_*.jsonl"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1])):
        R = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        R = [r for r in R if r.get("poem")]
        P = [r["poem"] for r in R]
        rows = []
        for k, r in enumerate(R):
            d = drift_row(P[k])
            rows.append({
                "it": r["iteration"],
                "poem": P[k],
                "title": P[k].split("\n")[0].strip("*# "),
                "words": d["words"],
                "lines": d["lines"],
                "human": len(HUMAN.findall(P[k])),
                "prev": round(text_sim(P[k - 1], P[k]), 3) if k else None,
                "orig": round(text_sim(P[0], P[k]), 3),
                "fb": r.get("feedback"),
                "diff": word_diff(P[k - 1], P[k]) if k else None,
            })
        chains.append({"id": int(re.findall(r"\d+", f.stem)[-1]), "rows": rows})
    # cross-chain similarity of latest poems
    lasts = [c["rows"][-1]["poem"] for c in chains]
    cross = [[round((text_sim(a, b) + text_sim(b, a)) / 2, 2) for b in lasts] for a in lasts]
    meta = {
        "run": run.name,
        "model": next((l.split(":", 1)[1].split("#")[0].strip() for l in (run / "config.yaml").read_text().splitlines()
                       if l.startswith("model:")), "?"),
        "iters": cfg_iters, "nChains": n_chains,
        "updated": dt.datetime.now().strftime("%-d %b %Y, %H:%M"),
        "cross": cross,
    }
    blob = json.dumps({"meta": meta, "chains": chains}, ensure_ascii=False).replace("</", "<\\/")
    tpl = (Path(__file__).resolve().parent / "report_template.html").read_text()
    out.write_text(tpl.replace("__DATA__", blob))
    print("wrote", out, "chains:", [(c["id"], len(c["rows"])) for c in chains])


if __name__ == "__main__":
    main()
