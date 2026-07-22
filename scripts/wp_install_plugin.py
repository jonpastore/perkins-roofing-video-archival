"""Install (or replace) the Perkins JSON-LD plugin on WordPress via the admin UI with Playwright.

mu-plugins can't be installed over REST, so this logs into wp-admin and uploads the zip. The WP
base URL comes from the admin config (PlatformConfig WP_URL — needs DB_URL/proxy); WP_USER and the
admin LOGIN password come from env (WP_LOGIN_PW / /tmp/wp_login_pw / WP_APP_PWD — creds are key
transport, not config).

Run: .venv/bin/python scripts/wp_install_plugin.py [/path/to/plugin.zip]
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ZIP = sys.argv[1] if len(sys.argv) > 1 else "/tmp/perkins-jsonld.zip"
# WP base URL from the admin config (PlatformConfig WP_URL) — the single runtime source;
# env WP_URL is deliberately not read. Requires DB_URL pointed at the platform DB
# (locally: Cloud SQL proxy on 127.0.0.1:5432).
from adapters.wordpress import resolved_wp_url  # noqa: E402

BASE = resolved_wp_url()
if not BASE:
    sys.exit("PlatformConfig WP_URL is unset (or DB_URL doesn't reach the platform DB) — "
             "start the Cloud SQL proxy and export DB_URL before running this script.")
USER = os.environ["WP_USER"]
_pwfile = Path("/tmp/wp_login_pw")
PW = (os.environ.get("WP_LOGIN_PW")
      or (_pwfile.read_text().strip() if _pwfile.exists() and _pwfile.stat().st_size else None)
      or os.environ["WP_APP_PWD"])


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()

        pg.goto(f"{BASE}/wp-login.php", wait_until="domcontentloaded")
        pg.fill("#user_login", USER)
        pg.fill("#user_pass", PW)
        pg.click("#wp-submit")
        pg.wait_for_load_state("networkidle")
        if "wp-login" in pg.url and "dashboard" not in pg.url:
            # verify we actually reached admin
            pg.goto(f"{BASE}/wp-admin/", wait_until="domcontentloaded")
        if "/wp-admin" not in pg.url:
            print("LOGIN FAILED — still at", pg.url)
            b.close()
            sys.exit(1)
        print("logged in:", pg.url)

        # Upload plugin
        pg.goto(f"{BASE}/wp-admin/plugin-install.php?tab=upload", wait_until="domcontentloaded")
        pg.set_input_files('input[name="pluginzip"]', ZIP)
        pg.click("#install-plugin-submit")
        pg.wait_for_load_state("networkidle")

        body = pg.content().lower()
        # WP shows an "Activate Plugin" link on success, or "already installed"/overwrite prompt
        if "activate plugin" in body:
            pg.click("text=Activate Plugin")
            pg.wait_for_load_state("networkidle")
            print("INSTALLED + ACTIVATED")
        elif "replace current with uploaded" in body or "already installed" in body:
            # overwrite existing
            try:
                pg.click("text=Replace current with uploaded")
                pg.wait_for_load_state("networkidle")
                print("REPLACED existing plugin")
            except Exception:
                print("plugin already installed (no overwrite link)")
        else:
            print("UNEXPECTED result — check page. url:", pg.url)
            print(body[:400])
        b.close()


if __name__ == "__main__":
    main()
