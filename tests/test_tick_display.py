"""
Tests for tick data display component - TDD style.
Tests data formatting and preparation for UI rendering.
"""
import pytest
import tempfile
import shutil


class TestOIAdjustmentFormatter:
    """Tests for OI adjustment display formatting."""

    def test_format_adjustment_positive(self):
        """Positive adjustment should show + sign."""
        from components.tick_display import format_oi_adjustment

        result = format_oi_adjustment(
            raw_oi=1000,
            adjusted_oi=1050,
        )
        assert result["raw"] == 1000
        assert result["adjusted"] == 1050
        assert result["change"] == 50
        assert result["change_pct"] == 5.0
        assert result["direction"] == "up"
        assert "+50" in result["display"]

    def test_format_adjustment_negative(self):
        """Negative adjustment should show - sign."""
        from components.tick_display import format_oi_adjustment

        result = format_oi_adjustment(
            raw_oi=1000,
            adjusted_oi=950,
        )
        assert result["change"] == -50
        assert result["change_pct"] == -5.0
        assert result["direction"] == "down"
        assert "-50" in result["display"]

    def test_format_adjustment_no_change(self):
        """No change should show flat."""
        from components.tick_display import format_oi_adjustment

        result = format_oi_adjustment(
            raw_oi=1000,
            adjusted_oi=1000,
        )
        assert result["change"] == 0
        assert result["direction"] == "flat"

    def test_format_adjustment_zero_raw(self):
        """Zero raw OI should handle gracefully."""
        from components.tick_display import format_oi_adjustment

        result = format_oi_adjustment(
            raw_oi=0,
            adjusted_oi=50,
        )
        assert result["raw"] == 0
        assert result["adjusted"] == 50
        assert result["change_pct"] == 0  # Avoid division by zero


class TestVolumeBreakdownFormatter:
    """Tests for volume breakdown display formatting."""

    def test_format_volume_breakdown(self):
        """Should format buy/sell/undefined volumes."""
        from components.tick_display import format_volume_breakdown

        result = format_volume_breakdown(
            buy_volume=150,
            sell_volume=80,
            undefined_volume=20,
        )
        assert result["buy"] == 150
        assert result["sell"] == 80
        assert result["undefined"] == 20
        assert result["net"] == 70  # 150 - 80
        assert result["total"] == 250
        assert result["buy_pct"] == 60.0  # 150/250
        assert result["sell_pct"] == 32.0  # 80/250

    def test_format_volume_breakdown_zero_total(self):
        """Should handle zero total volume."""
        from components.tick_display import format_volume_breakdown

        result = format_volume_breakdown(
            buy_volume=0,
            sell_volume=0,
            undefined_volume=0,
        )
        assert result["total"] == 0
        assert result["buy_pct"] == 0
        assert result["sell_pct"] == 0


class TestStrikeFlowData:
    """Tests for per-strike flow data preparation."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_prepare_strike_flow_data(self, temp_data_dir):
        """Should prepare flow data for multiple strikes."""
        from utils.tick_data_manager import TickDataManager
        from components.tick_display import prepare_strike_flow_data

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager.accumulator.add_tick(".SPXW260312C5700", 40, "SELL")
        manager.set_opening_oi(".SPXW260312P5700", 800)
        manager.accumulator.add_tick(".SPXW260312P5700", 50, "SELL")

        option_data = {
            ".SPXW260312C5700": {"oi": 1060, "strike": 5700, "type": "C"},
            ".SPXW260312P5700": {"oi": 750, "strike": 5700, "type": "P"},
        }

        result = prepare_strike_flow_data(option_data, manager)

        # Call should have data
        call_data = result[".SPXW260312C5700"]
        assert call_data["buy_volume"] == 100
        assert call_data["sell_volume"] == 40
        assert call_data["net_flow"] == 60
        assert call_data["has_tick_data"] is True

        # Put should have data
        put_data = result[".SPXW260312P5700"]
        assert put_data["sell_volume"] == 50
        assert put_data["net_flow"] == -50

    def test_prepare_strike_flow_no_tick_data(self, temp_data_dir):
        """Should handle symbols without tick data."""
        from utils.tick_data_manager import TickDataManager
        from components.tick_display import prepare_strike_flow_data

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)

        option_data = {
            ".SPXW260312C5700": {"oi": 1000, "strike": 5700, "type": "C"},
        }

        result = prepare_strike_flow_data(option_data, manager)

        assert result[".SPXW260312C5700"]["has_tick_data"] is False
        assert result[".SPXW260312C5700"]["net_flow"] == 0


class TestTickDataSummary:
    """Tests for overall tick data summary."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_get_tick_summary(self, temp_data_dir):
        """Should provide summary statistics."""
        from utils.tick_data_manager import TickDataManager
        from components.tick_display import get_tick_summary

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager.accumulator.add_tick(".SPXW260312C5700", 30, "SELL")
        manager.accumulator.add_tick(".SPXW260312P5700", 50, "BUY")

        summary = get_tick_summary(manager)

        assert summary["symbol_count"] == 2
        assert summary["total_buy"] == 150
        assert summary["total_sell"] == 30
        assert summary["net_flow"] == 120
        assert summary["flow_direction"] == "BUY"

    def test_get_tick_summary_sell_dominant(self, temp_data_dir):
        """Should detect sell-dominant flow."""
        from utils.tick_data_manager import TickDataManager
        from components.tick_display import get_tick_summary

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.accumulator.add_tick(".SPXW260312C5700", 50, "BUY")
        manager.accumulator.add_tick(".SPXW260312C5700", 200, "SELL")

        summary = get_tick_summary(manager)

        assert summary["net_flow"] == -150
        assert summary["flow_direction"] == "SELL"

    def test_get_tick_summary_no_manager(self):
        """Should handle None manager."""
        from components.tick_display import get_tick_summary

        summary = get_tick_summary(None)

        assert summary["symbol_count"] == 0
        assert summary["total_buy"] == 0
        assert summary["flow_direction"] == "NEUTRAL"
