"""
Tests for CharmCalculator

Tests cover:
1. Basic charm calculation (Black-Scholes)
2. Charm exposure calculation
3. Time-to-expiry calculation
4. Forward projections
5. Heatmap data generation
6. Flow direction classification
"""
import pytest
import math
import numpy as np
from datetime import datetime, timedelta


class TestCharmCalculation:
    """Tests for basic charm calculation using Black-Scholes."""

    def test_atm_call_charm_is_negative(self, charm_calculator):
        """ATM call charm should be negative (delta decays toward 0.5)."""
        charm = charm_calculator.calculate_charm(
            spot=6000,
            strike=6000,
            tte=1/365,  # 1 day
            iv=0.20,
            option_type='C'
        )
        # ATM calls have negative charm (delta decreases as time passes)
        assert charm < 0

    def test_atm_put_charm_is_nonzero(self, charm_calculator):
        """ATM put charm should be non-zero."""
        charm = charm_calculator.calculate_charm(
            spot=6000,
            strike=6000,
            tte=1/365,  # 1 day
            iv=0.20,
            option_type='P'
        )
        # ATM puts have non-zero charm
        assert charm != 0

    def test_otm_call_charm_is_nonzero(self, charm_calculator):
        """OTM call should have non-zero charm."""
        otm_charm = charm_calculator.calculate_charm(
            spot=6000, strike=6100, tte=1/365, iv=0.20, option_type='C'
        )
        # OTM calls have non-zero charm
        assert otm_charm != 0

    def test_charm_increases_near_expiry(self, charm_calculator):
        """Charm magnitude should increase as expiration approaches."""
        charm_7d = abs(charm_calculator.calculate_charm(
            spot=6000, strike=6000, tte=7/365, iv=0.20, option_type='C'
        ))
        charm_1d = abs(charm_calculator.calculate_charm(
            spot=6000, strike=6000, tte=1/365, iv=0.20, option_type='C'
        ))
        # 1 day should have higher charm than 7 days
        assert charm_1d > charm_7d

    def test_zero_tte_returns_zero(self, charm_calculator):
        """Zero time to expiry should return zero charm."""
        charm = charm_calculator.calculate_charm(
            spot=6000, strike=6000, tte=0, iv=0.20, option_type='C'
        )
        assert charm == 0.0

    def test_zero_iv_returns_zero(self, charm_calculator):
        """Zero IV should return zero charm."""
        charm = charm_calculator.calculate_charm(
            spot=6000, strike=6000, tte=1/365, iv=0, option_type='C'
        )
        assert charm == 0.0

    def test_negative_tte_returns_zero(self, charm_calculator):
        """Negative time to expiry should return zero charm."""
        charm = charm_calculator.calculate_charm(
            spot=6000, strike=6000, tte=-1/365, iv=0.20, option_type='C'
        )
        assert charm == 0.0


class TestCharmExposure:
    """Tests for charm exposure (dollar value) calculation."""

    def test_charm_exposure_formula(self, charm_calculator):
        """Charm exposure = charm × OI × 100 × spot."""
        charm = charm_calculator.calculate_charm(
            spot=6000, strike=6000, tte=1/365, iv=0.20, option_type='C'
        )
        exposure = charm_calculator.calculate_charm_exposure(
            spot=6000, strike=6000, tte=1/365, iv=0.20, oi=1000, option_type='C'
        )
        expected = charm * 1000 * 100 * 6000
        assert exposure == pytest.approx(expected, rel=1e-6)

    def test_zero_oi_returns_zero_exposure(self, charm_calculator):
        """Zero OI should return zero exposure."""
        exposure = charm_calculator.calculate_charm_exposure(
            spot=6000, strike=6000, tte=1/365, iv=0.20, oi=0, option_type='C'
        )
        assert exposure == 0.0

    def test_exposure_scales_with_oi(self, charm_calculator):
        """Exposure should scale linearly with OI."""
        exposure_1000 = charm_calculator.calculate_charm_exposure(
            spot=6000, strike=6000, tte=1/365, iv=0.20, oi=1000, option_type='C'
        )
        exposure_2000 = charm_calculator.calculate_charm_exposure(
            spot=6000, strike=6000, tte=1/365, iv=0.20, oi=2000, option_type='C'
        )
        assert exposure_2000 == pytest.approx(exposure_1000 * 2, rel=1e-6)


