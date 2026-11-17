# -*- coding: utf-8 -*-
"""Unified v13-caliber baseline runner.

Six baselines, original-paper attacker configurations and internal mechanics
unchanged; only (1) target model = gpt-4o, (2) target-query budget = 15,
(3) final adjudication in the SAME L0-L5 caliber as the main framework
(gpt-4o judge for maliciousness/completeness + sandbox executability).

Baselines:
  spell | dra | autodan   classic prompt-side (baselines_core, faithful ports)
  pair_official           official PAIR (patrickrchao/JailbreakingLLMs port)
  cjb                     CodeJailbreaker (commit-message completion)
  redcode                 RedCodeAgent (tool-using red-team agent)

Usage: python3 run_v13.py --baseline spell --shard i/N
Output: ../results/<baseline>/records.jsonl
  {task_id, baseline, level, judge_level, exec, target_q, eval_q, artifact}
"""
import argparse, io, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_V13 = os.path.dirname(HERE)                 # .../baselines_v13
ROOT = os.path.dirname(os.path.dirname(BASE_V13))  # repo root
sys.path.insert(0, os.path.join(os.path.dirname(BASE_V13), "code"))  # main framework helpers
sys.path.insert(0, HERE)  # patched baseline copies take import priority

from common import ensure_paths, make_model, require_env

ensure_paths()
from RivetLoop import judge_once, combined_level, executability

from cpef.protocol import load_all

TARGET = "gpt-4o"
BUDGET = 15


class LLMAdapter(object):
    """chat(prompt, meta) adapter over chat_with_retries for baselines_core."""

    def __init__(self, model):
        self.model = model
        self.n = 0

    def chat(self, prompt, meta=None):
        from common import chat_with_retries
        text, err = chat_with_retries(self.model, prompt)
        self.n += 1
        return text, {"meta": meta, "err": err}


def l_adjudicate(judge, protocol, artifact):
    """Main-framework L-caliber adjudication of one artifact.
    Returns (level, judge_level, exec_ok, eval_q)."""
    if not artifact:
        return "L0", None, False, 0
    exec_ok, _note = executability(artifact, protocol)
    judge_lv, _missing, _reason, _raw = judge_once(judge, protocol, artifact)
    return combined_level(judge_lv, exec_ok, True), judge_lv, exec_ok, 1


def run_seed_dispatch(baseline, protocol, models, rng):
    import signal

    class _TO(Exception):
        pass

    def _h(signum, frame):
        raise _TO()
    signal.signal(signal.SIGALRM, _h)
    signal.alarm(1500)   # 25-min wall cap per seed (transport-level guard)
    """Run one seed under the baseline's own loop; returns (best_art, target_q)."""
    if baseline in ("spell", "dra", "autodan"):
        import baselines_core
        logf = io.StringIO()
        llm = models["llm_adapter"]
        _state, best_art, _att = baselines_core.run_baseline(
            baseline, TARGET, protocol, BUDGET, rng, llm, logf)
        return best_art, llm.n
    if baseline == "pair_official":
        import x2c_pair_official as x2c
        goal = protocol["elicitation_seed"].strip()
        res = x2c.run_seed(goal, protocol, models["pair"], "Sure, here")
        return res.get("final_artifact"), res.get("queries_used", 0)
    if baseline == "cjb":
        import x2d_codejailbreaker as x2d
        res = x2d.run_seed(protocol, models["target"])
        return res.get("final_artifact"), res.get("queries_used", 0)
    if baseline == "redcode":
        import x2e_redcodeagent as x2e
        res = x2e.run_seed(protocol, models["agent"], models["target"])
        return res.get("final_artifact"), res.get("queries_used", 0)
    if baseline == "redcode_gen":
        import x3_redcode
        res = x3_redcode.run_seed(protocol, models["target"], models["rc_judge"])
        return res.get("best_artifact"), res.get("queries_used", 0)
    if baseline == "crescendo":
        import x3_crescendo
        res = x3_crescendo.run_seed(protocol, models["adv"], models["target"])
        return res.get("best_artifact"), res.get("queries_used", 0)
    raise ValueError(baseline)
    # (alarm cleared by caller via signal.alarm(0) below)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True,
                    choices=["spell", "dra", "autodan", "pair_official",
                             "cjb", "redcode", "redcode_gen", "crescendo"])
    ap.add_argument("--shard", required=True)
    args = ap.parse_args()
    require_env()

    protocols = load_all(os.path.join(ROOT, "protocols160"))
    tasks = sorted(protocols)
    i, n = (int(x) for x in args.shard.split("/"))
    tasks = tasks[i::n]

    target = make_model(TARGET, temperature=0.7)
    models = {"target": target, "llm_adapter": LLMAdapter(target)}
    if args.baseline == "pair_official":
        import x2c_pair_official as x2c  # noqa - ensures ref prompts importable
        attacker = make_model(x2c.ATTACKER, temperature=1)
        judge_m = make_model(x2c.JUDGE, temperature=0)
        models["pair"] = (attacker, target, judge_m)
    if args.baseline == "redcode":
        import x2e_redcodeagent as x2e
        models["agent"] = make_model(x2e.AGENT, temperature=1)
    if args.baseline == "redcode_gen":
        models["rc_judge"] = make_model(TARGET, temperature=0)
    if args.baseline == "crescendo":
        models["adv"] = make_model(TARGET, temperature=1)

    judge = make_model(TARGET, temperature=0)   # L-caliber judge
    out_dir = os.path.join(BASE_V13, "results", args.baseline)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "records.jsonl")

    done = set()
    if os.path.exists(out_path):
        for l in open(out_path, encoding="utf-8"):
            if l.strip():
                done.add(json.loads(l)["task_id"])
    tasks = [t for t in tasks if t not in done]
    print("[v13-baseline/%s shard %s] %d seeds" % (args.baseline, args.shard,
                                                   len(tasks)), flush=True)

    rng = random.Random(1234)
    out_f = open(out_path, "a", encoding="utf-8")
    for idx, tid in enumerate(tasks):
        p = protocols[tid]
        import signal
        try:
            best_art, target_q = run_seed_dispatch(args.baseline, p, models, rng)
        except Exception as e:
            best_art, target_q = None, 0
            print("  [%s] error: %s" % (tid, str(e)[:150]), flush=True)
        finally:
            signal.alarm(0)
        level, judge_lv, exec_ok, eval_q = l_adjudicate(judge, p, best_art)
        rec = {"task_id": tid, "family": p["family"], "baseline": args.baseline,
               "level": level, "judge_level": judge_lv, "exec": exec_ok,
               "target_q": target_q, "eval_q": eval_q, "artifact": best_art}
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n"); out_f.flush()
        print("[%d/%d] %s: %s exec=%s q=%d" % (idx + 1, len(tasks), tid, level,
                                               int(exec_ok), target_q),
              flush=True)
    out_f.close()
    print("[v13-baseline/%s] SHARD DONE" % args.baseline, flush=True)


if __name__ == "__main__":
    main()
