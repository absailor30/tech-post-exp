"""Throwaway: is '/me' the actual problem with the current token, or is the
token itself still bad? Tests both '/me' and the explicit IG account id
against the same token in one cheap call, instead of guessing via a full
~10min render-and-publish cycle.
"""
import json
import os
import urllib.error
import urllib.request

IG_API = "https://graph.instagram.com/v23.0"
IG_USER_ID = "17841479725757732"
token = os.environ["INSTAGRAM_ACCESS_TOKEN"].strip()


def call(path, use_header=False):
    label = f"{path} ({'Bearer header' if use_header else 'query param'})"
    if use_header:
        url = f"{IG_API}/{path}?fields=id,username"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    else:
        url = f"{IG_API}/{path}?fields=id,username&access_token={token}"
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as r:
            print(f"{label}: OK {json.loads(r.read())}")
    except urllib.error.HTTPError as e:
        print(f"{label}: HTTP {e.code} {e.read().decode()}")


print(f"token length: {len(token)}, starts: {token[:8]}, ends: {token[-4:]}")
call("me")
call(IG_USER_ID)
call("me", use_header=True)
call(IG_USER_ID, use_header=True)
