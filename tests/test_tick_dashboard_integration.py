"""
Tests for tick accumulator dashboard integration - TDD style.
Tests the TickDataManager component that manages accumulator lifecycle.
"""
import pytest
import tempfile
import shutil
from unittest.mock import MagicMock, patch


class TestTickDataManager:
    """Tests for TickDataManager - manages accumulator lifecycle."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_manager_initialization(self, temp_data_dir):
        """Manager should initialize with expiry and create accumulator."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        assert manager.expiry == "260312"
        assert manager.accumulator is not None

    def test_manager_loads_existing_data(self, temp_data_dir):
        """Manager should load existing tick data on init."""
        from utils.tick_accumulator import TickDataAccumulator
        from utils.tick_data_manager import TickDataManager

        # Create and save some data
        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)
        acc.add_tick(".SPXW260312C5700", 100, "BUY")
        acc.save_to_disk()

        # Manager should load it
        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        assert manager.get_adjusted_oi(".SPXW260312C5700") == 1100

    def test_process_websocket_message(self, temp_data_dir):
        """Manager should process WebSocket FEED_DATA messages."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)

        msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "TimeAndSale",
                    "eventSymbol": ".SPXW260312C5700",
                    "aggressorSide": "BUY",
                    "size": 50,
                    "price": 15.50,
                }
            ]
        }

        manager.process_message(msg)
        assert manager.get_adjusted_oi(".SPXW260312C5700") == 1050

    def test_process_summary_sets_opening_oi(self, temp_data_dir):
        """Manager should set opening OI from Summary events."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)

        msg = {
            "type": "FEED_DATA",
            "data": [
                {
                    "eventType": "Summary",
                    "eventSymbol": ".SPXW260312C5700",
                    "openInterest": 5000,
                }
            ]
        }

        manager.process_message(msg, set_opening_oi=True)
        assert manager.get_adjusted_oi(".SPXW260312C5700") == 5000

    def test_get_effective_oi_with_fallback(self, temp_data_dir):
        """Should return adjusted OI or fall back to raw."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 50, "BUY")

        # Has tick data - return adjusted
        assert manager.get_effective_oi(".SPXW260312C5700", raw_oi=1000) == 1050

        # No tick data - return raw
        assert manager.get_effective_oi(".SPXW260312P5700", raw_oi=800) == 800

    def test_save_periodically(self, temp_data_dir):
        """Manager should track if save is needed."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 50, "BUY")

        # Should indicate dirty state
        assert manager.needs_save() is True

        manager.save()
        assert manager.needs_save() is False

    def test_generate_subscriptions(self, temp_data_dir):
        """Manager should generate TimeAndSale subscriptions."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        symbols = [".SPXW260312C5700", ".SPXW260312P5700"]

        subs = manager.generate_subscriptions(symbols)

        assert len(subs) == 2
        assert all(s["type"] == "TimeAndSale" for s in subs)

    def test_get_stats(self, temp_data_dir):
        """Manager should provide statistics."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager.accumulator.add_tick(".SPXW260312C5700", 30, "SELL")

        stats = manager.get_stats()
        assert stats["symbol_count"] == 1
        assert stats["total_buy_volume"] == 100
        assert stats["total_sell_volume"] == 30
        assert stats["net_volume"] == 70


class TestTickDataManagerExpirySwitching:
    """Tests for handling expiry changes."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_switch_expiry(self, temp_data_dir):
        """Manager should handle expiry switching."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager.save()

        # Switch to new expiry
        manager.switch_expiry("260313")

        # Old data should be gone
        assert manager.get_adjusted_oi(".SPXW260312C5700") is None
        assert manager.expiry == "260313"

    def test_switch_expiry_saves_current(self, temp_data_dir):
        """Switching expiry should save current data first."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")

        # Switch without explicit save
        manager.switch_expiry("260313")

        # Reload old expiry - data should be persisted
        manager2 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        assert manager2.get_adjusted_oi(".SPXW260312C5700") == 1100


class TestApplyAdjustedOI:
    """Tests for applying adjusted OI to option data."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_apply_to_option_data(self, temp_data_dir):
        """Should update option_data dict with adjusted OI."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager.accumulator.add_tick(".SPXW260312C5700", 30, "SELL")

        option_data = {
            ".SPXW260312C5700": {"oi": 1000, "gamma": 0.05},
            ".SPXW260312P5700": {"oi": 800, "gamma": 0.04},
        }

        updated = manager.apply_adjusted_oi(option_data)

        # Call should have adjusted OI
        assert updated[".SPXW260312C5700"]["oi"] == 1070  # 1000 + 100 - 30
        assert updated[".SPXW260312C5700"]["oi_adjusted"] is True

        # Put should keep raw OI (no tick data)
        assert updated[".SPXW260312P5700"]["oi"] == 800
        assert updated[".SPXW260312P5700"].get("oi_adjusted") is False
