"""
VIX Tracker
Fetches VIX from Tastytrade dxFeed and tracks history.
Uses slope-based trend detection for IV direction.
"""
import json
import os
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
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


@dataclass
class VIXSlope:
    """VIX slope analysis result."""
    direction: str          # "RISING", "FALLING", "FLAT"
    normalized_slope: float # -1 to +1 scale
    steepness: str          # "EXTREME", "FAST", "SLOW", "FLAT"
    pct_per_hour: float     # Raw % change per hour
    data_points: int        # Number of readings used




def determine_iv_direction(
    current_vix: float,
    previous_vix: Optional[float],
    threshold_pct: float = 0.5,
) -> tuple:
    """
    LEGACY: Determine if IV is rising or falling based on single VIX change.
    Use calculate_vix_slope() for better trend detection.

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


def calculate_vix_slope(
    history: List[Dict],
    window_minutes: int = 60,
    max_pct_per_hour: float = 5.0,
) -> VIXSlope:
    """
    Calculate VIX slope over a time window, normalized to -1 to +1 scale.

    Uses linear regression to find the trend direction and steepness.

    Args:
        history: List of VIX records with 'timestamp' and 'vix' keys
        window_minutes: Time window to analyze (default 60 minutes)
        max_pct_per_hour: Max expected % change per hour for normalization

    Returns:
        VIXSlope with direction, normalized_slope (-1 to +1), and steepness
    """
    if not history or len(history) < 2:
        return VIXSlope(
            direction="FLAT",
            normalized_slope=0.0,
            steepness="FLAT",
            pct_per_hour=0.0,
            data_points=len(history) if history else 0
        )

    # Filter to recent window
    now = datetime.now()
    cutoff = now - timedelta(minutes=window_minutes)

    recent = []
    for record in history:
        try:
            ts = datetime.fromisoformat(record['timestamp'])
            if ts >= cutoff:
                recent.append({
                    'minutes_ago': (now - ts).total_seconds() / 60,
                    'vix': record['vix']
                })
        except (KeyError, ValueError):
            continue

    if len(recent) < 2:
        # Not enough data, use simple comparison if we have any history
        if history:
            first_vix = history[0].get('vix', 0)
            last_vix = history[-1].get('vix', 0)
            if first_vix > 0:
                change_pct = ((last_vix - first_vix) / first_vix) * 100
                normalized = max(-1.0, min(1.0, change_pct / max_pct_per_hour))
                direction = "RISING" if normalized > 0.1 else "FALLING" if normalized < -0.1 else "FLAT"
                steepness = _get_steepness(abs(normalized))
                return VIXSlope(
                    direction=direction,
                    normalized_slope=round(normalized, 3),
                    steepness=steepness,
                    pct_per_hour=round(change_pct, 2),
                    data_points=len(history)
                )
        return VIXSlope(
            direction="FLAT",
            normalized_slope=0.0,
            steepness="FLAT",
            pct_per_hour=0.0,
            data_points=len(recent)
        )

    # Calculate linear regression slope
    # x = minutes ago (inverted so older = lower x)
    # y = VIX value
    n = len(recent)
    x_vals = [window_minutes - r['minutes_ago'] for r in recent]  # 0 = oldest, window_minutes = now
    y_vals = [r['vix'] for r in recent]

    # Simple linear regression: slope = (n*Σxy - Σx*Σy) / (n*Σx² - (Σx)²)
    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_x2 = sum(x * x for x in x_vals)

    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        slope = 0.0
    else:
        slope = (n * sum_xy - sum_x * sum_y) / denominator

    # slope is VIX points per minute, convert to % per hour
    avg_vix = sum_y / n
    if avg_vix > 0:
        # slope * 60 = points per hour
        # (points per hour / avg_vix) * 100 = % per hour
        pct_per_hour = (slope * 60 / avg_vix) * 100
    else:
        pct_per_hour = 0.0

    # Normalize to -1 to +1
    normalized = max(-1.0, min(1.0, pct_per_hour / max_pct_per_hour))

    # Determine direction (threshold at 0.1 normalized)
    if normalized > 0.1:
        direction = "RISING"
    elif normalized < -0.1:
        direction = "FALLING"
    else:
        direction = "FLAT"

    steepness = _get_steepness(abs(normalized))

    return VIXSlope(
        direction=direction,
        normalized_slope=round(normalized, 3),
        steepness=steepness,
        pct_per_hour=round(pct_per_hour, 2),
        data_points=n
    )


def _get_steepness(abs_normalized: float) -> str:
    """Get steepness label from absolute normalized slope."""
    if abs_normalized >= 0.8:
        return "EXTREME"
    elif abs_normalized >= 0.4:
        return "FAST"
    elif abs_normalized >= 0.1:
        return "SLOW"
    else:
        return "FLAT"


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

    def get_slope(self, window_minutes: int = 60) -> VIXSlope:
        """
        Calculate VIX slope over the specified time window.

        Args:
            window_minutes: Time window in minutes (default 60)

        Returns:
            VIXSlope with direction, normalized_slope, and steepness
        """
        return calculate_vix_slope(self.history, window_minutes)

    def get_session_open_vix(self) -> Optional[float]:
        """Get the first VIX reading of the session."""
        if self.history:
            return self.history[0].get('vix')
        return None
