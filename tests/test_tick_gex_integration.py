"""
Tests for GEX integration with tick accumulator - TDD style.
Tests that adjusted OI is used in GEX calculations when available.
"""
import pytest
import tempfile
import shutil


class TestAdjustedOIRetrieval:
    """Tests for getting adjusted OI for GEX calculations."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_get_oi_with_accumulator(self, temp_data_dir):
        """Should return adjusted OI when accumulator has data."""
        from utils.tick_accumulator import TickDataAccumulator, get_effective_oi

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)
        acc.add_tick(".SPXW260312C5700", 50, "BUY")
        acc.add_tick(".SPXW260312C5700", 30, "SELL")

        # Effective OI should be adjusted: 1000 + 50 - 30 = 1020
        effective_oi = get_effective_oi(".SPXW260312C5700", raw_oi=1000, accumulator=acc)
        assert effective_oi == 1020

    def test_get_oi_fallback_to_raw(self, temp_data_dir):
        """Should fall back to raw OI when symbol not in accumulator."""
        from utils.tick_accumulator import TickDataAccumulator, get_effective_oi

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        # Don't add any data for the symbol

        # Should fall back to raw OI
        effective_oi = get_effective_oi(".SPXW260312C5700", raw_oi=1000, accumulator=acc)
        assert effective_oi == 1000

    def test_get_oi_no_accumulator(self):
        """Should return raw OI when no accumulator provided."""
        from utils.tick_accumulator import get_effective_oi

        effective_oi = get_effective_oi(".SPXW260312C5700", raw_oi=1500, accumulator=None)
        assert effective_oi == 1500

    def test_get_oi_zero_raw(self, temp_data_dir):
        """Should handle zero raw OI."""
        from utils.tick_accumulator import TickDataAccumulator, get_effective_oi

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)

        effective_oi = get_effective_oi(".SPXW260312C5700", raw_oi=0, accumulator=acc)
        assert effective_oi == 0

    def test_get_oi_adjusted_can_be_negative(self, temp_data_dir):
        """Adjusted OI can go negative (more sells than buys + opening)."""
        from utils.tick_accumulator import TickDataAccumulator, get_effective_oi

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 100)
        acc.add_tick(".SPXW260312C5700", 50, "BUY")
        acc.add_tick(".SPXW260312C5700", 200, "SELL")

        # 100 + 50 - 200 = -50 (net closing)
        effective_oi = get_effective_oi(".SPXW260312C5700", raw_oi=100, accumulator=acc)
        assert effective_oi == -50


class TestOIAdjustmentInfo:
    """Tests for getting OI adjustment metadata."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_get_adjustment_info(self, temp_data_dir):
        """Should return adjustment info for display."""
        from utils.tick_accumulator import TickDataAccumulator, get_oi_adjustment_info

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)
        acc.add_tick(".SPXW260312C5700", 150, "BUY")
        acc.add_tick(".SPXW260312C5700", 50, "SELL")
        acc.add_tick(".SPXW260312C5700", 10, "UNDEFINED")

        info = get_oi_adjustment_info(".SPXW260312C5700", accumulator=acc)

        assert info["opening_oi"] == 1000
        assert info["buy_volume"] == 150
        assert info["sell_volume"] == 50
        assert info["undefined_volume"] == 10
        assert info["net_adjustment"] == 100  # 150 - 50
        assert info["adjusted_oi"] == 1100   # 1000 + 100
        assert info["has_tick_data"] is True

    def test_get_adjustment_info_no_data(self, temp_data_dir):
        """Should return empty info when no tick data."""
        from utils.tick_accumulator import TickDataAccumulator, get_oi_adjustment_info

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)

        info = get_oi_adjustment_info(".SPXW260312C5700", accumulator=acc)

        assert info["has_tick_data"] is False
        assert info["net_adjustment"] == 0

    def test_get_adjustment_info_no_accumulator(self):
        """Should handle None accumulator."""
        from utils.tick_accumulator import get_oi_adjustment_info

        info = get_oi_adjustment_info(".SPXW260312C5700", accumulator=None)

        assert info["has_tick_data"] is False


class TestBulkOIRetrieval:
    """Tests for getting OI for multiple symbols efficiently."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_get_bulk_effective_oi(self, temp_data_dir):
        """Should return effective OI for multiple symbols."""
        from utils.tick_accumulator import TickDataAccumulator, get_bulk_effective_oi

        acc = TickDataAccumulator(expiry="260312", data_folder=temp_data_dir)
        acc.set_opening_oi(".SPXW260312C5700", 1000)
        acc.add_tick(".SPXW260312C5700", 100, "BUY")

        raw_oi_map = {
            ".SPXW260312C5700": 1000,  # Has tick data
            ".SPXW260312P5700": 800,   # No tick data
        }

        result = get_bulk_effective_oi(raw_oi_map, accumulator=acc)

        assert result[".SPXW260312C5700"] == 1100  # Adjusted
        assert result[".SPXW260312P5700"] == 800   # Fallback to raw
