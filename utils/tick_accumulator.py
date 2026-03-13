"""
Tick Data Accumulator for Real-Time OI Estimation.

Tracks buy vs sell initiated volume from TimeAndSale tick data
to estimate intraday OI changes.

Formula: Estimated OI = Opening OI + (Buy Volume - Sell Volume)
"""
import json
import os
import logging
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from utils.app_paths import get_data_folder

logger = logging.getLogger(__name__)

TICK_DATA_FOLDER = get_data_folder("tick_data")


@dataclass
class TickAccumulation:
    """Accumulated tick data for a single symbol."""

    opening_oi: int = 0
    buy_volume: int = 0
    sell_volume: int = 0
    undefined_volume: int = 0
    last_update: float = 0.0

    @property
    def net_volume(self) -> int:
        """Net volume = buy - sell."""
        return self.buy_volume - self.sell_volume

    @property
    def adjusted_oi(self) -> int:
        """Estimated OI = opening OI + net volume."""
        return self.opening_oi + self.net_volume

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "opening_oi": self.opening_oi,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "undefined_volume": self.undefined_volume,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "TickAccumulation":
        """Deserialize from dictionary."""
        return cls(
            opening_oi=d.get("opening_oi", 0),
            buy_volume=d.get("buy_volume", 0),
            sell_volume=d.get("sell_volume", 0),
            undefined_volume=d.get("undefined_volume", 0),
            last_update=d.get("last_update", 0.0),
        )


