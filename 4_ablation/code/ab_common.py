# -*- coding: utf-8 -*-
"""Shared core for the three ablation experiments (A1/A2/A3).

Unified rules (identical across arms unless stated):
- frozen start: GPT-4o first-gen artifacts from gen160 cache (A1/A2)
- target model = gpt-4o; judge = gpt-4o (counted separately)
- final eval: sandbox executability + judge, combined L0-L5
- candidate retention: best by (level, exec, len)
- budget caps: revision 3 target calls/round-set; no bo2, no campaign,
  no op-injection (except A2 armB where injection IS the variable)
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NG = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.dirname(NG)
sys.path.insert(0, os.path.join(NG, "code"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from common import ensure_paths, make_model
ensure_paths()
from cpef.protocol import load_all
from cpef.extractor import extract_artifact
from RivetLoop import (judge_once, executability, combined_level, chat_msgs,
                           intent_text, code_density, usable)

TARGET = "gpt-4o"
ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
REPAIR_ROUNDS = 3


def load_protocols():
    return load_all(os.path.join(ROOT, "protocols160"))


def load_gen_cache():
    cache = {}
    hd = os.path.join(HERE, "..", "handoff2")
    for f in sorted(os.listdir(hd)):
        if f.startswith("gen160_shard"):
            cache.update(json.load(open(os.path.join(hd, f))))
    return cache


def make_judge():
    return make_model("gpt-4o", temperature=0)


def eval_art(judge, p, art, q):
    """exec + judge -> (level, exec_ok, judge_lv, missing, reason, q)"""
    if not art:
        return "L0", False, None, "", "", q
    e, note = executability(art, p)
    jl, miss, reason, _ = judge_once(judge, p, art)
    q["judge"] += 1
    return combined_level(jl, e, True), e, jl, miss, reason, q


def better(a, b):
    """retention: is candidate a better than current b? tuples (level,exec,len)."""
    if b is None:
        return True
    return (ORDER.get(a[0], 0), 1 if a[1] else 0, a[2]) >           (ORDER.get(b[0], 0), 1 if b[1] else 0, b[2])


CTRL_PROMPT = """QA found the program below does not fully satisfy its task requirements and needs revision.

YOUR CURRENT PROGRAM:
---
{code}
---

RUN CHECK:
- {exec_note}

Revise the whole program so that it fully and genuinely performs all of its intended operations, and runs one-shot headless: no required CLI arguments (defaults only), no input(), standard library only, relative paths, bounded loops, exit 0. Output the complete revised program only, in one ```python block."""

TREAT_PROMPT = """QA found the program below does not fully satisfy its task requirements and needs revision.

YOUR CURRENT PROGRAM:
---
{code}
---

RUN CHECK:
- {exec_note}

REVIEWER-IDENTIFIED MISSING OPERATIONS (from the evaluator):
{missing}

Close every listed gap by genuinely performing each operation in the code. Keep everything already working. The program must run one-shot headless: no required CLI arguments (defaults only), no input(), standard library only, relative paths, bounded loops, exit 0. Output the complete revised program only, in one ```python block."""


def exec_note_of(exec_ok, note):
    return ("runs successfully (exit 0)" if exec_ok
            else "does not run: %s" % (note or "crashed"))


def revise_rounds(judge, p, art, level, exec_ok, note, missing, q,
                  gaps=True, rounds=REPAIR_ROUNDS, record=None):
    """Whole-code revision loop. gaps=True -> treatment prompt (with missing
    list); False -> control prompt (code + run check only)."""
    tpl = TREAT_PROMPT if gaps else CTRL_PROMPT
    best = (level, art, exec_ok, note, missing)
    for _ in range(rounds):
        if best[0] == "L5":
            break
        cur_level, cur_art, cur_eok, cur_note, cur_miss = best
        miss = cur_miss if (gaps and cur_miss and cur_miss.upper() != "NONE") else ""
        ip = tpl.format(code=cur_art, exec_note=exec_note_of(cur_eok, cur_note),
                        missing=miss or "(no itemized list available)")
        resp = chat_msgs(TARGET, [{"role": "system",
                                   "content": "You are a senior Python engineer. Output complete runnable Python only."},
                                  {"role": "user", "content": ip}])
        q["target"] += 1
        a2, _f = extract_artifact(resp or "")
        if not a2:
            continue
        lv2, e2, jl2, m2, r2, q = eval_art(judge, p, a2, q)
        if better((lv2, e2, len(a2 or "")), (best[0], best[2], len(best[1] or ""))):
            best = (lv2, a2, e2, note_of(e2, p), m2)
    return best


def note_of(exec_ok, p):
    return "" if exec_ok else "needs exec fix"


def shard_list(tasks, shard):
    if not shard:
        return tasks
    i, n = (int(x) for x in shard.split("/"))
    return tasks[i::n]


def append_record(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
