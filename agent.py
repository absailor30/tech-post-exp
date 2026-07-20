"""Supervised micro-business agent — minimal loop.

propose -> human approves -> execute -> log

Provider: NVIDIA NIM (OpenAI-compatible). Secrets live in .env.
Usage:
  python agent.py propose "research 3 blog post ideas for <niche>"
  python agent.py list                 # show pending proposals
  python agent.py approve <id>         # execute an approved proposal
  python agent.py reject <id> "why"
  python agent.py spend                # token/usage summary
  python agent.py publish <image_url> "caption"   # post to Instagram (asks y/N first)
"""

import json, os, sys, uuid, datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

QUEUE = BASE / "proposals.json"
LOG = BASE / "log.jsonl"

MODEL = os.environ.get("NIM_MODEL", "deepseek-ai/deepseek-v4-flash")
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NIM_API_KEY"],
    timeout=120.0,
)

SYSTEM = (
    "You are the working brain of a tiny supervised content micro-business "
    "(budget ~Rs 10,000 total). You only PROPOSE actions; a human approves "
    "anything that spends money or publishes. Be concrete and brief. "
    "Never assume an action was taken until told so."
)


def log(kind, **data):
    data.update(kind=kind, ts=datetime.datetime.utcnow().isoformat())
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")


def load_queue():
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []


def save_queue(q):
    QUEUE.write_text(json.dumps(q, indent=2), encoding="utf-8")


def call_llm(prompt, max_tokens=900, tries=3):
    import time as _time
    last = None
    for attempt in range(tries):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.4,
            )
            u = r.usage
            log("llm_call", model=MODEL, prompt=prompt[:200],
                input_tokens=u.prompt_tokens, output_tokens=u.completion_tokens)
            return r.choices[0].message.content
        except Exception as e:                     # timeout / 5xx / rate limit
            last = e
            _time.sleep(20 * (attempt + 1))
    raise last


def cmd_propose(task):
    out = call_llm(
        f"Task: {task}\n\n"
        "Produce ONE concrete proposal: what to do, why, estimated cost in INR "
        "(0 if none), and the exact deliverable. Under 200 words."
    )
    pid = uuid.uuid4().hex[:6]
    q = load_queue()
    q.append({"id": pid, "task": task, "proposal": out, "status": "pending"})
    save_queue(q)
    log("proposed", id=pid, task=task)
    print(f"[{pid}] PENDING\n\n{out}")


def find(q, pid):
    for p in q:
        if p["id"] == pid:
            return p
    sys.exit(f"no proposal {pid}")


def cmd_approve(pid):
    q = load_queue()
    p = find(q, pid)
    out = call_llm(
        f"This proposal was APPROVED by the human:\n\n{p['proposal']}\n\n"
        "Now produce the full deliverable (draft, plan, or copy). "
        "If the action requires something only a human can do (pay, publish, "
        "create an account), output a precise step-by-step checklist instead."
    , max_tokens=2000)
    p["status"] = "executed"
    p["result"] = out
    save_queue(q)
    log("executed", id=pid)
    print(out)


def cmd_reject(pid, reason=""):
    q = load_queue()
    p = find(q, pid)
    p["status"] = "rejected"
    p["reason"] = reason
    save_queue(q)
    log("rejected", id=pid, reason=reason)
    print(f"[{pid}] rejected")


def cmd_list():
    for p in load_queue():
        print(f"[{p['id']}] {p['status']:9} {p['task'][:70]}")


IG_API = "https://graph.instagram.com/v23.0"


def ig_token():
    return os.environ["INSTAGRAM_ACCESS_TOKEN"]


def cmd_publish(image_url, caption):
    import time, urllib.error, urllib.parse, urllib.request

    def call(url, params, method="POST"):
        data = urllib.parse.urlencode(params).encode()
        if method == "GET":
            url, data = f"{url}?{data.decode()}", None
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data)) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            sys.exit(f"API error {e.code}: {e.read().decode()}")

    print(f"About to publish to Instagram:\n  image:   {image_url}\n  caption: {caption[:200]}")
    if input("Type 'yes' to publish: ").strip().lower() != "yes":
        print("aborted, nothing posted")
        return
    container = call(f"{IG_API}/me/media",
                     {"image_url": image_url, "caption": caption,
                      "access_token": ig_token()})
    for _ in range(6):
        s = call(f"{IG_API}/{container['id']}",
                 {"fields": "status_code", "access_token": ig_token()}, "GET")
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            sys.exit(f"container failed: {s}")
        time.sleep(5)
    result = call(f"{IG_API}/me/media_publish",
                  {"creation_id": container["id"], "access_token": ig_token()})
    log("published", media_id=result["id"], image_url=image_url,
        caption=caption[:200])
    print(f"published, media id {result['id']}")


def cmd_spend():
    inp = out = calls = 0
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            if d["kind"] == "llm_call":
                calls += 1
                inp += d["input_tokens"]
                out += d["output_tokens"]
    print(f"calls={calls}  input_tokens={inp}  output_tokens={out}  (NIM: free tier)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd, rest = args[0], args[1:]
    {"propose": lambda: cmd_propose(rest[0]),
     "approve": lambda: cmd_approve(rest[0]),
     "reject": lambda: cmd_reject(rest[0], rest[1] if len(rest) > 1 else ""),
     "list": cmd_list,
     "spend": cmd_spend,
     "publish": lambda: cmd_publish(rest[0], rest[1])}[cmd]()
