"""Translate Chinese fields in protocol YAMLs to English using gpt-4o."""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import yaml

KEY = os.environ.get("CPEF_API_KEY", "")
BASE = os.environ.get("CPEF_BASE_URL", "")
PROTO_DIR = "1_main/code/protocols160"

def chat(prompt):
    payload = {"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.1, "max_tokens": 2000}
    req = urllib.request.Request(BASE + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            time.sleep(5 * (a + 1))
    return None

def translate_yaml(fp):
    """Read YAML, translate Chinese fields, write back."""
    with open(fp, encoding='utf-8') as f:
        p = yaml.safe_load(f)
    if not p:
        return fp, False

    changed = False

    # Translate seed_text
    st = p.get('seed_text', '')
    if st and any('\u4e00' <= c <= '\u9fff' for c in st):
        r = chat(f"Translate to English. Output ONLY the translation, nothing else:\n\n{st}")
        if r:
            p['seed_text'] = r
            changed = True

    # Translate benign_wrapper_spec
    bws = p.get('benign_wrapper_spec', '')
    if bws and any('\u4e00' <= c <= '\u9fff' for c in bws):
        r = chat(f"Translate to English. Keep technical terms, file paths, and formatting. Output ONLY the translation:\n\n{bws}")
        if r:
            p['benign_wrapper_spec'] = r
            changed = True

    # Translate required_behaviors descriptions
    for b in p.get('required_behaviors', []):
        for field in ('description', 'prompt_phrase'):
            v = b.get(field, '')
            if v and any('\u4e00' <= c <= '\u9fff' for c in v):
                r = chat(f"Translate to English. Output ONLY the translation:\n\n{v}")
                if r:
                    b[field] = r
                    changed = True

    # Translate optional_behaviors
    for b in p.get('optional_behaviors', []):
        for field in ('description', 'prompt_phrase'):
            v = b.get(field, '')
            if v and any('\u4e00' <= c <= '\u9fff' for c in v):
                r = chat(f"Translate to English. Output ONLY the translation:\n\n{v}")
                if r:
                    b[field] = r
                    changed = True

    if changed:
        with open(fp, 'w', encoding='utf-8') as f:
            yaml.dump(p, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return fp, changed

def main():
    files = sorted(f for f in os.listdir(PROTO_DIR) if f.endswith('.yaml'))
    print(f"Translating {len(files)} YAML files...", flush=True)

    done = 0
    for fn in files:
        fp = os.path.join(PROTO_DIR, fn)
        _, changed = translate_yaml(fp)
        done += 1
        if done % 20 == 0:
            print(f"[{done}/{len(files)}]", flush=True)

    # Count remaining Chinese
    remaining = 0
    for fn in files:
        fp = os.path.join(PROTO_DIR, fn)
        content = open(fp, encoding='utf-8').read()
        if any('\u4e00' <= c <= '\u9fff' for c in content):
            remaining += 1
    print(f"Done. {done} processed, {remaining} still have Chinese.")

if __name__ == '__main__':
    main()
