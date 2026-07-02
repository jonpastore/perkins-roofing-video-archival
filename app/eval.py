"""Eval harness (council requirement). Runs a seed question set against the indexed corpus,
calibrates the abstain threshold (separating answerable vs off-topic by retrieval confidence),
and measures citation + keyword-hit quality. Run: python3 -m app.eval"""
import json, os
from .config import settings
from .retrieval import hybrid_search
from .answer import ask

SEED = os.path.join(os.path.dirname(__file__), "eval_seed.json")

def run():
    qs = json.load(open(SEED))
    ans_conf, off_conf, rows = [], [], []
    for item in qs:
        r = hybrid_search(item["q"], 8)
        top = max((sc for _, sc in r["chunks"]), default=0.0)
        (ans_conf if item["answerable"] else off_conf).append(top)
        rows.append((item, top))

    print("=== retrieval confidence ===")
    print(f"  answerable: min={min(ans_conf):.2f} mean={sum(ans_conf)/len(ans_conf):.2f}")
    print(f"  off-topic:  max={max(off_conf):.2f} mean={sum(off_conf)/len(off_conf):.2f}")

    # calibrate threshold: maximize separation accuracy
    best = (settings.ABSTAIN_THRESHOLD, 0.0)
    for i in range(30, 90):
        t = i / 100.0
        tp = sum(1 for c in ans_conf if c >= t)
        tn = sum(1 for c in off_conf if c < t)
        acc = (tp + tn) / (len(ans_conf) + len(off_conf))
        if acc > best[1]:
            best = (t, acc)
    sth = best[0]
    print(f"\n=== calibration ===")
    print(f"  current threshold: {settings.ABSTAIN_THRESHOLD}")
    print(f"  SUGGESTED threshold: {sth:.2f}  (separation accuracy {best[1]*100:.0f}%)")
    off_abst = sum(1 for c in off_conf if c < sth)
    ans_fire = sum(1 for c in ans_conf if c >= sth)
    print(f"  @ {sth:.2f}: off-topic abstained {off_abst}/{len(off_conf)}, "
          f"answerable answered {ans_fire}/{len(ans_conf)}")

    # answer quality on answerable set (uses LLM)
    cite = kw = n = 0
    for item, _ in rows:
        if not item["answerable"]:
            continue
        n += 1
        res = ask(item["q"])
        if res.get("citations"):
            cite += 1
        if any(k.lower() in (res.get("answer") or "").lower() for k in item.get("keywords", [])):
            kw += 1
    print(f"\n=== answer quality (answerable, n={n}) ===")
    print(f"  with citations: {cite}/{n}")
    print(f"  hit expected keyword: {kw}/{n}")
    return sth

if __name__ == "__main__":
    run()
