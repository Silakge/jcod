import json, os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

OUT = "new_gpt2/Detector/results"
tok = AutoTokenizer.from_pretrained("openai-community/gpt2")
model = AutoModelForCausalLM.from_pretrained("openai-community/gpt2",
                                             torch_dtype=torch.float16, device_map="cuda:0")
model.eval()

def ppl(text):
    ids = tok(text, return_tensors="pt", truncation=True, max_length=1024).input_ids.to(model.device)
    if ids.shape[1] < 2: return float("inf")
    with torch.no_grad():
        out = model(ids, labels=ids)
    return torch.exp(out.loss).item()

benign = json.load(open(os.path.join(OUT, "benign_200_v2.json")))
scores = [round(ppl(t), 3) for t in benign]
json.dump(scores, open(os.path.join(OUT, "ppl_benign_200_v2.json"), "w"))

s = sorted(scores)
print("benign-v2: p50=%.1f p90=%.1f p95=%.1f max=%.1f" % (s[100], s[180], s[190], s[-1]))
for TH in (21.3, 30.0, 50.0):
    n = sum(1 for x in scores if x > TH)
    print(">%.1f: %d/200 (%.1f%%)" % (TH, n, 100*n/200))
