"""
The chains this board covers, and the facts about each that are not measurements.

Everything here is either a protocol constant or an endpoint. Anything that can
differ between two polls — height, fee, fullness, cadence — is measured by the
adapters and never stored here.

`target_block_seconds` is the cadence the protocol aims for, not an observation.
It earns its place because "the last block was 19 seconds ago" means nothing on
its own: the same 19 seconds is a stalled Ethereum and an idle Bitcoin. Every
value below was read off the live chain rather than out of documentation, and
that mattered — BSC has produced 0.45s blocks since the 2025 upgrades, while
most references still quote the 3s it launched with.

`gas_ceiling` is the one flag that changes what may be reported. Arbitrum
publishes a `gasLimit` of 2^50, which is a sentinel rather than a capacity: a
recent block used 79,373 of 1,125,899,906,842,624, so `gasUsed / gasLimit` is
0.00001%. Rendering that as a fullness bar would show a permanently empty chain
and invite the reading that Arbitrum is idle. Chains marked False report no
fullness at all. A gap the UI labels is honest; a zero is not.

`l1_data_fee` marks the OP-stack rollups, whose execution fee is only part of
what a transaction costs — the rest is posting the data to Ethereum, which the
block header does not carry. See `evm.l1_data_fee_wei`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chain:
    key: str
    name: str
    #: Ticker of the coin fees are actually paid in — not the chain's brand. The
    #: three OP-stack/L2 entries all settle in ETH, which is what makes their
    #: fees directly comparable with mainnet's on the same row.
    symbol: str
    #: Which adapter reads it: "evm", "bitcoin", "solana" or "tron".
    family: str
    target_block_seconds: float
    explorer_block_url: str
    #: JSON-RPC endpoints, tried in order. Empty for families with a REST API.
    rpc_urls: tuple[str, ...] = ()
    #: Whether `gasLimit` is a real capacity. See the module docstring.
    gas_ceiling: bool = True
    #: Whether the chain also charges for posting its data to Ethereum.
    l1_data_fee: bool = False
    #: Leading characters of the block hash that encode the block *height*
    #: rather than the digest, and which a short label has to skip.
    #:
    #: Only TRON has any. Its `blockID` is the header hash with the first eight
    #: bytes overwritten by the zero-padded block number, so sixteen of its
    #: sixty-four hex characters are the height — a number the column already
    #: prints in decimal beside it. A six-character label taken off the front is
    #: therefore the same string for sixteen consecutive blocks, which is the
    #: one thing a per-block label must not be. Verified against live blocks
    #: 85,433,201 through 85,433,204: every prefix matched `f"{height:016x}"`.
    hash_height_prefix_chars: int = 0


# Gas a plain native-value transfer costs on every EVM chain. Fixed by the
# protocol, not by the network's load, which is what makes it the honest unit
# for "what does it cost to move money here right now" — the same work priced
# eight different ways.
EVM_TRANSFER_GAS = 21_000

# Bitcoin's equivalent: a one-input, two-output P2WPKH spend, which is what an
# ordinary wallet broadcasts. Fees there are quoted per virtual byte, so the
# comparable number is a size rather than a gas count.
BTC_TRANSFER_VBYTES = 141

# Solana charges per signature and ignores load entirely, so the fee floor for a
# one-signature transfer is a constant. Priority fees exist but are optional and
# are not what a plain transfer pays.
SOLANA_LAMPORTS_PER_SIGNATURE = 5_000
LAMPORTS_PER_SOL = 1_000_000_000

# Ordered as the board renders them: Bitcoin and Ethereum first because they are
# the two the rest are read against, then the L2s that settle onto Ethereum,
# then the independent L1s.
CHAINS: tuple[Chain, ...] = (
    Chain(
        key="bitcoin",
        name="Bitcoin",
        symbol="BTC",
        family="bitcoin",
        target_block_seconds=600.0,
        explorer_block_url="https://mempool.space/block/",
    ),
    Chain(
        key="ethereum",
        name="Ethereum",
        symbol="ETH",
        family="evm",
        target_block_seconds=12.0,
        explorer_block_url="https://etherscan.io/block/",
        rpc_urls=("https://ethereum-rpc.publicnode.com",),
    ),
    Chain(
        key="base",
        name="Base",
        symbol="ETH",
        family="evm",
        target_block_seconds=2.0,
        explorer_block_url="https://basescan.org/block/",
        rpc_urls=("https://base-rpc.publicnode.com", "https://mainnet.base.org"),
        l1_data_fee=True,
    ),
    Chain(
        key="arbitrum",
        name="Arbitrum One",
        symbol="ETH",
        family="evm",
        target_block_seconds=0.25,
        explorer_block_url="https://arbiscan.io/block/",
        rpc_urls=("https://arb1.arbitrum.io/rpc",),
        # 2^50, not a capacity. See the module docstring.
        gas_ceiling=False,
    ),
    Chain(
        key="optimism",
        name="OP Mainnet",
        symbol="ETH",
        family="evm",
        target_block_seconds=2.0,
        explorer_block_url="https://optimistic.etherscan.io/block/",
        rpc_urls=("https://mainnet.optimism.io",),
        l1_data_fee=True,
    ),
    Chain(
        key="bsc",
        name="BNB Chain",
        symbol="BNB",
        family="evm",
        # Measured, not quoted. See the module docstring.
        target_block_seconds=0.45,
        explorer_block_url="https://bscscan.com/block/",
        rpc_urls=("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.binance.org"),
    ),
    Chain(
        key="solana",
        name="Solana",
        symbol="SOL",
        family="solana",
        target_block_seconds=0.4,
        explorer_block_url="https://solscan.io/block/",
        # publicnode first, and the order is not cosmetic: Solana's own public
        # endpoint rate-limits hard, and this adapter spends four calls a
        # refresh. A run of ordinary polling had `api.mainnet-beta` answering
        # 429 to the stream while still serving epoch info, which cost the card
        # its load bar. publicnode served the same window without complaint and
        # is the vendor this project already leans on for Ethereum and BNB.
        rpc_urls=(
            "https://solana-rpc.publicnode.com",
            "https://api.mainnet-beta.solana.com",
        ),
    ),
    Chain(
        key="tron",
        name="TRON",
        symbol="TRX",
        family="tron",
        target_block_seconds=3.0,
        explorer_block_url="https://tronscan.org/#/block/",
        hash_height_prefix_chars=16,
    ),
)

BY_KEY: dict[str, Chain] = {c.key: c for c in CHAINS}

# Every coin a fee on this board can be denominated in. Priced once per refresh
# rather than per chain, so the five L2/L1 rows that all settle in ETH cost one
# price lookup between them rather than five.
FEE_SYMBOLS: tuple[str, ...] = tuple(sorted({c.symbol for c in CHAINS}))
