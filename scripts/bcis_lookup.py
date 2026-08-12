from playwright.sync_api import sync_playwright
import sys, re
TARGET = sys.argv[1] if len(sys.argv)>1 else "FL30780"
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36")
    pg.goto("https://www.floridabuilding.org/pr/pr_app_srch.aspx", wait_until="domcontentloaded", timeout=60000)
    pg.select_option("#lstCodeVersion_drpCustomDropdown", label="2023"); pg.wait_for_timeout(1200)
    pg.select_option("#lstManufacturer_drpCustomDropdown", value="12519"); pg.wait_for_timeout(1200)
    pg.click("#lnkSearch"); pg.wait_for_load_state("networkidle", timeout=60000); pg.wait_for_timeout(1500)

    link = None
    for a in pg.query_selector_all("a"):
        if a.inner_text().strip().startswith(TARGET):
            link = a; break
    if not link:
        print("link not found for", TARGET); b.close(); sys.exit(1)
    print("clicking:", link.inner_text().strip())
    link.click(); pg.wait_for_load_state("networkidle", timeout=60000); pg.wait_for_timeout(2000)
    print("URL:", pg.url)
    t = pg.inner_text("body")
    # key fields
    for pat in (r"FL\s?#?\s*[:\s]\s*FL\d+[-R\d]*", r"Application Status.*", r"Code Version.*",
                r"Approved Date.*", r"Expiration.*", r"Subcategory.*", r"Compliance Method.*"):
        for m in re.findall(pat, t)[:2]:
            print("  ", m.strip()[:110])
    print("\n--- MODELS / product rows mentioning 150MS or 26 ---")
    for line in t.splitlines():
        L=line.strip()
        if re.search(r"(150MS|26\s?ga|218\.8|MSALL)", L, re.I) and len(L)>4:
            print("   ", L[:140])
    print("\n--- documentation links ---")
    for a in pg.query_selector_all("a[href*='.pdf'], a[href*='Docs']"):
        h=a.get_attribute("href") or ""
        if ".pdf" in h.lower(): print("   ", a.inner_text().strip()[:50], "->", h[:120])
    b.close()
