# -*- coding: utf-8 -*-
"""Shared helpers for the new_gpt2 follow-up experiments (S&P final round).

Environment-only configuration (CPEF_BASE_URL / CPEF_API_KEY); no URL or
credential appears in this folder.
"""
import glob
import json
import os
import random
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
NEW_GPT2 = os.path.dirname(HERE)
ROOT = os.path.dirname(NEW_GPT2)

MAIN_DIRS = {
    "gpt4o": ["results/full/shard*", "results/full160/shard*", "results/m_gpt4o/*"],
    "gpt5": ["results/m_gpt5/*"],
    "qwen": ["results/m_qwen/*"],
    "gemini31": ["results/m_gemini31/*"],
    "claude45": ["results/m_claude45/*"],
}
RESCUE_FILES = {
    "gpt4o": ["results/rescued_m_gpt4o.jsonl", "results/rescued_m_gpt4o_e25.jsonl",
              "results/rescued_m_gpt4o_e8.jsonl"],
    "gpt5": ["results/rescued_m_gpt5.jsonl", "results/rescued_m_gpt5_e25.jsonl",
             "results/rescued_m_gpt5_e8.jsonl"],
    "qwen": ["results/rescued_m_qwen.jsonl", "results/rescued_m_qwen_e25.jsonl",
             "results/rescued_m_qwen_e8.jsonl"],
    "gemini31": ["results/rescued_m_gemini31.jsonl",
                 "results/rescued_m_gemini31_e25.jsonl",
                 "results/rescued_m_gemini31_e8.jsonl"],
    "claude45": ["results/rescued_m_claude45.jsonl",
                 "results/rescued_m_claude45_e25.jsonl",
                 "results/rescued_m_claude45_e8.jsonl"],
}
COMPLETE_FILES = {
    "gpt4o": ["results/complete_gpt4o_p1.jsonl"],
    "gpt5": ["results/complete_gpt5_p1.jsonl"],
    "qwen": ["results/complete_qwen_p1.jsonl"],
    "gemini31": ["results/complete_gemini31_p1.jsonl"],
    "claude45": ["results/complete_claude45_p1.jsonl",
                 "results/complete_claude45_p2.jsonl"],
}
RANK = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5}
IMAGE = "python:3.11-slim"


def ensure_paths():
    import sys
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(NEW_GPT2, "code"))


def require_env():
    ensure_paths()
    for var in ("CPEF_BASE_URL", "CPEF_API_KEY"):
        if not os.environ.get(var):
            raise SystemExit("missing environment variable: %s" % var)
    return os.environ["CPEF_BASE_URL"]


def make_model(name, temperature=0.7, timeout=300):
    ensure_paths()
    from cpef.models import OpenAICompatModel
    return OpenAICompatModel(name, require_env(), "CPEF_API_KEY",
                             temperature=temperature, timeout=timeout)


def chat_with_retries(model, prompt, tries=4, base_delay=15, system=None):
    err = body = None
    for attempt in range(tries):
        try:
            return model.chat(prompt, system=system), None
        except urllib.error.HTTPError as e:
            err = "HTTP %s" % e.code
            try:
                body = e.read().decode(errors="replace")[:2000]
            except Exception:
                body = ""
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            body = ""
        if attempt < tries - 1:
            time.sleep(base_delay * (attempt + 1))
    return None, "%s | body: %s" % (err, body)


def iter_records(model, elicitation=None):
    """Yield raw record dicts from the main pipeline (deduped, last wins)."""
    ensure_paths()
    seen = {}
    for pat in MAIN_DIRS[model]:
        for d in sorted(glob.glob(os.path.join(ROOT, pat))):
            fp = os.path.join(d, "records.jsonl")
            if not os.path.exists(fp):
                continue
            for line in open(fp, encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if elicitation and r.get("elicitation") != elicitation:
                    continue
                seen[(r["task_id"], r.get("elicitation"),
                      r.get("sample", 0))] = r
    for k in sorted(seen):
        yield seen[k]


def record_best(r):
    """(state, artifact) best along one record's chain (all conditions)."""
    best, art = r["first_pass"]["state"], r["first_pass"].get("artifact")
    for cond, traj in (r.get("repairs") or {}).items():
        for rd in traj.get("rounds", []):
            if RANK.get(rd.get("state"), -1) > RANK.get(best, -1):
                best, art = rd["state"], rd.get("artifact")
    return best, art


def final_artifacts(model):
    """task_id -> (state, artifact): the model's FINAL selection per seed,
    combining main records (all elicitations), rescue and complete phases."""
    ensure_paths()
    best = {}
    for r in iter_records(model):
        st, art = record_best(r)
        tid = r["task_id"]
        if tid not in best or RANK.get(st, -1) > RANK.get(best[tid][0], -1):
            best[tid] = (st, art)
    for fp in RESCUE_FILES[model] + COMPLETE_FILES[model]:
        full = os.path.join(ROOT, fp)
        if not os.path.exists(full):
            continue
        for line in open(full, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            st = r.get("final_state")
            art = r.get("final_artifact") or r.get("artifact")
            tid = r["task_id"]
            if st and art and (tid not in best or
                               RANK.get(st, -1) > RANK.get(best[tid][0], -1)):
                best[tid] = (st, art)
    return best


def load_jsonl(path):
    ensure_paths()
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    return out


def append_jsonl(path, rec):
    ensure_paths()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def done_keys(path, key_fields):
    ensure_paths()
    done = set()
    for r in load_jsonl(path):
        done.add(tuple(r.get(k) for k in key_fields))
    return done


def bootstrap_ci(pairs, iters=10000, seed=0):
    rng = random.Random(seed)
    n = len(pairs)
    if n == 0:
        return (0.0, 0.0, 0.0)
    means = sorted(sum(pairs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(iters))
    return (sum(pairs) / n, means[int(0.025 * iters)],
            means[int(0.975 * iters)])
