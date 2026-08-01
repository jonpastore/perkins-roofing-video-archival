"""Commission lever — % of profit vs % of job, with an adjustable rate."""
import json
from core.pricing_config import load_config
from core.estimator import QuoteInput, estimate

CFG = load_config(json.load(open("infra/fixtures/pricing_config_exhibit_b.json")))
BASE = dict(code_zone="FBC", roof_type="13_tile", num_squares=30)


def test_default_commission_is_half_of_net():
    """Tim, 2026-08-02: 50% of net is the default slider position on the profit basis."""
    r = estimate(CFG, QuoteInput(**BASE))
    assert CFG.commission_rate("profit") == 0.50
    assert r["estimated_commission"] == round(r["profit_dollars"] * 0.50, 2)


def test_default_commission_on_gross_is_15pct():
    """...and 15% of gross on the job basis. The RATE follows the basis; the roof is not a term."""
    r = estimate(CFG, QuoteInput(**BASE, commission_basis="job"))
    assert r["estimated_commission"] == round(r["project_total"] * 0.15, 2)


def test_commission_pct_of_profit_override():
    r = estimate(CFG, QuoteInput(**BASE, commission_basis="profit", commission_rate_override=0.30))
    assert r["estimated_commission"] == round(r["profit_dollars"] * 0.30, 2)


def test_commission_pct_of_job():
    r = estimate(CFG, QuoteInput(**BASE, commission_basis="job", commission_rate_override=0.10))
    assert r["estimated_commission"] == round(r["project_total"] * 0.10, 2)