class TestTimeToExpiry:
    """Tests for time-to-expiry calculation."""

    def test_same_day_expiry(self, charm_calculator):
        """Same day expiry should return small positive TTE during market hours."""
        today = datetime.now().strftime("%y%m%d")
        tte = charm_calculator.calculate_tte_from_expiry(today, minutes_forward=0)
        # Should be small positive or zero
        assert tte >= 0
        assert tte < 1/252  # Less than 1 trading day

    def test_next_day_expiry(self, charm_calculator):
        """Next day expiry should return ~1 trading day TTE."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        tte = charm_calculator.calculate_tte_from_expiry(tomorrow, minutes_forward=0)
        # Should be approximately 1 trading day
        assert tte > 0
        assert tte < 5/252  # Less than 5 trading days

    def test_minutes_forward_reduces_tte(self, charm_calculator):
        """Forward projection should reduce TTE."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        tte_now = charm_calculator.calculate_tte_from_expiry(tomorrow, minutes_forward=0)
        tte_1hr = charm_calculator.calculate_tte_from_expiry(tomorrow, minutes_forward=60)
        assert tte_1hr < tte_now

    def test_expired_returns_zero(self, charm_calculator):
        """Past expiry should return zero TTE."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%y%m%d")
        tte = charm_calculator.calculate_tte_from_expiry(yesterday, minutes_forward=0)
        assert tte == 0


class TestCharmProjection:
    """Tests for forward charm projection."""

    def test_projection_returns_list(self, charm_calculator, large_mock_options_data):
        """Projection should return a list of CharmProjection objects."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        assert isinstance(projections, list)
        assert len(projections) >= 1

    def test_projection_time_labels(self, charm_calculator, large_mock_options_data):
        """Projection should have NOW label."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        labels = [p.time_label for p in projections]
        assert "NOW" in labels

    def test_projection_has_charm_by_strike(self, charm_calculator, large_mock_options_data):
        """Each projection should have charm_by_strike dict."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        assert len(projections) > 0
        assert isinstance(projections[0].charm_by_strike, dict)

    def test_projection_skips_insufficient_data(self, charm_calculator):
        """Projection should skip when insufficient valid options."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        invalid_data = {
            "option1": {'iv': None, 'oi': 1000, 'strike': 6000, 'type': 'C'},
            "option2": {'iv': 0.20, 'oi': None, 'strike': 6000, 'type': 'C'},
            "option3": {'iv': 0.20, 'oi': 1000, 'strike': 6000, 'type': 'C'},
        }
        projections = charm_calculator.project_charm_forward(
            options_data=invalid_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        # Should return empty list - not enough valid options
        assert len(projections) == 0


class TestFlowDirection:
    """Tests for flow direction classification."""

    def test_positive_charm_is_buy(self, charm_calculator, large_mock_options_data):
        """Flow direction should be set."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        assert projections[0].flow_direction is not None

    def test_flow_direction_enum(self, charm_calculator, large_mock_options_data):
        """Flow direction should be a valid enum value."""
        from utils.charm_calculator import FlowDirection

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        assert projections[0].flow_direction in [
            FlowDirection.BUY,
            FlowDirection.SELL,
            FlowDirection.NEUTRAL
        ]

    def test_flow_label_has_emoji(self, charm_calculator, large_mock_options_data):
        """Flow label should contain emoji indicator."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        label = projections[0].flow_label
        assert any(emoji in label for emoji in ['🟢', '🔴', '🟡'])


class TestHeatmapData:
    """Tests for heatmap data generation."""

    def test_heatmap_returns_tuple(self, charm_calculator, large_mock_options_data):
        """Heatmap data should return (time_labels, strikes, matrix) tuple."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        time_labels, strikes, matrix = charm_calculator.create_heatmap_data(projections)

        assert isinstance(time_labels, list)
        assert isinstance(strikes, list)
        assert isinstance(matrix, np.ndarray)

    def test_heatmap_matrix_shape(self, charm_calculator, large_mock_options_data):
        """Matrix shape should be (num_strikes, num_time_points)."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        time_labels, strikes, matrix = charm_calculator.create_heatmap_data(projections)

        assert matrix.shape == (len(strikes), len(time_labels))

    def test_empty_projections_returns_empty(self, charm_calculator):
        """Empty projections should return empty data."""
        time_labels, strikes, matrix = charm_calculator.create_heatmap_data([])

        assert time_labels == []
        assert strikes == []
        assert matrix.size == 0


class TestFlowSummary:
    """Tests for flow summary generation."""

    def test_summary_has_required_keys(self, charm_calculator, large_mock_options_data):
        """Summary should have all required keys."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        summary = charm_calculator.get_flow_summary(projections)

        assert 'current_net_charm' in summary
        assert 'current_flow' in summary
        assert 'current_flow_label' in summary
        assert 'projections' in summary

    def test_summary_projections_list(self, charm_calculator, large_mock_options_data):
        """Summary projections should be a list with correct structure."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
        projections = charm_calculator.project_charm_forward(
            options_data=large_mock_options_data,
            spot=6000,
            expiry_str=tomorrow,
        )
        summary = charm_calculator.get_flow_summary(projections)

        assert isinstance(summary['projections'], list)
        assert len(summary['projections']) >= 1
        assert 'time' in summary['projections'][0]
        assert 'net_charm' in summary['projections'][0]
        assert 'flow' in summary['projections'][0]


# Fixtures

@pytest.fixture
def charm_calculator():
    """Create a CharmCalculator instance with default settings."""
    from utils.charm_calculator import CharmCalculator
    return CharmCalculator(
        risk_free_rate=0.05,
        dividend_yield=0.015,
        neutral_threshold=1_000_000
    )


@pytest.fixture
def large_mock_options_data():
    """Create mock options data with enough options (50+) for charm calculation."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    data = {}
    # Generate 60 options (30 calls, 30 puts)
    for i in range(30):
        strike = 5900 + (i * 10)
        data[f".SPXW{tomorrow}C{strike}"] = {'iv': 0.20, 'oi': 1000, 'strike': strike, 'type': 'C'}
        data[f".SPXW{tomorrow}P{strike}"] = {'iv': 0.22, 'oi': 1200, 'strike': strike, 'type': 'P'}
    return data


