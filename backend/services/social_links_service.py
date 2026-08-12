"""
Self-declared social links on a profile.

Nothing here proves an account belongs to the person who typed its handle.
Supabase's manual identity linking would, but proving ownership is not what
this feature is for — no caller stores a token, and no UI shows a verified
mark. Anyone reading these is taking the profile owner's word for it.

What this module *is* responsible for is that a stored link goes where its
platform says it goes. For every known platform the URL is built here from a
template; a `url` in the request body is ignored. Only a `custom` entry carries
a caller-supplied URL, and then only with an http(s) scheme. Nothing in the
application ever fetches one of these URLs, so there is no SSRF surface.

Kept out of `profile_service` deliberately: that module is already 460 lines,
and a registry plus its validation is a separate thing to reason about.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_CUSTOM = 3
MAX_LINKS = 16
MAX_BIO = 200
MAX_URL = 200
MAX_LABEL = 40

CUSTOM = "custom"


class InvalidLink(Exception):
    """A link the caller sent cannot be stored, with a reason fit to show them."""


@dataclass(frozen=True)
class Platform:
    """One entry in the registry."""

    id: str
    label: str
    # None where the platform has no addressable profile URL.
    url_template: Optional[str]
    pattern: re.Pattern[str]
    # True where the platform's own identifiers are case-insensitive, so that
    # two spellings of the same handle cannot both be stored.
    lowercase: bool


def _p(
    id: str,
    label: str,
    url_template: Optional[str],
    pattern: str,
    *,
    lowercase: bool = False,
) -> Platform:
    return Platform(id, label, url_template, re.compile(pattern), lowercase)


PLATFORMS: dict[str, Platform] = {
    p.id: p
    for p in (
        _p("x", "X", "https://x.com/{h}", r"^[A-Za-z0-9_]{1,15}$"),
        # No URL. A modern Discord username is not addressable —
        # discord.com/users/{id} wants the numeric snowflake, which a user
        # cannot read off their own profile. The client renders this one as
        # copyable text; a dead href would be worse than no link.
        _p("discord", "Discord", None, r"^[a-z0-9._]{2,32}$", lowercase=True),
        _p("telegram", "Telegram", "https://t.me/{h}", r"^[A-Za-z0-9_]{5,32}$"),
        _p(
            "github",
            "GitHub",
            "https://github.com/{h}",
            r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$",
        ),
        _p("linkedin", "LinkedIn", "https://www.linkedin.com/in/{h}", r"^[A-Za-z0-9-]{3,100}$"),
        _p("youtube", "YouTube", "https://www.youtube.com/@{h}", r"^[A-Za-z0-9._-]{3,30}$"),
        _p("instagram", "Instagram", "https://instagram.com/{h}", r"^[A-Za-z0-9._]{1,30}$"),
        _p("tiktok", "TikTok", "https://www.tiktok.com/@{h}", r"^[A-Za-z0-9._]{2,24}$"),
        _p("reddit", "Reddit", "https://reddit.com/user/{h}", r"^[A-Za-z0-9_-]{3,20}$"),
        _p("twitch", "Twitch", "https://twitch.tv/{h}", r"^[A-Za-z0-9_]{4,25}$", lowercase=True),
        _p("medium", "Medium", "https://medium.com/@{h}", r"^[A-Za-z0-9._-]{1,50}$"),
        _p(
            "substack",
            "Substack",
            "https://{h}.substack.com",
            r"^[a-z0-9-]{1,63}$",
            lowercase=True,
        ),
        _p(
            "tradingview",
            "TradingView",
            "https://www.tradingview.com/u/{h}/",
            r"^[A-Za-z0-9_]{1,30}$",
        ),
    )
}


def normalise_handle(platform: str, raw: str) -> str:
    """
    Trim, drop a leading `@`, and lowercase where the platform is case-blind.

    Pasting `@yigtwx` is the common case; refusing it would be pedantry.
    """
    handle = (raw or "").strip()
    if handle.startswith("@"):
        handle = handle[1:]

    spec = PLATFORMS.get(platform)
    if spec and spec.lowercase:
        handle = handle.lower()
    return handle


def build_url(platform: str, handle: str) -> Optional[str]:
    """The profile URL for `handle`, or None where the platform has none."""
    spec = PLATFORMS.get(platform)
    if spec is None or spec.url_template is None:
        return None
    return spec.url_template.replace("{h}", handle)


def validate_custom(label: str, url: str) -> tuple[str, str]:
    """
    Check one free-form link and return its cleaned `(label, url)`.

    The scheme allowlist is what keeps `javascript:` and `data:` out of an
    `href` the public page renders.
    """
    clean_label = (label or "").strip()
    if not clean_label:
        raise InvalidLink("A custom link needs a label.")
    if len(clean_label) > MAX_LABEL:
        raise InvalidLink(f"Link labels must be {MAX_LABEL} characters or fewer.")

    clean_url = (url or "").strip()
    if len(clean_url) > MAX_URL:
        raise InvalidLink(f"Links must be {MAX_URL} characters or fewer.")

    parsed = urlparse(clean_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidLink("Links must start with http:// or https://")

    return clean_label, clean_url


def validate_links(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Validate a whole replacement list and return rows ready to insert.

    `position` comes from the array order, never from the caller — it is display
    order, and letting a client set it invites collisions for no benefit.
    """
    if len(items) > MAX_LINKS:
        raise InvalidLink(f"You can list at most {MAX_LINKS} links.")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    custom_count = 0

    for position, item in enumerate(items):
        platform = str(item.get("platform") or "").strip().lower()

        if platform == CUSTOM:
            custom_count += 1
            if custom_count > MAX_CUSTOM:
                raise InvalidLink(f"You can list at most {MAX_CUSTOM} custom links.")
            label, url = validate_custom(item.get("label") or "", item.get("url") or "")
            rows.append(
                {
                    "platform": CUSTOM,
                    "handle": None,
                    "label": label,
                    "url": url,
                    "position": position,
                }
            )
            continue

        spec = PLATFORMS.get(platform)
        if spec is None:
            raise InvalidLink(f"{item.get('platform')!r} is not a platform we support.")
        if platform in seen:
            raise InvalidLink(f"{spec.label} can only be listed once.")
        seen.add(platform)

        handle = normalise_handle(platform, str(item.get("handle") or ""))
        if not spec.pattern.match(handle):
            raise InvalidLink(f"{handle!r} is not a valid {spec.label} username.")

        rows.append(
            {
                "platform": platform,
                "handle": handle,
                "label": None,
                "url": build_url(platform, handle),
                "position": position,
            }
        )

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

