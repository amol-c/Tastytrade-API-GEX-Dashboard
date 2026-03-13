"""
Tests for Delta Flow Calculator and History Tracker.

TDD: These tests are written FIRST, before implementation.

Delta Flow measures dealer hedging from customer trades:
- Customer buys call (+delta) → dealer sells call → dealer SELLS to hedge
- Customer buys put (-delta) → dealer sells put → dealer BUYS to hedge
- Customer sells call (-delta) → dealer buys call → dealer BUYS to hedge
- Customer sells put (+delta) → dealer buys put → dealer SELLS to hedge

Sign convention (aligned with Charm/Vanna):
- Positive ES = dealers BUY underlying
- Negative ES = dealers SELL underlying
"""
import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch


class TestDeltaFlowCalculation:
    """Tests for delta flow calculation logic."""

    def test_buy_call_increases_customer_delta(self):
        """Buying calls increases customer delta (customer gains +delta)."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.process_trade(
            symbol=".SPXW260313C6000",
            aggressor_side="BUY",
            contracts=100,
            delta=0.50,
        )
        # 100 contracts × 0.50 delta × 100 multiplier = +5,000
        assert calc.cumulative_customer_delta == 5000

    def test_buy_put_decreases_customer_delta(self):
        """Buying puts decreases customer delta (puts have negative delta)."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.process_trade(
            symbol=".SPXW260313P5900",
            aggressor_side="BUY",
            contracts=100,
            delta=-0.40,
        )
        # 100 × (-0.40) × 100 = -4,000
        assert calc.cumulative_customer_delta == -4000

    def test_sell_call_decreases_customer_delta(self):
        """Selling calls decreases customer delta (customer loses +delta)."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.process_trade(
            symbol=".SPXW260313C6000",
            aggressor_side="SELL",
            contracts=100,
            delta=0.50,
        )
        # -(100 × 0.50 × 100) = -5,000
        assert calc.cumulative_customer_delta == -5000

    def test_sell_put_increases_customer_delta(self):
        """Selling puts increases customer delta (customer loses -delta = gains +delta)."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.process_trade(
            symbol=".SPXW260313P5900",
            aggressor_side="SELL",
            contracts=100,
            delta=-0.40,
        )
        # -(100 × (-0.40) × 100) = +4,000
        assert calc.cumulative_customer_delta == 4000

    def test_cumulative_multiple_trades(self):
        """Multiple trades accumulate correctly."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()

        # Buy 100 calls at 0.5 delta = +5000
        calc.process_trade("C1", "BUY", 100, 0.50)

        # Sell 50 puts at -0.4 delta = +2000
        calc.process_trade("P1", "SELL", 50, -0.40)

        # Buy 200 puts at -0.3 delta = -6000
        calc.process_trade("P2", "BUY", 200, -0.30)

        # Total: 5000 + 2000 - 6000 = 1000
        assert calc.cumulative_customer_delta == 1000
        assert calc.trade_count == 3

    def test_zero_delta_trade_no_effect(self):
        """Trade with zero delta has no effect."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.process_trade("C1", "BUY", 100, 0.0)
        assert calc.cumulative_customer_delta == 0

    def test_reset_clears_state(self):
        """Reset clears cumulative delta and trade count."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.process_trade("C1", "BUY", 100, 0.50)
        assert calc.cumulative_customer_delta == 5000

        calc.reset()
        assert calc.cumulative_customer_delta == 0
        assert calc.trade_count == 0


class TestESEquivalentCalculation:
    """Tests for ES futures equivalent conversion."""

    def test_es_equivalent_positive_delta(self):
        """Positive customer delta → negative ES (dealers SELL)."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.cumulative_customer_delta = 5_000  # +5K delta (100 calls × 0.50 × 100)

        es = calc.get_dealer_hedge_es(spot_price=6000)
        # ES = -delta / 50 = -5000 / 50 = -100
        # Customer long → dealer short → dealer SELLS → negative ES
        assert es == pytest.approx(-100)

    def test_es_equivalent_negative_delta(self):
        """Negative customer delta → positive ES (dealers BUY)."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.cumulative_customer_delta = -5_000  # -5K delta

        es = calc.get_dealer_hedge_es(spot_price=6000)
        # ES = -(-5000) / 50 = +100
        # Customer short → dealer long → dealer BUYS → positive ES
        assert es == pytest.approx(100)

    def test_es_equivalent_zero_spot_returns_zero(self):
        """Zero spot price returns zero to avoid division error."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.cumulative_customer_delta = 300_000

        es = calc.get_dealer_hedge_es(spot_price=0)
        assert es == 0

    def test_es_equivalent_zero_delta_returns_zero(self):
        """Zero customer delta returns zero ES."""
        from utils.delta_flow_calculator import DeltaFlowCalculator

        calc = DeltaFlowCalculator()
        calc.cumulative_customer_delta = 0

        es = calc.get_dealer_hedge_es(spot_price=6000)
        assert es == 0


