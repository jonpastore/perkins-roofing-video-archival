"""Behavioral validation for claim verification.

The contract under test is the division of labour: the model REPORTS what a span says, code
DECIDES whether that supports the claim. If a test ever has to ask the model whether something
is supported, the design has regressed.
"""
import json

from core.claim_verify import ClaimResult, read_span, verify_claim
from core.claims import Claim, ClaimType, Verdict


class _Chunk:
    def __init__(self, vid, start, text):
        self.video_id, self.start, self.text = vid, start, text
        self.end = start + 30


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, n):
        return _Q(self._rows[:n])

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a, **k):
        return _Q(self._rows)


class _LLM:
    """Returns a scripted slot-reading. Never asked to judge support."""

    def __init__(self, payload):
        self._payload = payload
        self.prompts = []

    def chat(self, prompt, want_json=False, **kw):
        self.prompts.append(prompt)
        return json.dumps(self._payload)


TIM = _Chunk("v1", 100.0, "you cut the stucco and put the wall flashing into the block")


def test_the_model_is_never_asked_whether_the_claim_is_supported():
    """The prompt must ask what the SPAN states, and must not mention the claim at all.

    Asking a model "does this support X?" is what the critic lenses already do; they answer
    "clean" to everything. It is also how v1 laundered real quotes into fake support.
    """
    llm = _LLM({"states_anything": True, "subject": "caulk", "measure": "time_to_failure",
                "value_lo": 10, "value_hi": 15, "unit": "years"})
    read_span("caulk fails in 10 to 15 years", ClaimType.NUMBER, llm=llm)
    p = llm.prompts[0].lower()
    assert "report only what this span itself states" in p
    assert "do not judge" in p
    assert "support" not in p.replace("supports", ""), "the model must not be asked about support"


def test_a_real_span_that_does_not_support_the_claim_is_not_support():
    # article: "acrylic coating lasts 10-15 years"; span: "I've seen some fail in 10-15 years"
    claim = Claim(type=ClaimType.NUMBER, sentence="Acrylic coating lasts 10-15 years.",
                  subject="acrylic coating", measure="lifespan", value=(10, 15), unit="years")
    llm = _LLM({"states_anything": True, "subject": "acrylic coating",
                "measure": "time_to_failure", "value_lo": 10, "value_hi": 15, "unit": "years"})
    r = verify_claim(claim, _DB([_Chunk("v1", 10.0, "I've seen some fail in 10 to 15 years")]),
                     llm=llm, vocab=frozenset({"acrylic", "coating", "years", "fail"}))
    assert r.verdict is Verdict.UNSUPPORTED, "same number, different proposition"


def test_a_genuinely_supporting_span_is_supported_and_cites_its_source():
    claim = Claim(type=ClaimType.NUMBER, sentence="Caulk fails in 10-15 years.",
                  subject="caulk", measure="time_to_failure", value=(10, 15), unit="years")
    llm = _LLM({"states_anything": True, "subject": "caulk", "measure": "time_to_failure",
                "value_lo": 10, "value_hi": 15, "unit": "yrs"})
    r = verify_claim(claim, _DB([_Chunk("abc123", 90.0, "it fails 10 15 years down the road")]),
                     llm=llm, vocab=frozenset({"caulk", "years"}))
    assert r.verdict is Verdict.SUPPORTED
    assert r.video_id == "abc123" and "youtu.be/abc123?t=90" in r.url, "a verdict must cite"


def test_out_of_corpus_is_distinct_from_unsupported():
    """'Solar Reflectance Index': 0 hits in 14,592 chunks — imported from the model's own
    knowledge, not merely unsupported by this article's sources. Different diagnosis."""
    claim = Claim(type=ClaimType.CODE, sentence="Solar Reflectance Index matters.",
                  entity="Solar Reflectance Index", proposition="sri matters")
    r = verify_claim(claim, _DB([]), llm=_LLM({"states_anything": False}),
                     vocab=frozenset({"stucco", "flashing", "roof"}))
    assert r.verdict is Verdict.OUT_OF_CORPUS


def test_retrieval_finding_nothing_is_unverifiable_not_an_accusation():
    """A retrieval miss must never read as an invention — that is how a gate becomes a
    randomiser and starts blocking true claims."""
    claim = Claim(type=ClaimType.NUMBER, sentence="The roof lasts 20 years.",
                  subject="roof", measure="lifespan", value=(20, 20), unit="years")
    r = verify_claim(claim, _DB([]), llm=_LLM({"states_anything": False}),
                     vocab=frozenset({"roof", "lasts", "years", "lifespan"}))
    assert r.verdict is Verdict.UNVERIFIABLE
    assert r.verdict is not Verdict.OUT_OF_CORPUS


def test_no_vocabulary_never_accuses():
    # An empty vocabulary means we could not load the corpus; it must not become evidence.
    claim = Claim(type=ClaimType.CODE, sentence="ASTM D226.", entity="ASTM D226")
    r = verify_claim(claim, _DB([]), llm=_LLM({"states_anything": False}), vocab=frozenset())
    assert r.verdict is Verdict.UNVERIFIABLE


def test_attribution_to_someone_else_is_not_support():
    claim = Claim(type=ClaimType.ATTRIBUTION, sentence="Tim recommends foam.",
                  speaker="Tim", proposition="recommends foam adhesive")
    llm = _LLM({"states_anything": True, "speaker": "some contractors",
                "stance": "reports_others", "proposition": "recommends foam adhesive"})
    r = verify_claim(claim, _DB([_Chunk("v1", 5.0, "some contractors recommend foam adhesive")]),
                     llm=llm, vocab=frozenset({"contractors", "recommend", "foam", "adhesive"}))
    assert r.verdict is Verdict.UNSUPPORTED


def test_an_unreadable_span_does_not_crash_the_verifier():
    class _Broken:
        def chat(self, *a, **k):
            raise RuntimeError("llm down")

    claim = Claim(type=ClaimType.NUMBER, subject="roof", measure="lifespan",
                  value=(20, 20), unit="years", sentence="20 years.")
    r = verify_claim(claim, _DB([TIM]), llm=_Broken(), vocab=frozenset({"roof", "years"}))
    assert r.verdict is Verdict.UNVERIFIABLE


def test_verification_stops_paying_once_a_span_supports_the_claim():
    claim = Claim(type=ClaimType.NUMBER, subject="caulk", measure="time_to_failure",
                  value=(10, 15), unit="years", sentence="Caulk fails in 10-15 years.")
    llm = _LLM({"states_anything": True, "subject": "caulk", "measure": "time_to_failure",
                "value_lo": 10, "value_hi": 15, "unit": "years"})
    rows = [_Chunk(f"v{i}", float(i), "it fails 10 15 years down the road") for i in range(6)]
    verify_claim(claim, _DB(rows), llm=llm, vocab=frozenset({"caulk", "years"}))
    assert len(llm.prompts) == 1, "a verified span is the answer; stop calling the LLM"


def test_result_without_a_video_has_no_url():
    r = ClaimResult(Claim(type=ClaimType.NUMBER, sentence="x"), Verdict.UNVERIFIABLE)
    assert r.url == ""
