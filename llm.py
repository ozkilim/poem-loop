"""The single model-call function. Every call is stateless: one user message, nothing else."""
import json
import os
import time

try:  # openai>=3 ships its transport as httpx2; older versions use httpx
    import httpx2 as httpx
except ImportError:
    import httpx
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError, BadRequestError, NotFoundError

from clean import clean_feedback, clean_poem

_cfg = None
_client = None
_system = None
_seed_supported = True


class HealthCheckError(RuntimeError):
    pass


def _dump_request(request: httpx.Request):
    """If POEMLOOP_DUMP_REQUESTS is set, append every outgoing request body to that file (for audits)."""
    path = os.environ.get("POEMLOOP_DUMP_REQUESTS")
    if path and request.method == "POST":
        with open(path, "a") as f:
            f.write(json.dumps({"url": str(request.url), "body": json.loads(request.content or b"{}")}) + "\n")


def setup(cfg: dict, system_prompt=None):
    global _cfg, _client, _system
    _cfg = cfg
    _system = system_prompt
    _client = OpenAI(
        base_url=cfg["base_url"],
        api_key=os.environ.get("OPENAI_API_KEY", "local"),
        timeout=cfg.get("request_timeout_s", 300),
        max_retries=0,  # we do our own retries
        http_client=httpx.Client(event_hooks={"request": [_dump_request]}, timeout=cfg.get("request_timeout_s", 300)),
    )


def _qwen_style(model):
    """/no_think and enable_thinking are Qwen controls; never send them to another model family."""
    return "qwen" in (model or _cfg["model"]).lower()


def _messages(prompt: str, model=None):
    if _cfg.get("disable_thinking") and _qwen_style(model):
        prompt = prompt.rstrip() + "\n\n/no_think"
    msgs = []
    if _system:
        msgs.append({"role": "system", "content": _system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


_clients = {}


def _client_for(base_url):
    """Extra clients for roles served from another endpoint (e.g. a second model on its own server)."""
    if not base_url or base_url == _cfg["base_url"]:
        return _client
    if base_url not in _clients:
        _clients[base_url] = OpenAI(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "local"),
                                    timeout=_cfg.get("request_timeout_s", 300), max_retries=0)
    return _clients[base_url]


def call(prompt: str, max_tokens: int, seed: int, kind: str = "poem", temperature=None, model=None, base_url=None):
    """One fresh model call. Returns (clean, raw, stats).

    kind: "poem" (strip lead-ins + trailing notes) or "feedback" (strip think blocks only).
    Transport errors are retried up to max_retries; raises on final failure.
    """
    global _seed_supported
    msgs = _messages(prompt, model)
    assert len(msgs) == (2 if _system else 1), "stateless: exactly one user message per call"
    kwargs = dict(
        model=model or _cfg["model"],
        messages=msgs,
        max_tokens=max_tokens,
        temperature=_cfg["temperature"] if temperature is None else temperature,
        top_p=_cfg["top_p"],
    )
    if _cfg.get("disable_thinking") and _qwen_style(model):
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    cl = _client_for(base_url)
    last_err = None
    for attempt in range(1, _cfg.get("max_retries", 3) + 1):
        try:
            t0 = time.time()
            if _seed_supported:
                try:
                    resp = cl.chat.completions.create(seed=seed, **kwargs)
                except BadRequestError as e:
                    if "seed" in str(e).lower():
                        _seed_supported = False
                        resp = cl.chat.completions.create(**kwargs)
                    else:
                        raise
            else:
                resp = cl.chat.completions.create(**kwargs)
            dt = time.time() - t0
            msg = resp.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or (msg.model_extra or {}).get("reasoning_content")
            raw = (f"<think>{reasoning}</think>\n" if reasoning else "") + content
            clean = clean_poem(raw) if kind == "poem" else clean_feedback(raw)
            usage = resp.usage
            stats = {
                "seconds": round(dt, 3),
                "tokens_in": getattr(usage, "prompt_tokens", None) if usage else None,
                "tokens_out": getattr(usage, "completion_tokens", None) if usage else None,
                "finish_reason": resp.choices[0].finish_reason,
                "seed": seed if _seed_supported else None,
                "seed_sent": _seed_supported,
                "attempts": attempt,
                "n_messages": len(msgs),
            }
            return clean, raw, stats
        except (APIConnectionError, APITimeoutError) as e:
            last_err = e
        except APIStatusError as e:
            if 400 <= e.status_code < 500 and e.status_code not in (408, 429):
                raise
            last_err = e
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"model call failed after {_cfg.get('max_retries', 3)} attempts: {last_err}")


def health_check(cfg: dict):
    """Fail fast if the server is down or the model name is wrong."""
    base = cfg["base_url"]
    c = OpenAI(base_url=base, api_key=os.environ.get("OPENAI_API_KEY", "local"), timeout=10, max_retries=0)
    try:
        ids = [m.id for m in c.models.list().data]
    except (APIConnectionError, APITimeoutError) as e:
        raise HealthCheckError(
            f"Cannot reach the model server at {base}.\n"
            f"  Is it running? (Ollama: `ollama serve`; LM Studio: start the local server; "
            f"llama.cpp: `llama-server ...`). Error: {e}"
        )
    except APIStatusError as e:
        raise HealthCheckError(f"Server at {base} answered {e.status_code} on /models: {e}")
    if ids and cfg["model"] not in ids:
        raise HealthCheckError(
            f"Model '{cfg['model']}' not found on {base}.\n  Available: {', '.join(ids)}\n"
            f"  Set `model:` in config.yaml to one of these."
        )
    # One tiny real call (also loads the model if the server lazy-loads).
    c2 = OpenAI(base_url=base, api_key=os.environ.get("OPENAI_API_KEY", "local"),
                timeout=cfg.get("request_timeout_s", 300), max_retries=0)
    try:
        extra = {"chat_template_kwargs": {"enable_thinking": False}} if cfg.get("disable_thinking") else None
        r = c2.chat.completions.create(model=cfg["model"], max_tokens=8,
                                       messages=[{"role": "user", "content": "Say OK." + (" /no_think" if cfg.get("disable_thinking") else "")}],
                                       extra_body=extra)
    except NotFoundError as e:
        raise HealthCheckError(f"Model '{cfg['model']}' not found on {base}: {e}")
    except (APIConnectionError, APITimeoutError) as e:
        raise HealthCheckError(f"Server at {base} stopped responding during the test call: {e}")
    except APIStatusError as e:
        raise HealthCheckError(f"Test call to model '{cfg['model']}' failed ({e.status_code}): {e}")
    return {"models": ids, "test_reply": (r.choices[0].message.content or "").strip()}


def embed(texts, cfg: dict):
    """Embeddings via the same (or a separate) OpenAI-compatible server. Returns list of vectors."""
    base = cfg.get("embedding_base_url") or cfg["base_url"]
    c = OpenAI(base_url=base, api_key=os.environ.get("OPENAI_API_KEY", "local"), timeout=120, max_retries=1)
    out = []
    for i in range(0, len(texts), 32):
        r = c.embeddings.create(model=cfg["embedding_model"], input=[t or " " for t in texts[i:i + 32]])
        out.extend(d.embedding for d in r.data)
    return out