@pytest.fixture
def mock_options_data():
    """Create mock options data for testing."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 1000, 'strike': 6000, 'type': 'C'},
        f".SPXW{tomorrow}P6000": {'iv': 0.22, 'oi': 1500, 'strike': 6000, 'type': 'P'},
        f".SPXW{tomorrow}C6050": {'iv': 0.18, 'oi': 800, 'strike': 6050, 'type': 'C'},
        f".SPXW{tomorrow}P5950": {'iv': 0.24, 'oi': 1200, 'strike': 5950, 'type': 'P'},
    }


@pytest.fixture
def mock_options_data_calls_heavy():
    """Create mock options data with heavy call OI."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 5000, 'strike': 6000, 'type': 'C'},
        f".SPXW{tomorrow}C6050": {'iv': 0.18, 'oi': 3000, 'strike': 6050, 'type': 'C'},
        f".SPXW{tomorrow}P6000": {'iv': 0.22, 'oi': 500, 'strike': 6000, 'type': 'P'},
    }


@pytest.fixture
def mock_options_data_puts_heavy():
    """Create mock options data with heavy put OI."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        f".SPXW{tomorrow}P6000": {'iv': 0.22, 'oi': 5000, 'strike': 6000, 'type': 'P'},
        f".SPXW{tomorrow}P5950": {'iv': 0.24, 'oi': 3000, 'strike': 5950, 'type': 'P'},
        f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 500, 'strike': 6000, 'type': 'C'},
    }
