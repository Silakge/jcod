# -*- coding: utf-8 -*-
"""LlamaGuard-7B on v13 INPUTS (3 turns/seed) and OUTPUTS (final artifacts
of the 4 main-framework models). 'unsafe' = flagged. GPU 0."""
import json, os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

ROOT = "/data1/syh/jailbreak_code_untar_1/jailbreak_code"
TURNS = os.path.join(ROOT, "new_gpt2", "code", "turns160.json")
OUT = os.path.join(ROOT, "new_gpt2", "Detector", "results")
MODEL = "/data1/syh/Model/llama/llamaguard-7b"

tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16,
                                             device_map="cuda:0")
model.eval()

def moderate(text):
    chat = [{"role": "user", "content": (text or "")[:6000]}]
    inp = tok.apply_chat_template(chat, tokenize=True, return_tensors="pt",
                                  return_dict=True).to(model.device)
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=20, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inp["input_ids"].shape[1]:],
                      skip_special_tokens=True).strip()

def is_unsafe(v):
    s = (v or "").lower()
    return s.startswith("unsafe") or ("unsafe" in s and "safe" not in s.replace("unsafe", ""))

# ---- INPUT side: the three turns per seed ----
turns_map = json.load(open(TURNS, encoding="utf-8"))
rows = []
for i, (tid, v) in enumerate(sorted(turns_map.items())):
    rec = {"task_id": tid}
    for j, t in enumerate(v["turns"][:3]):
        verdict = moderate(t)
        rec["v_t%d" % (j + 1)] = verdict[:120]
        rec["f_t%d" % (j + 1)] = bool(is_unsafe(verdict))
    rows.append(rec)
    if (i + 1) % 40 == 0:
        print("inputs [%d/160]" % (i + 1), flush=True)
json.dump(rows, open(os.path.join(OUT, "llamaguard_inputs_turns.json"), "w"), indent=1)
for j in (1, 2, 3):
    n = sum(1 for r in rows if r["f_t%d" % j])
    print("INPUT t%d flagged: %d/160" % (j, n))

# ---- OUTPUT side: final artifacts per model ----
for m in ("gemini31", "gpt4o", "qwen", "claude45"):
    src = os.path.join(ROOT, "new_gpt2", "results", "RivetLoop", m, "records.jsonl")
    recs = {}
    for l in open(src, encoding="utf-8"):
        r = json.loads(l); t = r["task_id"]
        if t not in recs or r["level"] == "L5":
            recs[t] = r
    orows = []
    for i, (tid, r) in enumerate(sorted(recs.items())):
        art = r.get("artifact") or ""
        if not art:
            orows.append({"task_id": tid, "flag": False, "verdict": "(no artifact)"})
            continue
        verdict = moderate(art)
        orows.append({"task_id": tid, "flag": bool(is_unsafe(verdict)),
                      "verdict": verdict[:120]})
        if (i + 1) % 40 == 0:
            print("%s [%d/160]" % (m, i + 1), flush=True)
    n = sum(1 for r in orows if r["flag"])
    json.dump(orows, open(os.path.join(OUT, "llamaguard_output_%s.json" % m), "w"), indent=1)
    print("OUTPUT %s flagged: %d/160" % (m, n), flush=True)
print("done")
