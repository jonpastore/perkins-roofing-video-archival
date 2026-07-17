"""100% coverage tests for core/oauth_state.py — the OAuth capture-state binding."""
import pytest

from core.oauth_state import sign_state, verify_state

KEY = b"k1-secret-material"
KEY2 = b"k2-rotated-material"
NOW = 1_800_000_000


def _mint(**over):
    args = dict(tenant_id=1, platform="youtube", nonce="n-abc", exp=NOW + 600, key=KEY)
    args.update(over)
    return sign_state(**args)


class TestRoundtrip:
    def test_valid_state_verifies(self):
        out = verify_state(_mint(), [KEY], now=NOW)
        assert out == {"tenant_id": 1, "platform": "youtube", "nonce": "n-abc"}

    def test_second_key_rotation_window(self):
        # Signed with the old key; verifier holds [new, old] — must still verify.
        state = _mint(key=KEY)
        assert verify_state(state, [KEY2, KEY], now=NOW) is not None

    def test_wrong_key_rejected(self):
        assert verify_state(_mint(key=KEY), [KEY2], now=NOW) is None


class TestTampering:
    def test_tampered_payload_rejected(self):
        state = _mint()
        p, m = state.split(".")
        # Flip a payload char (keeps base64 shape, breaks the MAC).
        bad = ("A" if p[0] != "A" else "B") + p[1:]
        assert verify_state(f"{bad}.{m}", [KEY], now=NOW) is None

    def test_tampered_mac_rejected(self):
        state = _mint()
        p, m = state.split(".")
        bad = ("A" if m[0] != "A" else "B") + m[1:]
        assert verify_state(f"{p}.{bad}", [KEY], now=NOW) is None

    def test_cross_tenant_forgery_needs_key(self):
        # An attacker re-minting for tenant 2 without the key can't produce a valid MAC.
        forged = _mint(tenant_id=2, key=b"attacker-guess")
        assert verify_state(forged, [KEY], now=NOW) is None


class TestExpiry:
    def test_expired_rejected(self):
        assert verify_state(_mint(exp=NOW - 1), [KEY], now=NOW) is None

    def test_exactly_now_rejected(self):
        # Strictly-greater: exp == now fails closed.
        assert verify_state(_mint(exp=NOW), [KEY], now=NOW) is None


class TestHostileInput:
    @pytest.mark.parametrize("state", [
        "", "no-dot", "a.b", "!!!.###", "£€.∆∆",
    ])
    def test_malformed_returns_none(self, state):
        assert verify_state(state, [KEY], now=NOW) is None

    def test_none_ish_inputs(self):
        assert verify_state("", [KEY], now=NOW) is None
        assert verify_state(_mint(), [], now=NOW) is None
        assert verify_state(_mint(), [b""], now=NOW) is None

    def test_valid_mac_but_non_dict_payload(self):
        import json

        from core.oauth_state import _b64e, _mac
        payload = json.dumps(["not", "a", "dict"]).encode()
        state = f"{_b64e(payload)}.{_b64e(_mac(KEY, payload))}"
        assert verify_state(state, [KEY], now=NOW) is None

    def test_valid_mac_but_wrong_field_types(self):
        import json

        from core.oauth_state import _b64e, _mac
        for obj in (
            {"t": "1", "p": "youtube", "n": "n", "e": NOW + 9},   # tenant str
            {"t": 1, "p": "", "n": "n", "e": NOW + 9},             # empty platform
            {"t": 1, "p": "youtube", "n": "", "e": NOW + 9},       # empty nonce
            {"t": 1, "p": "youtube", "n": "n", "e": "soon"},       # exp str
            {"t": 1, "p": 7, "n": "n", "e": NOW + 9},              # platform int
        ):
            payload = json.dumps(obj).encode()
            state = f"{_b64e(payload)}.{_b64e(_mac(KEY, payload))}"
            assert verify_state(state, [KEY], now=NOW) is None

    def test_valid_mac_but_json_garbage(self):
        from core.oauth_state import _b64e, _mac
        payload = b"not json at all"
        state = f"{_b64e(payload)}.{_b64e(_mac(KEY, payload))}"
        assert verify_state(state, [KEY], now=NOW) is None


class TestMintValidation:
    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="key"):
            _mint(key=b"")

    def test_empty_nonce_raises(self):
        with pytest.raises(ValueError, match="nonce"):
            _mint(nonce="")

    def test_empty_platform_raises(self):
        with pytest.raises(ValueError, match="nonce and platform"):
            _mint(platform="")

    def test_bad_tenant_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _mint(tenant_id=0)

    def test_bad_exp_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _mint(exp=0)
