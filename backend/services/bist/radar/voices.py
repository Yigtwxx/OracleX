"""
What the commentators the user trusts said lately about the Radar's candidates.

A step inside the scan, not a system of its own. Once the candidates are known
the step reads three YouTube channels' feeds, pulls the Turkish captions of the
videos from the last four weeks, finds the passages where a candidate is named
and asks the model one question per (video, company): bullish, bearish, neutral
or no view. Everything it touches is cached on disk by video id, so the second
scan of a day costs a few feed requests and no model time.

Three rules hold the step honest:

* **The model never picks the company.** Tickers and spoken company names are
  matched deterministically first; the model sees passages already known to be
  about one company and answers only for that one. A hallucinated ticker is the
  failure this design exists to make impossible.
* **A call is graded against the market, not against zero.** A "yükselir" that
  rose 3% while the index rose 8% is a miss. Grading uses the close *after* the
  video, so the speaker is never credited with the move they were describing.
* **Small samples say so.** The accuracy shown is Bayesian-shrunk toward 50%,
  so one lucky call reads as 60%, not 100%, and the score adjuster ignores any
  speaker with fewer than ten graded calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Optional

import feedparser
import httpx

from services.asset_registry import DATA_DIR, REGISTRY_DIR, read_json_cache, write_json_cache
from services.bist.equity_service import fetch_candles
from services.bist.radar.scoring import Adjustment
from services.bist.text import fold
from services.bist.tradingview_client import EquityRow
from services.http_client import get_text

logger = logging.getLogger(__name__)

REGISTRY_FILE = os.path.join(REGISTRY_DIR, "bist_voices.json")
CACHE_DIR = os.path.join(DATA_DIR, "bist_voices")
TRANSCRIPT_DIR = os.path.join(CACHE_DIR, "transcripts")
CALLS_FILE = os.path.join(CACHE_DIR, "calls.json")

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"

LOOKBACK_DAYS = 28
"""How far back a scan looks. The user asked for a short read, not an archive."""

WINDOW_SECONDS = 60
"""Captions either side of a mention that travel to the model."""

MAX_PASSAGE_CHARS = 3200
MAX_EXTRACTIONS_PER_SCAN = 12
"""Model calls per scan. The cache makes the cap bite only on the first scan of a busy week."""

MAX_GRADES_PER_SCAN = 30

HIT_THRESHOLD = 0.01
"""Excess return below this in either direction is noise, graded `flat`."""

MIN_HORIZON_DAYS = 3
MAX_HORIZON_DAYS = 45

MIN_SAMPLE = 10
MIN_ACCURACY = 0.65
ADJUST_POINTS = 3

STANCES = ("bullish", "bearish", "neutral", "none")

INDEX_TICKER = "XU100"

# Words that open a company name without naming the company.
_NAME_STOPWORDS = {"türk", "türkiye", "anadolu", "borsa", "yatırım", "holding", "grubu", "enerji"}
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(a\.?ş\.?|a\.?o\.?|t\.?a\.?ş\.?|holding|sanayi|ticaret|ve|san\.|tic\.)\b", re.I
)


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    channel_id: str
    url: str
    default_horizon_days: int = 21
    kind: str = "youtube"


@dataclass(frozen=True)
class Video:
    voice_id: str
    video_id: str
    title: str
    published: str
    """ISO date."""
    description: str
    url: str


@dataclass
class Call:
    key: str
    """`{video_id}:{ticker}`."""
    voice_id: str
    voice_name: str
    video_id: str
    video_title: str
    url: str
    ticker: str
    stance: str
    horizon_days: int
    target: Optional[float]
    quote: str
    said_at: str
    """ISO date the video was published."""
    outcome: Optional[dict[str, Any]] = None
    """Set once graded: entry, exit, return, index_return, excess, result, graded_at."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Accuracy:
    hits: int
    misses: int
    flats: int
    pending: int

    @property
    def n(self) -> int:
        return self.hits + self.misses

    @property
    def raw(self) -> Optional[float]:
        return self.hits / self.n if self.n else None

    @property
    def shrunk(self) -> float:
        """Toward 50% with a prior worth four calls: one lucky call reads 60%, not 100%."""
        return (self.hits + 2) / (self.n + 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "flats": self.flats,
            "pending": self.pending,
            "n": self.n,
            "raw": None if self.raw is None else round(self.raw, 3),
            "shrunk": round(self.shrunk, 3),
        }


