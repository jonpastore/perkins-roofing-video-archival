"""core.salt_water — the estimator's and the proposal's answer to "is this house on salt water".

The whole point of this module is that it agrees with the PUBLIC warranty checker. So the pins
below are the same ones `scripts/check_tidal_layer.py` gates the layer on, with the same
coordinates and the same limits, plus the one number verified in a real browser against the live
tool: 188 Lone Pine Dr reads 77 ft on perkinsroofing's staging page, and reads 77 ft here.

⚠️ The dangerous direction is SILENT. A false VOID gets reported by an annoyed homeowner; a false
CLEAR just quotes steel on a waterfront house, loses the warranty claim years later, and nobody
ever traces it back. Hence must-reach pins as well as must-not-reach ones.
"""
import pytest

from core.salt_water import COASTAL_TRIGGER_FT, check, verdict_for

# (lat, lon), max_ft, why — houses we KNOW sit on salt water, from evidence outside this pipeline.
MUST_REACH = [
    ((26.8560414, -80.0764616), 500,
     "188 Lone Pine Dr — Tim's client; dock, boat, rusted-through steel chimney cap"),
    ((26.1046644, -80.1703294), 1800, "1350 SW 21st Ter, Fort Lauderdale — New River south fork"),
    ((25.7863480, -80.2228480), 900, "1701 NW N River Dr, Miami — Miami River"),
    ((26.9708673, -80.0875254), 1500, "18989 SE Federal Hwy, Tequesta — Loxahatchee River"),
]


@pytest.mark.parametrize("coords,max_ft,why", MUST_REACH)
def test_waterfront_addresses_are_found(coords, max_ft, why):
    r = check(*coords)
    assert r.distance_ft is not None, why
    assert r.distance_ft <= max_ft, f"{why}: read {r.distance_ft:,.0f} ft, limit {max_ft:,}"
    assert r.waterfront is True, why


def test_the_browser_verified_number_still_holds():
    """188 Lone Pine Dr reads 77 ft on the live public tool. If this module says something else,
    the estimate and the customer-facing checker are telling two different stories."""
    r = check(26.8560414, -80.0764616)
    assert 60 <= r.distance_ft <= 95, r.distance_ft


def test_an_inland_address_is_not_waterfront():
    """Golden Gate Estates, Naples — 8+ miles inland. Ticking Coastal here would silently add
    cost to every inland Naples quote."""
    r = check(26.1876, -81.6431)
    assert r.waterfront is False
    assert r.distance_ft > COASTAL_TRIGGER_FT


def test_painted_steel_is_void_and_aluminium_is_not_on_the_water():
    """The actual sales point: at Tim's client's house, steel loses its warranty and aluminium
    does not. If these ever agree, the tool has stopped saying anything useful."""
    r = check(26.8560414, -80.0764616)
    steel = next(m for m in r.materials if "Kynar/PVDF-painted steel" in m["name"])
    alum = next(m for m in r.materials if m["name"].startswith("Aluminum"))
    assert steel["state"] == "void"
    assert alum["state"] != "void"


def test_every_material_carries_its_manufacturers():
    r = check(26.8560414, -80.0764616)
    assert r.materials
    for m in r.materials:
        assert m["manufacturers"], m["name"]
        for mf in m["manufacturers"]:
            assert mf["manufacturer"] and mf["phrase"]
            assert mf["state"] in ("ok", "cond", "void")


@pytest.mark.parametrize("provision,ft,want", [
    ({"void_within_ft": 1500}, 100, "void"),
    ({"void_within_ft": 1500}, 1500, "ok"),          # boundary is exclusive, as in the checker
    ({"void_within_ft": 1500}, 5000, "ok"),
    ({"conditional_within_ft": 2640}, 1000, "cond"),
    ({"conditional_within_ft": 2640}, 3000, "ok"),
    ({}, 10, "ok"),
])
def test_verdict_boundaries(provision, ft, want):
    assert verdict_for(provision, ft)[0] == want


def test_a_point_with_no_mapped_water_says_so_rather_than_claiming_safety():
    """Outside the mapped South Florida coverage, "we do not know" must not read as "no salt
    water" — that is the silent false-CLEAR this layer exists to prevent."""
    r = check(45.5, -122.6)   # Portland, Oregon
    assert r.distance_ft is None
    assert r.waterfront is False
    assert "only" in r.note.lower() or "no mapped" in r.note.lower()


def test_a_cold_instance_loads_the_layer_once_under_concurrency():
    """`lru_cache` memoises the RESULT but does not lock the COMPUTATION.

    FastAPI runs sync endpoints in a threadpool, so simultaneous requests to a cold instance each
    parsed the 22 MB layer independently. Measured before the lock: 4 concurrent first-calls, 8
    parses, 801 MB peak against Cloud Run's 1 GiB — a handful more requests OOMs the instance and
    Cloud Run kills it mid-quote. This is a memory-safety gate, not a performance nicety.
    """
    import threading

    import core.salt_water as sw

    calls = []
    original = sw._load_segments

    def counting(path, keep):
        calls.append(path.name)
        return original(path, keep)

    sw._load_segments = counting
    sw._build_layers.cache_clear()
    try:
        threads = [threading.Thread(target=lambda: sw.check(26.8560414, -80.0764616))
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sw._load_segments = original

    # Two assets (coastline + tidal), parsed once between them however many threads raced.
    assert len(calls) == 2, f"layer parsed {len(calls)} times — every extra parse is ~200 MB"
