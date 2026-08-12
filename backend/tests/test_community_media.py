"""
Tests for the community image allowlist.

`sniff_image` reads the file's own first bytes rather than the browser-supplied
`Content-Type` or the filename, both of which the uploader controls. These tests
pin that down: a PHP script named `photo.png` and served as `image/png` must
still be refused.
"""

import pytest

from services.community.errors import InvalidRequest
from services.community.media import sniff_image

PNG = b"\x89PNG\r\n\x1a\n" + b"rest of the file"
JPEG = b"\xff\xd8\xff\xe0" + b"rest of the file"
GIF = b"GIF89a" + b"rest of the file"
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 "


@pytest.mark.parametrize(
    "data,expected",
    [
        (PNG, ("image/png", "png")),
        (JPEG, ("image/jpeg", "jpg")),
        (GIF, ("image/gif", "gif")),
        (WEBP, ("image/webp", "webp")),
    ],
)
def test_supported_formats_are_identified_by_their_magic_bytes(data, expected):
    assert sniff_image(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"<?php system($_GET['c']); ?>",
        b"GIF87",  # truncated signature, not a real GIF
        b"RIFF\x24\x00\x00\x00WAVE",  # a RIFF container that is not WebP
        b"\x00\x01\x02\x03",
    ],
)
def test_anything_else_is_refused(data):
    with pytest.raises(InvalidRequest):
        sniff_image(data)


def test_an_empty_file_is_refused():
    with pytest.raises(InvalidRequest, match="empty"):
        sniff_image(b"")
