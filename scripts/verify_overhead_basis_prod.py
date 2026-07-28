"""Prove the branch overhead basis is LIVE in prod: overhead must equal days x branch burn.

A config key the deployed image does not know is silently ignored, so flipping overhead_basis in
the DB proves nothing until the image that reads it is serving. This asserts the arithmetic on a
real quote from the real API, per branch.
"""
import json
import urllib.error
import urllib.request

import firebase_admin
from firebase_admin import auth, credentials

PROJECT = "video-archival-and-content-gen"
API_KEY = "AIzaSyAUybRX1XK6thj4hQDWLKEcZwpH1Uxi0CQ"
API = "https://api-jnr6bsxyea-uc.a.run.app"
UID = "smoke-overhead-basis"
BURN = {"jupiter": 1400.0, "miami": 4250.0, "naples": 1400.0}

firebase_admin.initialize_app(
    credentials.Certificate("/home/jon/.config/gcloud/perkins-deploy-sa.json"),
    {"projectId": PROJECT},
)


def _call(method, url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


custom = auth.create_custom_token(UID, {"role": "admin"}).decode()
st, res = _call(
    "POST",
    f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={API_KEY}",
    {"Content-Type": "application/json"}, {"token": custom, "returnSecureToken": True})
if st != 200:
    print("TOKEN EXCHANGE FAILED", st, res)
    raise SystemExit(1)
H = {"Authorization": f"Bearer {res['idToken']}", "Content-Type": "application/json"}

failures = 0
try:
    for branch, burn in BURN.items():
        st_q, q = _call("POST", f"{API}/estimator/quote", H, {
            "branch": branch, "code_zone": "FBC", "roof_type": "13_tile", "slope_type": "sloped",
            "num_squares": 30.0, "project_kind": "residential", "demo": True,
            "overhead_mode": "daily", "debug": True,
        })
        if st_q != 200:
            print(f"{branch}: HTTP {st_q} {str(q.get('detail'))[:160]}")
            failures += 1
            continue
        oh = next((li for li in q.get("line_items_detail", []) if li["key"] == "overhead"), None)
        if oh is None:
            print(f"{branch}: no overhead line item")
            failures += 1
            continue
        inputs = (oh.get("explain") or {}).get("inputs") or {}
        days = inputs.get("total_days")
        basis = inputs.get("overhead_basis")
        expect = (days or 0) * burn
        ok = basis == "branch" and abs(oh["amount"] - expect) < 0.01
        print(f"{branch:<8} basis={basis!s:<8} days={days} x ${burn:,.0f} = ${expect:,.0f}  "
              f"actual ${oh['amount']:,.2f}  total ${q['project_total']:,.2f}  {'OK' if ok else 'MISMATCH'}")
        failures += 0 if ok else 1
finally:
    auth.delete_user(UID)

raise SystemExit(1 if failures else 0)
