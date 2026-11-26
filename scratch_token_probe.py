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


def call(path):
    url = f"{IG_API}/{path}?fields=id,username&access_token={token}"
    try:
        with urllib.request.urlopen(url) as r:
            print(f"{path}: OK {json.loads(r.read())}")
    except urllib.error.HTTPError as e:
        print(f"{path}: HTTP {e.code} {e.read().decode()}")


call("me")
call(IG_USER_ID)
