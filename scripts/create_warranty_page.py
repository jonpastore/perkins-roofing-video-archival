"""Create (or update) the Metal Roofing Warranty page on staging with the checker
shortcode + placeholder ELI5/TL;DR/deep-specs content (real content comes from Josh)."""
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from adapters import wordpress as wp  # noqa: E402

TITLE = "Metal Roofing Warranty"

PLACEHOLDER = (
    '<!-- PLACEHOLDER CONTENT — replace with Josh\'s copy. Structure is intentional: '
    'ELI5 + TL;DR up top for homeowners, deep technical specs at the bottom. -->\n'

    '<h2>In Plain English (ELI5)</h2>\n'
    '<div style="background:#f7f8fa;border:1px dashed #cbd5e1;border-radius:10px;padding:16px 18px;margin:12px 0">'
    '<p><em>[Placeholder — Josh\'s ELI5 copy goes here.]</em> If your home is near the ocean, salt in '
    'the air can eat away at a metal roof. Some metals hold up right on the water; others lose their '
    'manufacturer warranty if they\'re installed too close. This page helps you figure out which metal '
    'roof is safe for your address — check yours with the tool below.</p></div>\n'

    '<h2>TL;DR</h2>\n'
    '<div style="background:#f7f8fa;border:1px dashed #cbd5e1;border-radius:10px;padding:16px 18px;margin:12px 0">'
    '<ul>'
    '<li><em>[Placeholder — Josh\'s TL;DR bullets go here.]</em></li>'
    '<li>Aluminum (Kynar/PVDF) is the coastal choice — warrantied even beachfront, usually with a '
    'twice-yearly fresh-water rinse.</li>'
    '<li>Painted and bare steel warranties are often <strong>void</strong> within ~1,500 ft to ½ mile '
    'of salt or brackish water — brand-dependent.</li>'
    '<li>Tidal/brackish canals count as salt water. Use the checker below for your exact address.</li>'
    '</ul></div>\n'

    '<h2>Check Your Address</h2>\n'
    '<p>Enter your South Florida address to see which metal roofing materials keep their manufacturer '
    'warranty valid at your distance from salt water:</p>\n'
    '[metal_warranty_checker]\n'

    '<h2>Deep Technical Specifications</h2>\n'
    '<div style="background:#f7f8fa;border:1px dashed #cbd5e1;border-radius:10px;padding:16px 18px;margin:12px 0">'
    '<p><em>[Placeholder — Josh\'s deep technical content goes here: per-manufacturer coastal warranty '
    'provisions, coating specs (PVDF/FEVE, ZM90+/AZ50/AZ55), setback distances, rinse/maintenance '
    'requirements, substrate and fastener detail, HVHZ/FBC notes, and source warranty documents.]</em></p>'
    '</div>\n'
)

existing = wp.find_page_by_title(TITLE)
if existing:
    wp.update_page(
        page_id=existing, title=TITLE, html=PLACEHOLDER,
        meta_description="Check which metal roofing materials keep their manufacturer warranty valid "
                         "at your South Florida address, based on distance to salt water.",
        jsonld=[], status="publish",
        focus_keyword="metal roofing warranty",
    )
    print(f"UPDATED page id={existing}")
else:
    pid = wp.create_page(
        title=TITLE, html=PLACEHOLDER,
        meta_description="Check which metal roofing materials keep their manufacturer warranty valid "
                         "at your South Florida address, based on distance to salt water.",
        jsonld=[], status="publish",
        focus_keyword="metal roofing warranty",
    )
    print(f"CREATED page id={pid}")
