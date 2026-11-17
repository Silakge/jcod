# -*- coding: utf-8 -*-
""" """
import csv
import json
import os
import uuid

import yaml


def make_packet(artifact, observations, protocol, state, detail, out_root,
                master_index_path):
    """ """
    packet_id = uuid.uuid4().hex[:12]
    pdir = os.path.join(out_root, packet_id)
    os.makedirs(pdir, exist_ok=True)

    with open(os.path.join(pdir, "artifact.py"), "w", encoding="utf-8") as f:
        f.write(artifact or "")
    with open(os.path.join(pdir, "observations.json"), "w", encoding="utf-8") as f:
        json.dump(observations, f, ensure_ascii=False, indent=1)
    with open(os.path.join(pdir, "protocol.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(protocol, f, allow_unicode=True, sort_keys=False)

    form = {"packet_id": packet_id, "auto_state": None,
            "behaviors": {}}
    for b in protocol["required_behaviors"] + (protocol.get("optional_behaviors") or []):
        r = (detail or {}).get("behavior_results", {}).get(b["id"], {})
        form["behaviors"][b["id"]] = {
            "description": b["description"],
            "evidence": r.get("evidence", ""),
            "decision": "",       #
            "note": "",
        }
    form["final_decision"] = ""   #
    with open(os.path.join(pdir, "form.json"), "w", encoding="utf-8") as f:
        json.dump(form, f, ensure_ascii=False, indent=1)

    header = ["packet_id", "task_id", "model", "elicitation", "condition", "round", "state"]
    header = header + ["sample"]
    new = not os.path.exists(master_index_path)
    with open(master_index_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
    return packet_id


def append_index(master_index_path, packet_id, task_id, model, elicitation,
                 condition, round_, state, sample=None):
    header = ["packet_id", "task_id", "model", "elicitation", "condition",
              "round", "state", "sample"]
    new = not os.path.exists(master_index_path)
    with open(master_index_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow([packet_id, task_id, model, elicitation, condition,
                    round_, state, sample])


def packets_for_record(record, protocol, out_root, master_index_path):
    """ """
    fp = record["first_pass"]
    ids = []
    pid = make_packet(fp["artifact"], fp["observations"], protocol, fp["state"],
                      fp["detail"], out_root, master_index_path)
    append_index(master_index_path, pid, record["task_id"], record["model"],
                 record["elicitation"], "first_pass", 0, fp["state"],
                 sample=record.get("sample"))
    ids.append(pid)
    for cond, traj in record.get("repairs", {}).items():
        for rd in traj["rounds"][1:]:
            pid = make_packet(rd["artifact"], rd["observations"], protocol,
                              rd["state"], rd["detail"], out_root, master_index_path)
            append_index(master_index_path, pid, record["task_id"], record["model"],
                         record["elicitation"], cond, rd["round"], rd["state"],
                         sample=record.get("sample"))
            ids.append(pid)
    return ids
