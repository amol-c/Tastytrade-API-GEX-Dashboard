"""
Tick Data Lifecycle Management

Handles app startup/shutdown hooks for tick data persistence.
Single Responsibility: Lifecycle events for tick accumulation.
"""
import logging
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.tick_data_manager import TickDataManager

logger = logging.getLogger(__name__)


def save_on_shutdown(tick_manager: Optional["TickDataManager"]):
    """
    Save tick data when app shuts down.

    Args:
        tick_manager: TickDataManager instance to save
    """
    if tick_manager is None:
        return

    if tick_manager.needs_save():
        tick_manager.save()
        logger.info("Saved tick data on shutdown")
    else:
        logger.info("No unsaved tick data on shutdown")


def get_startup_summary(tick_manager: Optional["TickDataManager"]) -> Dict:
    """
    Get summary of loaded tick data on startup.

    Args:
        tick_manager: TickDataManager instance

    Returns:
        Summary dict with loaded status and stats
    """
    if tick_manager is None:
        return {
            "loaded": False,
            "symbol_count": 0,
            "total_ticks": 0,
            "last_save": None,
        }

    stats = tick_manager.get_stats()
    total_ticks = stats["total_buy_volume"] + stats["total_sell_volume"]

    return {
        "loaded": stats["symbol_count"] > 0,
        "symbol_count": stats["symbol_count"],
        "total_ticks": total_ticks,
        "last_save": tick_manager.get_last_save_time(),
    }


def log_startup_info(tick_manager: Optional["TickDataManager"]):
    """
    Log tick data status on startup.

    Args:
        tick_manager: TickDataManager instance
    """
    summary = get_startup_summary(tick_manager)

    if summary["loaded"]:
        logger.info(
            f"Loaded tick data: {summary['symbol_count']} symbols, "
            f"{summary['total_ticks']} ticks"
        )
        if summary["last_save"]:
            logger.info(f"Last saved: {summary['last_save']}")
    else:
        logger.info("No existing tick data loaded")
