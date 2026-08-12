"""
Supabase Storage helpers, with no opinion about which feature is uploading.

This started life as `services/community/media.py` and was lifted here when the
profile service needed the same image handling for avatars. The pattern is the
one `services/db.py` already follows: the reusable half moves out, and the
original module stays as a thin binding that keeps its public names so nothing
that imports it has to change.

The type of an upload is decided by sniffing the first bytes, never by trusting
the browser's `Content-Type` or the filename — both are attacker-controlled, and
the bucket's own `allowed_mime_types` check reads the header we send it.

Errors are raised as this module's own two exceptions rather than a domain's, so
a call from `routers/profile.py` never has to catch a `CommunityError`.
"""

import logging
import uuid
from typing import Any

from services.db import SupabaseOps

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base class for every failure this module reports."""


class ImageRejected(StorageError):
    """The bytes are not an image we accept, or the file is too large."""


class StorageFailure(StorageError):
    """The bucket itself failed."""


_ops = SupabaseOps(domain="storage", wrap=StorageFailure)

# (magic prefix, mime type, extension). WebP needs a second check because its
# RIFF container is shared with other formats.
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
)


def sniff_image(data: bytes) -> tuple[str, str]:
    """
    Return `(mime_type, extension)` for a supported image, or raise.

    Pure and synchronous, so the allowlist is testable without a bucket.
    """
    if not data:
        raise ImageRejected("the file is empty")

    for prefix, mime, extension in _SIGNATURES:
        if data.startswith(prefix):
            return mime, extension

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"

    raise ImageRejected("only PNG, JPEG, WebP and GIF images are supported")


async def upload_image(
    *,
    bucket: str,
    user_id: str,
    data: bytes,
    max_bytes: int,
    declared_name: str | None = None,
) -> tuple[str, str]:
    """
    Store `data` under `{user_id}/{uuid}.{ext}` and return `(public_url, path)`.

    The per-user folder is what makes a storage policy expressible — a user can
    only ever write inside their own prefix — and it is also what lets
    `list_user_objects` clean up after them.
    """
    if len(data) > max_bytes:
        raise ImageRejected(f"images must be {max_bytes // (1024 * 1024)} MB or smaller")

    mime, extension = sniff_image(data)
    path = f"{user_id}/{uuid.uuid4().hex}.{extension}"

    if declared_name:
        # Logged, never used to build the path: a filename can carry "../" or a
        # second extension, and neither belongs in an object key.
        logger.info("storage: uploading %s as %s/%s (%s)", declared_name[:80], bucket, path, mime)

    await _ops.run(
        lambda: (
            _client()
            .storage.from_(bucket)
            .upload(path, data, {"content-type": mime, "cache-control": "31536000"})
        ),
        what=f"upload to {bucket}",
    )

    url = await _ops.run(
        lambda: _client().storage.from_(bucket).get_public_url(path),
        what=f"resolve {bucket} url",
    )
    if not isinstance(url, str) or not url:
        raise StorageFailure("the upload succeeded but no public URL came back")

    # supabase-py has historically appended a trailing "?" to public URLs.
    return url.rstrip("?"), path


async def list_user_objects(*, bucket: str, user_id: str) -> list[str]:
    """
    Every object key under `{user_id}/` in `bucket`.

    Returns full paths, ready to hand back to `remove_objects`. An empty list is
    the normal answer for a user who has never uploaded, not an error.
    """
    entries: Any = await _ops.run(
        lambda: _client().storage.from_(bucket).list(user_id),
        what=f"list {bucket} objects",
    )
    if not entries:
        return []

    paths = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
        # Supabase returns a placeholder row for an empty folder; it has no id.
        if name and name != ".emptyFolderPlaceholder":
            paths.append(f"{user_id}/{name}")
    return paths


async def remove_objects(*, bucket: str, paths: list[str]) -> None:
    """Delete `paths` from `bucket`. A no-op when the list is empty."""
    if not paths:
        return

    await _ops.run(
        lambda: _client().storage.from_(bucket).remove(paths),
        what=f"remove {len(paths)} objects from {bucket}",
    )


def _client() -> Any:
    from services.supabase_service import get_supabase

    return get_supabase()
