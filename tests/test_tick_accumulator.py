"""
Tests for TickDataAccumulator - TDD style.
Run with: pytest tests/test_tick_accumulator.py -v
"""
import pytest
import os
import json
import tempfile
import shutil
from datetime import datetime
from unittest.mock import patch


class TestTickAccumulation:
    """Tests for the TickAccumulation dataclass."""

    def test_default_values(self):
        """TickAccumulation should have sensible defaults."""
        from utils.tick_accumulator import TickAccumulation

        acc = TickAccumulation()
        assert acc.opening_oi == 0
        assert acc.buy_volume == 0
        assert acc.sell_volume == 0
        assert acc.undefined_volume == 0
        assert acc.last_update == 0.0

    def test_net_volume_calculation(self):
        """Net volume should be buy - sell."""
        from utils.tick_accumulator import TickAccumulation

        acc = TickAccumulation(buy_volume=100, sell_volume=40)
        assert acc.net_volume == 60

    def test_adjusted_oi_calculation(self):
        """Adjusted OI = opening_oi + net_volume."""
        from utils.tick_accumulator import TickAccumulation

        acc = TickAccumulation(opening_oi=1000, buy_volume=50, sell_volume=30)
        # 1000 + (50 - 30) = 1020
        assert acc.adjusted_oi == 1020

    def test_to_dict(self):
        """Should serialize to dictionary."""
        from utils.tick_accumulator import TickAccumulation

        acc = TickAccumulation(
            opening_oi=1000,
            buy_volume=50,
            sell_volume=30,
            undefined_volume=5,
            last_update=1234567890.0
        )
        d = acc.to_dict()
        assert d["opening_oi"] == 1000
        assert d["buy_volume"] == 50
        assert d["sell_volume"] == 30
        assert d["undefined_volume"] == 5

    def test_from_dict(self):
        """Should deserialize from dictionary."""
        from utils.tick_accumulator import TickAccumulation

        d = {
            "opening_oi": 1000,
            "buy_volume": 50,
            "sell_volume": 30,
            "undefined_volume": 5
        }
        acc = TickAccumulation.from_dict(d)
        assert acc.opening_oi == 1000
        assert acc.buy_volume == 50
        assert acc.sell_volume == 30
        assert acc.undefined_volume == 5


class TestTickDataAccumulator:
    """Tests for the TickDataAccumulator class."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory for tests."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def accumulator(self, temp_data_dir):
        """Create a TickDataAccumulator with temp directory."""
        from utils.tick_accumulator import TickDataAccumulator

        with patch('utils.tick_accumulator.TICK_DATA_FOLDER', temp_data_dir):
            acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
            yield acc

    def test_set_opening_oi(self, accumulator):
        """Should store opening OI for a symbol."""
        accumulator.set_opening_oi(".SPXW260312C5700", 1000)
        assert accumulator.get_adjusted_oi(".SPXW260312C5700") == 1000

    def test_add_buy_tick(self, accumulator):
        """Buy tick should increase buy_volume."""
        accumulator.set_opening_oi(".SPXW260312C5700", 1000)
        accumulator.add_tick(".SPXW260312C5700", 50, "BUY")

        breakdown = accumulator.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["buy_volume"] == 50
        assert breakdown["sell_volume"] == 0

    def test_add_sell_tick(self, accumulator):
        """Sell tick should increase sell_volume."""
        accumulator.set_opening_oi(".SPXW260312C5700", 1000)
        accumulator.add_tick(".SPXW260312C5700", 30, "SELL")

        breakdown = accumulator.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["buy_volume"] == 0
        assert breakdown["sell_volume"] == 30

    def test_add_undefined_tick(self, accumulator):
        """Undefined tick should increase undefined_volume."""
        accumulator.set_opening_oi(".SPXW260312C5700", 1000)
        accumulator.add_tick(".SPXW260312C5700", 10, "UNDEFINED")

        breakdown = accumulator.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["undefined_volume"] == 10

    def test_adjusted_oi_with_ticks(self, accumulator):
        """Adjusted OI should reflect buy/sell balance."""
        accumulator.set_opening_oi(".SPXW260312C5700", 1000)
        accumulator.add_tick(".SPXW260312C5700", 50, "BUY")
        accumulator.add_tick(".SPXW260312C5700", 30, "SELL")

        # 1000 + 50 - 30 = 1020
        assert accumulator.get_adjusted_oi(".SPXW260312C5700") == 1020

    def test_multiple_ticks_same_symbol(self, accumulator):
        """Multiple ticks should accumulate."""
        accumulator.set_opening_oi(".SPXW260312C5700", 1000)
        accumulator.add_tick(".SPXW260312C5700", 10, "BUY")
        accumulator.add_tick(".SPXW260312C5700", 20, "BUY")
        accumulator.add_tick(".SPXW260312C5700", 5, "SELL")

        breakdown = accumulator.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["buy_volume"] == 30
        assert breakdown["sell_volume"] == 5

    def test_unknown_symbol_returns_none(self, accumulator):
        """Unknown symbol should return None for adjusted OI."""
        result = accumulator.get_adjusted_oi(".UNKNOWN123")
        assert result is None

    def test_unknown_symbol_volume_breakdown(self, accumulator):
        """Unknown symbol should return empty breakdown."""
        breakdown = accumulator.get_volume_breakdown(".UNKNOWN123")
        assert breakdown["buy_volume"] == 0
        assert breakdown["sell_volume"] == 0
        assert breakdown["undefined_volume"] == 0
        assert breakdown["opening_oi"] == 0


class TestTickDataPersistence:
    """Tests for save/load functionality."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory for tests."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_save_to_disk(self, temp_data_dir):
        """Should save accumulated data to JSON file."""
        from utils.tick_accumulator import TickDataAccumulator

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)
        acc.add_tick(".SPXW260312C5700", 100, "BUY")
        acc.save_to_disk()

        # Check file exists
        expected_file = os.path.join(temp_data_dir, "260312.json")
        assert os.path.exists(expected_file)

        # Check contents
        with open(expected_file, 'r') as f:
            data = json.load(f)

        assert data["expiry"] == "260312"
        assert ".SPXW260312C5700" in data["symbols"]
        assert data["symbols"][".SPXW260312C5700"]["buy_volume"] == 100

    def test_load_from_disk(self, temp_data_dir):
        """Should load accumulated data from JSON file."""
        from utils.tick_accumulator import TickDataAccumulator

        # Create and save first accumulator
        acc1 = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc1.set_opening_oi(".SPXW260312C5700", 1000)
        acc1.add_tick(".SPXW260312C5700", 100, "BUY")
        acc1.save_to_disk()

        # Load in new accumulator
        acc2 = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc2.load_from_disk()

        breakdown = acc2.get_volume_breakdown(".SPXW260312C5700")
        assert breakdown["buy_volume"] == 100
        assert breakdown["opening_oi"] == 1000

    def test_load_nonexistent_file(self, temp_data_dir):
        """Loading nonexistent file should not error."""
        from utils.tick_accumulator import TickDataAccumulator

        acc = TickDataAccumulator(expiry="999999", data_folder=temp_data_dir)
        acc.load_from_disk()  # Should not raise

        # Should have empty data
        assert acc.get_adjusted_oi(".ANYYMBOL") is None

    def test_persistence_roundtrip(self, temp_data_dir):
        """Data should survive save/load cycle."""
        from utils.tick_accumulator import TickDataAccumulator

        # Create with multiple symbols
        acc1 = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc1.set_opening_oi(".SPXW260312C5700", 1000)
        acc1.set_opening_oi(".SPXW260312P5700", 800)
        acc1.add_tick(".SPXW260312C5700", 50, "BUY")
        acc1.add_tick(".SPXW260312C5700", 30, "SELL")
        acc1.add_tick(".SPXW260312P5700", 100, "BUY")
        acc1.save_to_disk()

        # Load in new instance
        acc2 = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc2.load_from_disk()

        # Verify call
        assert acc2.get_adjusted_oi(".SPXW260312C5700") == 1020  # 1000 + 50 - 30
        # Verify put
        assert acc2.get_adjusted_oi(".SPXW260312P5700") == 900   # 800 + 100 - 0


