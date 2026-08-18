# TRD: Connection login-request

Status: **implemented-local**

## Interfaces
- `POST /connections/{integration}/request-login` (`manage_config`).
- `core.login_request.LOGIN_COPY` keys: knowify, youtube, youtube_reply, wordpress.
  `companycam` is absent; route 400s.
- Recipients: `jon@perkinsroofing.net`, `jon@degenito.ai`.
- `email_gate.decide` must allow before send.

## Tests
- `tests/core/test_login_request.py`
- `tests/api/test_connections.py` CompanyCam 400 (local WIP)
