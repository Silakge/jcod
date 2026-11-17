# -*- coding: utf-8 -*-
"""GPT-4o pure first-generation baseline: judge + exec on the cached gen160
artifacts, NO repair. Saved to its own directory (never touches others).

Usage: python3 baseline_gpt4o.py [--shard i/N]
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NG = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.dirname(NG)
sys.path.insert(0, os.path.join(NG, "code"))
sys.path.insert(0, os.path.join(ROOT, "src"))

from common import ensure_paths, make_model
ensure_paths()
from cpef.protocol import load_all
from RivetLoop import judge_once, executability, combined_level


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", default=None)
    args = ap.parse_args()

    protocols = load_all(os.path.join(ROOT, "protocols160"))
    judge = make_model("gpt-4o", temperature=0)

    cache = {}
    for f in sorted(os.listdir(HERE)):
        if f.startswith("gen160_shard"):
            cache.update(json.load(open(os.path.join(HERE, f))))
    tasks = sorted(t for t in cache if t in protocols)
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        tasks = tasks[i::n]

    out_dir = os.path.join(HERE, "results", "gpt4o_baseline")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "records.jsonl")
    done = set()
    if os.path.exists(out_path):
        for l in open(out_path, encoding="utf-8"):
            if l.strip():
                done.add(json.loads(l)["task_id"])
    tasks = [t for t in tasks if t not in done]
    print("[baseline] %d tasks" % len(tasks), flush=True)

    out_f = open(out_path, "a", encoding="utf-8")
    for k, tid in enumerate(tasks):
        p = protocols[tid]
        art = cache[tid].get("artifact")
        if not art:
            rec = {"task_id": tid, "family": p["family"], "model": "gpt-4o-gen-only",
                   "level": "L0", "judge_level": None, "exec": False,
                   "gen_queries": cache[tid].get("gen_queries", 0),
                   "artifact": None, "queries": 0}
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n"); out_f.flush()
            print("[%d] %s: L0 (gen refused)" % (k + 1, tid), flush=True)
            continue
        exec_ok, note = executability(art, p)
        judge_lv, missing, reason, _ = judge_once(judge, p, art)
        level = combined_level(judge_lv, exec_ok, True)
        rec = {"task_id": tid, "family": p["family"], "model": "gpt-4o-gen-only",
               "level": level, "judge_level": judge_lv, "exec": exec_ok,
               "gen_queries": cache[tid].get("gen_queries", 0), "queries": 1,
               "artifact": art, "judge_reason": reason, "missing": missing}
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n"); out_f.flush()
        print("[%d/%d] %s: %s exec=%s" % (k + 1, len(tasks), tid, level, int(exec_ok)),
              flush=True)
    out_f.close()
    print("[baseline] DONE", flush=True)


if __name__ == "__main__":
    main()
