"""
Charm History Tracker
Stores charm projections over time in JSON format for historical analysis.
Each expiration gets its own file in the charm_history folder.
"""
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

from utils.app_paths import get_data_folder

logger = logging.getLogger(__name__)

# ES Futures multiplier ($50 per point)
ES_MULTIPLIER = 50

# Folder for charm history files (OS-specific app data directory)
CHARM_HISTORY_FOLDER = get_data_folder("charm_history")


def calculate_es_futures_equivalent(net_charm: float, spot_price: float) -> float:
    """
    Convert net charm to ES futures contracts dealers will trade.

    Formula: ES Contracts = -Net Charm / (SPX_Price × $50)

    Sign convention (matches flow direction):
    - Positive ES = dealers BUY
    - Negative ES = dealers SELL

    Args:
        net_charm: Net charm exposure in dollars
        spot_price: Current SPX spot price

    Returns:
        Number of ES futures contracts (positive = buy, negative = sell)
    """
    if spot_price <= 0:
        return 0.0

    notional_per_contract = spot_price * ES_MULTIPLIER
    # Negate so sign matches dealer action (negative charm = buy = positive ES)
    return -net_charm / notional_per_contract


class CharmHistoryTracker:
    """
    Tracks charm projections over time and persists to JSON.
    Each expiration gets its own file: charm_history/{expiry}.json
    """

    def __init__(self, expiry: str = None, max_records: int = 1000):
        """
        Initialize charm history tracker.

        Args:
            expiry: Option expiry in YYMMDD format (e.g., "260308")
            max_records: Maximum number of records to keep per file
        """
        self.expiry = expiry
        self.max_records = max_records
        self.history: List[Dict] = []
        self._ensure_folder()
        if expiry:
            self._load_history()

    def _ensure_folder(self):
        """Create charm_history folder if it doesn't exist."""
        if not os.path.exists(CHARM_HISTORY_FOLDER):
            os.makedirs(CHARM_HISTORY_FOLDER)
            logger.info(f"Created {CHARM_HISTORY_FOLDER} folder")

    def _get_history_file(self, expiry: str = None) -> str:
        """Get the history file path for an expiry."""
        exp = expiry or self.expiry
        return os.path.join(CHARM_HISTORY_FOLDER, f"{exp}.json")

    def _load_history(self, expiry: str = None):
        """Load history from JSON file if exists."""
        history_file = self._get_history_file(expiry)
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.history = json.load(f)
                logger.info(f"Loaded {len(self.history)} records from {history_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load charm history: {e}")
                self.history = []
        else:
            self.history = []

    def _save_history(self, expiry: str = None):
        """Save history to JSON file."""
        history_file = self._get_history_file(expiry)
        try:
            with open(history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
            logger.info(f"Saved {len(self.history)} records to {history_file}")
        except IOError as e:
            logger.error(f"Could not save charm history: {e}")

    def add_record(
        self,
        spot_price: float,
        net_charm: float,
        flow_direction: str,
        expiry: str,
    ):
        """
        Add a new charm record.

        Args:
            spot_price: Current SPX spot price
            net_charm: Current net charm exposure
            flow_direction: BUY/SELL/NEUTRAL
            expiry: Option expiry (YYMMDD)
        """
        # Load history for this expiry if different from current
        if expiry != self.expiry:
            self.expiry = expiry
            self._load_history(expiry)

        es_futures = calculate_es_futures_equivalent(net_charm, spot_price)

        record = {
            'timestamp': datetime.now().isoformat(),
            'expiry': expiry,
            'spot_price': spot_price,
            'net_charm': net_charm,
            'es_futures': round(es_futures, 1),
            'flow_direction': flow_direction,
        }

        self.history.append(record)

        # Trim to max records
        if len(self.history) > self.max_records:
            self.history = self.history[-self.max_records:]

        self._save_history(expiry)

        return record

    def get_latest(self) -> Optional[Dict]:
        """Get the most recent record."""
        return self.history[-1] if self.history else None

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Get recent history records."""
        return self.history[-limit:]

    def get_es_futures_series(self, limit: int = 100) -> List[Dict]:
        """
        Get time series of ES futures equivalent for charting.

        Returns:
            List of {timestamp, es_futures, spot_price}
        """
        records = self.history[-limit:]
        return [
            {
                'timestamp': r['timestamp'],
                'es_futures': r['es_futures'],
                'spot_price': r['spot_price'],
                'flow': r['flow_direction'],
            }
            for r in records
        ]
