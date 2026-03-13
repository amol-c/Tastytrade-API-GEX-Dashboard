"""
Tests for CharmHistoryTracker
"""
import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch
from utils.charm_history import (
    CharmHistoryTracker,
    calculate_es_futures_equivalent,
    ES_MULTIPLIER,
)


class TestESFuturesCalculation:
    """Tests for ES futures equivalent calculation.

    Sign convention (dealers SHORT puts, LONG calls):
    - Negative charm (delta decreasing) → dealers BUY → positive ES
    - Positive charm (delta increasing) → dealers SELL → negative ES

    Formula: ES = -net_charm / (spot × 50)
    """

    def test_es_futures_formula(self):
        """ES futures = -net_charm / (spot × 50)."""
        # -$33M charm at SPX 6000 = -(-33,000,000) / (6000 × 50) = +110 contracts (BUY)
        net_charm = -33_000_000
        spot = 6000
        expected = -net_charm / (spot * ES_MULTIPLIER)
        result = calculate_es_futures_equivalent(net_charm, spot)
        assert result == pytest.approx(expected)
        assert result == pytest.approx(110)  # Positive = BUY

    def test_negative_charm_gives_positive_es(self):
        """Negative charm (delta decreasing) should give positive ES (dealers BUY)."""
        result = calculate_es_futures_equivalent(-30_000_000, 6000)
        assert result > 0

    def test_positive_charm_gives_negative_es(self):
        """Positive charm (delta increasing) should give negative ES (dealers SELL)."""
        result = calculate_es_futures_equivalent(30_000_000, 6000)
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
    def temp_data_dir(self):
        """Create a temporary data directory for charm history."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_tracker_initialization(self, temp_data_dir):
        """Tracker should initialize with empty history."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310")
            assert tracker.history == []

    def test_add_record(self, temp_data_dir):
        """Should add a record with correct fields."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310")
            record = tracker.add_record(
                spot_price=6000,
                net_charm=-33_000_000,
                flow_direction='BUY',  # Negative charm = BUY
                expiry='260310',
            )
            assert record['spot_price'] == 6000
            assert record['net_charm'] == -33_000_000
            assert record['flow_direction'] == 'BUY'
            assert record['expiry'] == '260310'
            assert record['es_futures'] == pytest.approx(110, abs=0.5)  # Positive = BUY
            assert 'timestamp' in record

    def test_add_record_has_es_futures(self, temp_data_dir):
        """Should include ES futures equivalent."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310")
            record = tracker.add_record(
                spot_price=6000,
                net_charm=-33_000_000,
                flow_direction='BUY',
                expiry='260310',
            )
            assert record['es_futures'] == pytest.approx(110, abs=0.5)  # Positive = BUY

    def test_persistence(self, temp_data_dir):
        """History should persist to JSON and reload."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            # Add record
            tracker1 = CharmHistoryTracker(expiry="260310")
            tracker1.add_record(
                spot_price=6000,
                net_charm=-33_000_000,
                flow_direction='BUY',
                expiry='260310',
            )

            # Create new tracker, should load history
            tracker2 = CharmHistoryTracker(expiry="260310")
            assert len(tracker2.history) == 1
            assert tracker2.history[0]['net_charm'] == -33_000_000

    def test_get_latest(self, temp_data_dir):
        """Should return most recent record."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310")
            tracker.add_record(spot_price=6000, net_charm=-30_000_000, flow_direction='BUY', expiry='260310')
            tracker.add_record(spot_price=6010, net_charm=-31_000_000, flow_direction='BUY', expiry='260310')

            latest = tracker.get_latest()
            assert latest['net_charm'] == -31_000_000
            assert latest['spot_price'] == 6010

    def test_get_latest_empty(self, temp_data_dir):
        """Should return None when no history."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310")
            assert tracker.get_latest() is None

    def test_max_records_limit(self, temp_data_dir):
        """Should trim to max_records."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310", max_records=5)
            for i in range(10):
                tracker.add_record(
                    spot_price=6000 + i,
                    net_charm=-30_000_000,
                    flow_direction='BUY',
                    expiry='260310',
                )

            assert len(tracker.history) == 5
            # Should keep the most recent
            assert tracker.history[0]['spot_price'] == 6005
            assert tracker.history[-1]['spot_price'] == 6009

    def test_get_es_futures_series(self, temp_data_dir):
        """Should return time series data for charting."""
        with patch('utils.charm_history.CHARM_HISTORY_FOLDER', temp_data_dir):
            tracker = CharmHistoryTracker(expiry="260310")
            tracker.add_record(spot_price=6000, net_charm=-30_000_000, flow_direction='BUY', expiry='260310')
            tracker.add_record(spot_price=6010, net_charm=-31_000_000, flow_direction='BUY', expiry='260310')

            series = tracker.get_es_futures_series()
            assert len(series) == 2
            assert 'timestamp' in series[0]
            assert 'es_futures' in series[0]
            assert 'spot_price' in series[0]
            assert 'flow' in series[0]
