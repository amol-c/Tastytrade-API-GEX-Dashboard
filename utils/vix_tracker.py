"""
VIX Tracker
Fetches VIX from Tastytrade dxFeed and tracks history.
"""
import json
import os
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

VIX_HISTORY_FOLDER = "vix_history"


@dataclass
class VIXState:
    """Current VIX state with direction."""
    current: float
    previous: Optional[float]
    direction: str  # "RISING", "FALLING", "FLAT"
    change_pct: float


def get_vix_price(ws, timeout: int = 3) -> Optional[float]:
    """
    Get current VIX level from Tastytrade dxFeed WebSocket.

    Args:
        ws: Active WebSocket connection (already authenticated)
        timeout: Seconds to wait for data

    Returns:
        VIX price (e.g., 24.93) or None if unavailable
    """
    try:
        ws.send(json.dumps({
            "type": "FEED_SUBSCRIPTION",
            "channel": 1,
            "add": [{"symbol": "VIX", "type": "Trade"}]
        }))

        start = time.time()
        while time.time() - start < timeout:
            try:
                ws.settimeout(1)
                msg = json.loads(ws.recv())
                if msg.get("type") == "FEED_DATA":
                    for data in msg.get("data", []):
                        if data.get("eventSymbol") == "VIX" and data.get("eventType") == "Trade":
                            price = data.get("price")
                            if price:
                                return float(price)
            except:
                continue

    except Exception as e:
        logger.error(f"Error fetching VIX: {e}")

    return None


def determine_iv_direction(
    current_vix: float,
    previous_vix: Optional[float],
    threshold_pct: float = 0.5,
) -> tuple:
    """
    Determine if IV is rising or falling based on VIX change.

    Args:
        current_vix: Current VIX level
        previous_vix: Previous VIX level
        threshold_pct: Minimum % change to consider directional

    Returns:
        Tuple of (direction, change_pct)
    """
    if previous_vix is None or previous_vix <= 0:
        return "FLAT", 0.0

    change_pct = ((current_vix - previous_vix) / previous_vix) * 100

    if change_pct > threshold_pct:
        return "RISING", change_pct
    elif change_pct < -threshold_pct:
        return "FALLING", change_pct
    else:
        return "FLAT", change_pct


class VIXHistoryTracker:
    """
    Tracks VIX over time and persists to JSON.
    Each day gets its own file: vix_history/{YYMMDD}.json
    """

    def __init__(self, date_str: str = None, max_records: int = 1000):
        """
        Initialize VIX history tracker.

        Args:
            date_str: Date in YYMMDD format (defaults to today)
            max_records: Maximum records per file
        """
        self.date_str = date_str or datetime.now().strftime("%y%m%d")
        self.max_records = max_records
        self.history: List[Dict] = []
        self._ensure_folder()
        self._load_history()

    def _ensure_folder(self):
        """Create vix_history folder if it doesn't exist."""
        if not os.path.exists(VIX_HISTORY_FOLDER):
            os.makedirs(VIX_HISTORY_FOLDER)
            logger.info(f"Created {VIX_HISTORY_FOLDER} folder")

    def _get_history_file(self) -> str:
        """Get the history file path."""
        return os.path.join(VIX_HISTORY_FOLDER, f"{self.date_str}.json")

    def _load_history(self):
        """Load history from JSON file if exists."""
        history_file = self._get_history_file()
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.history = json.load(f)
                logger.info(f"Loaded {len(self.history)} VIX records from {history_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load VIX history: {e}")
                self.history = []
        else:
            self.history = []

    def _save_history(self):
        """Save history to JSON file."""
        history_file = self._get_history_file()
        try:
            with open(history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
            logger.info(f"Saved {len(self.history)} VIX records to {history_file}")
        except IOError as e:
            logger.error(f"Could not save VIX history: {e}")

    def add_record(self, vix: float, direction: str, change_pct: float):
        """
        Add a new VIX record.

        Args:
            vix: Current VIX level
            direction: "RISING", "FALLING", or "FLAT"
            change_pct: Percentage change from previous
        """
        record = {
            'timestamp': datetime.now().isoformat(),
            'vix': round(vix, 2),
            'direction': direction,
            'change_pct': round(change_pct, 2),
        }

        self.history.append(record)

        # Trim to max records
        if len(self.history) > self.max_records:
            self.history = self.history[-self.max_records:]

        self._save_history()

        return record

    def get_latest(self) -> Optional[Dict]:
        """Get the most recent record."""
        return self.history[-1] if self.history else None

    def get_history(self, limit: int = 100) -> List[Dict]:
        """Get recent history records."""
        return self.history[-limit:]

    def get_previous_vix(self) -> Optional[float]:
        """Get the previous VIX value for direction calculation."""
        if len(self.history) >= 1:
            return self.history[-1].get('vix')
        return None
