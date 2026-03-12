"""
Vanna History Tracker
Stores vanna exposure over time in JSON format.
"""
import json
import os
import logging
from datetime import datetime
import pytz
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

VANNA_HISTORY_FOLDER = "vanna_history"
ES_MULTIPLIER = 50


def calculate_es_futures_from_vanna(
    net_vanna: float,
    spot_price: float,
    iv_rising: bool,
) -> float:
    """
    Convert vanna exposure to ES futures equivalent.

    Sign matches dealer action:
    - Positive = dealers will BUY
    - Negative = dealers will SELL

    Args:
        net_vanna: Net vanna exposure in dollars
        spot_price: Current SPX price
        iv_rising: True if IV is rising

    Returns:
        ES contracts (positive = buy, negative = sell)
    """
    if spot_price <= 0:
        return 0.0

    notional_per_contract = spot_price * ES_MULTIPLIER
    es_contracts = abs(net_vanna) / notional_per_contract

    # Determine sign based on flow direction
    # Positive vanna + IV rising = SELL (negative)
    # Positive vanna + IV falling = BUY (positive)
    # Negative vanna + IV rising = BUY (positive)
    # Negative vanna + IV falling = SELL (negative)

    if net_vanna > 0:
        return es_contracts if not iv_rising else -es_contracts
    else:
        return es_contracts if iv_rising else -es_contracts


class VannaHistoryTracker:
    """
    Tracks vanna exposure over time and persists to JSON.
    Each expiry gets its own file: vanna_history/{expiry}.json
    """

    def __init__(self, expiry: str = None, max_records: int = 1000):
        self.expiry = expiry
        self.max_records = max_records
        self.history: List[Dict] = []
        self._ensure_folder()
        if expiry:
            self._load_history()

    def _ensure_folder(self):
        if not os.path.exists(VANNA_HISTORY_FOLDER):
            os.makedirs(VANNA_HISTORY_FOLDER)
            logger.info(f"Created {VANNA_HISTORY_FOLDER} folder")

    def _get_history_file(self, expiry: str = None) -> str:
        exp = expiry or self.expiry
        return os.path.join(VANNA_HISTORY_FOLDER, f"{exp}.json")

    def _load_history(self, expiry: str = None):
        history_file = self._get_history_file(expiry)
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.history = json.load(f)
                logger.info(f"Loaded {len(self.history)} vanna records from {history_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load vanna history: {e}")
                self.history = []
        else:
            self.history = []

    def _save_history(self, expiry: str = None):
        history_file = self._get_history_file(expiry)
        try:
            with open(history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
            logger.info(f"Saved {len(self.history)} vanna records to {history_file}")
        except IOError as e:
            logger.error(f"Could not save vanna history: {e}")

    def add_record(
        self,
        spot_price: float,
        net_vanna: float,
        flow_direction: str,
        iv_direction: str,
        expiry: str,
    ):
        """Add a new vanna record."""
        if expiry != self.expiry:
            self.expiry = expiry
            self._load_history(expiry)

        iv_rising = (iv_direction == "RISING")
        es_futures = calculate_es_futures_from_vanna(net_vanna, spot_price, iv_rising)

        ny_tz = pytz.timezone('US/Eastern')
        record = {
            'timestamp': datetime.now(ny_tz).isoformat(),
            'expiry': expiry,
            'spot_price': spot_price,
            'net_vanna': net_vanna,
            'es_futures': round(es_futures, 1),
            'flow_direction': flow_direction,
            'iv_direction': iv_direction,
        }

        self.history.append(record)

        if len(self.history) > self.max_records:
            self.history = self.history[-self.max_records:]

        self._save_history(expiry)

        return record

    def get_latest(self) -> Optional[Dict]:
        return self.history[-1] if self.history else None

    def get_history(self, limit: int = 100) -> List[Dict]:
        return self.history[-limit:]

    def get_es_futures_series(self, limit: int = 100) -> List[Dict]:
        """Get time series of ES futures for charting."""
        records = self.history[-limit:]
        return [
            {
                'timestamp': r['timestamp'],
                'es_futures': r['es_futures'],
                'flow': r['flow_direction'],
                'iv_direction': r['iv_direction'],
            }
            for r in records
        ]
