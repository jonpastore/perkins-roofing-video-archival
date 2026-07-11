#!/usr/bin/env python3
"""Knowify read-only bulk importer — pulls all data via the Knowify v2 REST API.

Requires a token from knowify_oauth.py (read-only scopes). Auto-refreshes the
access token when expired. Writes one JSON file per entity to OUT_DIR plus a
summary of record counts. Read-only: this tool never POSTs/PUTs to the API.

    python scripts/knowify/knowify_oauth.py     # once, to log in
    python scripts/knowify/knowify_pull.py       # pull everything
    python scripts/knowify/knowify_pull.py invoices clients   # subset
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.knowify.com/v2"
TOKEN_URL = "https://developers-v2.knowify.com/oauth/token"
UA = "perkins-knowify-importer/1.0"
CFG = os.path.expanduser("~/.config/knowify/tokens.json")
OUT_DIR = os.environ.get("KNOWIFY_OUT", "/tmp/knowify_data")

ENTITIES = [
    "invoices", "clients", "projects", "bills", "payments", "milestones",
    "items", "purchases", "purchase-items", "time-entries", "contracts",
    "documents", "vendors", "submittals", "assets", "list-items",
    "resources", "departments", "service-tickets", "tickets",
    "allocations", "billables", "aia-invoices", "users",
]


def _load():
    if not os.path.exists(CFG):
        sys.exit("No token — run: python scripts/knowify/knowify_oauth.py")
    return json.load(open(CFG))


def _save(tok):
    json.dump(tok, open(CFG, "w"), indent=1)
    os.chmod(CFG, 0o600)


def _refresh(tok):
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        "client_id": tok["client_id"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json", "User-Agent": UA})
    new = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    tok["access_token"] = new["access_token"]
    if new.get("refresh_token"):
        tok["refresh_token"] = new["refresh_token"]
    _save(tok)
    return tok


def _get(path, tok, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + tok["access_token"],
        "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode()), tok
    except urllib.error.HTTPError as e:
        if e.code == 401 and tok.get("refresh_token"):
            tok = _refresh(tok)
            return _get(path, tok, params)
        raise


def _records(resp):
    """Extract the record list + any next-page cursor from an unknown-shape response."""
    if isinstance(resp, list):
        return resp, None
    if isinstance(resp, dict):
        for key in ("data", "results", "items", "records"):
            if isinstance(resp.get(key), list):
                nxt = (resp.get("meta") or {}).get("next") or (resp.get("links") or {}).get("next") \
                    or resp.get("next") or resp.get("next_cursor")
                return resp[key], nxt
    return [], None


def pull(entity, tok):
    all_rows, page, cursor, limit = [], 1, None, 100
    while True:
        params = {"cursor": cursor} if cursor else {"page": page, "limit": limit}
        resp, tok = _get("/" + entity, tok, params)
        rows, nxt = _records(resp)
        all_rows.extend(rows)
        if nxt and isinstance(nxt, str):
            cursor = nxt.split("cursor=")[-1] if "cursor=" in nxt else nxt
            continue
        if not rows or len(rows) < limit:
            break
        page += 1
        time.sleep(0.2)
    return all_rows, tok


def main():
    tok = _load()
    os.makedirs(OUT_DIR, exist_ok=True)
    which = [a for a in sys.argv[1:] if not a.startswith("-")] or ENTITIES
    summary = {}
    for e in which:
        try:
            rows, tok = pull(e, tok)
            json.dump(rows, open(os.path.join(OUT_DIR, e + ".json"), "w"), indent=1, default=str)
            summary[e] = len(rows)
            print(f"  {e:16s} {len(rows):6d} records")
        except urllib.error.HTTPError as ex:
            summary[e] = f"HTTP {ex.code}"
            print(f"  {e:16s} ERROR HTTP {ex.code}")
        except Exception as ex:  # noqa: BLE001
            summary[e] = "err:" + type(ex).__name__
            print(f"  {e:16s} ERROR {type(ex).__name__}: {str(ex)[:80]}")
    json.dump(summary, open(os.path.join(OUT_DIR, "_summary.json"), "w"), indent=1)
    print(f"\nWrote {OUT_DIR}/ (one file per entity + _summary.json)")


if __name__ == "__main__":
    main()
