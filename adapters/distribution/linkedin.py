"""LinkedIn video publishing adapter (I/O — coverage-omitted).

UGC Posts video flow (urllib, injectable urlopen):

  1. GET  video_url                         (download transcoded bytes)
  2. POST /v2/assets?action=registerUpload  (initialize upload)
  3. PUT  <uploadUrl>                       (binary upload)
  4. POST /v2/ugcPosts                      (VIDEO share, media.status=READY)

Creds: ``access_token``, ``author_urn`` (``urn:li:person:*`` or ``urn:li:organization:*``).
Scopes: ``w_member_social`` (person) or ``w_organization_social`` (org page).

Ref: https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_REGISTER_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_RECIPE = "urn:li:digitalmediaRecipe:feedshare-video"
_HTTP_TIMEOUT = 30
_DOWNLOAD_TIMEOUT = 120
_UPLOAD_TIMEOUT = 300
_UA = "perkins-platform/1.0 (+https://perkinsroofing.net)"
_UPLOAD_MECH = "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"


class LinkedInPublisher:
    """Publish a video post to LinkedIn via the UGC Posts API."""

    def __init__(self, *, access_token: str, author_urn: str = "", urlopen=None) -> None:
        if not access_token:
            raise RuntimeError("LinkedIn publish requires an OAuth access token")
        self._token = access_token
        self._author_urn = author_urn
        self._urlopen = urlopen or urllib.request.urlopen

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        """Download *video_url*, upload to LinkedIn, create a VIDEO UGC post.

        ``idempotency_key`` is unused by LinkedIn; stored externally like IG/TikTok.

        Returns:
            Post URN from the ``X-RestLi-Id`` response header.

        Raises:
            RuntimeError: missing creds/bytes, or any HTTP error.
        """
        del idempotency_key
        if not self._author_urn:
            raise RuntimeError("LinkedIn publish requires an author_urn")
        if not video_url:
            raise RuntimeError("LinkedIn publish requires a video_url")
        video_bytes = self._download_video(video_url)
        asset_urn, upload_url = self._register_upload()
        self._upload_binary(upload_url, video_bytes)
        return self._create_ugc_post(asset_urn, caption)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "User-Agent": _UA,
        }

    def _download_video(self, video_url: str) -> bytes:
        req = urllib.request.Request(video_url, method="GET", headers={"User-Agent": _UA})
        with self._open(req, _DOWNLOAD_TIMEOUT) as resp:
            data = resp.read()
        if not data:
            raise RuntimeError("LinkedIn publish requires video bytes")
        return data

    def _register_upload(self) -> tuple[str, str]:
        payload = {
            "registerUploadRequest": {
                "recipes": [_RECIPE],
                "owner": self._author_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        body = self._json("POST", _REGISTER_URL, payload, _HTTP_TIMEOUT)
        value = body.get("value") or {}
        mech = (value.get("uploadMechanism") or {}).get(_UPLOAD_MECH) or {}
        upload_url = mech.get("uploadUrl") or ""
        asset = value.get("asset") or ""
        if not upload_url or not asset:
            raise RuntimeError("LinkedIn registerUpload missing uploadUrl or asset")
        return asset, upload_url

    def _upload_binary(self, upload_url: str, video_bytes: bytes) -> None:
        headers = {**self._auth_headers(), "Content-Type": "application/octet-stream"}
        req = urllib.request.Request(upload_url, data=video_bytes, method="PUT", headers=headers)
        with self._open(req, _UPLOAD_TIMEOUT) as resp:
            resp.read()

    def _create_ugc_post(self, asset_urn: str, caption: str) -> str:
        payload = {
            "author": self._author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": caption or ""},
                    "shareMediaCategory": "VIDEO",
                    "media": [{"status": "READY", "media": asset_urn}],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        req = self._json_req("POST", _UGC_POSTS_URL, payload)
        with self._open(req, _HTTP_TIMEOUT) as resp:
            post_id = _header(resp.headers, "X-RestLi-Id", "x-restli-id")
            resp.read()
        if not post_id:
            raise RuntimeError("LinkedIn ugcPosts returned no post id")
        return post_id

    def _json(self, method: str, url: str, payload: dict, timeout: int) -> dict:
        req = self._json_req(method, url, payload)
        with self._open(req, timeout) as resp:
            raw = resp.read().decode()
        return json.loads(raw) if raw else {}

    def _json_req(self, method: str, url: str, payload: dict) -> urllib.request.Request:
        return urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            method=method,
            headers={**self._auth_headers(), "Content-Type": "application/json; charset=UTF-8"},
        )

    def _open(self, req: urllib.request.Request, timeout: int):
        try:
            return self._urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_http_err(exc)) from exc


def _header(headers, *names: str) -> str:
    getter = getattr(headers, "get", None)
    if getter:
        for name in names:
            val = getter(name)
            if val:
                return val
    return ""


def _http_err(exc: urllib.error.HTTPError) -> str:
    snippet = ""
    try:
        snippet = (exc.read() or b"").decode("utf-8", errors="replace")[:300]
    except Exception:
        snippet = ""
    if snippet:
        return f"LinkedIn API error {exc.code}: {snippet}"
    return f"LinkedIn API error {exc.code}"
