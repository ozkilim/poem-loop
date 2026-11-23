#!/usr/bin/env python3
"""Post-hoc convergence analysis. Never calls the writer/judge/rewriter.

  python analyze.py runs/<timestamp>

Writes runs/<timestamp>/analysis/{summary.md, similarity.png, length.png, drift.png, viewer.html}.
"""
import argparse
import difflib
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import yaml

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

HERE = Path(__file__).resolve().parent
CONV_THRESH = 0.95
CONV_RUN = 10
NEAR_THRESH = 0.95

STOP = set("""a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her
here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of
off on once only or other our ours ourselves out over own same she should so some such than that the their theirs
them themselves then there these they this those through to too under until up very was we were what when where
which while who whom why will with would you your yours yourself yourselves upon yet till thee thy thou thine o oh
let like still each every one ever even may might must shall into onto within without us im ive dont cant""".split())


# ---------- metrics ----------

def text_sim(a, b):
    return difflib.SequenceMatcher(None, a or "", b or "", autojunk=False).ratio()


def cos(u, v):
    u, v = np.asarray(u, float), np.asarray(v, float)
    d = np.linalg.norm(u) * np.linalg.norm(v)
    return float(u @ v / d) if d else 0.0


def words(t):
    return re.findall(r"[a-z']+", (t or "").lower())


def body_lines(t):
    return [l for l in (t or "").split("\n") if l.strip()]


def rhyme_share(t):
    ends = []
    for l in body_lines(t):
        w = re.findall(r"[a-z]+", l.lower())
        if w:
            last = w[-1]
            ends.append(last[-3:] if len(last) > 4 else last[-2:])
    if len(ends) < 2:
        return 0.0
    c = Counter(ends)
    return sum(1 for e in ends if c[e] > 1) / len(ends)


def drift_row(t):
    w = words(t)
    return {
        "lines": len(body_lines(t)),
        "words": len(w),
        "ttr": len(set(w)) / len(w) if w else 0.0,
        "rhyme": rhyme_share(t),
    }


def top_content(poems, n=10):
    c = Counter(w.strip("'") for p in poems for w in words(p) if w.strip("'") not in STOP and len(w) > 2)
    return [w for w, _ in c.most_common(n)]


def convergence_point(sims):
    """sims[k] = sim(poem k, poem k-1), k>=1 (sims[0] is None). First k where CONV_RUN in a row >= thresh."""
    run = 0
    for k in range(1, len(sims)):
        if sims[k] is not None and sims[k] >= CONV_THRESH:
            run += 1
            if run >= CONV_RUN:
                return k - CONV_RUN + 1
        else:
            run = 0
    return None


def cycles(poems, hashes):
    first_seen, exact, near = {}, [], []
    for i, h in enumerate(hashes):
        if h in first_seen:
            exact.append((i, first_seen[h], i - first_seen[h]))
        else:
            first_seen[h] = i
    for i in range(len(poems)):
        for j in range(0, i - 1):  # 2+ steps back
            if hashes[i] == hashes[j]:
                continue
            sm = difflib.SequenceMatcher(None, poems[j], poems[i], autojunk=False)
            if sm.real_quick_ratio() < NEAR_THRESH or sm.quick_ratio() < NEAR_THRESH:
                continue
            r = sm.ratio()
            if r >= NEAR_THRESH:
                near.append((i, j, i - j, r))
    return exact, near


def word_diff(a, b):
    """Word-level diff of a -> b as list of [op, text], op in '=', '-', '+'. Newlines kept as tokens."""
    ta = re.findall(r"\n|[^\S\n]+|[^\s]+", a or "")
    tb = re.findall(r"\n|[^\S\n]+|[^\s]+", b or "")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(["=", "".join(ta[i1:i2])])
        else:
            if i2 > i1:
                out.append(["-", "".join(ta[i1:i2])])
            if j2 > j1:
                out.append(["+", "".join(tb[j1:j2])])
    return out


# ---------- io ----------

