"""
Tests for CharmHistoryTracker
"""
import pytest
import os
import json
import tempfile
from utils.charm_history import (
    CharmHistoryTracker,
    calculate_es_futures_equivalent,
    ES_MULTIPLIER,
)


class TestESFuturesCalculation:
    """Tests for ES futures equivalent calculation."""

    def test_es_futures_formula(self):
        """ES futures = net_charm / (spot × 50)."""
        # -$33M charm at SPX 6000 = -33,000,000 / (6000 × 50) = -110 contracts
        net_charm = -33_000_000
        spot = 6000
        expected = net_charm / (spot * ES_MULTIPLIER)
        result = calculate_es_futures_equivalent(net_charm, spot)
        assert result == pytest.approx(expected)
        assert result == pytest.approx(-110)

    def test_positive_charm_gives_positive_es(self):
        """Positive charm should give positive ES (need to buy)."""
        result = calculate_es_futures_equivalent(30_000_000, 6000)
        assert result > 0

    def test_negative_charm_gives_negative_es(self):
        """Negative charm should give negative ES (need to sell)."""
        result = calculate_es_futures_equivalent(-30_000_000, 6000)
        assert result < 0

    def test_zero_spot_returns_zero(self):
        """Zero spot price should return zero to avoid division error."""
        result = calculate_es_futures_equivalent(-30_000_000, 0)
        assert result == 0

    def test_zero_charm_returns_zero(self):
        """Zero charm should return zero ES."""
        result = calculate_es_futures_equivalent(0, 6000)
        assert result == 0


class TestCharmHistoryTracker:
    """Tests for CharmHistoryTracker class."""

    @pytest.fixture
    def temp_history_file(self):
        """Create a temporary file for history."""
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_tracker_initialization(self, temp_history_file):
        """Tracker should initialize with empty history."""
        tracker = CharmHistoryTracker(history_file=temp_history_file)
        assert tracker.history == []

    def test_add_record(self, temp_history_file):
        """Should add a record with correct fields."""
        tracker = CharmHistoryTracker(history_file=temp_history_file)
        record = tracker.add_record(
            spot_price=6000,
            net_charm=-33_000_000,
            flow_direction='SELL',
            expiry='260310',
        )
        assert record['spot_price'] == 6000
        assert record['net_charm'] == -33_000_000
        assert record['flow_direction'] == 'SELL'
        assert record['expiry'] == '260310'
        assert record['es_futures'] == pytest.approx(-110, abs=0.5)
        assert 'timestamp' in record

    def test_add_record_has_es_futures(self, temp_history_file):
        """Should include ES futures equivalent."""
        tracker = CharmHistoryTracker(history_file=temp_history_file)
        record = tracker.add_record(
            spot_price=6000,
            net_charm=-33_000_000,
            flow_direction='SELL',
            expiry='260310',
        )
        assert record['es_futures'] == pytest.approx(-110, abs=0.5)

    def test_persistence(self, temp_history_file):
        """History should persist to JSON and reload."""
        # Add record
        tracker1 = CharmHistoryTracker(history_file=temp_history_file)
        tracker1.add_record(
            spot_price=6000,
            net_charm=-33_000_000,
            flow_direction='SELL',
            expiry='260310',
        )

        # Create new tracker, should load history
        tracker2 = CharmHistoryTracker(history_file=temp_history_file)
        assert len(tracker2.history) == 1
        assert tracker2.history[0]['net_charm'] == -33_000_000

    def test_get_latest(self, temp_history_file):
        """Should return most recent record."""
        tracker = CharmHistoryTracker(history_file=temp_history_file)
        tracker.add_record(spot_price=6000, net_charm=-30_000_000, flow_direction='SELL', expiry='260310')
        tracker.add_record(spot_price=6010, net_charm=-31_000_000, flow_direction='SELL', expiry='260310')

        latest = tracker.get_latest()
        assert latest['net_charm'] == -31_000_000
        assert latest['spot_price'] == 6010

    def test_get_latest_empty(self, temp_history_file):
        """Should return None when no history."""
        tracker = CharmHistoryTracker(history_file=temp_history_file)
        assert tracker.get_latest() is None

    def test_max_records_limit(self, temp_history_file):
        """Should trim to max_records."""
        tracker = CharmHistoryTracker(history_file=temp_history_file, max_records=5)
        for i in range(10):
            tracker.add_record(
                spot_price=6000 + i,
                net_charm=-30_000_000,
                flow_direction='SELL',
                expiry='260310',
            )

        assert len(tracker.history) == 5
        # Should keep the most recent
        assert tracker.history[0]['spot_price'] == 6005
        assert tracker.history[-1]['spot_price'] == 6009

    def test_get_es_futures_series(self, temp_history_file):
        """Should return time series data for charting."""
        tracker = CharmHistoryTracker(history_file=temp_history_file)
        tracker.add_record(spot_price=6000, net_charm=-30_000_000, flow_direction='SELL', expiry='260310')
        tracker.add_record(spot_price=6010, net_charm=-31_000_000, flow_direction='SELL', expiry='260310')

        series = tracker.get_es_futures_series()
        assert len(series) == 2
        assert 'timestamp' in series[0]
        assert 'es_futures' in series[0]
        assert 'spot_price' in series[0]
        assert 'flow' in series[0]