class TickDataAccumulator:
    """
    Accumulates tick data for real-time OI estimation.

    Thread-safe accumulator that:
    - Tracks buy/sell volume per symbol
    - Persists to disk for recovery
    - Resets on new trading day
    """

    def __init__(self, expiry: str, data_folder: str = None):
        """
        Initialize accumulator for a specific expiry.

        Args:
            expiry: Option expiry in YYMMDD format (e.g., "260312")
            data_folder: Override data folder (for testing)
        """
        self.expiry = expiry
        self.data_folder = data_folder or TICK_DATA_FOLDER
        self._data: Dict[str, TickAccumulation] = {}
        self._lock = threading.Lock()
        self._date: str = datetime.now().strftime("%Y-%m-%d")
        self._last_save: Optional[str] = None

        self._ensure_folder()

    def _ensure_folder(self):
        """Create data folder if it doesn't exist."""
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
            logger.info(f"Created {self.data_folder} folder")

    def _get_file_path(self) -> str:
        """Get the JSON file path for this expiry."""
        return os.path.join(self.data_folder, f"{self.expiry}.json")

    def set_opening_oi(self, symbol: str, oi: int):
        """
        Set the opening OI for a symbol.

        Args:
            symbol: Option symbol (e.g., ".SPXW260312C5700")
            oi: Opening OI from Summary event
        """
        with self._lock:
            if symbol not in self._data:
                self._data[symbol] = TickAccumulation()
            self._data[symbol].opening_oi = oi
            self._data[symbol].last_update = time.time()

    def add_tick(self, symbol: str, size: int, aggressor_side: str):
        """
        Add a tick from TimeAndSale event.

        Args:
            symbol: Option symbol
            size: Trade size (contracts)
            aggressor_side: "BUY", "SELL", or "UNDEFINED"
        """
        with self._lock:
            if symbol not in self._data:
                self._data[symbol] = TickAccumulation()

            acc = self._data[symbol]
            side = aggressor_side.upper() if aggressor_side else "UNDEFINED"

            if side == "BUY":
                acc.buy_volume += size
            elif side == "SELL":
                acc.sell_volume += size
            else:
                acc.undefined_volume += size

            acc.last_update = time.time()

    def get_adjusted_oi(self, symbol: str) -> Optional[int]:
        """
        Get the adjusted OI for a symbol.

        Returns:
            Adjusted OI or None if symbol not tracked
        """
        with self._lock:
            if symbol not in self._data:
                return None
            return self._data[symbol].adjusted_oi

    def get_volume_breakdown(self, symbol: str) -> Dict:
        """
        Get volume breakdown for a symbol.

        Returns:
            Dict with buy_volume, sell_volume, undefined_volume, opening_oi
        """
        with self._lock:
            if symbol not in self._data:
                return {
                    "buy_volume": 0,
                    "sell_volume": 0,
                    "undefined_volume": 0,
                    "opening_oi": 0,
                }

            acc = self._data[symbol]
            return {
                "buy_volume": acc.buy_volume,
                "sell_volume": acc.sell_volume,
                "undefined_volume": acc.undefined_volume,
                "opening_oi": acc.opening_oi,
            }

    def save_to_disk(self):
        """Persist accumulated data to JSON file."""
        with self._lock:
            data = {
                "date": self._date,
                "expiry": self.expiry,
                "last_save": datetime.now().isoformat(),
                "symbols": {
                    symbol: acc.to_dict()
                    for symbol, acc in self._data.items()
                },
            }

        file_path = self._get_file_path()
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            self._last_save = data["last_save"]
            logger.info(f"Saved {len(self._data)} symbols to {file_path}")
        except IOError as e:
            logger.error(f"Could not save tick data: {e}")

    def load_from_disk(self, check_date: bool = False):
        """
        Load accumulated data from JSON file.

        Args:
            check_date: If True, ignore file if date doesn't match today
        """
        file_path = self._get_file_path()

        if not os.path.exists(file_path):
            logger.info(f"No existing tick data at {file_path}")
            return

        try:
            with open(file_path, "r") as f:
                data = json.load(f)

            # Check date if requested
            if check_date:
                file_date = data.get("date", "")
                today = datetime.now().strftime("%Y-%m-%d")
                if file_date != today:
                    logger.info(
                        f"Ignoring old tick data (file: {file_date}, today: {today})"
                    )
                    return

            # Load symbols
            with self._lock:
                self._date = data.get("date", self._date)
                self._last_save = data.get("last_save")

                for symbol, acc_data in data.get("symbols", {}).items():
                    self._data[symbol] = TickAccumulation.from_dict(acc_data)

            logger.info(f"Loaded {len(self._data)} symbols from {file_path}")

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load tick data: {e}")

    def get_all_symbols(self) -> list:
        """Get list of all tracked symbols."""
        with self._lock:
            return list(self._data.keys())

    def get_stats(self) -> Dict:
        """Get accumulator statistics."""
        with self._lock:
            total_buy = sum(acc.buy_volume for acc in self._data.values())
            total_sell = sum(acc.sell_volume for acc in self._data.values())
            total_undefined = sum(acc.undefined_volume for acc in self._data.values())

            return {
                "symbol_count": len(self._data),
                "total_buy_volume": total_buy,
                "total_sell_volume": total_sell,
                "total_undefined_volume": total_undefined,
                "net_volume": total_buy - total_sell,
                "last_save": self._last_save,
            }


# --- WebSocket Integration Functions ---


def parse_time_and_sale_event(event: Dict) -> Optional[Dict]:
    """
    Parse a TimeAndSale event from dxFeed.

    Args:
        event: Raw event dict from FEED_DATA message

    Returns:
        Parsed dict with symbol, size, side, price or None if not TimeAndSale
    """
    if event.get("eventType") != "TimeAndSale":
        return None

    aggressor_side = event.get("aggressorSide")
    if aggressor_side is None:
        side = "UNDEFINED"
    else:
        side = aggressor_side.upper() if aggressor_side else "UNDEFINED"

    return {
        "symbol": event.get("eventSymbol"),
        "size": event.get("size", 0),
        "side": side,
        "price": event.get("price", 0.0),
        "time": event.get("time"),
    }


