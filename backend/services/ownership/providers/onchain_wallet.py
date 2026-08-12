"""
Labelled on-chain wallets, read through Blockscout.

Blockscout rather than Etherscan, which is the obvious choice and the wrong one
here: Etherscan's V1 API is retired, its `addresstokenbalance` endpoint moved
behind a paid plan, and its address nametags — the thing that makes a wallet
mean something — are Pro Plus only. Blockscout answers all three keyless, and
returns the USD rate inside the balance payload, so no second price lookup is
needed and the value cannot drift from the balance it belongs to.

The vocabulary here is deliberately weaker than elsewhere on the board. Coins
leaving a wallet may be a sale, a move to custody, or a shuffle between two
addresses the same person owns, and the chain does not say which. So these are
`transfer_in` / `transfer_out`, never buy or sell, and they are rendered in a
neutral colour. Publishing "Vitalik sold" on the strength of an outbound
transfer would be inventing a motive.

Dust is dropped, not summed. An address that has been airdropped four hundred
worthless tokens is not holding four hundred positions, and a table that says
so buries the three that matter.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from models.ownership import Position, SourceRef
from services import http_client
from services.ownership.providers.base import EntityConfig, ProviderResult

logger = logging.getLogger(__name__)

KIND = "onchain"

BLOCKSCOUT_BASE = "https://eth.blockscout.com/api/v2"
EXPLORER_BASE = "https://eth.blockscout.com/address"

# Below this a holding is airdrop noise rather than a position.
MIN_POSITION_USD = 25_000.0
# Ceiling per wallet after the dust filter.
MAX_POSITIONS = 25
REQUEST_TIMEOUT = 25.0


def _from_wei(raw: Any, decimals: Any) -> float | None:
    """Token amounts arrive as integer strings in the token's own base units."""
    try:
        value = int(str(raw))
        places = int(decimals) if decimals is not None else 18
    except (TypeError, ValueError):
        return None
    return value / (10**places)


def _rate(raw: Any) -> float | None:
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _position(
    key: str,
    label: str,
    symbol: str | None,
    amount: float,
    rate: float | None,
    address: str,
    retrieved_at: datetime,
) -> Position:
    value = amount * rate if rate is not None else None
    return Position(
        key=key,
        label=label,
        symbol=symbol,
        asset_class="crypto",
        quantity=amount,
        quantity_unit=symbol or "tokens",
        value_usd=value,
        # The chain reports the balance; the dollar figure is that balance
        # multiplied by a rate Blockscout supplied. Nobody published the total.
        value_basis="marked" if value is not None else "unknown",
        price_usd=rate,
        priced_at=retrieved_at if value is not None else None,
        source=SourceRef(
            kind=KIND,
            label="on-chain",
            url=f"{EXPLORER_BASE}/{address}",
            # A balance is true at the moment it is read, so unlike a filing the
            # retrieval time *is* the as-of time.
            as_of=retrieved_at.date(),
            retrieved_at=retrieved_at,
        ),
    )


async def _native_balance(address: str, retrieved_at: datetime) -> Position | None:
    payload = await http_client.get_json(
        f"{BLOCKSCOUT_BASE}/addresses/{address}", timeout=REQUEST_TIMEOUT
    )
    if not isinstance(payload, dict):
        return None

    amount = _from_wei(payload.get("coin_balance"), 18)
    if amount is None or amount <= 0:
        return None
    return _position(
        "ethereum",
        "Ethereum",
        "ETH",
        amount,
        _rate(payload.get("exchange_rate")),
        address,
        retrieved_at,
    )


async def _token_balances(address: str, retrieved_at: datetime) -> list[Position]:
    payload = await http_client.get_json(
        f"{BLOCKSCOUT_BASE}/addresses/{address}/token-balances", timeout=REQUEST_TIMEOUT
    )
    if not isinstance(payload, list):
        return []

    positions: list[Position] = []
    for entry in payload:
        token = entry.get("token") if isinstance(entry, dict) else None
        if not isinstance(token, dict):
            continue
        # NFTs have no meaningful fungible balance; a floor price is a guess.
        if (token.get("type") or "").upper() not in {"ERC-20", ""}:
            continue

        amount = _from_wei(entry.get("value"), token.get("decimals"))
        rate = _rate(token.get("exchange_rate"))
        if amount is None or amount <= 0 or rate is None:
            continue

        value = amount * rate
        if value < MIN_POSITION_USD:
            continue

        address_key = token.get("address") or token.get("address_hash") or token.get("symbol")
        positions.append(
            _position(
                f"erc20:{address_key}",
                token.get("name") or token.get("symbol") or "Unknown token",
                token.get("symbol"),
                amount,
                rate,
                address,
                retrieved_at,
            )
        )

    positions.sort(key=lambda p: -(p.value_usd or 0.0))
    return positions[:MAX_POSITIONS]


async def fetch_label(address: str) -> str | None:
    """
    Blockscout's own name for an address, if it has one.

    Used to check a curated label against the chain's rather than to replace it:
    a wallet we call "Ethereum Foundation" that the explorer calls something
    else is worth knowing about before it reaches the page.
    """
    try:
        payload = await http_client.get_json(
            "https://metadata.services.blockscout.com/api/v1/metadata",
            params={"addresses": address, "chainId": 1},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception:
        return None

    entry = (payload or {}).get("addresses", {}).get(address) if isinstance(payload, dict) else None
    for tag in (entry or {}).get("tags", []):
        if tag.get("tagType") == "name":
            return tag.get("name")
    return None


class OnChainWalletProvider:
    """ETH and ERC-20 balances for curated addresses."""

    kind: str = KIND
    timeout: float = 60.0

    async def fetch(self, entity: EntityConfig) -> ProviderResult:
        config = entity.sources.get(KIND)
        if not config:
            return ProviderResult.skipped(KIND)

        address = config.get("address")
        if not isinstance(address, str) or not address.startswith("0x"):
            return ProviderResult.failed(KIND, "registry entry needs an `address`")

        retrieved_at = datetime.now(UTC)
        positions: list[Position] = []
        problems: list[str] = []

        try:
            native = await _native_balance(address, retrieved_at)
            if native:
                positions.append(native)
        except Exception as e:
            problems.append(f"native balance: {e}")

        try:
            positions.extend(await _token_balances(address, retrieved_at))
        except Exception as e:
            problems.append(f"token balances: {e}")

        if not positions:
            return ProviderResult.failed(
                KIND, "; ".join(problems) or "no balances above the dust threshold"
            )

        positions.sort(key=lambda p: -(p.value_usd or 0.0))
        return ProviderResult(
            kind=KIND,
            ok=True,
            positions=positions,
            as_of=retrieved_at,
            error="; ".join(problems) or None,
        )
