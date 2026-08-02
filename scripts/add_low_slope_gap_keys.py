"""Add #417's low-slope keys to each branch's ACTIVE pricing config, as a new version.

WHY A SCRIPT AND NOT A MIGRATION. pricing_configs rows are application data, not schema, and they
are immutable-versioned: you never UPDATE a config, you insert the next version and move the
is_active pointer. A migration would also re-run on every replay (the runner has no ledger),
minting a new version each time.

WHAT IT ADDS. Only keys the engine gained in #417 and that no config carries yet:
  trash_chute_sections_per_story / trash_chute_per_section   (G6)
  cover_board_oh_adder / cover_board_deck_types              (G7)
  polyglass_warranty_upgrades                                (G8)
  detail_items                                               (G10)
  silicone_addons                                            (G13)

BRANCH SPLIT. Only `detail_items` differs, and only on two entries — Tim's overhead tabs give a
Jupiter and a Miami column. Each branch's own config carries its own values; there is no
branch-keyed map inside a config, because pricing_configs is already keyed by branch.

⚠️ NAPLES has no column in Tim's sheet. It gets Jupiter's numbers, which is what every other key
already does (all three configs are byte-identical today) — but it is an assumption, not his data.

PRICE IMPACT, measured against prod before writing this (2026-08-02):
  Of 101 estimates, ZERO are low_slope, ZERO use a densdeck deck, ZERO are 3-5 storey.
  So no existing quote changes. Two of these keys fire automatically once present — the cover
  board (+$40/sq OH on a densdeck deck) and the chute sections (+$900 on a 3-5 storey job) — and
  both are Tim's own stated rules. Everything else is opt-in and cannot move a price by itself.

Reversible: re-activate the prior version (its row is never modified).

    python scripts/add_low_slope_gap_keys.py --check     # report only, writes nothing
    python scripts/add_low_slope_gap_keys.py --apply
"""
import argparse
import json
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

# Shared by every branch.
COMMON = {
    "trash_chute_sections_per_story": 3,
    "trash_chute_per_section": 100,
    "cover_board_oh_adder": 40,
    "cover_board_deck_types": ["tpo_wood_densdeck_iso"],
    "polyglass_warranty_upgrades": {
        "polyfresko_20yr": 80,
        "sav_plus_2ply": 65,
        "sav_plus_3ply_25yr": 175,
        "polyfresko_sav_plus_30yr": 315,
    },
    "silicone_addons": {"granules": 50, "traffic_coat_1coat": 225, "tpo_primer": 25},
}

# Jupiter column of the overhead-tab detail list.
_DETAIL_JUPITER = {
    "penetration_flashing": 70,
    "l_metal_galv_10ft": 85,
    "term_bar_counter_flashing_10ft": 90,
    "scupper_drain_detail": 350,
    "alum_coping_cap_10ft": 250,
    "third_ply_sav_fr_20yr": 25,
    "additional_demo_layer": 35,
    "flashing_valley_metal_oh_per_lf": 2.30,
}
# Miami differs on exactly two entries.
_DETAIL_MIAMI = {**_DETAIL_JUPITER, "penetration_flashing": 75, "third_ply_sav_fr_20yr": 43}

DETAIL_BY_BRANCH = {
    "jupiter": _DETAIL_JUPITER,
    "miami": _DETAIL_MIAMI,
    "naples": _DETAIL_JUPITER,  # assumption — no Naples column exists
}


def _new_config(raw: dict, branch: str) -> dict:
    out = json.loads(json.dumps(raw))  # deep copy; never mutate the row we read
    ls = out.setdefault("low_slope", {})
    ls.update(json.loads(json.dumps(COMMON)))
    ls["detail_items"] = dict(DETAIL_BY_BRANCH[branch])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write; otherwise report only")
    args = ap.parse_args()

    from apply_migrations_adc import CONN, _password
    from google.cloud.sql.connector import Connector

    from core.pricing_config import compute_hash

    connector = Connector()
    conn = connector.connect(CONN, "pg8000", user="app", password=_password(), db="perkins")
    cur = conn.cursor()
    cur.execute("SET app.tenant_id = '1'")
    cur.execute("SELECT id, branch, version, config FROM pricing_configs "
                "WHERE is_active ORDER BY branch")
    rows = cur.fetchall()

    for cfg_id, branch, version, raw in rows:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if branch not in DETAIL_BY_BRANCH:
            print(f"SKIP    {branch}: no detail-item column defined")
            continue

        new_cfg = _new_config(raw, branch)
        if new_cfg == raw:
            print(f"NOCHANGE {branch} v{version}: keys already present")
            continue

        added = sorted(set(new_cfg["low_slope"]) - set((raw.get("low_slope") or {})))
        if not args.apply:
            print(f"WOULD ADD {branch} v{version} -> v{version + 1}: {', '.join(added)}")
            continue

        new_hash = compute_hash(new_cfg)
        # Deferred unique index allows both rows to be active inside the transaction.
        cur.execute("UPDATE pricing_configs SET is_active = false WHERE id = %s", (cfg_id,))
        cur.execute(
            "INSERT INTO pricing_configs "
            "(tenant_id, branch, version, label, config, config_hash, is_active, created_by) "
            "VALUES (1, %s, %s, %s, %s, %s, true, %s) RETURNING id, version",
            (branch, version + 1, "#417 low-slope gap keys", json.dumps(new_cfg),
             new_hash, "jon@perkinsroofing.net"),
        )
        new_id, new_ver = cur.fetchone()
        conn.commit()
        print(f"APPLIED {branch}: v{version} -> v{new_ver} (id={new_id}) "
              f"hash={new_hash[:16]}... added: {', '.join(added)}")

    conn.close()
    connector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
