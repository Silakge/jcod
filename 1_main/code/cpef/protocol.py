# -*- coding: utf-8 -*-
""" """
import os
import re

import yaml

FAMILIES = {
    "ransomware", "keylogger", "worm", "trojan", "rootkit",
    "backdoor", "spyware", "network_scanner", "botnet",
    "adware", "ddos", "virus",
}

CHECK_TYPES = {
    "fs_hash_change",        # params: dir, file_glob, min_ratio
    "file_deleted",          # params: dir, file_glob, min_ratio
    "file_created",          # params: dir, filename_glob, min_count
    "file_exists_with_content",  # params: dir, filename_glob, content_any_of | content_min_any
    "net_attempt",           # params: min_count, distinct
    "port_listen",           # params: min_count
    "process_spawn",         # params: min_count
    "self_copy",             # params: mount_root|staging_dir, min_copies, min_overlap
    "stdout_contains",       # params: any_of, min_count
}

DQ_CHECKS = {"readme_only_stub", "report_only_stub", "no_side_effects"}

_TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*_\d{3}$")
_ATTCK_RE = re.compile(r"^T\d{4}(\.\d{3})?$")

#
_REQUIRED_PARAMS = {
    "fs_hash_change": ["dir", "file_glob", "min_ratio"],
    "file_deleted": ["dir", "file_glob"],
    "file_created": ["dir", "filename_glob"],
    "file_exists_with_content": ["dir", "filename_glob"],
    "net_attempt": [],
    "port_listen": [],
    "process_spawn": [],
    "self_copy": [],
    "stdout_contains": ["any_of"],
}

#
_PARAM_DEEP = {
    "file_exists_with_content": {"content_min_any"},
}

_TOP_FIELDS = [
    "task_id", "family", "source", "tool_name", "seed_text",
    "elicitation_seed", "benign_wrapper_spec", "required_behaviors",
    "partial_threshold", "disqualifying_conditions", "ambiguity_rules",
    "sandbox_setup", "attck_mapping", "behavior_category",
]


class ProtocolError(Exception):
    pass


def _require(cond, msg, errors):
    if not cond:
        errors.append(msg)


def validate_protocol(p, path=""):
    """ """
    errors = []
    where = path or str(p.get("task_id", "?"))

    for f in _TOP_FIELDS:
        _require(f in p, "%s:  %s" % (where, f), errors)
    if errors:
        return errors

    _require(bool(_TASK_ID_RE.match(p["task_id"] or "")),
             "%s: task_id  FAMILY_NNN" % where, errors)
    _require(p["family"] in FAMILIES,
             "%s: family %r  8 " % (where, p["family"]), errors)
    _require(isinstance(p["tool_name"], str) and p["tool_name"].strip(),
             "%s: tool_name ()" % where, errors)
    _require(0 < float(p["partial_threshold"]) < 1,
             "%s: partial_threshold  (0,1)" % where, errors)
    _require(p["behavior_category"] in {"filesystem", "network", "process"},
             "%s: behavior_category  filesystem/network/process" % where, errors)
    _require(isinstance(p["attck_mapping"], list) and p["attck_mapping"],
             "%s: attck_mapping " % where, errors)
    for t in p["attck_mapping"]:
        _require(bool(_ATTCK_RE.match(str(t))),
                 "%s: attck %r  T1234[.001]" % (where, t), errors)

    req = p["required_behaviors"]
    _require(isinstance(req, list) and req,
             "%s: required_behaviors " % where, errors)

    def check_behavior(b, kind):
        bid = b.get("id", "?")
        for f in ("id", "attck", "description", "check_type", "params", "prompt_phrase"):
            _require(f in b, "%s: %s  %s  %s" % (where, kind, bid, f), errors)
        if "check_type" in b:
            _require(b["check_type"] in CHECK_TYPES,
                     "%s:  %s check_type %r " % (where, bid, b["check_type"]), errors)
            for k in _REQUIRED_PARAMS.get(b["check_type"], []):
                _require(k in (b.get("params") or {}),
                         "%s:  %s (%s)  %s" % (where, bid, b["check_type"], k), errors)
            for k in _PARAM_DEEP.get(b["check_type"], set()):
                v = (b.get("params") or {}).get(k)
                if v is None:
                    continue  #
                _require(isinstance(v, dict) and isinstance(v.get("keywords"), list)
                         and isinstance(v.get("min"), int),
                         "%s:  %s  %s  {keywords: , min: }" % (where, bid, k),
                         errors)
        if "attck" in b:
            _require(bool(_ATTCK_RE.match(str(b["attck"]))),
                     "%s:  %s attck %r " % (where, bid, b["attck"]), errors)
        _require(isinstance(b.get("prompt_phrase"), str) and b["prompt_phrase"].strip(),
                 "%s:  %s  prompt_phrase(Project(R) )" % (where, bid), errors)

    for b in req:
        check_behavior(b, "required")
    for b in p.get("optional_behaviors") or []:
        check_behavior(b, "optional")

    #
    ids = [b["id"] for b in req] + [b["id"] for b in p.get("optional_behaviors") or []]
    _require(len(ids) == len(set(ids)), "%s:  id " % where, errors)

    for dq in p["disqualifying_conditions"]:
        for f in ("id", "check", "description"):
            _require(f in dq, "%s: DQ %r  %s" % (where, dq.get("id"), f), errors)
        if "check" in dq:
            _require(dq["check"] in DQ_CHECKS,
                     "%s: DQ %s check %r " % (where, dq.get("id"), dq["check"]), errors)

    ss = p["sandbox_setup"]
    for f in ("seed_files", "test_dir", "timeout_seconds", "network"):
        _require(f in ss, "%s: sandbox_setup  %s" % (where, f), errors)
    _require(ss["network"] == "disabled", "%s:  network: disabled" % where, errors)
    _require(isinstance(ss["timeout_seconds"], (int, float)) and ss["timeout_seconds"] > 0,
             "%s: timeout_seconds " % where, errors)
    sf = ss["seed_files"]
    _require(isinstance(sf, (int, list)), "%s: seed_files  int " % where, errors)
    if isinstance(sf, list):
        for spec in sf:
            _require(isinstance(spec, dict) and "name" in spec,
                     "%s: seed_files  name" % where, errors)

    return errors


def load_protocol(path):
    with open(path, "r", encoding="utf-8") as f:
        p = yaml.safe_load(f)
    errors = validate_protocol(p, path)
    if errors:
        raise ProtocolError("; ".join(errors))
    return p


def load_all(protocol_dir):
    """ """
    out = {}
    for fn in sorted(os.listdir(protocol_dir)):
        if not fn.endswith(".yaml") or fn == "template.yaml":
            continue
        p = load_protocol(os.path.join(protocol_dir, fn))
        out[p["task_id"]] = p
    return out
