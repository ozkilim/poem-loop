#!/usr/bin/env python3
"""Recursive poem loop: write -> (judge -> rewrite) x N, one model, every call fresh.

  python loop.py                              # run with config.yaml
  python loop.py --chains 1 --iterations 5    # quick smoke test
  python loop.py --resume runs/<timestamp>    # continue a killed run (add --iterations N to extend)

Nothing here checks for convergence (except the opt-in early_stop_on_exact_repeat).
"""
import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

import llm

HERE = Path(__file__).resolve().parent
log = logging.getLogger("poemloop")


def sha1(s):
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------- persistence ----------

def append_jsonl(path: Path, rec: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_atomic(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_jsonl(path: Path):
    """Read records; a torn last line (crash mid-write) is dropped and the file repaired."""
    if not path.exists():
        return []
    recs, good_lines, torn = [], [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            recs.append(json.loads(line))
            good_lines.append(line)
        except json.JSONDecodeError:
            torn = True
    if torn:
        log.warning("%s: dropped a torn line", path.name)
        write_atomic(path, "".join(l + "\n" for l in good_lines))
    return recs


# ---------- one chain ----------

class ChainStop(Exception):
    pass


def generate(prompt, max_tokens, seed, kind, retries, temperature=None, model=None):
    """Model call that retries when the cleaned output is empty (different seed per retry)."""
    base_url = None
    if isinstance(model, dict):  # role served by another endpoint: {model, base_url}
        model, base_url = model.get("model"), model.get("base_url")
    last = None
    for attempt in range(retries + 1):
        s = seed + 1000 * attempt
        clean, raw, stats = llm.call(prompt, max_tokens, s, kind=kind, temperature=temperature, model=model, base_url=base_url)
        stats["empty_retries"] = attempt
        if clean.strip():
            return clean, raw, stats
        last = raw
        log.warning("  empty %s after cleaning (attempt %d/%d, seed %s, finish=%s)",
                    kind, attempt + 1, retries + 1, s, stats.get("finish_reason"))
    raise ChainStop(f"empty {kind} after {retries + 1} attempts; last raw output: {last!r:.300}")


def new_poem_record(chain, iteration, seed, clean, raw, stats, role, extra=None):
    return {**(extra or {}),
        "chain": chain, "iteration": iteration, "role": role,
        "poem": clean, "poem_raw": raw, "poem_sha1": sha1(clean),
        "feedback": None, "feedback_raw": None,
        "seed": seed,
        "tokens_in": {"judge": None, "rewrite": stats.get("tokens_in")},
        "tokens_out": {"judge": None, "rewrite": stats.get("tokens_out")},
        "seconds_judge": None, "seconds_rewrite": stats.get("seconds"),
        "finish_reason": {"judge": None, "rewrite": stats.get("finish_reason")},
        "seed_used": {"judge": None, "rewrite": stats.get("seed")},
        "seed_sent": stats.get("seed_sent"),
        "error": None, "stop_reason": None,
        "time": now(),
    }


def run_chain(c, cfg, prompts, run_dir: Path, spec=None):
    spec = spec or {}
    path = run_dir / f"chain_{c}.jsonl"
    pending_path = run_dir / f"chain_{c}.pending.json"
    seed = spec.get("seed", cfg["base_seed"] + c)
    temp = spec.get("temperature", cfg["temperature"])
    label = spec.get("label")
    extra = {"label": label, "temperature": temp}
    N = cfg["iterations"]
    retries = cfg.get("max_retries", 3)
    judge_tpl = prompts["judge_knows_goal"] if cfg.get("judge_knows_goal") else prompts["judge"]
    roles = spec.get("role_models") or cfg.get("role_models") or {}
    m_write, m_judge, m_rewrite = roles.get("writer"), roles.get("judge"), roles.get("rewriter")
    no_critic = cfg.get("no_critic", False)
    rewrite_tpl = prompts["rewriter_nocritic"] if no_critic else prompts["rewriter"]
    extra.update(role_models=roles or None, no_critic=no_critic or None)

    # ---- resume state ----
    recs = read_jsonl(path)
    cur = None
    popped = False
    while recs and (recs[-1].get("error") or recs[-1].get("feedback") is None):
        last = recs[-1]
        if last.get("stop_reason") == "max_iterations" and last["iteration"] >= N:
            log.info("chain %d: already complete (%d iterations)", c, last["iteration"])
            return
        if last.get("stop_reason") == "exact_repeat" and cfg.get("early_stop_on_exact_repeat"):
            log.info("chain %d: already stopped on exact repeat at iteration %d", c, last["iteration"])
            return
        recs.pop()
        popped = True
        if last.get("poem") is not None:
            last.update(error=None, stop_reason=None)
            cur = last  # may still carry feedback (if only the rewrite failed it has none here)
            break
        # poem is None -> the rewrite from recs[-1].feedback failed; redo it.
    if popped:
        write_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
        log.info("chain %d: resume reopened iteration %s", c,
                 cur["iteration"] if cur else (recs[-1]["iteration"] + 1 if recs else 0))

    if cur is None and pending_path.exists():
        p = json.loads(pending_path.read_text())
        want = recs[-1]["iteration"] + 1 if recs else 0
        if p.get("iteration") == want:
            cur = p
    seen = {r["poem_sha1"]: r["iteration"] for r in recs}

    if recs and recs[-1].get("stop_reason") == "critic_finished":
        log.info("chain %d: already finished by the critic at iteration %d", c, recs[-1]["iteration"])
        return
    if cur is None and recs and recs[-1]["iteration"] >= N:
        log.info("chain %d: already complete (%d iterations)", c, recs[-1]["iteration"])
        return

    t_chain = time.time()
    done_this_session = 0
    try:
        if cur is None:
            if recs:
                # rewrite step from the last complete record
                prev = recs[-1]
                log.info("chain %d: resuming with rewrite of iteration %d", c, prev["iteration"])
            else:
                log.info("chain %d (%s): seed %d, T=%s, %s poem 0", c, label, seed, temp,
                         "given" if spec.get("start") else "writing")
                if spec.get("start"):
                    # experiment-given starting poem: no writer call
                    text = spec["start"].strip()
                    cur = new_poem_record(c, 0, seed, text, text,
                                          {"seconds": 0, "tokens_in": None, "tokens_out": None,
                                           "finish_reason": None, "seed": None, "seed_sent": None}, "start", extra)
                else:
                    try:
                        clean, raw, st = generate(prompts["writer"], cfg["max_tokens_poem"], seed, "poem", retries, temp, m_write)
                    except Exception as e:
                        append_jsonl(path, {"chain": c, "iteration": 0, "role": "write", "poem": None, "poem_raw": None,
                                            "poem_sha1": None, "feedback": None, "feedback_raw": None, "seed": seed,
                                            "error": f"write failed: {e}", "stop_reason": "error", "time": now()})
                        log.error("chain %d iter 0: write failed, chain stopped: %s", c, e)
                        return
                    cur = new_poem_record(c, 0, seed, clean, raw, st, "write", extra)
                    log.info("chain %d iter 0: write %.1fs, %d words", c, st["seconds"], len(clean.split()))
                write_atomic(pending_path, json.dumps(cur, ensure_ascii=False))
                prev = None
        else:
            prev = None
            log.info("chain %d: resuming at iteration %d", c, cur["iteration"])

        while True:
            if cur is None:
                # ---- rewrite (from prev, which is complete and already logged) ----
                k = prev["iteration"] + 1
                prompt = rewrite_tpl.format(poem=prev["poem"], feedback=prev["feedback"])
                try:
                    clean, raw, st = generate(prompt, cfg["max_tokens_poem"], seed, "poem", retries, temp, m_rewrite)
                except Exception as e:
                    err = {"chain": c, "iteration": k, "role": "rewrite", "poem": None, "poem_raw": None,
                           "poem_sha1": None, "feedback": None, "feedback_raw": None, "seed": seed,
                           "error": f"rewrite failed: {e}", "stop_reason": "error", "time": now()}
                    append_jsonl(path, err)
                    log.error("chain %d iter %d: rewrite failed, chain stopped: %s", c, k, e)
                    return
                cur = new_poem_record(c, k, seed, clean, raw, st, "rewrite", extra)
                write_atomic(pending_path, json.dumps(cur, ensure_ascii=False))

            k = cur["iteration"]
            repeat_of = seen.get(cur["poem_sha1"])
            if repeat_of is not None:
                log.info("chain %d iter %d: exact repeat of iteration %d", c, k, repeat_of)

            # ---- stop conditions (the loop just runs; only these two) ----
            if k >= N or (repeat_of is not None and cfg.get("early_stop_on_exact_repeat")):
                cur["stop_reason"] = "max_iterations" if k >= N else "exact_repeat"
                cur["feedback"] = None
                append_jsonl(path, cur)
                pending_path.unlink(missing_ok=True)
                log.info("chain %d: finished at iteration %d (%s) in %.1f min",
                         c, k, cur["stop_reason"], (time.time() - t_chain) / 60)
                return

            # ---- judge ----
            if cur.get("feedback") is None and no_critic:
                # ablation: no critic call at all; the rewriter only sees the poem
                cur.update(feedback="", feedback_raw="", seconds_judge=0.0)
            if cur.get("feedback") is None:
                prompt = judge_tpl.format(poem=cur["poem"])
                try:
                    fb, fb_raw, js = generate(prompt, cfg["max_tokens_feedback"], seed, "feedback", retries, temp, m_judge)
                except Exception as e:
                    cur["error"] = f"judge failed: {e}"
                    cur["stop_reason"] = "error"
                    append_jsonl(path, cur)
                    pending_path.unlink(missing_ok=True)
                    log.error("chain %d iter %d: judge failed, chain stopped: %s", c, k, e)
                    return
                cur.update(feedback=fb, feedback_raw=fb_raw, seconds_judge=js["seconds"])
                cur["tokens_in"]["judge"] = js.get("tokens_in")
                cur["tokens_out"]["judge"] = js.get("tokens_out")
                cur["finish_reason"]["judge"] = js.get("finish_reason")
                cur["seed_used"]["judge"] = js.get("seed")

            stop = cfg.get("stop_phrase")
            fw = re.findall(r"[A-Za-z]+", cur["feedback"] or "")
            if stop and fw and len(fw) <= 30 and stop.upper() in (fw[0].upper(), fw[-1].upper()):
                # opt-in experiment: the critic may declare the poem finished; the chain ends here.
                cur["stop_reason"] = "critic_finished"
                append_jsonl(path, cur)
                pending_path.unlink(missing_ok=True)
                log.info("chain %d: critic said %s at iteration %d", c, stop, k)
                return

            append_jsonl(path, cur)  # iteration k is now complete: poem k + feedback on it
            pending_path.unlink(missing_ok=True)
            seen.setdefault(cur["poem_sha1"], k)
            recs.append(cur)
            done_this_session += 1
            el = time.time() - t_chain
            per = el / done_this_session
            log.info("chain %d iter %d/%d: judge %.1fs rewrite %.1fs | %d words | ~%.0f min left in chain",
                     c, k, N, cur["seconds_judge"] or 0, cur["seconds_rewrite"] or 0,
                     len(cur["poem"].split()), per * (N - k) / 60)
            prev, cur = cur, None
    except ChainStop as e:
        log.error("chain %d: %s", c, e)
        raise


# ---------- main ----------

def setup_logging(run_dir: Path):
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.FileHandler(run_dir / "run.log"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--prompts", default=str(HERE / "prompts.yaml"))
    ap.add_argument("--chains", type=int)
    ap.add_argument("--iterations", type=int)
    ap.add_argument("--resume", help="runs/<timestamp> to continue")
    ap.add_argument("--model")
    ap.add_argument("--base-url")
    ap.add_argument("--workers", type=int, help="chains run in parallel (server needs that many slots); default config workers or 1")
    a = ap.parse_args()

    if a.resume:
        run_dir = Path(a.resume)
        if not run_dir.is_absolute() and not run_dir.exists():
            run_dir = HERE / run_dir
        if not (run_dir / "config.yaml").exists():
            sys.exit(f"--resume: no config.yaml in {run_dir}")
        cfg = yaml.safe_load((run_dir / "config.yaml").read_text())
        prompts = yaml.safe_load((run_dir / "prompts.yaml").read_text())
    else:
        cfg = yaml.safe_load(Path(a.config).read_text())
        prompts = yaml.safe_load(Path(a.prompts).read_text())

    changed = False
    for key, val in (("chains", a.chains), ("iterations", a.iterations), ("model", a.model), ("base_url", a.base_url)):
        if val is not None and cfg.get(key) != val:
            cfg[key] = val
            changed = True

    if cfg.get("chain_specs"):
        cfg["chains"] = len(cfg["chain_specs"])

    # Fail fast before creating anything.
    try:
        hc = llm.health_check(cfg)
    except llm.HealthCheckError as e:
        sys.exit(f"HEALTH CHECK FAILED: {e}")

    if not a.resume:
        out = Path(cfg.get("out_dir", "runs/"))
        out = out if out.is_absolute() else HERE / out
        run_dir = out / dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=False)
        if changed:
            (run_dir / "config.yaml").write_text(
                "# effective config (CLI overrides applied)\n" + yaml.safe_dump(cfg, sort_keys=False))
        else:
            shutil.copy(a.config, run_dir / "config.yaml")
        shutil.copy(a.prompts, run_dir / "prompts.yaml")
    elif changed:
        (run_dir / "config.yaml").write_text(
            "# effective config (updated on resume)\n" + yaml.safe_dump(cfg, sort_keys=False))

    setup_logging(run_dir)
    log.info("%s run dir %s | model %s @ %s | chains %d x %d iterations",
             "RESUME" if a.resume else "START", run_dir, cfg["model"], cfg["base_url"], cfg["chains"], cfg["iterations"])

    log.info("health check ok: model '%s' answered %r", cfg["model"], hc["test_reply"][:40])

    llm.setup(cfg, system_prompt=prompts.get("system"))
    specs = cfg.get("chain_specs") or [{} for _ in range(cfg["chains"])]
    workers = a.workers or cfg.get("workers", 1)

    def one(c):
        try:
            run_chain(c, cfg, prompts, run_dir, specs[c])
        except ChainStop:
            pass  # logged; move on to next chain
        except Exception:
            log.exception("chain %d crashed; resume later to retry it", c)

    t0 = time.time()
    try:
        if workers <= 1:
            for c in range(len(specs)):
                one(c)
        else:
            log.info("running %d chains with %d parallel workers", len(specs), workers)
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(one, range(len(specs))))
    except KeyboardInterrupt:
        log.warning("interrupted; resume with: python loop.py --resume %s", run_dir.relative_to(HERE) if run_dir.is_relative_to(HERE) else run_dir)
        sys.exit(130)
    log.info("ALL DONE in %.1f min. Next: python analyze.py %s", (time.time() - t0) / 60,
             run_dir.relative_to(HERE) if run_dir.is_relative_to(HERE) else run_dir)
    log.info("seed passed to server: %s", llm._seed_supported)


if __name__ == "__main__":
    main()
