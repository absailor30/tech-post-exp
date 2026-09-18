"""One-off connectivity check for the Vertex AI / Veo service account.

Not part of the production pipeline. Exists purely so a GitHub Actions run
can authenticate with GCP_SA_KEY and confirm, from real Google infrastructure
rather than guesswork, that the key is valid and the project can actually
reach a Veo model before any of this gets wired into autonomous_run.py.

Usage (in Actions): GCP_SA_KEY=<json> GCP_PROJECT=<id> python veo_probe.py
"""

import json
import os
import sys
import tempfile

from google.auth.transport.requests import Request
from google.oauth2 import service_account
import requests

PROJECT = os.environ["GCP_PROJECT"]
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL = os.environ.get("VEO_MODEL", "veo-3.0-generate-001")

# The key never touches disk in the repo checkout -- written to a throwaway
# temp file for the one call that needs a file path, then removed.
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    f.write(os.environ["GCP_SA_KEY"])
    key_path = f.name

def call(url, body):
    r = requests.post(url, headers={"Authorization": f"Bearer {creds.token}",
                                    "Content-Type": "application/json"},
                      data=json.dumps(body), timeout=60)
    print(f"-> HTTP {r.status_code}")
    print(r.text[:1200])
    return r.status_code


try:
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    print("auth: token acquired OK\n")

    # Baseline first: if a plain Gemini text call also 404s, the problem is
    # project/IAM access in general, not Veo specifically -- disambiguates
    # in one run instead of burning another whole Actions round trip.
    print("=== baseline: gemini-2.0-flash-001 generateContent ===")
    gemini_url = (f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
                 f"/locations/{LOCATION}/publishers/google/models/gemini-2.0-flash-001:generateContent")
    gemini_status = call(gemini_url, {"contents": [{"role": "user", "parts": [{"text": "say OK"}]}]})

    print(f"\n=== veo: {MODEL} predictLongRunning ===")
    veo_url = (f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}"
              f"/locations/{LOCATION}/publishers/google/models/{MODEL}:predictLongRunning")
    veo_status = call(veo_url, {
        "instances": [{"prompt": "a calm abstract gold gradient background, slow motion"}],
        "parameters": {"aspectRatio": "9:16", "durationSeconds": 4, "sampleCount": 1}})

    print(f"\nSUMMARY: gemini={gemini_status}  veo={veo_status}")
    if gemini_status < 400 and veo_status < 400:
        print("SUCCESS: both reachable.")
    elif gemini_status < 400 and veo_status >= 400:
        print("Gemini works, Veo specifically does not -- Veo needs separate "
              "allowlisting/enablement, this is not a general IAM problem.")
    else:
        print("Even the baseline Gemini call fails -- this is a general "
              "project/IAM access problem, not something specific to Veo.")
        sys.exit(1)
finally:
    os.unlink(key_path)