@dataclass
class VoicesReport:
    checked: bool
    voices: int = 0
    videos: int = 0
    transcripts: int = 0
    extractions: int = 0
    graded: int = 0
    failures: list[str] = field(default_factory=list)


# ── Registry ────────────────────────────────────────────────────────────────


def load_registry(path: str = REGISTRY_FILE) -> tuple[list[Voice], dict[str, list[str]]]:
    raw = read_json_cache(path)
    if not isinstance(raw, dict):
        return [], {}
    voices = [
        Voice(
            id=str(v["id"]),
            name=str(v["name"]),
            channel_id=str(v["channel_id"]),
            url=str(v.get("url") or f"https://www.youtube.com/channel/{v['channel_id']}"),
            default_horizon_days=int(v.get("default_horizon_days", 21)),
            kind=str(v.get("kind", "youtube")),
        )
        for v in raw.get("voices", [])
        if v.get("active", True) and v.get("kind", "youtube") == "youtube"
    ]
    aliases = {str(k).upper(): [str(a) for a in v] for k, v in (raw.get("aliases") or {}).items()}
    return voices, aliases


# ── Aliases and mentions ────────────────────────────────────────────────────


def aliases_for(rows: list[EquityRow], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Every string that names a company in speech or a title.

    Derived from the board's legal name — with the legal suffixes stripped and
    the first word on its own when it is distinctive — plus the hand-kept list
    for the names people actually say (`THY`, `Tüpraş`). Generic openers like
    `Türk` are never aliases on their own; they would match half the index.
    """
    out: dict[str, list[str]] = {}
    for row in rows:
        names = {row.ticker}
        clean = _LEGAL_SUFFIX_RE.sub(" ", row.name or "")
        clean = re.sub(r"[^\w\s]", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) >= 4:
            names.add(clean)
        first = clean.split(" ")[0] if clean else ""
        if len(first) >= 5 and fold(first) not in _NAME_STOPWORDS:
            names.add(first)
        names.update(extra.get(row.ticker, []))
        out[row.ticker] = sorted(names, key=len, reverse=True)
    return out


def _alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\wğüşöçı])" + re.escape(fold(alias)) + r"(?![\wğüşöçı])")


def find_mentions(
    segments: list[dict[str, Any]], aliases: dict[str, list[str]]
) -> dict[str, list[int]]:
    """Ticker → indices of the caption segments that name it."""
    patterns = {t: [_alias_pattern(a) for a in names] for t, names in aliases.items()}
    folded = [fold(str(s.get("text", ""))) for s in segments]
    out: dict[str, list[int]] = {}
    for ticker, pats in patterns.items():
        hits = [i for i, text in enumerate(folded) if any(p.search(text) for p in pats)]
        if hits:
            out[ticker] = hits
    return out


def passages(segments: list[dict[str, Any]], indices: list[int]) -> str:
    """The captions within `WINDOW_SECONDS` of each mention, merged, capped."""
    spans: list[tuple[float, float]] = []
    for i in indices:
        start = float(segments[i].get("start", 0.0))
        spans.append((max(0.0, start - WINDOW_SECONDS), start + WINDOW_SECONDS))
    spans.sort()
    merged: list[list[float]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    parts: list[str] = []
    for lo, hi in merged:
        text = " ".join(
            str(s.get("text", "")).strip()
            for s in segments
            if lo <= float(s.get("start", 0.0)) <= hi
        )
        if text:
            parts.append(f"[{int(lo // 60):02d}:{int(lo % 60):02d}] {text}")
    joined = "\n\n".join(parts)
    return joined[:MAX_PASSAGE_CHARS]


# ── YouTube ─────────────────────────────────────────────────────────────────


async def fetch_videos(voice: Voice, since: date) -> list[Video]:
    """The channel's feed — the last fifteen uploads — trimmed to the lookback."""
    body = await get_text(FEED_URL.format(channel_id=voice.channel_id), timeout=20.0)
    feed = feedparser.parse(body)
    out: list[Video] = []
    for entry in feed.entries:
        video_id = getattr(entry, "yt_videoid", None) or _video_id_from_link(
            getattr(entry, "link", "")
        )
        published = (getattr(entry, "published", "") or "")[:10]
        if not video_id or not published:
            continue
        try:
            when = date.fromisoformat(published)
        except ValueError:
            continue
        if when < since:
            continue
        description = ""
        media = getattr(entry, "media_group", None) or {}
        if isinstance(media, dict):
            description = str(media.get("media_description") or "")
        if not description:
            description = str(getattr(entry, "summary", "") or "")
        out.append(
            Video(
                voice_id=voice.id,
                video_id=video_id,
                title=str(getattr(entry, "title", "") or ""),
                published=published,
                description=description,
                url=VIDEO_URL.format(video_id=video_id),
            )
        )
    return out


def _video_id_from_link(link: str) -> Optional[str]:
    match = re.search(r"[?&]v=([\w-]{6,})", link or "")
    return match.group(1) if match else None


def _transcript_path(video_id: str) -> str:
    return os.path.join(TRANSCRIPT_DIR, f"{video_id}.json")


def _fetch_transcript_sync(video_id: str) -> list[dict[str, Any]]:
    from youtube_transcript_api import YouTubeTranscriptApi

    fetched = YouTubeTranscriptApi().fetch(video_id, languages=["tr"])
    return [{"start": float(s.start), "text": str(s.text)} for s in fetched]


async def fetch_transcript(video_id: str) -> Optional[list[dict[str, Any]]]:
    """Cached Turkish captions, or None when the video has none."""
    cached = read_json_cache(_transcript_path(video_id))
    if isinstance(cached, dict) and "segments" in cached:
        return cached["segments"] or None
    try:
        segments = await asyncio.to_thread(_fetch_transcript_sync, video_id)
    except Exception as e:  # noqa: BLE001 — a video without captions is a normal case
        logger.info("Radar voices: no transcript for %s: %s", video_id, e)
        segments = []
    write_json_cache(
        _transcript_path(video_id),
        {"video_id": video_id, "fetched_at": datetime.now(UTC).isoformat(), "segments": segments},
    )
    return segments or None


# ── Calls ledger ────────────────────────────────────────────────────────────


def load_calls() -> dict[str, Call]:
    raw = read_json_cache(CALLS_FILE)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Call] = {}
    for key, value in raw.get("calls", {}).items():
        try:
            out[key] = Call(**value)
        except TypeError:
            continue
    return out


