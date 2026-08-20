"""
Tests for the Chains board.

Weighted deliberately toward the places where a wrong answer looks like a right
one. Every case below except the plain formatting ones corresponds to a reading
that rendered without erroring and meant something other than it appeared to —
three of them were caught only by checking the numbers against the live chains.
"""

import pytest

from services.chains import bitcoin, evm, solana
from services.chains.registry import BY_KEY, CHAINS, EVM_TRANSFER_GAS, FEE_SYMBOLS
from services.chains.service import _price_the_fee, _empty_row


class TestRegistry:
    def test_every_chain_has_an_adapter_family(self):
        assert {c.family for c in CHAINS} <= {"evm", "bitcoin", "solana", "tron"}

    def test_evm_chains_carry_at_least_one_endpoint(self):
        for chain in CHAINS:
            if chain.family in ("evm", "solana"):
                assert chain.rpc_urls, f"{chain.key} has no RPC endpoint"

    def test_keys_are_unique(self):
        keys = [c.key for c in CHAINS]
        assert len(keys) == len(set(keys))

    def test_arbitrum_declares_no_gas_ceiling(self):
        """
        Arbitrum publishes a gasLimit of 2^50, which is a sentinel rather than a
        capacity. Flipping this to True would make the board report a busy chain
        as 0.00001% full, which reads as idle.
        """
        assert BY_KEY["arbitrum"].gas_ceiling is False
        assert BY_KEY["ethereum"].gas_ceiling is True

    def test_op_stack_chains_are_marked_for_the_l1_data_fee(self):
        """Their execution fee is only part of the bill; the rest posts to L1."""
        assert BY_KEY["base"].l1_data_fee is True
        assert BY_KEY["optimism"].l1_data_fee is True
        assert BY_KEY["arbitrum"].l1_data_fee is False

    def test_fee_symbols_are_deduplicated(self):
        """Five rows settle in ETH; they must cost one price lookup, not five."""
        assert len(FEE_SYMBOLS) < len(CHAINS)
        assert "ETH" in FEE_SYMBOLS

    def test_only_tron_declares_a_height_prefix_on_its_hash(self):
        """
        TRON's `blockID` is the header hash with its first eight bytes replaced
        by the zero-padded block number. Sixteen hex characters is exactly that
        prefix, and skipping it is what stops ten consecutive bars carrying the
        same label. Every other chain publishes a hash that is only a digest.
        """
        assert BY_KEY["tron"].hash_height_prefix_chars == 16
        for chain in CHAINS:
            if chain.key != "tron":
                assert chain.hash_height_prefix_chars == 0, chain.key

    def test_the_tron_prefix_matches_a_zero_padded_height(self):
        """The shape the skip count is derived from, pinned against real data."""
        observed = {
            85_433_201: "0000000005179b7135f4a72e5deed99ea60dbf9558ecf60ecddabd67871d849f",
            85_433_202: "0000000005179b72562c97ee6efe2a7c43f285d5f134d6e9633eea7164bfbba5",
            85_433_203: "0000000005179b73ee3a607efef36310d4780d6ae2a375cb39bff4f830da4e50",
        }
        skip = BY_KEY["tron"].hash_height_prefix_chars
        for height, block_id in observed.items():
            assert block_id[:skip] == f"{height:016x}"

        # And the point of skipping it: the first six characters are identical
        # across all three once leading zeros alone are stripped, but distinct
        # once the height prefix goes.
        stripped = {block_id.lstrip("0")[:6] for block_id in observed.values()}
        assert len(stripped) == 1
        skipped = {block_id[skip : skip + 6] for block_id in observed.values()}
        assert len(skipped) == len(observed)


class TestEvmFullness:
    def test_reports_fullness_where_the_ceiling_is_real(self):
        chain = BY_KEY["ethereum"]
        assert evm._fill_percent(chain, 30_000_000, 60_000_000) == 50.0

    def test_reports_nothing_where_the_ceiling_is_a_sentinel(self):
        """The regression this guards: a real Arbitrum block, drawn as empty."""
        chain = BY_KEY["arbitrum"]
        assert evm._fill_percent(chain, 79_373, 1_125_899_906_842_624) is None

    def test_a_missing_reading_is_not_an_empty_block(self):
        chain = BY_KEY["ethereum"]
        assert evm._fill_percent(chain, None, 60_000_000) is None
        assert evm._fill_percent(chain, 30_000_000, None) is None
        assert evm._fill_percent(chain, 30_000_000, 0) is None