class TestFlowDirection:
    """Tests for flow direction determination."""

    def test_customer_long_gives_sell_direction(self):
        """Customer net long delta → dealers SELL to hedge."""
        from utils.delta_flow_calculator import DeltaFlowCalculator, DeltaFlowDirection

        calc = DeltaFlowCalculator(neutral_threshold=500_000)
        calc.cumulative_customer_delta = 1_000_000

        assert calc.get_flow_direction() == DeltaFlowDirection.SELL

    def test_customer_short_gives_buy_direction(self):
        """Customer net short delta → dealers BUY to hedge."""
        from utils.delta_flow_calculator import DeltaFlowCalculator, DeltaFlowDirection

        calc = DeltaFlowCalculator(neutral_threshold=500_000)
        calc.cumulative_customer_delta = -1_000_000

        assert calc.get_flow_direction() == DeltaFlowDirection.BUY

    def test_small_delta_gives_neutral(self):
        """Small delta below threshold gives NEUTRAL."""
        from utils.delta_flow_calculator import DeltaFlowCalculator, DeltaFlowDirection

        calc = DeltaFlowCalculator(neutral_threshold=500_000)
        calc.cumulative_customer_delta = 100_000  # Below threshold

        assert calc.get_flow_direction() == DeltaFlowDirection.NEUTRAL

    def test_flow_direction_enum_values(self):
        """Flow direction enum has expected values."""
        from utils.delta_flow_calculator import DeltaFlowDirection

        assert DeltaFlowDirection.BUY.value == "BUY"
        assert DeltaFlowDirection.SELL.value == "SELL"
        assert DeltaFlowDirection.NEUTRAL.value == "NEUTRAL"


class TestDeltaFlowHistoryTracker:
    """Tests for delta flow history persistence."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_tracker_initialization(self, temp_data_dir):
        """Tracker initializes with empty history."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313")
            assert tracker.history == []

    def test_add_record(self, temp_data_dir):
        """Should add a record with correct fields."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313")
            record = tracker.add_record(
                spot_price=6000,
                cumulative_customer_delta=-5_000,  # -5K delta
                flow_direction='BUY',
                trade_count=150,
            )

            assert record['spot_price'] == 6000
            assert record['cumulative_delta'] == -5_000
            assert record['flow_direction'] == 'BUY'
            assert record['trade_count'] == 150
            # ES = -(-5000) / 50 = +100
            assert record['es_futures'] == pytest.approx(100, abs=0.5)
            assert 'timestamp' in record

    def test_es_futures_calculation_in_record(self, temp_data_dir):
        """Record includes correct ES futures calculation."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313")
            record = tracker.add_record(
                spot_price=6000,
                cumulative_customer_delta=5_000,  # Positive = SELL
                flow_direction='SELL',
                trade_count=100,
            )
            # ES = -5000 / 50 = -100 (dealers SELL)
            assert record['es_futures'] == pytest.approx(-100, abs=0.5)

    def test_persistence(self, temp_data_dir):
        """History persists to JSON and reloads."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            # Add record
            tracker1 = DeltaFlowHistoryTracker(expiry="260313")
            tracker1.add_record(
                spot_price=6000,
                cumulative_customer_delta=-300_000,
                flow_direction='BUY',
                trade_count=150,
            )

            # Create new tracker, should load history
            tracker2 = DeltaFlowHistoryTracker(expiry="260313")
            assert len(tracker2.history) == 1
            assert tracker2.history[0]['cumulative_delta'] == -300_000

    def test_get_latest(self, temp_data_dir):
        """Should return most recent record."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313")
            tracker.add_record(6000, -100_000, 'BUY', 50)
            tracker.add_record(6010, -200_000, 'BUY', 100)

            latest = tracker.get_latest()
            assert latest['cumulative_delta'] == -200_000
            assert latest['spot_price'] == 6010

    def test_get_latest_empty(self, temp_data_dir):
        """Should return None when no history."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313")
            assert tracker.get_latest() is None

    def test_max_records_limit(self, temp_data_dir):
        """Should trim to max_records."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313", max_records=5)

            for i in range(10):
                tracker.add_record(6000 + i, -100_000 * i, 'BUY', i * 10)

            assert len(tracker.history) == 5
            # Should keep the most recent
            assert tracker.history[0]['spot_price'] == 6005
            assert tracker.history[-1]['spot_price'] == 6009

    def test_get_es_futures_series(self, temp_data_dir):
        """Should return time series data for charting."""
        from utils.delta_flow_history import DeltaFlowHistoryTracker

        with patch('utils.delta_flow_history.DELTA_FLOW_FOLDER', temp_data_dir):
            tracker = DeltaFlowHistoryTracker(expiry="260313")
            tracker.add_record(6000, -150_000, 'BUY', 50)
            tracker.add_record(6010, -200_000, 'BUY', 100)

            series = tracker.get_es_futures_series()
            assert len(series) == 2
            assert 'timestamp' in series[0]
            assert 'es_futures' in series[0]
            assert 'spot_price' in series[0]
            assert 'flow' in series[0]


