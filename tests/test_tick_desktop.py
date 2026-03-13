"""
Tests for desktop app tick accumulation - TDD style.
Tests persistence, auto-save, and lifecycle management.
"""
import pytest
import tempfile
import shutil
import time
import json
import os
from datetime import datetime


class TestTickDataPersistenceOnStartup:
    """Tests for loading tick data when app starts."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_loads_existing_data_on_init(self, temp_data_dir):
        """Manager should load existing tick data on initialization."""
        from utils.tick_data_manager import TickDataManager

        # Create and save data
        manager1 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager1.set_opening_oi(".SPXW260312C5700", 1000)
        manager1.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager1.save()

        # New manager should load it
        manager2 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        assert manager2.get_adjusted_oi(".SPXW260312C5700") == 1100

    def test_auto_load_flag(self, temp_data_dir):
        """Manager should respect auto_load=False."""
        from utils.tick_data_manager import TickDataManager

        # Create and save data
        manager1 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager1.set_opening_oi(".SPXW260312C5700", 1000)
        manager1.save()

        # New manager with auto_load=False should not load
        manager2 = TickDataManager(expiry="260312", data_folder=temp_data_dir, auto_load=False)
        assert manager2.get_adjusted_oi(".SPXW260312C5700") is None


class TestPeriodicAutoSave:
    """Tests for periodic auto-save functionality."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_maybe_save_respects_interval(self, temp_data_dir):
        """maybe_save should only save after interval elapsed."""
        from utils.tick_data_manager import TickDataManager
        import time as time_module

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)

        # First save
        manager.save()
        first_save_time = manager._last_save_time

        # Add more data (via process_message to set _dirty)
        msg = {
            "type": "FEED_DATA",
            "data": [{"eventType": "TimeAndSale", "eventSymbol": ".SPXW260312C5700", "aggressorSide": "BUY", "size": 50}]
        }
        manager.process_message(msg)

        # maybe_save with long interval should not save
        manager.maybe_save(interval=3600)  # 1 hour
        assert manager._last_save_time == first_save_time

        # Force time to advance and save
        time_module.sleep(0.01)
        manager.maybe_save(interval=0)
        assert manager._last_save_time > first_save_time

    def test_needs_save_tracks_dirty_state(self, temp_data_dir):
        """needs_save should reflect unsaved changes."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)

        # Initially not dirty (no changes)
        assert manager.needs_save() is False

        # Add data - should be dirty
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        assert manager.needs_save() is True

        # After save - should not be dirty
        manager.save()
        assert manager.needs_save() is False

        # Add tick - should be dirty again
        manager.accumulator.add_tick(".SPXW260312C5700", 50, "BUY")
        manager._dirty = True  # Manually set since add_tick doesn't set it
        assert manager.needs_save() is True


class TestAppLifecycleHooks:
    """Tests for app startup/shutdown hooks."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_save_on_shutdown(self, temp_data_dir):
        """Should save data when app shuts down."""
        from utils.tick_data_manager import TickDataManager
        from components.tick_lifecycle import save_on_shutdown

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)
        manager.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")

        # Simulate shutdown
        save_on_shutdown(manager)

        # Verify data was saved
        file_path = os.path.join(temp_data_dir, "260312.json")
        assert os.path.exists(file_path)

        with open(file_path, 'r') as f:
            data = json.load(f)
        assert data["symbols"][".SPXW260312C5700"]["buy_volume"] == 100

    def test_get_startup_summary(self, temp_data_dir):
        """Should provide summary of loaded data on startup."""
        from utils.tick_data_manager import TickDataManager
        from components.tick_lifecycle import get_startup_summary

        # Create existing data
        manager1 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager1.set_opening_oi(".SPXW260312C5700", 1000)
        manager1.accumulator.add_tick(".SPXW260312C5700", 100, "BUY")
        manager1.accumulator.add_tick(".SPXW260312C5700", 30, "SELL")
        manager1.save()

        # Load and get summary
        manager2 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        summary = get_startup_summary(manager2)

        assert summary["loaded"] is True
        assert summary["symbol_count"] == 1
        assert summary["total_ticks"] == 130  # buy + sell


class TestLastSaveInfo:
    """Tests for last save timestamp tracking."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary data directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_last_save_timestamp_tracked(self, temp_data_dir):
        """Should track when data was last saved."""
        from utils.tick_data_manager import TickDataManager

        manager = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager.set_opening_oi(".SPXW260312C5700", 1000)

        # Before save - no timestamp
        assert manager.get_last_save_time() is None

        # After save - should have timestamp
        manager.save()
        last_save = manager.get_last_save_time()
        assert last_save is not None

    def test_last_save_persists_across_sessions(self, temp_data_dir):
        """Last save time should be loaded from file."""
        from utils.tick_data_manager import TickDataManager

        # Save with timestamp
        manager1 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        manager1.set_opening_oi(".SPXW260312C5700", 1000)
        manager1.save()

        # Load in new session
        manager2 = TickDataManager(expiry="260312", data_folder=temp_data_dir)
        assert manager2.get_last_save_time() is not None
