# -*- coding: utf-8 -*-
"""One-time: GPT-4o pure first-generation (multi-turn, no repair) for the
first-30 seeds, cached to shard files. Reused by every optimizer experiment."""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NG = os.path.join(os.path.dirname(HERE), "..")   # new_gpt2
sys.path.insert(0, os.path.abspath(os.path.join(NG, "code")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(NG)), "src")))

from common import ensure_paths
ensure_paths()
from cpef.protocol import load_all
from RivetLoop import multi_turn_chat
from cpef.extractor import extract_artifact

GEN_MODEL = "gpt-4o"
TURNS = os.path.join(NG, "code", "turns160.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True)
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    i, n = (int(x) for x in args.shard.split("/"))

    protocols = load_all(os.path.join(os.path.dirname(os.path.abspath(NG)), "protocols160"))
    turns_map = json.load(open(TURNS, encoding="utf-8"))
    tasks = sorted(t for t in turns_map if t in protocols)[:args.limit][i::n]
    out_path = os.path.join(HERE, "gen160_shard%d.json" % i)
    # reuse the existing first-30 cache as base (never overwrite gen30 files)
    cache = {}
    for f in sorted(os.listdir(HERE)):
        if f.startswith("gen30_shard"):
            cache.update(json.load(open(os.path.join(HERE, f))))
    if os.path.exists(out_path):
        cache.update(json.load(open(out_path)))
    if args.limit <= 30:
        out_path = os.path.join(HERE, "gen30_shard%d.json" % i)
    print("[gencache %s] %d tasks" % (args.shard, len([t for t in tasks if t not in cache])), flush=True)

    for tid in tasks:
        if tid in cache:
            continue
        best, ctx, q = multi_turn_chat(GEN_MODEL, turns_map[tid]["turns"], temperature=0.7)
        art, _f = extract_artifact(best or "")
        cache[tid] = {"artifact": art, "gen_queries": q,
                      "gen_ok": bool(art)}
        json.dump(cache, open(out_path, "w"))
        print("%s: %s q=%d" % (tid, "OK len=%d" % len(art) if art else "REFUSED", q), flush=True)
    print("[gencache %s] DONE" % args.shard, flush=True)


if __name__ == "__main__":
    main()