class TestDeltaWeightedTickMetrics:
    """Tests for delta-weighted tick data metrics."""

    def test_calculate_delta_bought(self):
        """Calculate total delta from buy-initiated trades."""
        from utils.delta_flow_calculator import calculate_delta_weighted_flow

        # Mock tick data: symbol -> {buy_volume, sell_volume}
        tick_data = {
            ".SPXW260313C6000": {"buy_volume": 100, "sell_volume": 50},
            ".SPXW260313P5900": {"buy_volume": 75, "sell_volume": 25},
        }

        # Mock greeks: symbol -> {delta}
        greeks_data = {
            ".SPXW260313C6000": {"delta": 0.50},
            ".SPXW260313P5900": {"delta": -0.40},
        }

        delta_bought, delta_sold = calculate_delta_weighted_flow(tick_data, greeks_data)

        # Call buys: 100 × 0.50 × 100 = +5,000
        # Put buys: 75 × (-0.40) × 100 = -3,000
        # Total bought: 5,000 + (-3,000) = 2,000
        assert delta_bought == pytest.approx(2000)

        # Call sells: 50 × 0.50 × 100 = 2,500 (negative for sold)
        # Put sells: 25 × (-0.40) × 100 = -1,000 (negative for sold)
        # Total sold: -(2,500) + -(-1,000) = -2,500 + 1,000 = -1,500
        assert delta_sold == pytest.approx(-1500)

    def test_missing_greeks_skipped(self):
        """Symbols without Greeks data are skipped."""
        from utils.delta_flow_calculator import calculate_delta_weighted_flow

        tick_data = {
            ".SPXW260313C6000": {"buy_volume": 100, "sell_volume": 50},
            ".SPXW260313C6100": {"buy_volume": 200, "sell_volume": 100},  # No greeks
        }

        greeks_data = {
            ".SPXW260313C6000": {"delta": 0.50},
            # C6100 missing
        }

        delta_bought, delta_sold = calculate_delta_weighted_flow(tick_data, greeks_data)

        # Only C6000 counted
        assert delta_bought == pytest.approx(5000)  # 100 × 0.50 × 100
        assert delta_sold == pytest.approx(-2500)  # -(50 × 0.50 × 100)


