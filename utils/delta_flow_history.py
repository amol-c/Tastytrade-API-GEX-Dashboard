"""
Delta Flow History Tracker

Persists delta flow records to JSON for charting.

Single Responsibility: Load/save delta flow history to disk.

Similar pattern to CharmHistoryTracker and VannaHistoryTracker
for consistency across the codebase.
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

DELTA_FLOW_FOLDER = "data/delta_flow_history"

ES_MULTIPLIER = 50


class DeltaFlowHistoryTracker:
    """
    Tracks delta flow over time for charting.

    Stores cumulative customer delta and ES equivalent at each data point.
    """

    def __init__(self, expiry: str, max_records: int = 500):
        """
        Initialize tracker.

        Args:
            expiry: Option expiry in YYMMDD format
            max_records: Maximum records to keep (oldest trimmed)
        """
        self.expiry = expiry
        self.max_records = max_records
        self.history: List[Dict] = []
        self._load_history()

    def _get_file_path(self) -> str:
        """Get path to history JSON file."""
        os.makedirs(DELTA_FLOW_FOLDER, exist_ok=True)
        return os.path.join(DELTA_FLOW_FOLDER, f"{self.expiry}.json")

    def _load_history(self):
        """Load history from disk if exists."""
        path = self._get_file_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    self.history = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.history = []

    def _save_history(self):
        """Save history to disk."""
        path = self._get_file_path()
        with open(path, 'w') as f:
            json.dump(self.history, f)

    def add_record(
        self,
        spot_price: float,
        cumulative_customer_delta: float,
        flow_direction: str,
        trade_count: int,
    ) -> Dict:
        """
        Add a delta flow record.

        Args:
            spot_price: Current underlying price
            cumulative_customer_delta: Total customer delta accumulated
            flow_direction: "BUY", "SELL", or "NEUTRAL"
            trade_count: Number of trades processed

        Returns:
            The created record
        """
        # Calculate ES equivalent with correct sign
        # ES = -customer_delta / 50 (not divided by spot)
        # Customer long (+delta) → dealer SELLS → negative ES
        es_equivalent = -cumulative_customer_delta / ES_MULTIPLIER

        record = {
            "timestamp": datetime.now().isoformat(),
            "spot_price": spot_price,
            "cumulative_delta": cumulative_customer_delta,
            "es_futures": es_equivalent,
            "flow_direction": flow_direction,
            "trade_count": trade_count,
            "expiry": self.expiry,
        }

        self.history.append(record)

        # Trim to max records (keep most recent)
        if len(self.history) > self.max_records:
            self.history = self.history[-self.max_records:]

        self._save_history()
        return record

    def get_es_futures_series(self, limit: int = 50) -> List[Dict]:
        """
        Get time series data for charting.

        Args:
            limit: Maximum records to return

        Returns:
            List of {timestamp, es_futures, spot_price, flow}
        """
        recent = self.history[-limit:] if len(self.history) > limit else self.history
        return [
            {
                "timestamp": r["timestamp"],
                "es_futures": r["es_futures"],
                "spot_price": r["spot_price"],
                "flow": r["flow_direction"],
            }
            for r in recent
        ]

    def get_latest(self) -> Optional[Dict]:
        """Get most recent record, or None if empty."""
        return self.history[-1] if self.history else None
