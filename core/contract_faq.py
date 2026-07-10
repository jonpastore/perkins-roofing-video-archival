"""Core contract FAQ functions — pure, no I/O."""
import re

from core.json_repair import parse_model_json


def build_contract_faq_prompt(tc_text: str, count: int = 10) -> str:
    count = max(1, min(count, 20))
    return (
        f'Generate exactly {count} customer-facing FAQ items grounded in the '
        'following contract Terms & Conditions.\n\n'
        f'{tc_text}\n\n'
        'Return a JSON array of objects with keys "q", "a", and "quote".\n'
        'Every answer MUST be grounded in a verbatim excerpt from the contract. '
        'Set "quote" to the exact clause you used — it must appear word-for-word '
        'in the contract text.\n'
        'Example: [{"q": "When is payment due?", "a": "Within 30 days.", '
        '"quote": "Payment is due within 30 days of invoice"}, ...]'
    )


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').lower()).strip()


def parse_contract_faq(raw: str) -> list[dict]:
    items = parse_model_json(raw)
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        q = item.get('q') or item.get('question', '')
        a = item.get('a') or item.get('answer', '')
        quote = item.get('quote') or item.get('supporting_quote', '') or ''
        if not q or not a:
            continue
        result.append({'q': str(q).strip(), 'a': str(a).strip(), 'quote': str(quote).strip()})
    return result


MIN_QUOTE_CHARS = 20   # H1: a bare substring test is bypassable with any common word —
MIN_QUOTE_TOKENS = 4   # require a real clause-sized verbatim excerpt before trusting an answer


def grounding_gate(items: list[dict], tc_text: str) -> tuple[list[dict], list[dict]]:
    norm_tc = _normalize(tc_text)
    kept, rejected = [], []
    for item in items:
        quote_n = _normalize(item.get('quote') or '')
        if (len(quote_n) >= MIN_QUOTE_CHARS
                and len(quote_n.split()) >= MIN_QUOTE_TOKENS
                and quote_n in norm_tc):
            kept.append(item)
        else:
            rejected.append(item)
    return kept, rejected