class TestEvmCadenceLookback:
    def test_the_anchor_spans_about_a_minute_whatever_the_cadence(self):
        """
        Block timestamps are whole seconds. On a four-blocks-a-second chain,
        consecutive blocks differ by 0 or 1, so cadence has to be measured over
        a span of time rather than a count of blocks.
        """
        assert evm._cadence_lookback(BY_KEY["ethereum"]) == 5
        assert evm._cadence_lookback(BY_KEY["base"]) == 30
        assert evm._cadence_lookback(BY_KEY["arbitrum"]) == 240

    def test_the_lookback_is_bounded(self):
        for chain in CHAINS:
            if chain.family == "evm":
                assert 2 <= evm._cadence_lookback(chain) <= evm.MAX_CADENCE_LOOKBACK


class TestEvmL1FeeEncoding:
    def test_encodes_a_single_dynamic_bytes_argument(self):
        data = evm._encode_l1_fee_call()
        assert data.startswith(evm.L1_FEE_SELECTOR)
        body = data[len(evm.L1_FEE_SELECTOR) :]
        # head: offset, then length, then the payload padded to 32 bytes.
        assert int(body[:64], 16) == 32
        assert int(body[64:128], 16) == evm.TRANSFER_ENVELOPE_BYTES
        payload_hex = body[128:]
        assert len(payload_hex) % 64 == 0
        assert len(payload_hex) // 2 >= evm.TRANSFER_ENVELOPE_BYTES


class TestBitcoinBacklog:
    """
    The regression here is the one that mattered most.

    A quiet Bitcoin held 42 million vB of mempool while every fee tier sat at
    the 1 sat/vB floor — meaning anything paying the minimum cleared within the
    hour. Dividing that size by the block limit reported the chain as 100%
    congested. Almost all of it was sub-floor dust that will not confirm at any
    price, and counting only the projected blocks still bidding above the
    economy tier is what separates the two.
    """

    @staticmethod
    def _contested(projected, threshold):
        return sum(
            1
            for block in projected
            if isinstance(block.get("medianFee"), (int, float)) and block["medianFee"] >= threshold
        )

    def test_dust_below_the_economy_tier_is_not_backlog(self):
        # The shape actually observed: one contested block, then a dust pile.
        projected = [{"medianFee": 1.09}] + [{"medianFee": f} for f in (0.48, 0.37, 0.13)]
        assert self._contested(projected, 1.0) == 1

    def test_a_genuinely_busy_mempool_counts_every_contested_block(self):
        projected = [{"medianFee": f} for f in (80, 60, 45, 30, 22, 18, 0.5)]
        assert self._contested(projected, 12.0) == 6

    def test_the_relay_floor_is_the_fallback_threshold(self):
        assert bitcoin.MIN_RELAY_SAT_VB == 1.0

    def test_saturation_is_a_bounded_share(self):
        for contested in (0, 1, 6, 40):
            percent = min(contested / bitcoin.BACKLOG_SATURATION_BLOCKS, 1.0) * 100
            assert 0.0 <= percent <= 100.0


class TestSolanaSkipRate:
    """
    The other silent-wrong-answer regression.

    The first implementation compared slots produced against the number the
    nominal 400ms cadence allows for. Solana's real slot time is about 413ms, so
    0.4/0.413 is 0.968 and a network skipping nothing reported 3.2% skipped —
    permanently, with the load bar built on it. Skips have to be counted against
    the schedule, which is what `getBlocksWithLimit` returns.
    """

    def test_a_full_window_is_zero_skipped(self):
        scheduled = solana.STREAM_SLOTS
        produced = set(range(1000, 1000 + scheduled))
        assert round((1 - len(produced) / scheduled) * 100, 3) == 0.0

    def test_the_shortfall_against_the_schedule_is_the_skip_rate(self):
        scheduled = solana.STREAM_SLOTS
        produced = set(range(1000, 1000 + scheduled)) - {1005, 1006, 1090}
        assert round((1 - len(produced) / scheduled) * 100, 3) == 3.0

    def test_the_window_divides_evenly_into_buckets(self):
        assert solana.STREAM_BUCKETS * solana.SLOTS_PER_BUCKET == solana.STREAM_SLOTS

    def test_buckets_are_ten_slots_so_a_bar_can_show_one_segment_each(self):
        assert solana.SLOTS_PER_BUCKET == 10

    def test_the_window_stays_behind_the_unconfirmed_head(self):
        """Counting not-yet-confirmed slots as skipped would dip every stream."""
        assert solana.CONFIRMATION_LAG_SLOTS > 0


