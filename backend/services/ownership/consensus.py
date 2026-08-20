"""
What the board says once you stop reading it one holder at a time.

The per-entity view answers "what does Buffett own". The interesting questions
are the ones that cut across it — what do the most of them own, what did the
most of them buy, who else is in the thing I am watching — and none of those
need a new source. Everything here is derived from the board that was already
built, so it costs a pass over a payload in memory and no upstream request.

Two rules carry over from the rest of the feature, for the same reasons.

Counting is on holders, not on dollars alone. "Nine of eighteen hold this" is a
statement about agreement; "$300bn is in this" is a statement about Berkshire.
Both are reported, but the ranking is by holder count, because that is the thing
the word consensus actually means.

Nothing is summed across a mix of bases. A 13F value is as-filed at a quarter
end and a crypto value is marked at this morning's price; adding them produces a
total that was never true at any single moment. So exposure is reported per
asset, where every contribution shares one basis, and never as a grand total.
"""

import logging
from typing import Any

from models.ownership import Move, Position
from services.ownership.board import _load_payload
from services.ownership.errors import BoardUnavailable

logger = logging.getLogger(__name__)

# Rows per consensus list. Enough to be a ranking, short enough to read.
TOP_N = 10


def _load() -> dict[str, Any]:
    payload = _load_payload()
    if payload is None:
        raise BoardUnavailable("No ownership board has been built yet")
    return payload


def _entity_names(payload: dict[str, Any]) -> dict[str, str]:
    return {e["id"]: e["name"] for e in payload["board"]["entities"]}


def _asset_key(position: Position) -> str | None:
    """
    What counts as "the same asset" across holders.

    The symbol, when there is one: two filers reporting the same CUSIP resolve
    to AAPL and belong on one row. Without a symbol the label is used, which
    keeps unresolved holdings visible rather than silently merging them all
    into one bucket.
    """
    if position.symbol:
        return position.symbol.upper()
    return position.label.upper() or None


def _iter_positions(payload: dict[str, Any]):
    for entity_id, rows in payload.get("positions", {}).items():
        for raw in rows:
            try:
                yield entity_id, Position.model_validate(raw)
            except Exception:
                continue


def _iter_moves(payload: dict[str, Any]):
    for rows in payload.get("moves", {}).values():
        for raw in rows:
            try:
                yield Move.model_validate(raw)
            except Exception:
                continue


