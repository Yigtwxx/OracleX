"""
The community package's binding of `services.storage`.

Files land in the public `community-media` bucket created by
`007_community_reddit.sql`, under `{user_id}/{uuid}.{ext}`.

The image sniffing and the upload itself used to live here in full. They moved
to `services/storage.py` when the profile service needed the same handling for
avatars; this module keeps the exact names, signatures and return type the
community package and its router already use, so nothing else in the package
changed. The one job left here is translating the storage layer's exceptions
into community ones, which is what lets `routers/community.py` keep its single
`CommunityError` handler.
"""

from models.community import UploadedMedia
from services import storage

from .errors import InvalidRequest, UpstreamFailure

BUCKET = "community-media"
MAX_BYTES = 5 * 1024 * 1024


def sniff_image(data: bytes) -> tuple[str, str]:
    """Return `(mime_type, extension)` for a supported image, or raise."""
    try:
        return storage.sniff_image(data)
    except storage.ImageRejected as e:
        raise InvalidRequest(str(e)) from e


async def upload_image(
    *, user_id: str, data: bytes, declared_name: str | None = None
) -> UploadedMedia:
    """Store `data` and return its public URL."""
    try:
        url, path = await storage.upload_image(
            bucket=BUCKET,
            user_id=user_id,
            data=data,
            max_bytes=MAX_BYTES,
            declared_name=declared_name,
        )
    except storage.ImageRejected as e:
        raise InvalidRequest(str(e)) from e
    except storage.StorageFailure as e:
        raise UpstreamFailure(str(e)) from e

    return UploadedMedia(url=url, path=path)
