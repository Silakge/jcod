# -*- coding: utf-8 -*-
""" """
import hashlib

from .classifier import classify_state, is_regression
from .executor import run_artifact
from .extractor import extract_artifact
from .feedback import build_repair_prompt, should_repair
from .prompts import build_elicitation_prompt


def _execute_and_classify(artifact, protocol, mode, docker_image):
    if artifact is None:
        obs = {"exit_code": None, "stdout": "", "stderr": "", "timed_out": False,
               "env_error": False, "error": None,
               "fs_changes": {"created": [], "deleted": [], "modified": []},
               "pre_state": {}, "post_state": {}, "file_contents": {},
               "net_attempts": [], "port_listens": [], "process_spawns": [],
               "artifact_sha256": None, "duration": 0.0, "mode": mode}
        state, detail = "S0", {"reason": "no artifact"}
        return state, detail, obs
    obs = run_artifact(artifact, protocol, mode=mode, docker_image=docker_image)
    state, detail = classify_state(artifact, obs, protocol)
    return state, detail, obs


def _slim_obs(obs):
    """ """
    o = dict(obs)
    o["stdout"] = (obs.get("stdout") or "")[:800]
    o["stderr"] = (obs.get("stderr") or "")[:800]
    o["pre_state"] = dict(list(obs.get("pre_state", {}).items())[:50])
    o["post_state"] = dict(list(obs.get("post_state", {}).items())[:50])
    o["file_contents"] = dict(list(obs.get("file_contents", {}).items())[:30])
    return o


def run_first_pass(model, protocol, elicitation, sample, mode="local",
                   docker_image=None, e2_template="roleplay"):
    prompt = build_elicitation_prompt(protocol, elicitation, e2_template)
    resp = model.chat(prompt, key=(protocol["task_id"], elicitation, None, 0))
    artifact, flags = extract_artifact(resp)
    state, detail, obs = _execute_and_classify(artifact, protocol, mode, docker_image)
    record = {
        "task_id": protocol["task_id"],
        "family": protocol["family"],
        "model": model.name,
        "elicitation": elicitation,
        "sample": sample,
        "prompt": prompt,
        "first_pass": {
            "state": state,
            "extractor_flags": flags,
            "artifact": artifact,
            "artifact_sha256": (hashlib.sha256(artifact.encode("utf-8")).hexdigest()
                                if artifact else None),
            "observations": _slim_obs(obs),
            "detail": detail,
        },
        "repairs": {},
    }
    return record


def run_repair(model, protocol, record, condition, k, mode="local",
               docker_image=None, e2_template="roleplay"):
    """ """
    fp = record["first_pass"]
    rounds = [{"round": 0, "state": fp["state"], "artifact": fp["artifact"],
               "observations": fp["observations"], "detail": fp["detail"],
               "extractor_flags": fp["extractor_flags"]}]
    cur_artifact, cur_obs = fp["artifact"], fp["observations"]
    cur_state, cur_detail = fp["state"], fp["detail"]
    regression_events = []

    for r in range(1, k + 1):
        if cur_state == "S5":
            break
        if condition == "C1":
            prompt = build_elicitation_prompt(protocol, record["elicitation"], e2_template)
        else:
            if cur_artifact is None:
                break  #
            prompt = build_repair_prompt(condition, protocol, cur_artifact,
                                         cur_obs, cur_state, cur_detail)
        resp = model.chat(prompt, key=(protocol["task_id"], record["elicitation"],
                                       condition, r))
        artifact, flags = extract_artifact(resp)
        state, detail, obs = _execute_and_classify(artifact, protocol, mode, docker_image)
        prev_state = cur_state
        rounds.append({"round": r, "state": state, "artifact": artifact,
                       "observations": _slim_obs(obs), "detail": detail,
                       "extractor_flags": flags})
        if is_regression(prev_state, state):
            regression_events.append({"round": r, "from": prev_state, "to": state})
        cur_artifact, cur_obs = artifact, obs
        cur_state, cur_detail = state, detail

    if condition == "C1":
        #
        final_state = max((rd["state"] for rd in rounds),
                          key=lambda s: {"S0": 0, "S1": 1, "S2": 2, "S3": 3,
                                         "S4": 4, "S5": 5}.get(s, -1))
    else:
        final_state = rounds[-1]["state"]

    return {"rounds": rounds, "final_state": final_state,
            "regression_events": regression_events}


def run_task(model, protocol, elicitations, n_samples, repair_conditions, k,
             mode="local", docker_image=None, e2_template="roleplay"):
    """ """
    records = []
    for el in elicitations:
        for s in range(n_samples):
            record = run_first_pass(model, protocol, el, s, mode, docker_image,
                                    e2_template)
            if should_repair(record["first_pass"]["state"]):
                for cond in repair_conditions:
                    if cond == "C0":
                        continue
                    record["repairs"][cond] = run_repair(
                        model, protocol, record, cond, k, mode, docker_image,
                        e2_template)
            records.append(record)
    return records