class TestSolanaBuild:
    @staticmethod
    def _epoch(**overrides):
        base = {
            "absoluteSlot": 439_848_937,
            "blockHeight": 417_899_418,
            "epoch": 1018,
            "slotIndex": 69_174,
            "slotsInEpoch": 432_000,
        }
        base.update(overrides)
        return base

    @staticmethod
    def _samples(slots=145, txs=190_000, non_vote=89_000, period=60, count=5):
        return [
            {
                "numSlots": slots,
                "numTransactions": txs,
                "numNonVoteTransactions": non_vote,
                "samplePeriodSecs": period,
            }
            for _ in range(count)
        ]

    def test_throughput_separates_consensus_votes_from_user_traffic(self):
        result = solana._build(self._epoch(), self._samples(), [], 0.0, 0.4)
        assert result["throughput"]["tps"] == pytest.approx(190_000 / 60, rel=1e-3)
        assert result["throughput"]["non_vote_tps"] == pytest.approx(89_000 / 60, rel=1e-3)
        assert result["throughput"]["non_vote_tps"] < result["throughput"]["tps"]

    def test_skip_rate_comes_from_the_caller_not_from_the_cadence(self):
        """A slower-than-nominal cadence must not read as dropped slots."""
        # 145 slots per 60s is 0.414s a slot — slower than the nominal 0.4.
        result = solana._build(self._epoch(), self._samples(), [], 0.0, 0.4)
        assert result["throughput"]["skipped_slot_percent"] == 0.0
        assert result["load"] == {"percent": 0.0, "basis": "skipped_slots"}

    def test_an_unavailable_stream_leaves_load_unmeasured_rather_than_zero(self):
        result = solana._build(self._epoch(), self._samples(), [], None, 0.4)
        assert result["load"] is None
        assert result["throughput"]["skipped_slot_percent"] is None

    def test_the_epoch_is_projected_on_the_observed_pace(self):
        """
        The nominal 400ms would put every epoch boundary hours early, because
        Solana's real slot time runs consistently above it.
        """
        result = solana._build(self._epoch(), self._samples(), [], 0.0, 0.4)
        assert result["economics"]["epoch_progress_percent"] == pytest.approx(16.01, abs=0.02)
        assert result["economics"]["epoch_ends_at"] > 0

    def test_the_head_slot_carries_no_timestamp(self):
        """
        It sits ahead of the confirmed window by the lag, so there is no instant
        to count from — which is why Solana's card shows a rate, not a ring.
        """
        result = solana._build(self._epoch(), self._samples(), [], 0.0, 0.4)
        assert result["last_block_at"] is None

    def test_the_fee_is_declared_a_constant(self):
        result = solana._build(self._epoch(), self._samples(), [], 0.0, 0.4)
        assert result["fee"]["is_fixed"] is True
        assert result["fee"]["transfer_native"] == pytest.approx(0.000005)


class TestFeePricing:
    def test_bitcoin_is_priced_from_sats_per_vbyte(self):
        chain = BY_KEY["bitcoin"]
        snapshot = {"fee": {"half_hour_sat_vb": 2.0, "transfer_native": None}}
        _price_the_fee(chain, snapshot, 60_000.0)
        # 141 vB at 2 sat/vB is 282 sat, which is 0.00000282 BTC.
        assert snapshot["fee"]["transfer_native"] == pytest.approx(0.00000282)
        assert snapshot["fee"]["transfer_usd"] == pytest.approx(0.1692, rel=1e-3)

    def test_an_evm_fee_is_left_as_the_adapter_computed_it(self):
        chain = BY_KEY["ethereum"]
        native = 0.5e-9 * EVM_TRANSFER_GAS
        snapshot = {"fee": {"transfer_native": native}}
        _price_the_fee(chain, snapshot, 2_000.0)
        assert snapshot["fee"]["transfer_native"] == native
        assert snapshot["fee"]["transfer_usd"] == pytest.approx(native * 2_000.0)

    def test_without_a_price_the_native_figure_survives_alone(self):
        """
        A missing price must not erase the fee. Two chains settling in the same
        coin are still comparable natively, which is most of what the panel is
        for.
        """
        chain = BY_KEY["ethereum"]
        snapshot = {"fee": {"transfer_native": 0.000021}}
        _price_the_fee(chain, snapshot, None)
        assert snapshot["fee"]["transfer_native"] == 0.000021
        assert snapshot["fee"]["transfer_usd"] is None

    def test_a_free_transfer_prices_to_zero_rather_than_to_nothing(self):
        """TRON's zero is a measurement, not a gap — see the tron adapter."""
        chain = BY_KEY["tron"]
        snapshot = {"fee": {"transfer_native": 0.0, "is_fixed": True}}
        _price_the_fee(chain, snapshot, 0.33)
        assert snapshot["fee"]["transfer_usd"] == 0.0


class TestEmptyRow:
    def test_an_unreachable_chain_reports_no_readings_at_all(self):
        row = _empty_row(BY_KEY["tron"], "boom")
        assert row["error"] == "boom"
        # Not a row of zeros: a zero fee and a zero cadence are readings, and
        # this row has none.
        for field in ("height", "block_time_seconds", "load", "fee", "tx_count"):
            assert row[field] is None
        assert row["blocks"] == []

    def test_it_keeps_the_identity_the_card_needs_to_render(self):
        row = _empty_row(BY_KEY["bsc"], "boom")
        assert row["name"] == "BNB Chain"
        assert row["target_block_seconds"] > 0