def save_calls(calls: dict[str, Call]) -> None:
    write_json_cache(
        CALLS_FILE,
        {
            "updated_at": datetime.now(UTC).isoformat(),
            "calls": {k: c.to_dict() for k, c in calls.items()},
        },
    )


def parse_stance(raw: Optional[str], passage_text: str) -> Optional[dict[str, Any]]:
    """
    The model's JSON, validated.

    A stance outside the four words is refused rather than coerced, and a quote
    the passages do not contain is dropped rather than shown — the quote is the
    reader's evidence and an invented one is worse than none.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    stance = str(data.get("stance", "")).strip().lower()
    if stance not in STANCES:
        return None
    horizon = data.get("horizon_days")
    horizon = int(horizon) if isinstance(horizon, (int, float)) and horizon > 0 else None
    target = data.get("target")
    target = float(target) if isinstance(target, (int, float)) and target > 0 else None
    quote = str(data.get("quote") or "").strip()
    if quote and fold(quote)[:60] not in fold(passage_text):
        quote = ""
    return {"stance": stance, "horizon_days": horizon, "target": target, "quote": quote}


async def extract_call(
    voice: Voice, video: Video, ticker: str, company: str, passage_text: str
) -> Optional[Call]:
    from config import settings
    from services import llm
    from services.prompts import load_prompt, render_prompt

    prompt = render_prompt(
        "voices/stance",
        company=company,
        ticker=ticker,
        speaker=voice.name,
        title=video.title,
        published=video.published,
        passages=passage_text,
    )
    try:
        raw = await llm.generate(
            prompt,
            system=load_prompt("generic/system_default"),
            temperature=0.1,
            max_tokens=300,
            timeout=90.0,
            reasoning=False,
            json_mode=True,
            extra={"num_ctx": settings.LLM_NUM_CTX, "repeat_penalty": 1.1},
            prefer=None,
        )
    except Exception as e:  # noqa: BLE001 — one failed extraction must not end the scan
        logger.warning("Radar voices: extraction failed for %s/%s: %s", video.video_id, ticker, e)
        return None
    parsed = parse_stance(raw, passage_text)
    if parsed is None:
        return None
    horizon = parsed["horizon_days"] or voice.default_horizon_days
    horizon = max(MIN_HORIZON_DAYS, min(MAX_HORIZON_DAYS, horizon))
    return Call(
        key=f"{video.video_id}:{ticker}",
        voice_id=voice.id,
        voice_name=voice.name,
        video_id=video.video_id,
        video_title=video.title,
        url=video.url,
        ticker=ticker,
        stance=parsed["stance"],
        horizon_days=horizon,
        target=parsed["target"],
        quote=parsed["quote"],
        said_at=video.published,
    )


# ── Grading ─────────────────────────────────────────────────────────────────


def grade(
    call: Call,
    candles: list[dict[str, Any]],
    index_candles: list[dict[str, Any]],
    today: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """
    The outcome of one directional call, or None while it is still open.

    Entry is the first close *after* the day the video went up, so the speaker
    is not credited with the move they were talking about. Exit is the first
    close on or after entry plus the horizon. Both legs are measured on the
    index too, and the call is judged on the difference.
    """
    if call.stance not in ("bullish", "bearish"):
        return None
    said = date.fromisoformat(call.said_at)
    entry = next((c for c in candles if date.fromisoformat(str(c["date"])[:10]) > said), None)
    if entry is None:
        return None
    entry_day = date.fromisoformat(str(entry["date"])[:10])
    due = entry_day + timedelta(days=call.horizon_days)
    if (today or date.today()) < due:
        return None
    exit_ = next((c for c in candles if date.fromisoformat(str(c["date"])[:10]) >= due), None)
    if exit_ is None:
        return None

    def index_close(day: date) -> Optional[float]:
        row = next(
            (c for c in index_candles if date.fromisoformat(str(c["date"])[:10]) >= day), None
        )
        return float(row["close"]) if row else None

    ret = float(exit_["close"]) / float(entry["close"]) - 1
    i_entry, i_exit = index_close(entry_day), index_close(due)
    index_ret = (i_exit / i_entry - 1) if i_entry and i_exit else 0.0
    excess = ret - index_ret
    signed = excess if call.stance == "bullish" else -excess
    touched_target = (
        call.target is not None
        and call.stance == "bullish"
        and any(
            float(c["high"]) >= call.target
            for c in candles
            if entry_day <= date.fromisoformat(str(c["date"])[:10]) <= due
        )
    )
    result = (
        "hit"
        if signed >= HIT_THRESHOLD or touched_target
        else "miss"
        if signed <= -HIT_THRESHOLD
        else "flat"
    )
    return {
        "entry_date": entry_day.isoformat(),
        "entry": round(float(entry["close"]), 4),
        "exit_date": str(exit_["date"])[:10],
        "exit": round(float(exit_["close"]), 4),
        "return": round(ret, 4),
        "index_return": round(index_ret, 4),
        "excess": round(excess, 4),
        "result": result,
        "graded_at": datetime.now(UTC).isoformat(),
    }


def accuracy_for(calls: dict[str, Call], voice_id: str) -> Accuracy:
    hits = misses = flats = pending = 0
    for call in calls.values():
        if call.voice_id != voice_id or call.stance not in ("bullish", "bearish"):
            continue
        if call.outcome is None:
            pending += 1
        elif call.outcome["result"] == "hit":
            hits += 1
        elif call.outcome["result"] == "miss":
            misses += 1
        else:
            flats += 1
    return Accuracy(hits, misses, flats, pending)


async def grade_pending(calls: dict[str, Call], limit: int = MAX_GRADES_PER_SCAN) -> int:
    """Grade every matured call the cache holds, a bounded number per scan."""
    open_calls = [
        c for c in calls.values() if c.outcome is None and c.stance in ("bullish", "bearish")
    ]
    if not open_calls:
        return 0
    try:
        index_candles = await fetch_candles(INDEX_TICKER, range_="3mo")
    except Exception:  # noqa: BLE001
        index_candles = []
    graded = 0
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for call in open_calls[:limit]:
        if call.ticker not in by_ticker:
            try:
                by_ticker[call.ticker] = await fetch_candles(call.ticker, range_="3mo")
            except Exception:  # noqa: BLE001
                by_ticker[call.ticker] = []
        outcome = grade(call, by_ticker[call.ticker], index_candles)
        if outcome is not None:
            call.outcome = outcome
            graded += 1
    return graded


# ── The step ────────────────────────────────────────────────────────────────


def adjustment_for(entries: list[dict[str, Any]]) -> Optional[Adjustment]:
    """
    ±3 when a speaker with a track record has called this name recently.

    A record means at least ten graded calls with a shrunk accuracy of 65%;
    below that the call is shown and moves nothing. Opposite calls from two
    such speakers cancel.
    """
    bull = bear = False
    names: list[str] = []
    for entry in entries:
        acc = entry.get("accuracy") or {}
        if acc.get("n", 0) < MIN_SAMPLE or acc.get("shrunk", 0) < MIN_ACCURACY:
            continue
        if entry["stance"] == "bullish":
            bull = True
            names.append(entry["voice_name"])
        elif entry["stance"] == "bearish":
            bear = True
            names.append(entry["voice_name"])
    if bull == bear:
        return None
    label = ("Yorumcu desteği: " if bull else "Yorumcu uyarısı: ") + ", ".join(sorted(set(names)))
    return Adjustment("voices", label, ADJUST_POINTS if bull else -ADJUST_POINTS)


async def voices_for(
    tickers: list[str],
    rows: list[EquityRow],
    *,
    on_progress: Optional[Callable[[int, int], None]] = None,
    today: Optional[date] = None,
) -> tuple[dict[str, list[dict[str, Any]]], VoicesReport]:
    """
    Recent calls on the given tickers, per ticker, newest first — plus a report
    of what the step managed to read.
    """
    voices, extra_aliases = load_registry()
    if not voices:
        return {}, VoicesReport(checked=False)
    if not tickers:
        # Nothing to look up is not a failure to look: the footer must not say
        # the check could not run on a day the scan simply found no one.
        return {}, VoicesReport(checked=True, voices=len(voices))

    wanted = {row.ticker: row for row in rows if row.ticker in set(tickers)}
    aliases = aliases_for(list(wanted.values()), extra_aliases)
    since = (today or date.today()) - timedelta(days=LOOKBACK_DAYS)
    calls = load_calls()
    report = VoicesReport(checked=True, voices=len(voices))

    videos: list[tuple[Voice, Video]] = []
    for voice in voices:
        try:
            for video in await fetch_videos(voice, since):
                videos.append((voice, video))
        except (httpx.HTTPError, OSError) as e:
            report.failures.append(f"{voice.name}: feed unavailable ({e})")
    report.videos = len(videos)

    extractions = 0
    for index, (voice, video) in enumerate(videos, start=1):
        segments = await fetch_transcript(video.video_id)
        header = [{"start": 0.0, "text": f"{video.title}. {video.description}"}]
        segments = header + (segments or [])
        if len(segments) > 1:
            report.transcripts += 1
        for ticker, hits in find_mentions(segments, aliases).items():
            key = f"{video.video_id}:{ticker}"
            if key in calls:
                continue
            if extractions >= MAX_EXTRACTIONS_PER_SCAN:
                break
            text = passages(segments, hits)
            call = await extract_call(voice, video, ticker, wanted[ticker].name, text)
            extractions += 1
            if call is not None:
                calls[key] = call
        if on_progress:
            on_progress(index, len(videos))
    report.extractions = extractions

    report.graded = await grade_pending(calls)
    save_calls(calls)

    accuracy = {v.id: accuracy_for(calls, v.id).to_dict() for v in voices}
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in tickers}
    for call in calls.values():
        if call.ticker not in out or call.stance == "none":
            continue
        if date.fromisoformat(call.said_at) < since:
            continue
        out[call.ticker].append(
            {
                "voice_id": call.voice_id,
                "voice_name": call.voice_name,
                "stance": call.stance,
                "said_at": call.said_at,
                "horizon_days": call.horizon_days,
                "target": call.target,
                "quote": call.quote,
                "video_title": call.video_title,
                "url": call.url,
                "outcome": call.outcome,
                "accuracy": accuracy.get(call.voice_id),
            }
        )
    for entries in out.values():
        entries.sort(key=lambda e: e["said_at"], reverse=True)
    return out, report
