"""Playwright visual walk of the admin console as jon@perkinsroofing.net.

Mints a Firebase custom token via the dev SA, exchanges it for an ID token through
the Identity Toolkit REST API, seeds it into the SPA's IndexedDB auth store, reloads
so Firebase picks up the signed-in user, then screenshots every console tab.

Run:
  GOOGLE_APPLICATION_CREDENTIALS=$(scripts/fetch_vertex_sa.sh) \
  .venv/bin/python -m scripts.visual_walk
"""
import json
import os
import time
import urllib.request

import firebase_admin
from firebase_admin import auth as admin_auth
from firebase_admin import credentials
from playwright.sync_api import sync_playwright


def _firebase_web_api_key() -> str:
    """The Firebase Web API key (public by design — it also ships in the SPA bundle as
    VITE_FIREBASE_API_KEY). Read it from the env or web/.env rather than hardcoding it,
    and keep it API-restricted (Identity Toolkit only) in the GCP console."""
    key = os.environ.get("FIREBASE_WEB_API_KEY")
    if key:
        return key
    import pathlib
    env = pathlib.Path(__file__).resolve().parent.parent / "web" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("VITE_FIREBASE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("Set FIREBASE_WEB_API_KEY or web/.env VITE_FIREBASE_API_KEY")


API_KEY = _firebase_web_api_key()
PROJECT = "video-archival-and-content-gen"
APP_URL = os.environ.get("WALK_URL", "https://video-archival-and-content-gen.web.app")
EMAIL = "jon@perkinsroofing.net"
OUT = "/tmp/perkins_walk"

TABS = ["Dashboard", "Search / Ask", "Content Opportunities", "Articles", "FAQ",
        "Email", "Content Scheduling", "Clip Studio", "Video Approval", "Archive",
        "Users", "Config"]


def mint_id_token() -> str:
    cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"projectId": PROJECT})
    # create_custom_token signs LOCALLY with the SA private key (no Auth-admin API call
    # needed). Embed email so the API's effective_role() maps jon to admin (default-admins).
    uid = "jon-visual-walk"
    custom = admin_auth.create_custom_token(
        uid, {"email": EMAIL, "email_verified": True}).decode()

    body = json.dumps({"token": custom, "returnSecureToken": True}).encode()
    req = urllib.request.Request(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={API_KEY}",
        data=body, headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req))
    return uid, resp["idToken"], resp["refreshToken"]


SEED_JS = """
([key, value]) => new Promise((resolve, reject) => {
  const open = indexedDB.open("firebaseLocalStorageDb");
  open.onupgradeneeded = () => open.result.createObjectStore("firebaseLocalStorage", { keyPath: "fbase_key" });
  open.onsuccess = () => {
    const db = open.result;
    const tx = db.transaction("firebaseLocalStorage", "readwrite");
    tx.objectStore("firebaseLocalStorage").put({ fbase_key: key, value });
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
  };
  open.onerror = () => reject(open.error);
})
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    uid, id_token, refresh = mint_id_token()
    now = int(time.time() * 1000)
    key = f"firebase:authUser:{API_KEY}:[DEFAULT]"
    user_val = {
        "uid": uid, "email": EMAIL, "emailVerified": True, "isAnonymous": False,
        "displayName": "Jon Pastore",
        "providerData": [{"providerId": "password", "uid": EMAIL, "displayName": "Jon Pastore",
                          "email": EMAIL, "phoneNumber": None, "photoURL": None}],
        "stsTokenManager": {"refreshToken": refresh, "accessToken": id_token,
                            "expirationTime": now + 3600 * 1000},
        "createdAt": str(now), "lastLoginAt": str(now), "apiKey": API_KEY, "appName": "[DEFAULT]",
    }

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1024})
        page.goto(APP_URL, wait_until="networkidle")
        page.evaluate(SEED_JS, [key, user_val])
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Confirm we're signed in (login button gone / nav present)
        signed_in = page.locator("text=Dashboard").count() > 0
        results.append(("signed_in", signed_in))
        page.screenshot(path=f"{OUT}/00_landing.png", full_page=True)

        for i, tab in enumerate(TABS, 1):
            try:
                loc = page.get_by_role("button", name=tab, exact=True)
                if loc.count() == 0:
                    loc = page.get_by_text(tab, exact=True)
                loc.first.click(timeout=5000)
                page.wait_for_timeout(2500)
                fn = f"{OUT}/{i:02d}_{tab.replace(' ', '_').replace('/', '')}.png"
                page.screenshot(path=fn, full_page=True)
                # crude render check: any error banners?
                errs = page.locator("text=/Error:|Failed to|Could not/i").count()
                results.append((tab, f"ok errs={errs} -> {fn}"))
            except Exception as e:  # noqa: BLE001
                results.append((tab, f"FAIL {type(e).__name__}: {e}"))
        browser.close()

    print(json.dumps({"uid": uid, "results": results}, indent=2))


if __name__ == "__main__":
    main()
