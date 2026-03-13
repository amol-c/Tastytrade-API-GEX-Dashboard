"""
Tick Data Manager - Dashboard integration layer for tick accumulation.

Single Responsibility: Manages accumulator lifecycle and provides
a clean interface for the dashboard to use.

This component:
- Creates and manages TickDataAccumulator instances
- Handles expiry switching
- Processes WebSocket messages
- Provides adjusted OI for GEX calculations
"""
import logging
import time
from typing import Dict, List, Optional

from utils.tick_accumulator import (
    TickDataAccumulator,
    process_feed_data,
    generate_tick_subscriptions,
    get_effective_oi,
)
from utils.app_paths import get_data_folder

logger = logging.getLogger(__name__)

# Default save interval in seconds
DEFAULT_SAVE_INTERVAL = 30


class TickDataManager:
    """
    Manages tick data accumulation for the dashboard.

    Responsibilities:
    - Accumulator lifecycle management
    - WebSocket message processing
    - Expiry switching with data persistence
    - Providing adjusted OI for calculations
    """

    def __init__(
        self,
        expiry: str,
        data_folder: str = None,
        auto_load: bool = True,
    ):
        """
        Initialize the tick data manager.

        Args:
            expiry: Option expiry in YYMMDD format
            data_folder: Override data folder (for testing)
            auto_load: Whether to load existing data on init
        """
        self.expiry = expiry
        self.data_folder = data_folder or get_data_folder("tick_data")
        self._last_save_time = time.time()
        self._dirty = False

        self.accumulator = TickDataAccumulator(
            expiry=expiry,
            data_folder=self.data_folder,
        )

        if auto_load:
            self.accumulator.load_from_disk(check_date=True)

    def set_opening_oi(self, symbol: str, oi: int):
        """Set opening OI for a symbol."""
        self.accumulator.set_opening_oi(symbol, oi)
        self._dirty = True

    def get_adjusted_oi(self, symbol: str) -> Optional[int]:
        """Get adjusted OI for a symbol."""
        return self.accumulator.get_adjusted_oi(symbol)

    def get_effective_oi(self, symbol: str, raw_oi: int) -> int:
        """
        Get effective OI - adjusted if available, otherwise raw.

        Args:
            symbol: Option symbol
            raw_oi: Raw OI from Summary event

        Returns:
            Adjusted OI if tick data exists, otherwise raw_oi
        """
        return get_effective_oi(symbol, raw_oi, self.accumulator)

    def process_message(self, msg: Dict, set_opening_oi: bool = False):
        """
        Process a WebSocket FEED_DATA message.

        Args:
            msg: The WebSocket message
            set_opening_oi: Whether to set opening OI from Summary events
        """
        if msg.get("type") != "FEED_DATA":
            return

        process_feed_data(msg, self.accumulator, set_opening_oi=set_opening_oi)
        self._dirty = True

    def generate_subscriptions(self, symbols: List[str]) -> List[Dict]:
        """
        Generate TimeAndSale subscription list.

        Args:
            symbols: List of option symbols

        Returns:
            List of subscription dicts for FEED_SUBSCRIPTION
        """
        return generate_tick_subscriptions(symbols)

    def needs_save(self) -> bool:
        """Check if accumulator has unsaved changes."""
        return self._dirty

    def save(self):
        """Save accumulator to disk."""
        self.accumulator.save_to_disk()
        self._last_save_time = time.time()
        self._dirty = False
        logger.info(f"Saved tick data for expiry {self.expiry}")

    def maybe_save(self, interval: int = DEFAULT_SAVE_INTERVAL):
        """
        Save if enough time has passed since last save.

        Args:
            interval: Minimum seconds between saves
        """
        if self._dirty and (time.time() - self._last_save_time) >= interval:
            self.save()

    def switch_expiry(self, new_expiry: str):
        """
        Switch to a new expiry, saving current data first.

        Args:
            new_expiry: New expiry in YYMMDD format
        """
        if new_expiry == self.expiry:
            return

        # Save current data
        if self._dirty:
            self.save()

        # Create new accumulator
        self.expiry = new_expiry
        self.accumulator = TickDataAccumulator(
            expiry=new_expiry,
            data_folder=self.data_folder,
        )
        self.accumulator.load_from_disk(check_date=True)
        self._dirty = False
        logger.info(f"Switched to expiry {new_expiry}")

    def get_stats(self) -> Dict:
        """Get accumulator statistics."""
        return self.accumulator.get_stats()

    def apply_adjusted_oi(self, option_data: Dict) -> Dict:
        """
        Apply adjusted OI to option data dictionary.

        Args:
            option_data: Dict mapping symbol -> {oi, gamma, ...}

        Returns:
            Updated option_data with adjusted OI where available
        """
        result = {}
        for symbol, data in option_data.items():
            raw_oi = data.get("oi", 0) or 0
            adjusted_oi = self.get_adjusted_oi(symbol)

            result[symbol] = data.copy()

            if adjusted_oi is not None:
                result[symbol]["oi"] = adjusted_oi
                result[symbol]["oi_adjusted"] = True
                result[symbol]["oi_raw"] = raw_oi
            else:
                result[symbol]["oi_adjusted"] = False

        return result

    def get_volume_breakdown(self, symbol: str) -> Dict:
        """Get volume breakdown for a symbol."""
        return self.accumulator.get_volume_breakdown(symbol)

    def get_last_save_time(self) -> Optional[str]:
        """Get the last save timestamp."""
        return self.accumulator._last_save