class TestThreadSafety:
    """Tests for thread-safe accumulation."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory for tests."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_concurrent_tick_adds(self, temp_data_dir):
        """Multiple threads adding ticks should not corrupt data."""
        import threading
        from utils.tick_accumulator import TickDataAccumulator

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 0)

        num_threads = 10
        ticks_per_thread = 100

        def add_ticks():
            for _ in range(ticks_per_thread):
                acc.add_tick(".SPXW260312C5700", 1, "BUY")

        threads = [threading.Thread(target=add_ticks) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        breakdown = acc.get_volume_breakdown(".SPXW260312C5700")
        expected = num_threads * ticks_per_thread
        assert breakdown["buy_volume"] == expected


class TestDayReset:
    """Tests for new trading day reset behavior."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory for tests."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_different_expiry_no_crossover(self, temp_data_dir):
        """Different expiries should not share data."""
        from utils.tick_accumulator import TickDataAccumulator

        # Create data for one expiry
        acc1 = TickDataAccumulator(expiry="260311", data_folder=temp_data_dir)
        acc1.set_opening_oi(".SPXW260311C5700", 500)
        acc1.add_tick(".SPXW260311C5700", 100, "BUY")
        acc1.save_to_disk()

        # Create new accumulator for different expiry
        acc2 = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc2.load_from_disk()

        # Should not have the other expiry's data
        assert acc2.get_adjusted_oi(".SPXW260311C5700") is None
        assert acc2.get_adjusted_oi(".SPXW260312C5700") is None

    def test_file_date_check(self, temp_data_dir):
        """Should check file date matches current date."""
        from utils.tick_accumulator import TickDataAccumulator

        # Create file with old date
        old_data = {
            "date": "2025-01-01",  # Old date
            "expiry": "260312",
            "symbols": {
                ".SPXW260312C5700": {
                    "opening_oi": 1000,
                    "buy_volume": 500,
                    "sell_volume": 200,
                    "undefined_volume": 0
                }
            }
        }

        file_path = os.path.join(temp_data_dir, "260312.json")
        with open(file_path, 'w') as f:
            json.dump(old_data, f)

        # Load with check_date=True should ignore old data
        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.load_from_disk(check_date=True)

        # Old data should be ignored (date mismatch)
        assert acc.get_adjusted_oi(".SPXW260312C5700") is None
