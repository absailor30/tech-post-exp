"""Which NVIDIA NIM models answer right now, and how fast? Prints one line per model."""
import json, os, time, urllib.request
from openai import OpenAI

KEY = os.environ["NIM_API_KEY"]
req = urllib.request.Request("https://integrate.api.nvidia.com/v1/models",
                             headers={"Authorization": f"Bearer {KEY}"})
ids = sorted(m["id"] for m in json.loads(urllib.request.urlopen(req, timeout=30).read())["data"])
print(len(ids), "models listed")
want = [i for i in ids if any(k in i for k in ("nemotron", "deepseek", "llama-3.3", "llama-3.1-70b",
        "llama-3.1-405b", "qwen", "mistral-large", "mixtral", "gpt-oss", "kimi", "glm"))]
print("candidates:", want)
c = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=KEY, timeout=45)
for m in ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-super-120b-a12b",
          "deepseek-ai/deepseek-v4-pro", "nvidia/nemotron-3-nano-30b-a3b", *want]:
    if m not in ids and m not in ("nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-super-120b-a12b",
                                  "deepseek-ai/deepseek-v4-pro", "nvidia/nemotron-3-nano-30b-a3b"):
        continue
    t = time.time()
    try:
        r = c.chat.completions.create(model=m, max_tokens=300, temperature=0.2,
                                      messages=[{"role": "user", "content": 'Reply with exactly this JSON and nothing else: {"ok": true}'}])
        txt = r.choices[0].message.content
        print(f"{time.time() - t:5.1f}s  {m}  finish={r.choices[0].finish_reason}  content={(txt or 'NONE')[:60]!r}")
    except Exception as e:
        print(f"{time.time() - t:5.1f}s  {m}  ERROR {str(e)[:110]}")
