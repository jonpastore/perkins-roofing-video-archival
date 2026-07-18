"""Prod e2e: verify the deployed low-slope boundary fix + CompanyCam webhook fail-closed.
Mints a transient admin custom token -> ID token -> hits prod API -> deletes the smoke user.
"""
import json
import urllib.error
import urllib.request

import firebase_admin
from firebase_admin import auth, credentials

PROJECT = "video-archival-and-content-gen"
API_KEY = "AIzaSyAUybRX1XK6thj4hQDWLKEcZwpH1Uxi0CQ"
API = "https://api-jnr6bsxyea-uc.a.run.app"
UID = "smoke-lowslope-e2e"

firebase_admin.initialize_app(
    credentials.Certificate("/home/jon/.config/gcloud/perkins-deploy-sa.json"),
    {"projectId": PROJECT},
)


def _call(method, url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


custom = auth.create_custom_token(UID, {"role": "admin"}).decode()
st, res = _call("POST", f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={API_KEY}",
                {"Content-Type": "application/json"}, {"token": custom, "returnSecureToken": True})
if st != 200:
    print("TOKEN EXCHANGE FAILED", st, res); raise SystemExit(1)
H = {"Authorization": f"Bearer {res['idToken']}", "Content-Type": "application/json"}

try:
    # CompanyCam webhook must be deployed + fail closed (no secret configured -> 503)
    st_cc, _ = _call("POST", f"{API}/companycam/webhook", {"Content-Type": "application/json", "X-CompanyCam-Signature": "bad"},
                     {"type": "photo.created", "payload": {"id": "x"}})
    print(f"[companycam webhook] status={st_cc}  (expect 503 fail-closed unconfigured)")

    # What low-slope systems are priced in prod?
    st_r, rates = _call("GET", f"{API}/estimator/rates?branch=miami&region=FBC", H)
    low = rates.get("low_slope_roof_types") or []
    print(f"[rates] status={st_r}  low_slope_roof_types={low}  pending={rates.get('low_slope_pending')}")

    # Quote a GRANULAR low-slope key — old Literal would pydantic-422 this; new boundary accepts it.
    test_rt = low[0] if low else "tpo_adhered"
    st_q, q = _call("POST", f"{API}/estimator/quote", H,
                    {"branch": "miami", "code_zone": "FBC", "roof_type": test_rt,
                     "slope_type": "sloped", "num_squares": 10.0, "deck_type": "existing_concrete"})
    print(f"[quote] roof_type={test_rt}  status={st_q}")
    if st_q == 200:
        print(f"   slope_type={q.get('slope_type')} (expect low_slope)  project_total={q.get('project_total')}")
    else:
        d = str(q.get("detail"))
        pyd = "roof_type" in d and ("permitted" in d or "Input should be" in d)
        print(f"   detail={d[:180]}")
        print(f"   -> pydantic-enum-rejection? {pyd}  (must be False — boundary accepts granular keys)")
finally:
    auth.delete_user(UID)
    print("[cleanup] smoke user deleted")