# Named explicitly rather than `*`. The backend authenticates with the
# service-role key, so row-level security will not stop an accidental `email`
# from reaching a stranger's browser — this list is the only thing that does.
PUBLIC_PROFILE_COLUMNS = "id, full_name, avatar_url, bio, subscription_plan, created_at"

_LINK_COLUMNS = "platform, handle, label, url, position"

_ZERO_KARMA = {"post_karma": 0, "comment_karma": 0, "total_karma": 0}


class LinkStoreError(Exception):
    """The link store could not answer, or the write did not happen."""


def _client() -> Any:
    from services.supabase_service import get_supabase

    return get_supabase()


async def get_links(user_id: str) -> list[dict[str, Any]]:
    """Every link a user has listed, in display order."""
    try:
        response = (
            _client()
            .table("profile_social_links")
            .select(_LINK_COLUMNS)
            .eq("user_id", user_id)
            .order("position")
            .execute()
        )
    except Exception as exc:
        logger.error("social links: could not read links for %s: %s", user_id, exc)
        raise LinkStoreError(str(exc)) from exc

    return response.data or []


async def replace_links(user_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Replace a user's whole link set.

    Validation runs first, on purpose: a single bad row must not cost someone
    the links they already had. Delete-then-insert rather than a diff — the set
    is at most 16 rows, and a diff would be more code than it saves.
    """
    rows = validate_links(items)

    try:
        client = _client()
        client.table("profile_social_links").delete().eq("user_id", user_id).execute()

        if rows:
            client.table("profile_social_links").insert(
                [{"user_id": user_id, **row} for row in rows]
            ).execute()
    except Exception as exc:
        logger.error("social links: could not replace links for %s: %s", user_id, exc)
        raise LinkStoreError(str(exc)) from exc

    return rows


async def get_karma(user_id: str) -> dict[str, int]:
    """
    Post and comment karma, computed on read.

    A counter column on `profiles` would drift the first time a post was
    deleted or a vote retracted, and nothing would notice. A user who has never
    posted gets zeroes; so does one whose karma lookup fails, because a missing
    number is not worth failing a whole profile over.
    """
    try:
        response = _client().rpc("community_user_karma", {"uid": user_id}).execute()
    except Exception as exc:
        logger.warning("social links: karma lookup failed for %s: %s", user_id, exc)
        return dict(_ZERO_KARMA)

    data = response.data or []
    if not data:
        return dict(_ZERO_KARMA)

    row = data[0] if isinstance(data, list) else data
    return {key: int(row.get(key, 0) or 0) for key in _ZERO_KARMA}


async def get_public_profile(user_id: str) -> Optional[dict[str, Any]]:
    """
    What one signed-in user may see about another.

    Returns None when there is no such profile, so the caller can answer 404
    rather than render an empty shell.
    """
    try:
        response = (
            _client()
            .table("profiles")
            .select(PUBLIC_PROFILE_COLUMNS)
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("social links: could not read profile %s: %s", user_id, exc)
        raise LinkStoreError(str(exc)) from exc

    rows = response.data or []
    if not rows:
        return None

    profile = dict(rows[0])
    profile["social_links"] = await get_links(user_id)
    profile["karma"] = await get_karma(user_id)
    return profile
