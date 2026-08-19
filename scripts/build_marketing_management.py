#!/usr/bin/env python3
"""Thursday addendum — styled to match the 15 August partnership (Noto Sans / LibreOffice)."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "DeGenito-Perkins-Marketing-Management-2026-08.pdf"
LOGO = ROOT / "degenito-mark.png"
FONT_DIR = Path("/usr/share/fonts/truetype/noto")

pdfmetrics.registerFont(TTFont("NotoSans", str(FONT_DIR / "NotoSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("NotoSans-Bold", str(FONT_DIR / "NotoSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("NotoSans-Italic", str(FONT_DIR / "NotoSans-Italic.ttf")))
pdfmetrics.registerFont(TTFont("NotoSans-BoldItalic", str(FONT_DIR / "NotoSans-BoldItalic.ttf")))
pdfmetrics.registerFontFamily(
    "NotoSans",
    normal="NotoSans",
    bold="NotoSans-Bold",
    italic="NotoSans-Italic",
    boldItalic="NotoSans-BoldItalic",
)

# Sampled from DeGenito-Perkins-Partnership-Proposal-2026-08.pdf
NAVY = colors.Color(11 / 255, 58 / 255, 91 / 255)          # #0B3A5B
TEAL = colors.Color(20 / 255, 136 / 255, 176 / 255)         # #1488B0
INK = colors.Color(26 / 255, 26 / 255, 26 / 255)            # #1A1A1A
MUTED = colors.Color(90 / 255, 101 / 255, 112 / 255)        # #5A6570
ROW = colors.Color(244 / 255, 248 / 255, 250 / 255)         # #F4F8FA
BORDER = colors.Color(197 / 255, 213 / 255, 222 / 255)      # #C5D5DE
DEC = colors.Color(230 / 255, 243 / 255, 248 / 255)         # light teal, on-palette
FOOT = colors.Color(120 / 255, 128 / 255, 136 / 255)
ML, MR = 0.70 * inch, 0.70 * inch
PW = letter[0] - ML - MR


def S():
    b = getSampleStyleSheet()
    return {
        "kicker": ParagraphStyle(
            "kicker", parent=b["Normal"], fontName="NotoSans-Bold", fontSize=8.5,
            textColor=TEAL, spaceAfter=6, leading=11, tracking=0.4,
        ),
        "title": ParagraphStyle(
            "title", parent=b["Title"], fontName="NotoSans-Bold", fontSize=22,
            textColor=INK, alignment=TA_LEFT, spaceAfter=4, leading=26,
        ),
        "sub": ParagraphStyle(
            "sub", parent=b["Normal"], fontName="NotoSans", fontSize=12,
            textColor=NAVY, spaceAfter=8, leading=16,
        ),
        "h1": ParagraphStyle(
            "h1", parent=b["Heading1"], fontName="NotoSans-Bold", fontSize=13,
            textColor=NAVY, spaceBefore=8, spaceAfter=1, leading=16,
        ),
        "body": ParagraphStyle(
            "body", parent=b["Normal"], fontName="NotoSans", fontSize=9,
            textColor=INK, leading=12.2, alignment=TA_JUSTIFY, spaceAfter=5,
        ),
        "rec": ParagraphStyle(
            "rec", parent=b["Normal"], fontName="NotoSans", fontSize=9,
            textColor=INK, leading=12.2, alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "cell", parent=b["Normal"], fontName="NotoSans", fontSize=7.8,
            textColor=INK, leading=10.4,
        ),
        "cellb": ParagraphStyle(
            "cellb", parent=b["Normal"], fontName="NotoSans-Bold", fontSize=7.8,
            textColor=colors.white, leading=10.4,
        ),
        "cellm": ParagraphStyle(
            "cellm", parent=b["Normal"], fontName="NotoSans", fontSize=8.5,
            textColor=INK, leading=11.2,
        ),
        "axis": ParagraphStyle(
            "axis", parent=b["Normal"], fontName="NotoSans", fontSize=7,
            textColor=MUTED, spaceAfter=8, leading=9, tracking=1.2,
        ),
        "src": ParagraphStyle(
            "src", parent=b["Normal"], fontName="NotoSans-Italic", fontSize=7.5,
            textColor=MUTED, leading=10, spaceAfter=6,
        ),
        "disc": ParagraphStyle(
            "disc", parent=b["Normal"], fontName="NotoSans-Italic", fontSize=8,
            textColor=MUTED, leading=11, spaceBefore=8,
        ),
        "help": ParagraphStyle(
            "help", parent=b["Normal"], fontName="NotoSans-Italic", fontSize=7.2,
            textColor=MUTED, leading=9.4, spaceBefore=2, spaceAfter=8,
        ),
        "oneline": ParagraphStyle(
            "oneline", parent=b["Normal"], fontName="NotoSans", fontSize=9,
            textColor=INK, leading=12, alignment=TA_LEFT,
        ),
    }


class NumberedCanvas(pdfcanvas.Canvas):
    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            _chrome(self, n)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)


def _chrome(c, n_pages):
    w, h = letter
    c.saveState()
    c.setFillColor(MUTED)
    c.setFont("NotoSans", 8)
    c.drawString(ML, h - 0.42 * inch, "DeGenito.AI  ·  Perkins Roofing")
    c.setFillColor(TEAL)
    c.setFont("NotoSans-Bold", 8)
    c.drawRightString(w - MR, h - 0.42 * inch, "CONFIDENTIAL")
    c.setStrokeColor(TEAL)
    c.setLineWidth(1.1)
    c.line(ML, h - 0.50 * inch, w - MR, h - 0.50 * inch)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.line(ML, 0.48 * inch, w - MR, 0.48 * inch)
    c.setFillColor(FOOT)
    c.setFont("NotoSans", 8)
    c.drawString(ML, 0.32 * inch, "degenito.ai  ·  +1 (561) 465-6666  ·  jon@degenito.ai")
    c.drawRightString(w - MR, 0.32 * inch, f"Page {c._pageNumber} of {n_pages}")
    c.restoreState()


def hr():
    t = Table([[""]], colWidths=[PW])
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, TEAL),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("LEFTPADDING", (0, 0), (-1, 0), 0),
        ("RIGHTPADDING", (0, 0), (-1, 0), 0),
    ]))
    return t


def navy_tbl(rows, widths, highlight=None):
    t = Table(rows, colWidths=widths, repeatRows=1)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ]
    hi = set(highlight or ())
    for i in range(1, len(rows)):
        if i in hi:
            cmds.append(("BACKGROUND", (0, i), (-1, i), DEC))
        elif i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), ROW))
    t.setStyle(TableStyle(cmds))
    return t


def meta_tbl(rows, widths):
    t = Table(rows, colWidths=widths)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("BACKGROUND", (0, 0), (0, -1), ROW),
    ]
    t.setStyle(TableStyle(cmds))
    return t


class HelpIcon(Flowable):
    """Circled-i. Busy copy lives in the footnote, not on the page."""

    def __init__(self, size=11):
        super().__init__()
        self.size = size
        self.width = size + 2
        self.height = size

    def draw(self):
        s = self.size
        self.canv.setStrokeColor(TEAL)
        self.canv.setFillColor(colors.white)
        self.canv.setLineWidth(1)
        self.canv.circle(s / 2, s / 2, s / 2 - 0.6, stroke=1, fill=1)
        self.canv.setFillColor(TEAL)
        self.canv.setFont("NotoSans-Bold", s - 4)
        self.canv.drawCentredString(s / 2, 2.1, "i")


def P(text, st):
    return Paragraph(text, st)


def section(story, s, title):
    story.append(P(title, s["h1"]))
    story.append(hr())


def build():
    s = S()
    c, cb, cm = s["cell"], s["cellb"], s["cellm"]
    story = []

    # ----- Cover (matches partnership page 1) -----
    if LOGO.exists():
        img = Image(str(LOGO), width=2.15 * inch, height=2.15 * inch * (309 / 625))
        img.hAlign = "LEFT"
        story.append(img)
        story.append(Spacer(1, 4))
    story.append(P("THE AXIS OF INTELLIGENCE", s["axis"]))
    story.append(P("CONFIDENTIAL  ·  THURSDAY ADDENDUM", s["kicker"]))
    story.append(P("Marketing Management", s["title"]))
    story.append(P("$1,000 / month, one company. The 15 August partnership is unchanged.", s["sub"]))

    meta = [
        [P("<b>Prepared for</b>", cm),
         P("Tim Kanak — Jupiter  ·  Marco Castillo — Miami  ·  Josh Kaufman — Miami  ·  Chris Young — Naples", cm)],
        [P("<b>Prepared by</b>", cm),
         P("Jonathan Pastore  ·  DeGenito Innovations, LLC (DeGenito.AI)", cm)],
        [P("<b>Date</b>", cm), P("August 20, 2026  ·  discuss Thursday afternoon with the 15 August partnership", cm)],
        [P("<b>Contact</b>", cm), P("jon@degenito.ai  ·  +1 (561) 465-6666  ·  degenito.ai", cm)],
        [P("<b>Properties</b>", cm),
         P("App.PerkinsRoofing.net (factory, quotes, reporting)  ·  Crm.PerkinsRoofing.net (GHL)  ·  Staging.PerkinsRoofing.net", cm)],
    ]
    story.append(meta_tbl(meta, [1.45 * inch, PW - 1.45 * inch]))
    story.append(Spacer(1, 12))

    sku = [
        [P("<b>The ask</b>", cb), P("<b>Amount</b>", cb)],
        [P("Marketing Management — one company (this sheet)", c), P("$1,000 / mo", c)],
        [P("AI SEM — already in the 15 August partnership", c), P("$200 / mo / branch  ·  $600 at three live offices", c)],
        [P("Shown appointments — already in the partnership", c), P("$100 / show  ·  DeGenito Facebook campaign", c)],
        [P("SEO / AIO  ·  app + socials — already in the partnership", c), P("$799 / mo  ·  $999 / mo", c)],
        [P("Media", c), P("Each live office’s card  ·  unmarked  ·  seasonal + growth caps below", c)],
        [P("New public site", c), P("$0  ·  gift  ·  unchanged", c)],
    ]
    story.append(navy_tbl(sku, [4.15 * inch, PW - 4.15 * inch]))
    story.append(P("The 15 August partnership PDF is not amended. This addendum sits next to it.", s["disc"]))

    # ----- 1. The offer -----
    story.append(PageBreak())
    section(story, s, "1. The offer")
    story.append(P(
        "<b>$1,000 / month Marketing Management, Perkins Roofing Corp., one invoice.</b> "
        "That is ChatGPT Ads, Google Business Profile / Maps, $30–$50 / day reel boosts, "
        "seasonal and growth caps, A/B, and reporting in the app. "
        "The partnership’s <b>$200 / mo / branch AI SEM</b> stays exactly as emailed — "
        "that is the license to the engine we built. We do not fold IP into this line and give it away. "
        "Franchisees, when they exist, are your ~8% and your lead routing. We still bill one company "
        "for this $1,000. $200 / branch follows the live offices already in the partnership.",
        s["rec"],
    ))
    lines = [
        [P("<b>Line</b>", cb), P("<b>Amount</b>", cb), P("<b>What it is</b>", cb)],
        [P("Marketing Management — one company", c), P("<b>$1,000 / mo</b>", c),
         P("The week: ChatGPT, GBP/Maps, reel-boost ops, seasonal + growth caps, A/B, Friday numbers in the app. New. Not in the 15 August sheet.", c)],
        [P("AI SEM — already in the partnership", c), P("<b>$200 / mo / branch</b>", c),
         P("Unchanged. Jupiter, Miami, Naples as each is live ($600 at three). Engine IP. We do not reopen or discount this.", c)],
        [P("Social posting / Clip Studio / comments", c), P("Already in <b>$999</b>", c),
         P("The app already runs the socials. Boost spend is new; posting is not.", c)],
        [P("SEO / AIO factory", c), P("Already in <b>$799</b>", c),
         P("Pages feed ChatGPT and Maps citations. People ask AI who to hire; the factory is how we get named.", c)],
        [P("DeGenito Facebook appointments", c), P("<b>$100 / shown</b>", c),
         P("Already in the partnership. Our campaign. GHL = Showed or Completed. Not inside the $1,000.", c)],
        [P("Media", c), P("As in the partnership", c),
         P("Each live office’s card, unmarked. Caps in §4–5. We never hold spend.", c)],
        [P("Already paid", c), P("$4,500 setup + creative", c),
         P("Not billed again. GHL is already stood up.", c)],
        [P("Franchise offices", c), P("<b>$0 from us</b> on this line", c),
         P("You charge ~8%. You route leads. This $1,000 does not become a file per franchisee.", c)],
    ]
    story.append(navy_tbl(lines, [2.05 * inch, 1.45 * inch, PW - 3.5 * inch]))

    section(story, s, "2. Soft start — first ads, then the calendar")
    story.append(P(
        "Perkins has never bought ads. Three to five shown appointments a week is the year-one exit, "
        "not week one, and not Christmas week. Low dollars until tracking, negatives, and a written "
        "cost/show exist. After day 90 the year-one calendar in §4 takes over.",
        s["body"],
    ))
    ph = [
        [P("<b>Window</b>", cb), P("<b>On</b>", cb), P("<b>Office media</b>", cb), P("<b>Expectation</b>", cb)],
        [P("Days 0–14", c),
         P("GBP / Maps. Apply ChatGPT Ads. Google Search Broward: brand + repair. Bing import. Engine live ($200 / live branch).", c),
         P("Google $40–60 / day<br/>Bing $10–15 / day<br/>≈ $1,500–$2,250 / mo", c),
         P("Tracking live. 1–3 shown / week possible. No boosts yet.", c)],
        [P("Days 15–45", c),
         P("Add $30–50 / day reel boosts on winning Clip Studio cuts — IG, TikTok, YouTube, Facebook. ChatGPT if approved.", c),
         P("+ $900–$1,500 boosts<br/>ChatGPT $10–20 / day once live", c),
         P("Climb toward 3 shown / week. Kill a placement with 14 days and no attributable call.", c)],
        [P("Days 45–90", c),
         P("Scale only the channel with a written cost/show. No Miami-Dade or Naples ads until that writing exists.", c),
         P("Hold, or +20% on the winner only", c),
         P("3–5 shown / week is the year-one gate, not a December promise.", c)],
    ]
    story.append(navy_tbl(ph, [0.95 * inch, 2.45 * inch, 1.7 * inch, PW - 5.1 * inch]))
    story.append(Spacer(1, 6))
    story.append(P(
        "Planning month in the middle of days 15–45: <b>about $2,400–$3,600 media</b> plus "
        "<b>$1,000</b> management plus <b>$200 × live branches</b> plus $100 × our Facebook shows. "
        "Fees do not move when we cut December. Media does move when a second market earns the right.",
        s["body"],
    ))

    # ----- 3. Competitive -----
    story.append(PageBreak())
    section(story, s, "3. Competitive analysis — agencies and private equity")
    story.append(P(
        "A percent-of-spend agency makes more when the budget goes up — including a loud December. "
        "A PE-backed roofer in Miami-Dade / Broward is a different animal: they will pay $40–$80 a click "
        "and $7,000–$15,000 a month in one metro to own the auction. Matching them dollar-for-dollar "
        "is how independents go broke. Beating them on cost per shown appointment is how you stay "
        "independent — and become something a buyer actually wants.",
        s["body"],
    ))
    story.append(P(
        "Google Ads management in 2026: <b>10–20% of spend</b> (street 15–20%) or <b>$500–$2,500 flat</b>, "
        "specialist floors $750–$1,500, mid desks $1,500–$2,500. Roofing shops: 15–20% with a "
        "$500–$1,000 minimum; Facebook management another $500–$1,500; full-service retainers "
        "<b>$2,500–$8,000 / month in fees, on top of media</b>.",
        s["body"],
    ))
    story.append(P(
        "Sources: ClicksGeek, Lotiva, Catmo 2026 Google Ads surveys; Inshalytics roofing agency cost, June 2026.",
        s["src"],
    ))
    why = [
        [P("<b>Shop</b>", cb), P("<b>What they sell</b>", cb),
         P("<b>Fees at $3k media</b>", cb), P("<b>Fees at $8k / PE month</b>", cb),
         P("<b>They win when…</b>", cb)],
        [P("Typical PPC % shop", c),
         P("15–20% of spend, $500–$1,000 floor.", c),
         P("$1,000 floor", c),
         P("$1,200–$1,600", c),
         P("The budget goes up. December stays loud.", c)],
        [P("Roofing full-service agency", c),
         P("$2,500–$8,000 retainer. New portal.", c),
         P("$2,500–$8,000 + media", c),
         P("Same retainer + they ask for more media", c),
         P("You stay on the retainer.", c)],
        [P("PE-backed competitor (the auction, not a vendor)", c),
         P("$7–15k / mo / metro. CPC $25–50 replacement, $40–80 storm.", c),
         P("They ignore a $3k shop", c),
         P("They set the floor you pay", c),
         P("You try to outspend them.", c)],
        [P("WebPower (what you had)", c),
         P("$2,295 hosting, topics, GMB. Not paid media.", c),
         P("$2,295, no ads", c),
         P("$2,295, no ads", c),
         P("The site stays up.", c)],
        [P("<b>This addendum</b>", c),
         P("<b>$1,000 management. $200 / branch already in the partnership. $100 only when our FB campaign shows.</b>", c),
         P("<b>$1,000 + $200 × live branches</b>", c),
         P("<b>Same fees</b> at 2.5× spend and at a December cut", c),
         P("<b>Cost/show falls. December is cut. Year two is earned.</b>", c)],
    ]
    story.append(navy_tbl(why, [1.25 * inch, 1.7 * inch, 1.3 * inch, 1.4 * inch, PW - 5.65 * inch]))
    story.append(Spacer(1, 8))

    section(story, s, "4. What PE-competitive markets actually cost")
    pe = [
        [P("<b>Signal</b>", cb), P("<b>Independent / national</b>", cb), P("<b>PE / South Florida metro</b>", cb), P("<b>What we do</b>", cb)],
        [P("Google Search spend / market", c),
         P("$1,500–$5,000 / mo typical", c),
         P("$7,000–$15,000 / mo. Tampa case: $7k to ~30 quality calls.", c),
         P("Start $1.5–2.2k Search+Bing. Step only with a written cost/show.", c)],
        [P("Non-brand CPL", c),
         P("$124 average (SearchLight, 15 contractors, Q1 2026, $310k spend)", c),
         P("$150–$250+ when PE and storm bids stack", c),
         P("We manage to shown appointment, not a cheap form fill.", c)],
        [P("Replacement CPC", c),
         P("$22–$42 typical converting terms", c),
         P("$40–$50+ in Dallas / Phoenix / Atlanta-class metros; FL storm $40–$80", c),
         P("Brand defense stays cheap. Do not buy vanity keywords PE is defending.", c)],
        [P("Marketing as % of revenue", c),
         P("5–10% established; 8–12% home services", c),
         P("12–15% in knife-fight metros. PE platforms spend to buy share, not CPA.", c),
         P("We spend less than PE and keep more of each job. Capacity is the cap, not the auction.", c)],
        [P("$5M+ regional shop", c),
         P("$10,000–$30,000 / mo all marketing (Cider House 2026)", c),
         P("Plus LSA + PMax + brand conquest on every branch", c),
         P("Year-five media in our plan is still ~$12–17k / mo — on purpose.", c)],
    ]
    story.append(navy_tbl(pe, [1.35 * inch, 1.85 * inch, 1.9 * inch, PW - 5.1 * inch]))
    story.append(Spacer(1, 4))
    story.append(P(
        "Sources: SearchLight roofing Google Ads CPL Q1 2026; Riverstone 2026 roofing PPC "
        "(converting CPC $22–$42, metro $25–$50); Cider House roofing marketing cost, July 2026 "
        "($1.5–10k+ Google, $80+ CPC on hot terms, $10–30k / mo at $5M+); Best Roofer Marketing "
        "Tampa $7k / mo to ~30 calls; Boomcycle / WebFX home-services 8–15% of revenue in competitive markets; "
        "LocaliQ 2025 roofing CPL ~$79 category, Search much higher on non-brand.",
        s["src"],
    ))
    story.append(P(
        "Read that against a percent shop. At PE-month spend of $12,000, 15% is <b>$1,800</b> — "
        "and they will tell you to stay there in December. We still bill $1,000 + $200 / live branch "
        "and we cut the card. That is cost control. It is also how you do not train a buyer to see "
        "a business that only works when the auction is on fire.",
        s["body"],
    ))
    stacked = [
        [P("<b>Line</b>", cb), P("<b>Stacked shop</b>", cb), P("<b>This stack (partnership + addendum)</b>", cb)],
        [P("AI / Google ads management", c), P("$1,000 min or 15–20% of spend", c), P("$200 / branch — already in the partnership", c)],
        [P("Marketing management (Maps, ChatGPT, boosts, caps, A/B)", c), P("Inside a $2,500–$8,000 retainer, or missing", c), P("<b>$1,000 / mo, one company — this sheet</b>", c)],
        [P("Factory + app + socials", c), P("Usually a second vendor", c), P("$799 + $999 — already in the partnership", c)],
        [P("<b>Fees before a dollar of media</b>", c), P("<b>$2,250–$8,000+</b>", c), P("<b>$1,000 + $200 × branches + $799 + $999</b> (at 3 branches: $3,598)", c)],
    ]
    story.append(navy_tbl(stacked, [2.2 * inch, 2.3 * inch, PW - 4.5 * inch]))

    # ----- 5. Calendar -----
    section(story, s, "5. Year-one calendar — seasonal, then it grows")
    story.append(P(
        "Florida is not Ohio, and it is not flat. Hurricane window is 1 June–30 November. "
        "December is the low. A percent shop and a PE platform both have reasons to keep spending. "
        "We do not. The calendar below is year one on one live market. The right-hand column is "
        "what that same month looks like in year two <b>only if</b> year one wrote a cost/show "
        "and a second geo is on a written go. No second market, no second spend.",
        s["body"],
    ))
    cal = [
        [P("<b>Month</b>", cb), P("<b>Season</b>", cb), P("<b>Y1 media (1 market)</b>", cb),
         P("<b>Y2 media if 2nd market earned</b>", cb), P("<b>What we protect</b>", cb)],
        [P("Sep 2026", c), P("Ramp / late storm", c), P("$2,400–$3,600", c),
         P("— (still Y1)", c), P("Learn. Broward only.", c)],
        [P("Oct 2026", c), P("Storm peak", c), P("$3,000–$3,600", c),
         P("—", c), P("Repair + insurance. Kill waste weekly.", c)],
        [P("Nov 2026", c), P("Winds down", c), P("$2,400–$2,800", c),
         P("—", c), P("Do not spend October dollars in November.", c)],
        [P("<b>Dec 2026</b>", c), P("<b>LOW</b>", c), P("<b>$900–$1,200</b>", c),
         P("—", c), P("<b>Brand + leak only. Boosts off. ~$2k banked for March.</b>", c)],
        [P("Jan 2027", c), P("Still slow", c), P("$1,400–$1,800", c),
         P("—", c), P("Cheaper CPCs. No fake New Year blast.", c)],
        [P("Feb 2027", c), P("HOA / spring", c), P("$2,000–$2,400", c),
         P("Gate: written Y1 cost/show?", c), P("Metal A/B returns. Decide Miami.", c)],
        [P("Mar–May 2027", c), P("Spring", c), P("$3,000–$3,400 / mo", c),
         P("If go: + $2,500–$4,000 Miami (PE-aware)", c), P("December’s unspent dollars belong here.", c)],
        [P("Jun–Jul 2027", c), P("Hurricane open", c), P("$3,400–$3,800 / mo", c),
         P("Two-market $6,500–$9,000 / mo", c), P("Crew capacity is the limit, not the ad account.", c)],
        [P("Aug–Oct 2027", c), P("Peak / Y2 starts", c), P("$3,600–$4,200 / mo", c),
         P("Two-market $7,500–$11,000 / mo", c), P("Daily storm cap. Kill the week if cost/show blows.", c)],
        [P("Nov–Dec 2027", c), P("Wind down + LOW", c), P("Nov $2.4–2.8k · Dec $0.9–1.2k", c),
         P("Nov $4.5–5.5k · <b>Dec $1.8–2.4k</b>", c), P("December still cuts, from a bigger run-rate. Every year.", c)],
    ]
    story.append(navy_tbl(cal, [0.95 * inch, 1.05 * inch, 1.35 * inch, 1.8 * inch, PW - 5.15 * inch], highlight={4}))
    story.append(Spacer(1, 6))
    story.append(P(
        "Year-one media on one market: about <b>$32,000–$38,000</b>. "
        "A “stay visible” $3,200 through Dec/Jan wastes <b>$4,000–$6,000</b> in the trough. "
        "Year-two media, two markets, still cutting December: about <b>$70,000–$95,000</b> — "
        "that is growth, and it is still under one PE metro ($84,000–$180,000 at $7–15k × 12). "
        "We do not open Miami because the calendar flipped. We open Miami because Broward "
        "has a written cost/show and a crew that can take the work.",
        s["body"],
    ))
    story.append(P(
        "Sources for the shape: NOAA Atlantic hurricane season (1 Jun–30 Nov); "
        "JobNimbus winter playbooks (Nov–Dec scale back, keep leak terms); "
        "WebFX 2025–26 home-services seasonality (replacement-cost queries trough in December). "
        "South Florida is flatter than the Midwest and still not flat in the holidays. "
        "Y2 Miami dollars assume PE-competitive CPC, not a copy of Broward’s year-one rate.",
        s["src"],
    ))
    inn = [
        [P("<b>In $200 / branch (partnership)</b>", cb), P("<b>In $1,000 Marketing Management</b>", cb), P("<b>Not either</b>", cb)],
        [P("The engine: constraints, negatives, geos, bids, Bing import, conversion import. Runs in December at $50/day the same as June at $150/day.", c),
         P("ChatGPT Ads, GBP/Maps, reel-boost ops, seasonal + growth caps, A/B, Friday numbers. The week.", c),
         P("Ad spend. Semrush. CallRail. $799 factory. $999 app hours. Tim’s YouTube replies. A second $1,000 per franchisee. Guaranteed 3–5 shows the week of Christmas.", c)],
    ]
    story.append(KeepTogether([
        P("Where the numbers live", s["h1"]),
        hr(),
        P(
            "Spend, the seasonal cap, the growth gate, A/B (brand vs metal), boosts, "
            "CallRail to GHL to shown, cost per show — all of it comes back into "
            "<b>app.perkinsroofing.net</b>. Friday is a view. Same login as the estimator, "
            "the archive, Clip Studio, and Tim’s comment inbox. That is the asset: one operating "
            "system a buyer can underwrite. Franchise later still logs in here. "
            "We do not become twelve QuickBooks customers.",
            s["body"],
        ),
        navy_tbl(inn, [PW / 3, PW / 3, PW / 3]),
    ]))

    # ----- 6. Five-year -----
    section(story, s, "6. Five-year plan — build something you can sell if you want")
    story.append(P(
        "We do not have your P&amp;L on this page, so we will not invent revenue. "
        "The plan is in units we can both count: shown appointments, live markets, "
        "whether you are still on every estimate, and whether a buyer sees a system or a founder. "
        "Sold dollars and EBITDA are your close rate and your crews. Marketing’s job is a "
        "repeatable, off-season-aware engine those numbers can sit on.",
        s["body"],
    ))
    story.append(P(
        "Most roofing companies still sell at <b>2–5× EBITDA</b> (median near 3.3×). "
        "That is a founder with a truck. Companies in the $3–10M revenue band with transferable "
        "ops land <b>5–7×</b>. Above $10M with growth, <b>7–9×</b>. Private equity pays "
        "<b>6–9×</b> almost only at <b>$3M+ EBITDA</b> with management depth. "
        "Storm-chase revenue is discounted to <b>2.5–3.5×</b> because it is not repeatable. "
        "The two highest-leverage moves on the multiple: <b>get the owner off sales</b>, "
        "and <b>show systems a stranger can run</b> — estimator, CRM, lead engine, Friday numbers. "
        "That is this app. That is why this $1,000 is not a campaign. It is the habit that makes "
        "the company worth more than Tim.",
        s["body"],
    ))
    story.append(P(
        "Sources: Profitability Partners roofing valuation 2026 (4–9×; &lt;$3M rev 3–5×, $3–10M 5–7×, "
        "$10M+ 7–9×); Auxo Capital 2026 bands ($1.5–3M EBITDA 4.5–6.5×, $3–7.5M 5.5–8×); "
        "Legacy ETA 2026 (median completed deal ~3.3×; PE 6–9× at $3M+ EBITDA); "
        "CTA / Peak 2026 (storm-chase 2.5–3.5×; commercial-maintenance +0.5–0.8 turns).",
        s["src"],
    ))
    yrs = [
        [P("<b></b>", cb), P("<b>Year 1</b><br/>to Aug 2027", cb),
         P("<b>Year 2</b>", cb), P("<b>Year 3</b>", cb), P("<b>Years 4–5</b>", cb)],
        [P("<b>Live markets</b>", c),
         P("Broward. Miami brand-only if needed.", c),
         P("Miami full, if Y1 cost/show is written.", c),
         P("Naples + first franchisee routed at your 8%.", c),
         P("3 company branches + N franchisees.", c)],
        [P("<b>Shown / week (exit rate)</b>", c),
         P("3–5. Ramp from 1–3.", c),
         P("7–10 company.", c),
         P("10–15 company, plus routed franchise leads.", c),
         P("15–22 company. Franchise book separate.", c)],
        [P("<b>Media (year)</b>", c),
         P("$32–38k. Dec cut.", c),
         P("$70–95k. Two PE-aware metros. Dec still cuts.", c),
         P("$100–140k. Third geo + franchise support, not PE vanity.", c),
         P("$150–200k. Still under one PE platform’s three-metro burn (~$250–540k).", c)],
        [P("<b>$200 / branch</b>", c),
         P("1–2 live.", c),
         P("2.", c),
         P("3 company.", c),
         P("3 company. Franchisees are your royalty, not our SKU.", c)],
        [P("<b>What a buyer sees</b>", c),
         P("First paid engine. App is the books for marketing.", c),
         P("Second market clone. Playbook, not a heroics week.", c),
         P("Owner off a share of estimates. Maria / GHL / estimator run the day.", c),
         P("Royalty + systems + retail mix. Not a storm-chase tape.", c)],
        [P("<b>Multiple you are building toward</b>", c),
         P("Still founder-weighted. Do not shop it.", c),
         P("Leaving 3× territory if the books are clean.", c),
         P("Entering 5–6× if EBITDA is real and you are not the closer.", c),
         P("5.5–8× if $1.5M+ adj. EBITDA and owner-light. 6–9× only if you ever want PE and the earnings are $3M+.", c)],
    ]
    story.append(navy_tbl(yrs, [1.3 * inch, 1.4 * inch, 1.4 * inch, 1.5 * inch, PW - 5.6 * inch]))
    story.append(PageBreak())

    line = Table(
        [[
            P(
                "<b>15–25% more shown appointments a year</b>, gated on crew. "
                "You do not have to sell. You should be able to.",
                s["oneline"],
            ),
            HelpIcon(12),
        ]],
        colWidths=[PW - 18, 16],
    )
    line.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    sig = [[
        P("<b>Tim Kanak</b><br/>Perkins Roofing Corp. · Jupiter<br/><br/>Signature: ______________________________<br/><br/>Date: ______________", cm),
        P("<b>Jonathan Pastore</b><br/>DeGenito Innovations, LLC<br/><br/>Signature: ______________________________<br/><br/>Date: ______________", cm),
    ]]
    story.append(KeepTogether([
        line,
        P(
            "Illustration only — close rate is yours. 4 shown/wk x 48 wks x 25% close x $20k ticket "
            "~ $1.0M incremental. Year-five at 18/wk ~ $4.3M. At 12% EBITDA that is ~$120k vs ~$520k. "
            "3.3x vs 6x on $500k transferable EBITDA is $1.35M of enterprise value.",
            s["help"],
        ),
        P("7. Acceptance", s["h1"]),
        hr(),
        P(
            "Ninety days, then month-to-month on 30 days’ written notice — same spine as the "
            "partnership retainers. December media cuts do not cut the $1,000 or the $200 / branch. "
            "A second market is a written go, not an automatic invoice. Adding a franchisee does not "
            "add a DeGenito $1,000. By signing, Perkins <b>adds</b> Marketing Management at $1,000 / month. "
            "The 15 August partnership is otherwise unchanged: $200 / mo / branch AI SEM, $799, $999, "
            "$4,500 paid, $100 / shown, $0 Astro site, media on each live office’s card. "
            "We do not bill franchisees.",
            s["body"],
        ),
        Spacer(1, 12),
        Table(sig, colWidths=[PW / 2, PW / 2]),
        P("Disclaimers: Partnership Appendix F still applies.", s["disc"]),
    ]))

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=ML,
        rightMargin=MR,
        topMargin=0.68 * inch,
        bottomMargin=0.62 * inch,
        title="DeGenito × Perkins Roofing — Marketing Management — August 2026",
        author="DeGenito.AI",
        creator="Writer",
    )
    doc.build(story, canvasmaker=NumberedCanvas)
    print(OUT)


if __name__ == "__main__":
    build()
