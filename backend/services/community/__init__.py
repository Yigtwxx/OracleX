"""
Community board service.

Replaces the single `services/community_service.py`, which had grown into one
file holding the feed, comments, likes and their counter bookkeeping. Each
module here owns one thing:

    posts         the feed, a single post, and the author's own writes
    comments      the thread: flat fetch, tree assembly, edits, tombstones
    votes         up/down on posts and comments
    link_preview  OpenGraph extraction for link posts, with an SSRF guard
    media         image uploads into the community-media bucket
    errors        the exception types the router translates into status codes
    _db           the asyncio.to_thread wrapper around the blocking client

Two behaviours changed with the split and are worth knowing about:

  * counters are maintained by database triggers now, not by a read-modify-write
    in Python, so concurrent votes no longer overwrite each other
  * writes raise instead of returning None, so a failed write can no longer come
    back as a 200
"""

from . import comments, link_preview, media, posts, votes
from .errors import (
    CommunityError,
    InvalidRequest,
    NotFound,
    NotOwner,
    UpstreamFailure,
)

__all__ = [
    "comments",
    "link_preview",
    "media",
    "posts",
    "votes",
    "CommunityError",
    "InvalidRequest",
    "NotFound",
    "NotOwner",
    "UpstreamFailure",
]
