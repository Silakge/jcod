# -*- coding: utf-8 -*-
"""Prompt-Guard-2-22M on v13 INPUTS (3 turns/seed). 0=benign 1=jailbreak.
GPU 0."""
import json, os
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

ROOT = "/data1/syh/jailbreak_code_untar_1/jailbreak_code"
TURNS = os.path.join(ROOT, "new_gpt2", "code", "turns160.json")
OUT = os.path.join(ROOT, "new_gpt2", "Detector", "results")
MODEL = "/data1/syh/Model/llama/Prompt-Guard-2-22M"

tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL, torch_dtype=torch.bfloat16, device_map="cuda:0")
model.eval()

def classify(text):
    ids = tok(text, return_tensors="pt", truncation=True, max_length=2048).to(model.device)
    with torch.no_grad():
        logits = model(**ids).logits[0].float()
    probs = torch.softmax(logits, dim=-1)
    return {"pred": int(logits.argmax()),
            "p_benign": probs[0].item(), "p_jailbreak": probs[1].item()}

turns_map = json.load(open(TURNS, encoding="utf-8"))
rows = []
for i, (tid, v) in enumerate(sorted(turns_map.items())):
    rec = {"task_id": tid}
    for j, t in enumerate(v["turns"][:3]):
        c = classify(t)
        rec["pred_t%d" % (j + 1)] = c["pred"]
        rec["pj_t%d" % (j + 1)] = round(c["p_jailbreak"], 4)
    rows.append(rec)
    if (i + 1) % 40 == 0:
        print("[%d/160]" % (i + 1), flush=True)

json.dump(rows, open(os.path.join(OUT, "promptguard_inputs_turns.json"), "w"), indent=1)
for j in (1, 2, 3):
    n = sum(1 for r in rows if r["pred_t%d" % j] == 1)
    n50 = sum(1 for r in rows if r["pj_t%d" % j] > 0.5)
    print("t%d flagged(default)=%d/128? /160=%d | p>0.5: %d" % (j, n, n, n50))
print("done")
