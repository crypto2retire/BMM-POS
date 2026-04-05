"""
DigitalOcean Spaces (S3-compatible) upload/delete helpers.

Falls back to local disk storage when Spaces is not configured so the app
works in local dev without any credentials.

Required env vars (set in Railway + .env):
  DO_SPACES_KEY          — Spaces access key ID
  DO_SPACES_SECRET       — Spaces secret access key
  DO_SPACES_REGION       — e.g. "nyc3"
  DO_SPACES_BUCKET       — bucket name, e.g. "bowenstreet-media"
  DO_SPACES_CDN_ENDPOINT — CDN URL, e.g. "https://bowenstreet-media.nyc3.cdn.digitaloceanspaces.com"
                           (omit trailing slash)
"""

import io
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy boto3 client — only initialised when Spaces is configured
# ---------------------------------------------------------------------------
_s3_client = None
_spaces_bucket: Optional[str] = None
_spaces_cdn: Optional[str] = None
_spaces_enabled: bool = False


def _get_client():
    global _s3_client, _spaces_bucket, _spaces_cdn, _spaces_enabled

    if _s3_client is not None:
        return _s3_client

    key = os.environ.get("DO_SPACES_KEY", "").strip()
    secret = os.environ.get("DO_SPACES_SECRET", "").strip()
    region = os.environ.get("DO_SPACES_REGION", "nyc3").strip()
    bucket = os.environ.get("DO_SPACES_BUCKET", "").strip()
    cdn = os.environ.get("DO_SPACES_CDN_ENDPOINT", "").strip().rstrip("/")

    if not all([key, secret, bucket]):
        logger.warning("DO Spaces not configured — falling back to local disk storage")
        _spaces_enabled = False
        return None

    try:
        import boto3
        _s3_client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://{region}.digitaloceanspaces.com",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
        )
        _spaces_bucket = bucket
        _spaces_cdn = cdn or f"https://{bucket}.{region}.digitaloceanspaces.com"
        _spaces_enabled = True
        logger.info("DO Spaces client initialised — bucket=%s cdn=%s", bucket, _spaces_cdn)
    except Exception as exc:
        logger.exception("Failed to initialise DO Spaces client: %s", exc)
        _spaces_enabled = False
        _s3_client = None

    return _s3_client


def spaces_enabled() -> bool:
    _get_client()
    return _spaces_enabled


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def upload_bytes(data: bytes, key: str, content_type: str = "image/jpeg") -> Optional[str]:
    """
    Upload raw bytes to Spaces.

    Returns the public CDN URL on success, or None if Spaces is not configured
    (caller should then fall back to local disk).

    key example: "items/123_abc.jpg"
    """
    client = _get_client()
    if client is None:
        return None

    try:
        client.put_object(
            Bucket=_spaces_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ACL="public-read",
            CacheControl="public, max-age=31536000",  # 1 year — files are content-addressed
        )
        url = f"{_spaces_cdn}/{key}"
        logger.debug("Uploaded %s to Spaces → %s", key, url)
        return url
    except Exception as exc:
        logger.exception("Spaces upload failed for key=%s: %s", key, exc)
        return None


def upload_fileobj(fileobj: io.IOBase, key: str, content_type: str = "image/jpeg") -> Optional[str]:
    """Upload a file-like object. Convenience wrapper around upload_bytes."""
    return upload_bytes(fileobj.read(), key, content_type)


def delete_object(key: str) -> bool:
    """
    Delete an object from Spaces by key.
    Returns True on success/not-found, False on error.

    Accepts either a bare key ("items/foo.jpg") or a full CDN URL
    ("https://bucket.nyc3.cdn.digitaloceanspaces.com/items/foo.jpg").
    """
    client = _get_client()
    if client is None:
        return False

    # Strip CDN prefix if a full URL was passed
    if key.startswith("http"):
        cdn_prefix = (_spaces_cdn or "").rstrip("/") + "/"
        if cdn_prefix and key.startswith(cdn_prefix):
            key = key[len(cdn_prefix):]
        else:
            # Try stripping any https://... prefix up to the first path segment
            from urllib.parse import urlparse
            key = urlparse(key).path.lstrip("/")

    try:
        client.delete_object(Bucket=_spaces_bucket, Key=key)
        logger.debug("Deleted Spaces object: %s", key)
        return True
    except Exception as exc:
        logger.exception("Spaces delete failed for key=%s: %s", key, exc)
        return False


def key_from_url(url: str) -> Optional[str]:
    """Extract the Spaces object key from a CDN/origin URL, or None if not a Spaces URL."""
    if not url or not url.startswith("http"):
        return None
    from urllib.parse import urlparse
    return urlparse(url).path.lstrip("/")
