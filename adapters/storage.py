"""GCS storage adapter (I/O, coverage-omitted) — thin wrapper around google-cloud-storage.

All bucket names are passed in by callers; nothing is hardcoded here.
"""
from __future__ import annotations


def upload_file(
    local_path: str,
    bucket: str,
    key: str,
    content_type: str = "video/mp4",
) -> str:
    """Upload *local_path* to GCS at *bucket*/*key*.

    Args:
        local_path:   Absolute or relative path to the local file.
        bucket:       GCS bucket name (without gs:// prefix).
        key:          Object key / path inside the bucket.
        content_type: MIME type for the uploaded object.

    Returns:
        ``gs://{bucket}/{key}``

    Raises:
        RuntimeError: if google-cloud-storage is unavailable or the upload fails.
    """
    try:
        from google.cloud import storage  # noqa: PLC0415
        from google.cloud.exceptions import GoogleCloudError  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is not installed; run: pip install google-cloud-storage"
        ) from exc

    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob(key)
        blob.upload_from_filename(local_path, content_type=content_type)
    except GoogleCloudError as exc:
        raise RuntimeError(
            f"GCS upload failed (bucket={bucket!r}, key={key!r}): {exc}"
        ) from exc

    return f"gs://{bucket}/{key}"


def object_exists(bucket: str, key: str) -> bool:
    """Return True if *bucket*/*key* already exists in GCS.

    Raises:
        RuntimeError: if google-cloud-storage is unavailable or the check fails.
    """
    return object_size(bucket, key) >= 0


def object_size(bucket: str, key: str) -> int:
    """Return the size in bytes of *bucket*/*key*, or -1 if it does not exist.

    Used as the archival integrity/resume signal: a bare exists() is True the moment
    any object is at the key, but a crash mid-upload can leave a 0-byte/partial object.
    Callers compare this against the local file size before trusting "already archived".

    Raises:
        RuntimeError: if google-cloud-storage is unavailable or the check fails.
    """
    try:
        from google.cloud import storage  # noqa: PLC0415
        from google.cloud.exceptions import GoogleCloudError  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is not installed; run: pip install google-cloud-storage"
        ) from exc

    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob(key)
        blob.reload()  # populate .size; raises NotFound if the object is absent
        return int(blob.size or 0)
    except GoogleCloudError:
        return -1
    except Exception as exc:  # NotFound and friends
        if exc.__class__.__name__ in ("NotFound", "Forbidden"):
            return -1
        raise RuntimeError(
            f"GCS size-check failed (bucket={bucket!r}, key={key!r}): {exc}"
        ) from exc


def signed_download_url(
    bucket: str,
    key: str,
    *,
    filename: str,
    ttl_seconds: int = 3600,
) -> str:
    """Generate a V4 signed download URL with Content-Disposition set to attachment.

    Requires the running service account to have the ``iam.serviceAccounts.signBlob``
    permission (granted by roles/iam.serviceAccountTokenCreator on itself).

    Args:
        bucket:      GCS bucket name.
        key:         Object key inside the bucket.
        filename:    Value for the ``filename`` parameter of Content-Disposition.
        ttl_seconds: Signed URL validity window (default 3600 s = 1 hour).

    Returns:
        HTTPS signed URL string.

    Raises:
        RuntimeError: if google-cloud-storage is unavailable or signing fails.
    """
    import datetime  # noqa: PLC0415

    try:
        from google.cloud import storage  # noqa: PLC0415
        from google.cloud.exceptions import GoogleCloudError  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is not installed; run: pip install google-cloud-storage"
        ) from exc

    disposition = f'attachment; filename="{filename}"'
    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob(key)
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=ttl_seconds),
            method="GET",
            response_disposition=disposition,
        )
    except (GoogleCloudError, Exception) as exc:
        # V4 signing without a key needs iam.serviceAccounts.signBlob; that failure is a
        # plain TransportError/Exception, not GoogleCloudError — catch broadly so the route
        # can return 503 rather than leaking a traceback as a 500.
        raise RuntimeError(
            f"GCS signed-URL failed (bucket={bucket!r}, key={key!r}): {exc}"
        ) from exc

    return url


def open_read_stream(bucket: str, key: str):
    """Return a file-like object for streaming *bucket*/*key* from GCS.

    The caller is responsible for closing the returned object (use as a context
    manager or call ``.close()``).

    Raises:
        RuntimeError: if google-cloud-storage is unavailable or the open fails.
    """
    try:
        from google.cloud import storage  # noqa: PLC0415
        from google.cloud.exceptions import GoogleCloudError  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-storage is not installed; run: pip install google-cloud-storage"
        ) from exc

    try:
        client = storage.Client()
        blob = client.bucket(bucket).blob(key)
        return blob.open("rb")
    except GoogleCloudError as exc:
        raise RuntimeError(
            f"GCS open-stream failed (bucket={bucket!r}, key={key!r}): {exc}"
        ) from exc