class TestWebSocketDeltaFlowIntegration:
    """Tests for WebSocket TimeAndSale → DeltaFlowCalculator integration."""

    def test_process_feed_data_with_delta_calculator(self):
        """process_feed_data updates delta calculator when provided."""
        from utils.tick_accumulator import (
            TickDataAccumulator,
            process_feed_data,
        )
        from utils.delta_flow_calculator import DeltaFlowCalculator

        accumulator = TickDataAccumulator(expiry="260313")
        calculator = DeltaFlowCalculator()

        # Mock Greeks data
        greeks_data = {
            ".SPXW260313C6000": {"delta": 0.50},
        }

        # Simulate FEED_DATA message with TimeAndSale
        msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260313C6000",
                    "size": 100,
                    "aggressorSide": "BUY",
                    "price": 10.5,
                }
            ],
        }

        process_feed_data(
            msg,
            accumulator,
            delta_calculator=calculator,
            greeks_data=greeks_data,
        )

        # Tick accumulator should have the volume
        breakdown = accumulator.get_volume_breakdown(".SPXW260313C6000")
        assert breakdown["buy_volume"] == 100

        # Delta calculator should have the delta
        # 100 contracts × 0.50 delta × 100 = 5,000
        assert calculator.cumulative_customer_delta == 5000
        assert calculator.trade_count == 1

    def test_process_feed_data_without_greeks_skips_delta(self):
        """Symbols without Greeks are skipped for delta calculation."""
        from utils.tick_accumulator import (
            TickDataAccumulator,
            process_feed_data,
        )
        from utils.delta_flow_calculator import DeltaFlowCalculator

        accumulator = TickDataAccumulator(expiry="260313")
        calculator = DeltaFlowCalculator()

        # Greeks for different symbol
        greeks_data = {
            ".SPXW260313C6100": {"delta": 0.40},
        }

        msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260313C6000",  # Not in greeks
                    "size": 100,
                    "aggressorSide": "BUY",
                    "price": 10.5,
                }
            ],
        }

        process_feed_data(
            msg,
            accumulator,
            delta_calculator=calculator,
            greeks_data=greeks_data,
        )

        # Tick accumulator still updated
        breakdown = accumulator.get_volume_breakdown(".SPXW260313C6000")
        assert breakdown["buy_volume"] == 100

        # Delta calculator NOT updated (no greeks for symbol)
        assert calculator.cumulative_customer_delta == 0
        assert calculator.trade_count == 0

    def test_process_feed_data_multiple_trades(self):
        """Multiple trades accumulate in delta calculator."""
        from utils.tick_accumulator import (
            TickDataAccumulator,
            process_feed_data,
        )
        from utils.delta_flow_calculator import DeltaFlowCalculator

        accumulator = TickDataAccumulator(expiry="260313")
        calculator = DeltaFlowCalculator()

        greeks_data = {
            ".SPXW260313C6000": {"delta": 0.50},
            ".SPXW260313P5900": {"delta": -0.40},
        }

        msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260313C6000",
                    "size": 100,
                    "aggressorSide": "BUY",
                    "price": 10.5,
                },
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260313P5900",
                    "size": 50,
                    "aggressorSide": "BUY",
                    "price": 5.0,
                },
            ],
        }

        process_feed_data(
            msg,
            accumulator,
            delta_calculator=calculator,
            greeks_data=greeks_data,
        )

        # Call buy: 100 × 0.50 × 100 = +5,000
        # Put buy: 50 × (-0.40) × 100 = -2,000
        # Total: 3,000
        assert calculator.cumulative_customer_delta == 3000
        assert calculator.trade_count == 2

    def test_tick_manager_has_delta_calculator(self):
        """TickDataManager should have optional delta_flow_calculator."""
        from utils.tick_data_manager import TickDataManager
        from utils.delta_flow_calculator import DeltaFlowCalculator

        manager = TickDataManager(expiry="260313", auto_load=False)

        # Should support attaching a delta calculator
        calculator = DeltaFlowCalculator()
        manager.set_delta_calculator(calculator)

        assert manager.delta_calculator is calculator

    def test_tick_manager_processes_with_delta(self):
        """TickDataManager processes delta when calculator and greeks set."""
        from utils.tick_data_manager import TickDataManager
        from utils.delta_flow_calculator import DeltaFlowCalculator

        manager = TickDataManager(expiry="260313", auto_load=False)
        calculator = DeltaFlowCalculator()
        manager.set_delta_calculator(calculator)

        greeks_data = {
            ".SPXW260313C6000": {"delta": 0.50},
        }
        manager.set_greeks_data(greeks_data)

        msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260313C6000",
                    "size": 100,
                    "aggressorSide": "BUY",
                    "price": 10.5,
                }
            ],
        }

        manager.process_message(msg)

        # Delta should be updated
        assert calculator.cumulative_customer_delta == 5000

    def test_tick_manager_get_delta_flow_es(self):
        """TickDataManager provides delta flow ES equivalent."""
        from utils.tick_data_manager import TickDataManager
        from utils.delta_flow_calculator import DeltaFlowCalculator

        manager = TickDataManager(expiry="260313", auto_load=False)
        calculator = DeltaFlowCalculator()
        calculator.cumulative_customer_delta = -5000  # Customer short
        manager.set_delta_calculator(calculator)

        es = manager.get_delta_flow_es(spot_price=6000)
        # ES = -(-5000) / 50 = +100 (dealers BUY)
        assert es == 100

    def test_tick_manager_get_delta_flow_direction(self):
        """TickDataManager provides delta flow direction."""
        from utils.tick_data_manager import TickDataManager
        from utils.delta_flow_calculator import DeltaFlowCalculator, DeltaFlowDirection

        manager = TickDataManager(expiry="260313", auto_load=False)
        calculator = DeltaFlowCalculator(neutral_threshold=500_000)
        calculator.cumulative_customer_delta = 1_000_000  # Customer long
        manager.set_delta_calculator(calculator)

        direction = manager.get_delta_flow_direction()
        # Customer long → dealers SELL
        assert direction == DeltaFlowDirection.SELL

    def test_tick_manager_no_calculator_returns_defaults(self):
        """TickDataManager returns defaults when no calculator set."""
        from utils.tick_data_manager import TickDataManager
        from utils.delta_flow_calculator import DeltaFlowDirection

        manager = TickDataManager(expiry="260313", auto_load=False)

        es = manager.get_delta_flow_es(spot_price=6000)
        assert es == 0

        direction = manager.get_delta_flow_direction()
        assert direction == DeltaFlowDirection.NEUTRAL