def process_feed_data(
    msg: Dict,
    accumulator: TickDataAccumulator,
    set_opening_oi: bool = False,
    delta_calculator=None,
    greeks_data: Optional[Dict] = None,
):
    """
    Process a FEED_DATA message and update the accumulator.

    Args:
        msg: The FEED_DATA message from WebSocket
        accumulator: TickDataAccumulator instance to update
        set_opening_oi: If True, also set opening OI from Summary events
        delta_calculator: Optional DeltaFlowCalculator to update with trade delta
        greeks_data: Dict mapping symbol -> {delta, ...} for delta calculation
    """
    if msg.get("type") != "FEED_DATA":
        return

    for event in msg.get("data", []):
        event_type = event.get("eventType")
        symbol = event.get("eventSymbol")

        if event_type == "TimeAndSale":
            parsed = parse_time_and_sale_event(event)
            if parsed and parsed["size"] > 0:
                accumulator.add_tick(
                    parsed["symbol"],
                    parsed["size"],
                    parsed["side"],
                )

                # Update delta calculator if provided
                if delta_calculator is not None and greeks_data is not None:
                    delta = greeks_data.get(parsed["symbol"], {}).get("delta", 0)
                    if delta != 0:
                        delta_calculator.process_trade(
                            symbol=parsed["symbol"],
                            aggressor_side=parsed["side"],
                            contracts=parsed["size"],
                            delta=delta,
                        )

        elif event_type == "Summary" and set_opening_oi:
            oi = event.get("openInterest", 0)
            if oi and symbol:
                accumulator.set_opening_oi(symbol, oi)


def generate_tick_subscriptions(symbols: list) -> list:
    """
    Generate TimeAndSale subscription list for symbols.

    Args:
        symbols: List of option symbols

    Returns:
        List of subscription dicts for FEED_SUBSCRIPTION message
    """
    return [{"symbol": s, "type": "TimeAndSale"} for s in symbols]


# --- GEX Integration Helpers ---


def get_effective_oi(
    symbol: str,
    raw_oi: int,
    accumulator: Optional[TickDataAccumulator] = None,
) -> int:
    """
    Get effective OI for a symbol, using adjusted OI when available.

    Args:
        symbol: Option symbol
        raw_oi: Raw OI from Summary event
        accumulator: Optional accumulator with tick data

    Returns:
        Adjusted OI if tick data available, otherwise raw OI
    """
    if accumulator is None:
        return raw_oi

    adjusted = accumulator.get_adjusted_oi(symbol)
    if adjusted is not None:
        return adjusted

    return raw_oi


def get_oi_adjustment_info(
    symbol: str,
    accumulator: Optional[TickDataAccumulator] = None,
) -> Dict:
    """
    Get detailed OI adjustment info for display.

    Args:
        symbol: Option symbol
        accumulator: Optional accumulator with tick data

    Returns:
        Dict with opening_oi, buy_volume, sell_volume, etc.
    """
    if accumulator is None:
        return {
            "has_tick_data": False,
            "opening_oi": 0,
            "buy_volume": 0,
            "sell_volume": 0,
            "undefined_volume": 0,
            "net_adjustment": 0,
            "adjusted_oi": 0,
        }

    breakdown = accumulator.get_volume_breakdown(symbol)
    has_data = breakdown["opening_oi"] > 0 or breakdown["buy_volume"] > 0 or breakdown["sell_volume"] > 0

    net_adjustment = breakdown["buy_volume"] - breakdown["sell_volume"]
    adjusted_oi = breakdown["opening_oi"] + net_adjustment

    return {
        "has_tick_data": has_data,
        "opening_oi": breakdown["opening_oi"],
        "buy_volume": breakdown["buy_volume"],
        "sell_volume": breakdown["sell_volume"],
        "undefined_volume": breakdown["undefined_volume"],
        "net_adjustment": net_adjustment,
        "adjusted_oi": adjusted_oi,
    }


def get_bulk_effective_oi(
    raw_oi_map: Dict[str, int],
    accumulator: Optional[TickDataAccumulator] = None,
) -> Dict[str, int]:
    """
    Get effective OI for multiple symbols efficiently.

    Args:
        raw_oi_map: Dict mapping symbol -> raw OI
        accumulator: Optional accumulator with tick data

    Returns:
        Dict mapping symbol -> effective OI
    """
    result = {}
    for symbol, raw_oi in raw_oi_map.items():
        result[symbol] = get_effective_oi(symbol, raw_oi, accumulator)
    return result
