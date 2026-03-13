"""
Tests for TimeAndSale WebSocket integration - TDD style.
Tests the parsing and handling of TimeAndSale events.
"""
import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil


class TestTimeAndSaleEventParsing:
    """Tests for parsing TimeAndSale events from dxFeed."""

    def test_parse_buy_event(self):
        """Should correctly parse BUY aggressor side."""
        from utils.tick_accumulator import parse_time_and_sale_event

        event = {
            "eventType": "TimeAndSale",
            "eventSymbol": ".SPXW260312C5700",
            "aggressorSide": "BUY",
            "size": 10,
            "price": 15.50,
            "time": 1710259200000
        }

        result = parse_time_and_sale_event(event)
        assert result["symbol"] == ".SPXW260312C5700"
        assert result["size"] == 10
        assert result["side"] == "BUY"
        assert result["price"] == 15.50

    def test_parse_sell_event(self):
        """Should correctly parse SELL aggressor side."""
        from utils.tick_accumulator import parse_time_and_sale_event

        event = {
            "eventType": "TimeAndSale",
            "eventSymbol": ".SPXW260312P5700",
            "aggressorSide": "SELL",
            "size": 25,
            "price": 8.25,
            "time": 1710259200000
        }

        result = parse_time_and_sale_event(event)
        assert result["side"] == "SELL"
        assert result["size"] == 25

    def test_parse_undefined_event(self):
        """Should handle UNDEFINED aggressor side."""
        from utils.tick_accumulator import parse_time_and_sale_event

        event = {
            "eventType": "TimeAndSale",
            "eventSymbol": ".SPXW260312C5700",
            "aggressorSide": "UNDEFINED",
            "size": 5,
            "price": 10.00,
        }

        result = parse_time_and_sale_event(event)
        assert result["side"] == "UNDEFINED"

    def test_parse_missing_aggressor_side(self):
        """Should default to UNDEFINED when aggressorSide is missing."""
        from utils.tick_accumulator import parse_time_and_sale_event

        event = {
            "eventType": "TimeAndSale",
            "eventSymbol": ".SPXW260312C5700",
            "size": 5,
            "price": 10.00,
        }

        result = parse_time_and_sale_event(event)
        assert result["side"] == "UNDEFINED"

    def test_parse_null_aggressor_side(self):
        """Should handle null aggressorSide."""
        from utils.tick_accumulator import parse_time_and_sale_event

        event = {
            "eventType": "TimeAndSale",
            "eventSymbol": ".SPXW260312C5700",
            "aggressorSide": None,
            "size": 5,
            "price": 10.00,
        }

        result = parse_time_and_sale_event(event)
        assert result["side"] == "UNDEFINED"

    def test_parse_invalid_event_type(self):
        """Should return None for non-TimeAndSale events."""
        from utils.tick_accumulator import parse_time_and_sale_event

        event = {
            "eventType": "Trade",
            "eventSymbol": ".SPXW260312C5700",
            "price": 10.00,
        }

        result = parse_time_and_sale_event(event)
        assert result is None


class TestTickAccumulatorIntegration:
    """Tests for accumulator integration with WebSocket events."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_process_feed_data_message(self, temp_data_dir):
        """Should process FEED_DATA message with TimeAndSale events."""
        from utils.tick_accumulator import TickDataAccumulator, process_feed_data

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)

        feed_msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260312C5700",
                    "aggressorSide": "BUY",
                    "size": 50,
                    "price": 15.50,
                },
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260312C5700",
                    "aggressorSide": "SELL",
                    "size": 20,
                    "price": 15.40,
                },
            ]
        }

        process_feed_data(feed_msg, acc)

        breakdown = acc.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["buy_volume"] == 50
        assert breakdown["sell_volume"] == 20

    def test_process_mixed_event_types(self, temp_data_dir):
        """Should only process TimeAndSale events, ignore others."""
        from utils.tick_accumulator import TickDataAccumulator, process_feed_data

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)

        feed_msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "Greeks",
                    "eventSymbol": ".SPXW260312C5700",
                    "gamma": 0.05,
                },
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260312C5700",
                    "aggressorSide": "BUY",
                    "size": 100,
                    "price": 15.50,
                },
                {
                    "eventType": "Trade",
                    "eventSymbol": ".SPXW260312C5700",
                    "price": 15.50,
                    "dayVolume": 5000,
                },
            ]
        }

        process_feed_data(feed_msg, acc)

        breakdown = acc.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["buy_volume"] == 100
        assert breakdown["sell_volume"] == 0

    def test_process_summary_sets_opening_oi(self, temp_data_dir):
        """Should set opening OI from Summary events."""
        from utils.tick_accumulator import TickDataAccumulator, process_feed_data

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)

        feed_msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "Summary",
                    "eventSymbol": ".SPXW260312C5700",
                    "openInterest": 5000,
                },
            ]
        }

        process_feed_data(feed_msg, acc, set_opening_oi=True)

        breakdown = acc.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["opening_oi"] == 5000


class TestSubscriptionGeneration:
    """Tests for generating TimeAndSale subscriptions."""

    def test_generate_subscription_list(self):
        """Should generate subscription list with TimeAndSale."""
        from utils.tick_accumulator import generate_tick_subscriptions

        symbols = [".SPXW260312C5700", ".SPXW260312P5700"]
        subs = generate_tick_subscriptions(symbols)

        assert len(subs) == 2
        assert all(s["type"] == "TimeAndSale" for s in subs)
        assert {s["symbol"] for s in subs} == set(symbols)

    def test_empty_symbol_list(self):
        """Should handle empty symbol list."""
        from utils.tick_accumulator import generate_tick_subscriptions

        subs = generate_tick_subscriptions([])
        assert subs == []
