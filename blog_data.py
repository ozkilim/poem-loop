#!/usr/bin/env python3
"""Collect every number, series and example the blog post needs into one JSON blob.

  python blog_data.py out.json
"""
import glob
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from physics import load_chains, chain_metrics, centroid, twins  # noqa: E402
from analyze import text_sim  # noqa: E402

REF = HERE / "runs/2026-11-07_210935"


def latest(pattern):
    d = sorted(glob.glob(str(HERE / pattern)))
    return Path(d[-1]) if d else None


def r3(v):
    return None if v is None else round(v, 3)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def series_mean(chains, key):
    n = max(len(c["rows"]) for c in chains)
    return [r3(mean([c["rows"][t][key] for c in chains if t < len(c["rows"])])) for t in range(n)]


def memory_curve(poems_list, t_from, t_to, lags):
    out = {}
    for L in lags:
        xs = [text_sim(P[t], P[t + L]) for P in poems_list for t in range(t_from, min(t_to, len(P) - L))]
        out[L] = r3(mean(xs)) if len(xs) >= 3 else None
    return out


def stop_stats(stop_dir):
    """Classify every critique that mentions FINISHED: sign-off at the end vs explicit refusal vs other."""
    sig = ref = oth = n = early = late = 0
    words, ex = [], {}
    for f in sorted(stop_dir.glob("chain_*.jsonl")):
        for i, r in enumerate(json.loads(l) for l in f.read_text().splitlines() if l.strip()):
            fb = r.get("feedback") or ""
            if not fb:
                continue
            n += 1
            words.append(len(fb.split()))
            if "FINISHED" not in fb.upper():
                continue
            t = re.sub(r"[\s*.\")]+$", "", fb)
            k = fb.upper().rfind("FINISHED")
            if t.upper().endswith("FINISHED") and not re.search(r"not\s+\S*\s*finished\W*$", t, re.I):
                sig += 1; early += i <= 30; late += i > 30
            elif re.search(r"not|isn.t", fb[max(0, k - 80):], re.I):
                ref += 1
            else:
                oth += 1
    words.sort()
    return {"n_crit": n, "signoff": sig, "refuse": ref, "other": oth, "sig_early": early, "sig_late": late,
            "min_words": words[0] if words else 0, "median_words": words[len(words) // 2] if words else 0,
            "bare": sum(1 for w in words if w <= 30)}


def stop_prose(S):
    c = S["chains"]
    ends = ", ".join(f"<i>{x['first_title']}</i> → <i>{x['last_title']}</i>" for x in c)
    return f"""<p>Every critique so far has suggested a change, so the loop has no fixed point to settle on. What if we offer one? In this experiment the critic’s prompt ended with one extra line: <i>If you would not change anything, reply with only the word FINISHED instead.</i> A reply of FINISHED alone ends the chain. We ran {len(c)} chains of 60 rounds, each starting from a fresh poem by the writer, as in run 1.</p>
<p>No chain stopped. Across {S['n_crit']} critiques the critic never once answered with the word alone. The shortest critique was {S['min_words']} words and the typical one {S['median_words']}. But it used the word {S['signoff'] + S['refuse'] + S['other']} times, in a way nobody asked for. {S['signoff']} times it wrote a full page of notes and then signed off with FINISHED at the bottom, as if the word were a closing salutation:</p>
<blockquote>The poem is already excellent, evocative, and emotionally resonant. It succeeds in its quiet power. If you are satisfied with the current version, it is ready.<br><br>FINISHED</blockquote>
<p>Another {S['refuse']} times it explained why it was <em>not</em> saying the word: “It’s not FINISHED yet, but it’s very close,” or, more candidly, “Note: since I suggested changes, I am not replying with FINISHED.” Once it simply repeated the instruction back, then obeyed it, underneath its own list of edits. Because none of these replies was the bare word, the rewriter took the notes and rewrote the poem every time.</p>
<p class="pull">Offered the exit, the critic walked up to it {S['signoff']} times, and each time it left a page of notes on the way out.</p>
<p>The timing fits experiment D. Only {S['sig_early']} of those sign-offs came in the first 30 rounds and {S['sig_late']} came in the last 30, after the poems had reached the plateau where the judge can no longer tell one rewrite from the next. The critic seems to sense when the poem is done. It just cannot stop critiquing. In physics terms, offering a stopping state is not enough to create a fixed point. The state has to be reachable, and the dynamics never land on it.</p>
<p>Meanwhile the chains drifted as before: {ends}. Three of the five poems lost about half their length (from 103–140 words to 53–64).</p>"""

def main():
    out_path = Path(sys.argv[1])
    ref = load_chains(REF)
    dark = centroid([p for c in ref for p in c["poems"][-10:]])
    light = centroid([p for c in ref for p in c["poems"][:5]])
    ref_m = [chain_metrics(c, dark, light) for c in ref]

    # ---- run 1 ----
    run1 = {"chains": [{"id": m["id"], **{k: [r[k] for r in m["rows"]] for k in ("step", "origin", "rhyme", "human", "words", "attr")},
                        "first_title": m["first"].split("\n")[0].strip("*# "), "last_title": m["last_title"]} for m in ref_m]}
    P = [c["poems"] for c in ref]
    lags = [1, 2, 3, 5, 8, 12, 20, 30, 40]
    run1["memory_early"] = memory_curve(P, 0, 50, lags)
    run1["memory_late"] = memory_curve(P, 50, 101, lags)
    run1["cross_late"] = r3(mean([text_sim(P[a][t], P[b][t]) for a in range(5) for b in range(a + 1, 5) for t in range(60, 101, 10)]))
    run1["poem0"], run1["poem20"], run1["poem100"] = P[0][0], P[0][20], P[0][100]
    run1["finals"] = [{"id": c["id"], "title": c["poems"][-1].split("\n")[0].strip("*# "), "poem": c["poems"][-1]} for c in ref]
    run1["first_lines"] = [[l for l in c["poems"][0].split("\n") if l.strip()][1] for c in ref]

    # ---- critic statistics over every critique ----
    fbs = []
    for f in glob.glob(str(HERE / "runs/2026-11-07_210935/chain_*.jsonl")) + glob.glob(str(HERE / "runs/temp_sweep/*/chain_*.jsonl")) + \
            glob.glob(str(HERE / "runs/basin/*/chain_*.jsonl")) + glob.glob(str(HERE / "runs/t0_serial/*/chain_*.jsonl")):
        for l in open(f):
            r = json.loads(l)
            if r.get("feedback"):
                fbs.append(r["feedback"])
    critic = {
        "n": len(fbs),
        "suggest": sum(bool(re.search(r"improv|suggest|consider|could be|tighten|cut", t, re.I)) for t in fbs),
        "cliche": sum(bool(re.search(r"clich", t, re.I)) for t in fbs),
        "abstract": sum(bool(re.search(r"abstract", t, re.I)) for t in fbs),
        "ask_rhyme": sum(bool(re.search(r"\b(add|introduce|restore|more|bring back) (a |some )?rhym", t, re.I)) for t in fbs),
        "loosen_rhyme": sum(bool(re.search(r"(loosen|drop|abandon|break|move away from|forced) (the |a )?rhym|rhyme[- ]forced|forced rhym", t, re.I)) for t in fbs),
    }

    # ---- experiment A: temperature sweep ----
    sweep_dir = latest("runs/temp_sweep/*")
    sweep = None
    if sweep_dir:
        ch = load_chains(sweep_dir)
        ms = [chain_metrics(c, dark, light) for c in ch]
        tw = twins(ch)
        temps = sorted({m["temperature"] for m in ms})
        sweep = {"temps": []}
        for T in temps:
            g = [m for m in ms if m["temperature"] == T and m["n"] >= 31]
            tws = [t for t in tw if t["temperature"] == T and len(t["sim"]) >= 31]
            if not g:
                continue
            n = min(len(t["sim"]) for t in tws) if tws else 0
            sweep["temps"].append({
                "T": T, "n_chains": len(g), "rounds": min(m["n"] for m in g) - 1,
                "late_step": [m["late_step"] for m in g], "frozen": [m["frozen"] for m in g],
                "mem12": [m["memory"].get(12) for m in g],
                "twin_end": [t["sim"][-1] for t in tws],
                "step_series": series_mean(g, "step"),
                "twin_series": [r3(mean([t["sim"][i] for t in tws])) for i in range(n)],
                "memory": {L: r3(mean([m["memory"].get(L) for m in g])) for L in [1, 2, 3, 5, 8, 12, 20]},
                "titles": [m["last_title"] for m in g],
                "exact_repeats": sum(m["exact_repeats"] for m in g),
            })
        # quiet spells: the chain with the largest frozen share
        q = max(ms, key=lambda m: (m["frozen"] or 0) if m["n"] >= 31 else -1)
        sweep["quiet"] = {"T": q["temperature"], "seed": q["seed"], "step": [r["step"] for r in q["rows"]], "frozen": q["frozen"]}
        # the butterfly: T=0 twins
        a, b = [c for c in ch if c["temperature"] == 0.0][:2]
        fa, fb = a["fb"][0], b["fb"][0]
        i = next(i for i in range(min(len(fa), len(fb))) if fa[i] != fb[i])
        j = next(j for j in range(min(len(a["poems"][1]), len(b["poems"][1]))) if a["poems"][1][j] != b["poems"][1][j])
        cut = fa.rfind(" ", 0, i)
        k0 = fa.find("rhyme-forced")
        ls = fa.rfind("\n", 0, k0) + 1
        le = fa.find("\n", fa.find("Suggestion", k0))
        sweep["first_crit"] = re.sub(r"\s+", " ", re.sub(r"[*]+", "", fa[ls:le])).strip(" -")
        sweep["butterfly"] = {
            "same_words": len(fa[:i].split()),
            "shared": fa[max(0, fa.rfind("\n", 0, i) + 1):cut].strip(),
            "a": fa[cut:fa.find("\n", i)].strip(), "b": fb[cut:fb.find("\n", i)].strip(),
            "poem_a": a["poems"][1], "poem_b": b["poems"][1], "poem_same_chars": j,
            "sims": [r3(text_sim(a["poems"][t], b["poems"][t])) for t in range(min(len(a["poems"]), len(b["poems"])))],
        }

    # ---- experiment B: basins ----
    basin_dir = latest("runs/basin/*")
    basin = None
    if basin_dir:
        ch = load_chains(basin_dir)
        ms = [chain_metrics(c, dark, light) for c in ch]
        tw = {t["label"]: t for t in twins(ch)}
        basin = {"starts": []}
        for lab in dict.fromkeys(m["label"] for m in ms):
            g = [m for m in ms if m["label"] == lab]
            basin["starts"].append({
                "label": lab,
                "rhyme": series_mean(g, "rhyme"), "human": series_mean(g, "human"),
                "words": series_mean(g, "words"), "attr": series_mean(g, "attr"),
                "first": g[0]["first"], "lasts": [{"seed": m["seed"], "title": m["last_title"], "poem": m["last"]} for m in g],
                "start_rhyme": g[0]["rows"][0]["rhyme"], "start_human": g[0]["rows"][0]["human"],
                "end_rhyme": r3(mean([m["end_rhyme"] for m in g])), "end_human": r3(mean([m["end_human"] for m in g])),
                "end_attr": r3(mean([m["end_attr"] for m in g])), "twin_end": tw[lab]["sim"][-1] if lab in tw else None,
            })

    # ---- experiment C: strict T=0 ----
    t0_dir = latest("runs/t0_serial/*")
    t0 = None
    if t0_dir:
        ch = load_chains(t0_dir)
        if ch:
            ms = [chain_metrics(c, dark, light) for c in ch]
            tw = twins(ch)
            t0 = {"chains": [{"seed": m["seed"], "rounds": m["n"] - 1, "late_step": m["late_step"], "frozen": m["frozen"],
                              "exact": m["exact_repeats"], "cycle": m["first_cycle"], "identical_steps": m["identical_steps"],
                              "step": [r["step"] for r in m["rows"]], "title": m["last_title"], "last": m["last"]} for m in ms],
                  "twin": ({"identical_until": tw[0]["identical_until"], "sim": tw[0]["sim"]} if tw else None),
                  "done": (t0_dir.parent.parent / "t0_serial.out").exists() and "ALL DONE" in (t0_dir.parent.parent / "t0_serial.out").read_text()}

    # ---- experiment D: the critic may say FINISHED ----
    stop_dir = latest("runs/stop_critic/*")
    stopx = None
    if stop_dir:
        cs = []
        for f in sorted(stop_dir.glob("chain_*.jsonl"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1])):
            R = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
            R = [r for r in R if r.get("poem")]
            if not R:
                continue
            fin = R[-1].get("stop_reason") == "critic_finished"
            Ps = [r["poem"] for r in R]
            cs.append({"chain": int(re.findall(r"\d+", f.stem)[-1]), "rounds": len(R) - 1, "finished": fin,
                       "stop_reason": R[-1].get("stop_reason"), "last": Ps[-1], "last_title": Ps[-1].split("\n")[0].strip("*# "),
                       "first_title": Ps[0].split("\n")[0].strip("*# "),
                       "mentions": sum("FINISHED" in (r.get("feedback") or "") for r in R),
                       "step": [None] + [r3(text_sim(Ps[t - 1], Ps[t])) for t in range(1, len(Ps))],
                       "origin_end": r3(text_sim(Ps[0], Ps[-1]))})
        out_d = HERE / "runs/stop_critic.out"
        stopx = {"chains": cs, "done": out_d.exists() and "ALL DONE" in out_d.read_text()}
        stopx.update(stop_stats(stop_dir))

    # ---- experiment E: does it get better? blind pairwise + ratings ----
    evx = None
    pf, rf = HERE / "runs/eval/pairs.jsonl", HERE / "runs/eval/ratings.jsonl"
    if pf.exists():
        P_ = [json.loads(l) for l in pf.read_text().splitlines() if l.strip()]
        by = {}
        for r in P_:
            by.setdefault((r["run"], r["chain"], r["i"], r["j"], r["kind"]), {})[r["order"]] = r["later_won"]
        verdict = []  # per pair: 1 later wins both orders, 0 earlier wins both, 0.5 split / unparsed
        for (run, ch, i, j, kind), o in by.items():
            if len(o) < 2:
                continue
            v = 1.0 if o["ij"] is True and o["ji"] is True else 0.0 if o["ij"] is False and o["ji"] is False else 0.5
            verdict.append({"run": run, "chain": ch, "i": i, "j": j, "kind": kind, "v": v})
        def summ(rows):
            return {"n": len(rows), "later": sum(r["v"] == 1 for r in rows), "earlier": sum(r["v"] == 0 for r in rows),
                    "split": sum(r["v"] == 0.5 for r in rows), "score": r3(mean([r["v"] for r in rows]))}
        groups = {}
        for r in verdict:
            groups.setdefault(f'{r["run"]}:{r["kind"]}', []).append(r)
        origin_by_j = {}
        for r in verdict:
            if r["run"] == "run1" and r["kind"] == "origin":
                origin_by_j.setdefault(r["j"], []).append(r["v"])
        blab = {}
        if basin_dir:
            for f in basin_dir.glob("chain_*.jsonl"):
                r0 = json.loads(f.read_text().splitlines()[0]); blab[r0["chain"]] = r0["label"]
        for r in verdict:
            r["label"] = blab.get(r["chain"]) if r["run"] == "basin" else None
        sel = lambda f: [r for r in verdict if f(r)]
        bars = [
            ("Round 0 vs rounds 10–100", "run 1", sel(lambda r: r["run"] == "run1" and r["kind"] == "origin")),
            ("Round 0 vs round 60", "temperature sweep", sel(lambda r: r["run"] == "sweep" and r["kind"] == "origin")),
            ("Start vs rounds 20 and 60", "five fresh starting poems", sel(lambda r: r["run"] == "basin" and r["kind"] == "origin" and r["label"] != "end_state")),
            ("Each rewrite vs the poem before it", "run 1, 50 single steps", sel(lambda r: r["run"] == "run1" and r["kind"] == "step")),
            ("Rounds 20, 50, 80 vs round 100", "run 1", sel(lambda r: r["run"] == "run1" and r["kind"] == "late")),
            ("Round 30 vs round 60", "temperature sweep", sel(lambda r: r["run"] == "sweep" and r["kind"] == "late")),
            ("Run 1’s final poem vs its own rewrites", "rounds 20 and 60", sel(lambda r: r["label"] == "end_state" and r["i"] == 0)),
        ]
        bars_out = [{"label": l, "sub": sub, **summ(rows)} for l, sub, rows in bars]
        first_pos = mean([1.0 if r["pick"] == "A" else 0.0 for r in P_ if r["pick"]])
        evx = {"groups": {k: summ(v) for k, v in groups.items()}, "all": summ(verdict),
               "origin_curve": {j: r3(mean(v)) for j, v in sorted(origin_by_j.items())},
               "pick_A_rate": r3(first_pos), "n_calls": len(P_), "bars": bars_out}
        if rf.exists():
            RT = [json.loads(l) for l in rf.read_text().splitlines() if l.strip()]
            curve = {}
            for r in RT:
                if r["run"] == "run1" and r["score"] is not None:
                    curve.setdefault(r["k"], []).append(r["score"])
            evx["rating_curve"] = {k: r3(mean(v)) for k, v in sorted(curve.items())}
            ends = {}
            for r in RT:
                if r["run"] in ("sweep", "basin") and r["score"] is not None:
                    ends.setdefault("start" if r["k"] == 0 else "end" if r["k"] >= 59 else "mid", []).append(r["score"])
            evx["rating_other"] = {k: r3(mean(v)) for k, v in ends.items()}
            starts = {}
            for r in RT:
                if r["run"] == "basin" and r["score"] is not None:
                    starts.setdefault(blab.get(r["chain"]), {}).setdefault(r["k"], []).append(r["score"])
            evx["rating_starts"] = {lab: {k: r3(mean(v)) for k, v in sorted(d.items())} for lab, d in starts.items()}
            evx["rating_counts"] = dict(__import__("collections").Counter(r["answer"] for r in RT).most_common(5))
            evx["n_ratings"] = len(RT)
        out_e = HERE / "runs/eval.out"
        evx["done"] = out_e.exists() and "ALL DONE" in out_e.read_text()

    data = {"stop_html": stop_prose(stopx) if stopx and stopx["done"] else None, "run1": run1, "critic": critic, "sweep": sweep, "basin": basin, "t0": t0, "stop": stopx, "eval": evx,
            "ref_band": [r3(mean([m["rows"][0]["attr"] for m in ref_m])), r3(mean([m["end_attr"] for m in ref_m]))]}
    import datetime as dt
    data["foot"] = (f"Built {dt.datetime.now():%-d %B %Y} from the chain logs of run 1 ({REF.name})"
                    + (f", experiment A ({sweep_dir.name})" if sweep_dir else "") + (f", experiment B ({basin_dir.name})" if basin_dir else "")
                    + (f" and experiment C ({t0_dir.name})" if t0_dir else "") + ". Code: ~/poem-loop.")
    out_path.write_text(json.dumps(data, ensure_ascii=False))
    if len(sys.argv) > 2:
        blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        Path(sys.argv[2]).write_text((HERE / "blog_template.html").read_text().replace("__DATA__", blob))
        print("wrote", sys.argv[2])
    print("wrote", out_path, f"{out_path.stat().st_size / 1e3:.0f} kB")
    print("critic", critic)
    if sweep:
        for t in sweep["temps"]:
            print("T", t["T"], "n", t["n_chains"], "late", [round(x, 2) for x in t["late_step"]], "twin_end", t["twin_end"], "repeats", t["exact_repeats"])
        print("butterfly", {k: v for k, v in sweep["butterfly"].items() if k in ("same_words", "a", "b", "poem_same_chars")})
    print("stop", None if not stopx else [(c["chain"], c["rounds"], c["stop_reason"]) for c in stopx["chains"]])
    print("eval", None if not evx else {k: evx[k] for k in ("all", "groups", "origin_curve", "pick_A_rate") if k in evx}, evx and evx.get("rating_curve"))
    print("t0", None if not t0 else [(c["rounds"], c["late_step"]) for c in t0["chains"]])


if __name__ == "__main__":
    main()