def load_chains(run_dir: Path):
    chains = {}
    for p in sorted(run_dir.glob("chain_*.jsonl"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1])):
        recs = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        n = int(re.findall(r"\d+", p.stem)[-1])
        chains[n] = {
            "all": recs,
            "poems": [r for r in recs if r.get("poem") is not None],
            "errors": [r for r in recs if r.get("error")],
        }
    return chains


def try_embed(texts, cfg):
    if not cfg.get("embedding_model"):
        return None, "embedding_model not set"
    try:
        sys.path.insert(0, str(HERE))
        import llm
        return llm.embed(texts, cfg), None
    except Exception as e:  # server down / model missing -> skip embedding metrics
        return None, f"embedding failed: {e}"


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--no-embed", action="store_true")
    a = ap.parse_args()
    run_dir = Path(a.run_dir)
    if not run_dir.exists() and (HERE / run_dir).exists():
        run_dir = HERE / run_dir
    cfg = yaml.safe_load((run_dir / "config.yaml").read_text())
    if a.no_embed:
        cfg["embedding_model"] = None
    out = run_dir / "analysis"
    out.mkdir(exist_ok=True)
    chains = load_chains(run_dir)
    if not chains:
        sys.exit(f"no chain_*.jsonl in {run_dir}")

    # embeddings for every poem at once
    flat = [(c, i) for c, ch in chains.items() for i in range(len(ch["poems"]))]
    vecs, emb_note = try_embed([chains[c]["poems"][i]["poem"] for c, i in flat], cfg)
    emb = {}
    if vecs:
        for (c, i), v in zip(flat, vecs):
            emb.setdefault(c, []).append(v)

    res = {}
    for c, ch in chains.items():
        P = [r["poem"] for r in ch["poems"]]
        H = [r.get("poem_sha1") for r in ch["poems"]]
        ts = [None] + [text_sim(P[k - 1], P[k]) for k in range(1, len(P))]
        es = [None] + [cos(emb[c][k - 1], emb[c][k]) for k in range(1, len(P))] if c in emb else None
        exact, near = cycles(P, H)
        res[c] = {
            "P": P, "ts": ts, "es": es, "conv": convergence_point(ts),
            "exact": exact, "near": near,
            "drift": [drift_row(p) for p in P],
            "top_first": top_content(P[:10]), "top_last": top_content(P[-10:]),
        }

    # ---- cross-chain table (last poems) ----
    keys = list(res)
    last = [res[c]["P"][-1] if res[c]["P"] else "" for c in keys]
    T = np.array([[(text_sim(x, y) + text_sim(y, x)) / 2 for y in last] for x in last])  # difflib is asymmetric
    E = np.array([[cos(emb[x][-1], emb[y][-1]) for y in keys] for x in keys]) if len(emb) == len(keys) and emb else None

    # ---- charts ----
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for c in keys:
        ts = res[c]["ts"]
        line, = ax.plot(range(1, len(ts)), ts[1:], label=f"chain {c} text", lw=1.4)
        if res[c]["es"]:
            ax.plot(range(1, len(ts)), res[c]["es"][1:], ls="--", lw=1, color=line.get_color(), alpha=.7,
                    label=f"chain {c} embed")
    ax.axhline(CONV_THRESH, color="grey", lw=.8, ls=":")
    ax.set(xlabel="iteration", ylabel="similarity to previous poem", ylim=(0, 1.02),
           title="Consecutive similarity (text = difflib ratio" + (", dashed = embedding cosine)" if emb else ")"))
    ax.legend(fontsize=8, ncol=2, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    fig.tight_layout(); fig.savefig(out / "similarity.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    for c in keys:
        ax.plot([d["words"] for d in res[c]["drift"]], label=f"chain {c}", lw=1.4)
    ax.set(xlabel="iteration", ylabel="word count", title="Poem length over iterations")
    ax.legend(fontsize=8, frameon=False); ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    fig.tight_layout(); fig.savefig(out / "length.png", dpi=150); plt.close(fig)

    fig, axs = plt.subplots(1, 3, figsize=(14, 4))
    for c in keys:
        d = res[c]["drift"]
        axs[0].plot([x["lines"] for x in d], label=f"chain {c}")
        axs[1].plot([x["ttr"] for x in d])
        axs[2].plot([x["rhyme"] for x in d])
    for ax, t in zip(axs, ["line count", "unique / total words", "share of lines that rhyme"]):
        ax.set(xlabel="iteration", title=t); ax.xaxis.set_major_locator(MaxNLocator(integer=True)); ax.spines[["top", "right"]].set_visible(False)
    axs[0].legend(fontsize=8, frameon=False)
    fig.tight_layout(); fig.savefig(out / "drift.png", dpi=150); plt.close(fig)

    # ---- summary.md ----
    L = [f"# Poem loop analysis: `{run_dir.name}`", "",
         f"Model `{cfg.get('model')}` · {len(keys)} chains · temperature {cfg.get('temperature')} · "
         f"judge_knows_goal={cfg.get('judge_knows_goal')}", "",
         f"Embeddings: {'`' + cfg['embedding_model'] + '`' if emb else 'skipped (' + (emb_note or '') + ')'}", "",
         f"Converged = first iteration where text similarity to the previous poem stays >= {CONV_THRESH} "
         f"for {CONV_RUN} iterations in a row.", "",
         "![similarity](similarity.png)", "", "![length](length.png)", "", "![drift](drift.png)", "",
         "## Overview", "",
         "| chain | poems | converged | exact repeats | near-cycles (>=0.95, 2+ back) | mean text sim (last 10) | errors |",
         "|---|---|---|---|---|---|---|"]
    for c in keys:
        r = res[c]
        tail = [x for x in r["ts"][-10:] if x is not None]
        conv = f"yes, at {r['conv']}" if r["conv"] is not None else "did not converge"
        ex = f"{len(r['exact'])} (first at {r['exact'][0][0]}, cycle {r['exact'][0][2]})" if r["exact"] else "none"
        nr = f"{len(r['near'])} (first at {r['near'][0][0]}, lag {r['near'][0][2]})" if r["near"] else "none"
        L.append(f"| {c} | {len(r['P'])} | {conv} | {ex} | {nr} | "
                 f"{np.mean(tail):.3f} | {len(chains[c]['errors'])} |" if tail else
                 f"| {c} | {len(r['P'])} | {conv} | {ex} | {nr} | – | {len(chains[c]['errors'])} |")

    L += ["", "## Do chains end up in the same place?", "",
          "Text similarity (difflib) between the **last** poem of each chain:", "",
          "| | " + " | ".join(f"c{c}" for c in keys) + " |", "|---" * (len(keys) + 1) + "|"]
    L += [f"| c{c} | " + " | ".join(f"{T[i, j]:.2f}" for j in range(len(keys))) + " |" for i, c in enumerate(keys)]
    off = T[~np.eye(len(keys), dtype=bool)] if len(keys) > 1 else np.array([])
    if off.size:
        L += ["", f"Mean off-diagonal text similarity: **{off.mean():.3f}**"]
    if E is not None:
        L += ["", "Embedding cosine between last poems:", "",
              "| | " + " | ".join(f"c{c}" for c in keys) + " |", "|---" * (len(keys) + 1) + "|"]
        L += [f"| c{c} | " + " | ".join(f"{E[i, j]:.2f}" for j in range(len(keys))) + " |" for i, c in enumerate(keys)]
        if len(keys) > 1:
            L += ["", f"Mean off-diagonal embedding cosine: **{E[~np.eye(len(keys), dtype=bool)].mean():.3f}**"]

    for c in keys:
        r = res[c]
        d0, d1 = (r["drift"][0], r["drift"][-1]) if r["drift"] else ({}, {})
        L += ["", f"## Chain {c}", ""]
        if r["conv"] is not None:
            L.append(f"- **Converged** at iteration {r['conv']}.")
        else:
            L.append("- **Did not converge.**")
        if r["exact"]:
            L.append(f"- Exact repeats: {len(r['exact'])}; first: poem {r['exact'][0][0]} == poem {r['exact'][0][1]} "
                     f"(cycle length {r['exact'][0][2]}). Lags seen: {sorted({e[2] for e in r['exact']})}")
        else:
            L.append("- No exact repeats.")
        if r["near"]:
            lags = Counter(n[2] for n in r["near"])
            L.append(f"- Near-cycles: {len(r['near'])}; first: poem {r['near'][0][0]} ~ poem {r['near'][0][1]} "
                     f"(lag {r['near'][0][2]}, sim {r['near'][0][3]:.3f}). Most common lags: {lags.most_common(5)}")
        else:
            L.append("- No near-cycles.")
        if d0:
            L.append(f"- Drift, first -> last: lines {d0['lines']} -> {d1['lines']}, words {d0['words']} -> {d1['words']}, "
                     f"unique/total {d0['ttr']:.2f} -> {d1['ttr']:.2f}, rhyme share {d0['rhyme']:.2f} -> {d1['rhyme']:.2f}")
        L.append(f"- Top content words, first 10 poems: {', '.join(r['top_first'])}")
        L.append(f"- Top content words, last 10 poems: {', '.join(r['top_last'])}")
        for e in chains[c]["errors"]:
            L.append(f"- Error at iteration {e.get('iteration')}: `{(e.get('error') or '')[:200]}`")
        L += ["", f"**Final poem (iteration {len(r['P']) - 1}):**", "", "```", r["P"][-1] if r["P"] else "", "```"]
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---- viewer.html ----
    data = {}
    for c in keys:
        rows = []
        for k, rec in enumerate(chains[c]["poems"]):
            rows.append({
                "it": rec["iteration"], "poem": rec["poem"], "fb": rec.get("feedback"),
                "diff": word_diff(chains[c]["poems"][k - 1]["poem"], rec["poem"]) if k else None,
                "ts": res[c]["ts"][k], "es": res[c]["es"][k] if res[c]["es"] else None,
                "words": res[c]["drift"][k]["words"], "sha": (rec.get("poem_sha1") or "")[:10],
                "err": rec.get("error"),
            })
        data[str(c)] = {"rows": rows, "conv": res[c]["conv"]}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (out / "viewer.html").write_text(VIEWER.replace("__DATA__", blob).replace("__TITLE__", html.escape(run_dir.name)),
                                     encoding="utf-8")

    print(f"wrote {out}/summary.md, similarity.png, length.png, drift.png, viewer.html")
    for c in keys:
        r = res[c]
        print(f"  chain {c}: {len(r['P'])} poems, " +
              (f"converged at {r['conv']}" if r["conv"] is not None else "did not converge") +
              f", exact repeats {len(r['exact'])}, near-cycles {len(r['near'])}")
    if emb_note and not emb:
        print(f"  (embeddings skipped: {emb_note})")


VIEWER = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Poem Loop Viewer</title>
<style>
:root{--bg:#faf8f4;--fg:#1d1b18;--mute:#6f6a62;--line:#e4dfd6;--card:#fff;--add:#d9f2dc;--addfg:#145a20;--del:#f7dcdc;--delfg:#8a1c1c;--acc:#7a4fd1}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161513;--fg:#ece8e1;--mute:#9a948a;--line:#2d2a26;--card:#1e1c19;--add:#173a1d;--addfg:#9be3a6;--del:#3e1b1b;--delfg:#f3a5a5;--acc:#b496ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;z-index:2}
h1{font-size:16px;margin:0 12px 0 0;font-weight:600}
select,button,input[type=range]{font:inherit;color:inherit}
select,button{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:5px 10px;cursor:pointer}
input[type=range]{flex:1;min-width:140px;accent-color:var(--acc)}
.meta{color:var(--mute);font-size:13px;font-variant-numeric:tabular-nums}
main{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px;max-width:1300px;margin:0 auto}
@media (max-width:800px){main{grid-template-columns:1fr}}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0}
section h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:0 0 10px;font-weight:600}
.poem{font-family:"Iowan Old Style",Georgia,serif;font-size:16.5px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
.fb{white-space:pre-wrap;font-size:14px;overflow-wrap:anywhere}
ins{background:var(--add);color:var(--addfg);text-decoration:none;border-radius:3px}
del{background:var(--del);color:var(--delfg);border-radius:3px}
.wide{grid-column:1/-1}.err{color:var(--delfg)}
kbd{border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:12px}
svg{width:100%;height:60px;display:block}
</style></head><body>
<header>
<h1>__TITLE__</h1>
<label>Chain <select id="chain"></select></label>
<button id="prev">&larr;</button><input id="slider" type="range" min="0" value="0"><button id="next">&rarr;</button>
<span class="meta" id="meta"></span>
<span class="meta"><kbd>&larr;</kbd><kbd>&rarr;</kbd> step · <kbd>Home</kbd><kbd>End</kbd></span>
</header>
<main>
<section class="wide"><h2>Similarity to previous poem</h2><svg id="spark" viewBox="0 0 1000 60" preserveAspectRatio="none"></svg></section>
<section><h2 id="ptitle">Poem</h2><div class="poem" id="poem"></div></section>
<section><h2>Changes from previous poem</h2><div class="poem" id="diff"></div></section>
<section class="wide"><h2>Judge feedback on this poem</h2><div class="fb" id="fb"></div></section>
</main>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const esc = s => (s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let chain = Object.keys(D)[0], i = 0;
for (const c of Object.keys(D)) { const o = document.createElement("option"); o.value = c; o.textContent = c + (D[c].conv != null ? " (conv @" + D[c].conv + ")" : ""); $("chain").appendChild(o); }
function spark() {
  const rows = D[chain].rows, n = Math.max(rows.length - 1, 1);
  const pts = rows.map((r, k) => r.ts == null ? null : [k / n * 1000, 58 - r.ts * 56]).filter(Boolean);
  const cur = i / n * 1000;
  $("spark").innerHTML = `<line x1="0" x2="1000" y1="${58 - .95 * 56}" y2="${58 - .95 * 56}" stroke="currentColor" stroke-opacity=".25" stroke-dasharray="4 4"/>` +
    `<polyline fill="none" stroke="var(--acc)" stroke-width="2" vector-effect="non-scaling-stroke" points="${pts.map(p => p.join(",")).join(" ")}"/>` +
    `<line x1="${cur}" x2="${cur}" y1="0" y2="60" stroke="currentColor" stroke-opacity=".5" vector-effect="non-scaling-stroke"/>`;
}
function render() {
  const rows = D[chain].rows; i = Math.max(0, Math.min(i, rows.length - 1));
  const r = rows[i];
  $("slider").max = rows.length - 1; $("slider").value = i;
  $("ptitle").textContent = "Poem " + r.it;
  $("poem").textContent = r.poem;
  $("diff").innerHTML = r.diff ? r.diff.map(([op, t]) => op === "=" ? esc(t) : op === "+" ? "<ins>" + esc(t) + "</ins>" : "<del>" + esc(t) + "</del>").join("") : "<span class=meta>(first poem)</span>";
  $("fb").innerHTML = r.err ? "<span class=err>" + esc(r.err) + "</span>" : r.fb ? esc(r.fb) : "<span class=meta>(no feedback: chain ended here)</span>";
  $("meta").textContent = `iteration ${r.it} / ${rows[rows.length - 1].it} · ${r.words} words` +
    (r.ts != null ? ` · text sim ${r.ts.toFixed(3)}` : "") + (r.es != null ? ` · embed ${r.es.toFixed(3)}` : "") + ` · ${r.sha}`;
  spark();
}
$("chain").onchange = e => { chain = e.target.value; render(); };
$("slider").oninput = e => { i = +e.target.value; render(); };
$("prev").onclick = () => { i--; render(); }; $("next").onclick = () => { i++; render(); };
document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT") return;
  if (e.key === "ArrowLeft") { i--; render(); e.preventDefault(); }
  else if (e.key === "ArrowRight") { i++; render(); e.preventDefault(); }
  else if (e.key === "Home") { i = 0; render(); } else if (e.key === "End") { i = 1e9; render(); }
});
render();
</script></body></html>
"""

if __name__ == "__main__":
    main()
