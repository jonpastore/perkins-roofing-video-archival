"""Map an article to a WordPress category (Wendy: articles must be filed under
the existing Roofing/Construction tree, never the default bucket).

Pure: keyword/content → category NAME. The adapter resolves the name to a WP
term id against the live taxonomy. First matching rule wins; ordered most- to
least-specific so e.g. "metal roof repair cost" lands under Roof Repair, not
Materials, when repair intent is present.
"""

# (substring patterns, category name) — names match the live WP taxonomy.
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("inspection",), "Roof Inspections"),
    (("insurance", "claim", "denial", "adjuster"), "Roof Insurance"),
    (("cost", "price", "pricing", "financing", "budget", "estimate", "quote"),
     "Roofing Costs & Financing"),
    (("repair", "leak", "patch"), "Roof Repair"),
    (("replace", "re-roof", "reroof", "re roof", "tear-off", "tear off"), "Roof Replacement"),
    (("maintenance", "maintain", "upkeep", "cleaning"), "Roof Maintenance"),
    (("install", "installation"), "Roof Installation"),
    (("commercial", "tpo", "flat roof", "low-slope", "low slope", "modified bitumen"),
     "Commercial Roofing"),
    (("hurricane", "wind mitigation", "hvhz", "storm", "coastal", "salt"), "Roofing Solutions"),
    (("metal", "aluminum", "steel", "copper", "standing seam", "tile", "shingle",
      "material", "underlayment", "membrane", "polyglass", "galvalume"), "Roofing Materials"),
    (("residential", "home", "house"), "Residential Roofing"),
]
DEFAULT_CATEGORY = "Roofing Insights"


def pick_category_name(keyword: str, content: str = "") -> str:
    """Best category name for an article. Never returns Uncategorized/default WP bucket."""
    hay = f"{keyword} {content}".lower()
    for patterns, name in _RULES:
        if any(p in hay for p in patterns):
            return name
    return DEFAULT_CATEGORY
