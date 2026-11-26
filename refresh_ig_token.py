"""Keep the Instagram long-lived access token from ever expiring on us again.

Instagram long-lived tokens last ~60 days and can be refreshed for another
~60 days via a dedicated endpoint -- but ONLY while still valid; a token
that has already expired cannot be resurrected this way, it needs a brand
new human login via Meta's Graph API Explorer. So this runs weekly (well
inside the 60-day window) to renew it before that ever happens again, and
writes the new token straight back to the GitHub Actions secret so no
human step is needed in the steady state.

Writing a repo secret needs a token with secret-write permission, which
the default GITHUB_TOKEN Actions gives itself does not have -- hence the
separate GH_SECRETS_PAT (a fine-grained PAT scoped to just this repo's
"Secrets" permission, read/write).

Env required:
  INSTAGRAM_ACCESS_TOKEN  - the current (still valid) long-lived token
  GH_SECRETS_PAT          - PAT with this repo's Actions-secrets write access
  GITHUB_REPOSITORY       - set automatically by Actions ("owner/repo")
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

from nacl import encoding, public

IG_API = "https://graph.instagram.com"


def refresh_token(current_token):
    url = (f"{IG_API}/refresh_access_token?grant_type=ig_refresh_token"
          f"&access_token={current_token}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url)) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        sys.exit(f"refresh failed: HTTP {e.code}: {body}")


def gh_api(method, path, pat, body=None):
    url = f"https://api.github.com{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()) if r.length != 0 else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"GitHub API {method} {path} failed: HTTP {e.code}: {e.read().decode()}")


def encrypt_secret(public_key_b64, secret_value):
    """libsodium sealed box, as required by the GitHub secrets API."""
    pk = public.PublicKey(public_key_b64, encoding.Base64Encoder())
    box = public.SealedBox(pk)
    return base64.b64encode(box.encrypt(secret_value.encode())).decode()


def update_github_secret(repo, pat, name, value):
    key_info = gh_api("GET", f"/repos/{repo}/actions/secrets/public-key", pat)
    encrypted = encrypt_secret(key_info["key"], value)
    gh_api("PUT", f"/repos/{repo}/actions/secrets/{name}", pat, {
        "encrypted_value": encrypted,
        "key_id": key_info["key_id"],
    })


def main():
    current = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()
    pat = os.environ["GH_SECRETS_PAT"]
    repo = os.environ["GITHUB_REPOSITORY"]

    result = refresh_token(current)
    new_token = result.get("access_token")
    if not new_token:
        sys.exit(f"refresh response had no access_token: {result}")
    expires_days = result.get("expires_in", 0) // 86400

    update_github_secret(repo, pat, "INSTAGRAM_ACCESS_TOKEN", new_token)
    print(f"refreshed OK, new token valid ~{expires_days} days, secret updated")


if __name__ == "__main__":
    main()
