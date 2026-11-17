# -*- coding: utf-8 -*-
"""A1: does the judge's gap list improve whole-code revision?

Two arms over the SAME 160 frozen first-gen artifacts:
  ctrl: sees code + run check only            (3 revision rounds)
  treat: ctrl + reviewer's missing-ops list   (3 revision rounds)
No function-level completion, no bo2, no campaign. Unified eval + retention.
Usage: python3 run_a1.py [--shard i/N] [--arm ctrl|treat]
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.dirname(HERE)
sys.path.insert(0, AB)
from ab_common import (load_protocols, load_gen_cache, make_judge, eval_art,
                       revise_rounds, shard_list, append_record, ORDER)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default=None)
    ap.add_argument("--arm", choices=["ctrl", "treat"], required=True)
    args = ap.parse_args()

    protocols = load_protocols()
    cache = load_gen_cache()
    judge = make_judge()
    tasks = shard_list(sorted(t for t in cache if t in protocols), args.shard)

    out_path = os.path.join(HERE, "results", "a1_%s.jsonl" % args.arm)
    done = set()
    if os.path.exists(out_path):
        for l in open(out_path):
            if l.strip():
                done.add(json.loads(l)["task_id"])
    tasks = [t for t in tasks if t not in done]
    print("[A1/%s] %d tasks" % (args.arm, len(tasks)), flush=True)

    for k, tid in enumerate(tasks):
        p = protocols[tid]
        art = cache[tid].get("artifact")
        q = {"target": 0, "judge": 0}
        if not art:
            append_record(out_path, {"task_id": tid, "family": p["family"],
                                     "arm": args.arm, "level0": "L0", "level": "L0",
                                     "exec": False, "target_q": 0, "judge_q": 0,
                                     "artifact": None})
            continue
        lv0, e0, jl0, m0, r0, q = eval_art(judge, p, art, q)
        best = revise_rounds(judge, p, art, lv0, e0,
                             "" if e0 else "initial run check", m0, q,
                             gaps=(args.arm == "treat"))
        append_record(out_path, {"task_id": tid, "family": p["family"],
                                 "arm": args.arm, "level0": lv0,
                                 "judge0": jl0, "level": best[0], "exec": best[2],
                                 "target_q": q["target"], "judge_q": q["judge"],
                                 "artifact": best[1]})
        print("[%d/%d] %s: %s -> %s (t=%d j=%d)" % (k + 1, len(tasks), tid,
              lv0, best[0], q["target"], q["judge"]), flush=True)
    print("[A1/%s] DONE" % args.arm, flush=True)

if __name__ == "__main__":
    main()
