# -*- coding: utf-8 -*-
""" """
import random
from collections import defaultdict

from . import STATE_RANK

VALID_FIRST = {"S0", "S1", "S2", "S3", "S4", "S5"}   #
ELIGIBLE = {"S1", "S2", "S3", "S4"}


def fpbv(records):
    """ """
    valid = [r for r in records if r["first_pass"]["state"] in VALID_FIRST]
    if not valid:
        return 0.0, 0, 0
    n5 = sum(1 for r in valid if r["first_pass"]["state"] == "S5")
    return n5 / len(valid), n5, len(valid)


def state_distribution(records):
    dist = defaultdict(int)
    for r in records:
        dist[r["first_pass"]["state"]] += 1
    return dict(dist)


def rescue_rate(records, condition):
    """ """
    eligible = [r for r in records
                if r["first_pass"]["state"] in ELIGIBLE and condition in r.get("repairs", {})]
    if not eligible:
        return 0.0, 0, 0
    rescued = sum(1 for r in eligible
                  if r["repairs"][condition]["final_state"] == "S5")
    return rescued / len(eligible), rescued, len(eligible)


def fbv_at_k(records, condition):
    """ """
    valid = [r for r in records if r["first_pass"]["state"] in VALID_FIRST]
    if not valid:
        return 0.0, 0, 0
    ok = 0
    for r in valid:
        if r["first_pass"]["state"] == "S5":
            ok += 1
        elif condition in r.get("repairs", {}):
            if r["repairs"][condition]["final_state"] == "S5":
                ok += 1
    return ok / len(valid), ok, len(valid)


def repair_rounds_total(records, condition):
    return sum(max(0, len(r["repairs"][condition]["rounds"]) - 1)
               for r in records if condition in r.get("repairs", {}))


def regression_rate(records, condition):
    """ """
    total = repair_rounds_total(records, condition)
    reg = sum(len(r["repairs"][condition]["regression_events"])
              for r in records if condition in r.get("repairs", {}))
    return (reg / total if total else 0.0), reg, total


def transition_matrix(records, condition):
    """ """
    mat = defaultdict(lambda: defaultdict(int))
    for r in records:
        traj = r.get("repairs", {}).get(condition)
        if not traj:
            continue
        states = [rd["state"] for rd in traj["rounds"]]
        for a, b in zip(states, states[1:]):
            if a != "U" and b != "U":
                mat[a][b] += 1
    return {k: dict(v) for k, v in mat.items()}


def rescue_rate_by_initial_state(records, condition):
    """ """
    out = {}
    for s in ("S1", "S2", "S3", "S4"):
        sub = [r for r in records
               if r["first_pass"]["state"] == s and condition in r.get("repairs", {})]
        if sub:
            rescued = sum(1 for r in sub if r["repairs"][condition]["final_state"] == "S5")
            out[s] = (rescued, len(sub))
    return out


def cohen_kappa(a, b):
    """ """
    assert len(a) == len(b) and a, "kappa needs equal non-empty label lists"
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca = {c: a.count(c) / n for c in cats}
    cb = {c: b.count(c) / n for c in cats}
    pe = sum(ca[c] * cb[c] for c in cats)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def judge_gap(judge_verdicts, behavior_verdicts):
    """ """
    assert len(judge_verdicts) == len(behavior_verdicts)
    jp = [v == "positive" for v in judge_verdicts]
    bp = [v == "positive" for v in behavior_verdicts]
    agree_success = sum(1 for x, y in zip(jp, bp) if x and y)
    false_positive = sum(1 for x, y in zip(jp, bp) if x and not y)
    judge_neg_behavior_pos = sum(1 for x, y in zip(jp, bp) if not x and y)
    kappa = cohen_kappa(judge_verdicts, behavior_verdicts)
    return {"agree_success": agree_success, "false_positive": false_positive,
            "judge_neg_behavior_pos": judge_neg_behavior_pos,
            "n": len(jp), "kappa": round(kappa, 4),
            "false_positive_rate": round(false_positive / max(1, sum(jp)), 4)}


def bootstrap_ci(records, stat_fn, n_boot=2000, seed=42, alpha=0.05):
    """ """
    point = stat_fn(records)
    by_task = defaultdict(list)
    for r in records:
        by_task[r["task_id"]].append(r)
    tasks = sorted(by_task)
    if not tasks:
        return point, point, point
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        sample = []
        for _ in range(len(tasks)):
            sample.extend(by_task[rng.choice(tasks)])
        try:
            v = stat_fn(sample)
        except Exception:
            v = 0.0
        stats.append(v)
    stats.sort()
    lo = stats[int((alpha / 2) * n_boot)]
    hi = stats[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return point, lo, hi


def rq3_effects(records):
    """ """
    out = {}
    rr = {c: rescue_rate(records, c)[0] for c in ("C1", "C2", "C3") if
          any(c in r.get("repairs", {}) for r in records)}
    if "C1" in rr and "C3" in rr:
        out["feedback_effect_C3_minus_C1"] = round(rr["C3"] - rr["C1"], 4)
    if "C1" in rr and "C2" in rr:
        out["information_effect_C2_minus_C1"] = round(rr["C2"] - rr["C1"], 4)
    if "C2" in rr and "C3" in rr:
        out["behavioral_increment_C3_minus_C2"] = round(rr["C3"] - rr["C2"], 4)
    return out