def most_held(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Assets ranked by how many tracked holders report them."""
    payload = payload or _load()
    names = _entity_names(payload)

    buckets: dict[str, dict[str, Any]] = {}
    for entity_id, position in _iter_positions(payload):
        key = _asset_key(position)
        if not key:
            continue
        bucket = buckets.setdefault(
            key,
            {
                "symbol": position.symbol,
                "label": position.label,
                "asset_class": position.asset_class,
                "holders": [],
                "total_value_usd": 0.0,
                "value_is_partial": False,
            },
        )
        if entity_id not in bucket["holders"]:
            bucket["holders"].append(entity_id)
        if position.value_usd is not None:
            bucket["total_value_usd"] += position.value_usd
        else:
            # Said out loud rather than folded in as zero.
            bucket["value_is_partial"] = True

    rows = [
        {
            **bucket,
            "holder_count": len(bucket["holders"]),
            "holder_names": [names.get(i, i) for i in bucket["holders"]],
        }
        for bucket in buckets.values()
    ]
    rows.sort(key=lambda r: (-r["holder_count"], -r["total_value_usd"]))
    return rows[:TOP_N]


def most_traded(payload: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Assets ranked by how many holders bought, and how many sold."""
    payload = payload or _load()

    bought: dict[str, dict[str, Any]] = {}
    sold: dict[str, dict[str, Any]] = {}
    buy_kinds = {"new", "add", "buy", "increase", "transfer_in"}
    sell_kinds = {"trim", "exit", "sell", "decrease", "transfer_out"}

    for move in _iter_moves(payload):
        side = bought if move.kind in buy_kinds else sold if move.kind in sell_kinds else None
        if side is None:
            continue
        key = (move.asset_symbol or move.asset_label).upper()
        bucket = side.setdefault(
            key,
            {
                "symbol": move.asset_symbol,
                "label": move.asset_label,
                "asset_class": move.asset_class,
                "holders": [],
                "total_value_usd": 0.0,
            },
        )
        if move.entity_name not in bucket["holders"]:
            bucket["holders"].append(move.entity_name)
        if move.value_usd_delta is not None:
            bucket["total_value_usd"] += abs(move.value_usd_delta)

    def rank(source: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [{**b, "holder_count": len(b["holders"])} for b in source.values()]
        rows.sort(key=lambda r: (-r["holder_count"], -r["total_value_usd"]))
        return rows[:TOP_N]

    return {"bought": rank(bought), "sold": rank(sold)}


def asset_owners(symbol: str) -> list[dict[str, Any]]:
    """
    Every tracked holder of one asset, largest position first.

    The inverse of the detail view, and free: the board already carries every
    position, so "who else owns this" is a filter rather than a query.
    """
    payload = _load()
    names = _entity_names(payload)
    wanted = symbol.strip().upper()

    rows: list[dict[str, Any]] = []
    for entity_id, position in _iter_positions(payload):
        if _asset_key(position) != wanted:
            continue
        rows.append(
            {
                "entity_id": entity_id,
                "entity_name": names.get(entity_id, entity_id),
                "label": position.label,
                "symbol": position.symbol,
                "quantity": position.quantity,
                "quantity_unit": position.quantity_unit,
                "value_usd": position.value_usd,
                "weight_pct": position.weight_pct,
                "delta_pct": position.delta_pct,
                "source": position.source.model_dump(mode="json"),
            }
        )

    rows.sort(key=lambda r: (r["value_usd"] is None, -(r["value_usd"] or 0.0)))
    return rows


async def watchlist_overlap(user_id: str | None) -> list[dict[str, Any]]:
    """
    Which of *this user's* watched symbols the tracked holders also hold.

    The user id is required rather than optional-in-practice: this used to call
    a `get_watchlists()` that read one shared file, so the panel showed the
    tracked holders overlaid on whatever watchlist happened to be on disk rather
    than on the caller's own. An anonymous caller gets an empty list, which is the
    honest answer to "what overlaps with your watchlist" when there is no you.

    Returns an empty list when nothing overlaps or the watchlist cannot be read.
    A panel with nothing to say should render nothing at all rather than an
    empty box explaining its own emptiness.
    """
    if not user_id:
        return []

    try:
        from services.watchlist_service import watchlist_symbols

        watched = await watchlist_symbols(user_id)
    except Exception as e:
        logger.info("Ownership: watchlist unavailable for overlap (%s)", e)
        return []

    # Watchlists store pair notation; the board stores bare tickers.
    symbols = {raw.upper().replace("USDT", "").replace("/", "") for raw in watched if raw}

    if not symbols:
        return []

    payload = _load()
    names = _entity_names(payload)
    overlap: dict[str, dict[str, Any]] = {}

    for entity_id, position in _iter_positions(payload):
        key = _asset_key(position)
        if key not in symbols:
            continue
        bucket = overlap.setdefault(
            key,
            {
                "symbol": position.symbol or key,
                "label": position.label,
                "asset_class": position.asset_class,
                "holders": [],
                "total_value_usd": 0.0,
            },
        )
        name = names.get(entity_id, entity_id)
        if name not in bucket["holders"]:
            bucket["holders"].append(name)
        if position.value_usd is not None:
            bucket["total_value_usd"] += position.value_usd

    rows = [{**b, "holder_count": len(b["holders"])} for b in overlap.values()]
    rows.sort(key=lambda r: -r["holder_count"])
    return rows


def consensus() -> dict[str, Any]:
    """Everything the cross-holder view shows, in one payload."""
    payload = _load()
    traded = most_traded(payload)
    return {
        "most_held": most_held(payload),
        "most_bought": traded["bought"],
        "most_sold": traded["sold"],
        "entity_count": len(payload["board"]["entities"]),
    }
