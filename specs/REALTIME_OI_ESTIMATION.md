# Real-Time OI Estimation via TimeAndSale Tick Data

## Problem

Open Interest (OI) from dxFeed is **end-of-day data only**. During trading hours, we're using yesterday's closing OI, which makes GEX/Charm calculations stale - especially on high-volume days or 0DTE.

## Solution

Estimate intraday OI changes by tracking buy vs sell initiated volume from TimeAndSale tick data:

```
Estimated OI = Opening OI + (Buy Volume - Sell Volume)
```

## Requirements

### Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Subscribe to TimeAndSale events for all option symbols |
| FR-2 | Parse `aggressorSide` field (BUY/SELL/UNDEFINED) from each tick |
| FR-3 | Accumulate buy_volume and sell_volume per symbol |
| FR-4 | Calculate adjusted_oi = opening_oi + net_volume |
| FR-5 | Persist accumulated data to disk (survives app restart) |
| FR-6 | Auto-reset data at start of new trading day |
| FR-7 | Use adjusted OI in GEX/Charm calculations |

### Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | Process 100-500 ticks/second without lag |
| NFR-2 | File size < 500 KB per day |
| NFR-3 | Memory usage < 10 MB for accumulator |
| NFR-4 | Save to disk every 30 seconds |
| NFR-5 | Thread-safe accumulation |

## Data Model

### TimeAndSale Event (from dxFeed)

```json
{
  "eventType": "TimeAndSale",
  "eventSymbol": ".SPXW260312C5700",
  "aggressorSide": "BUY",
  "size": 10,
  "price": 15.50,
  "time": 1710259200000
}
```

### Accumulated Data (per symbol)

```python
@dataclass
class TickAccumulation:
    opening_oi: int = 0       # From Summary event (EOD)
    buy_volume: int = 0       # Cumulative buy-initiated
    sell_volume: int = 0      # Cumulative sell-initiated
    undefined_volume: int = 0 # Trades without side
    last_update: float = 0    # Timestamp
```

### Persisted File Format

Location: `data/tick_data/{expiry}.json`

```json
{
  "date": "2026-03-12",
  "expiry": "260312",
  "market_open": "2026-03-12T09:30:00",
  "last_save": "2026-03-12T15:30:00",
  "symbols": {
    ".SPXW260312C5700": {
      "opening_oi": 12500,
      "buy_volume": 3420,
      "sell_volume": 2180,
      "undefined_volume": 45
    }
  }
}
```

## Architecture

### Component: TickDataAccumulator

Location: `utils/tick_accumulator.py`

```
┌─────────────────────────────────────────────────────────────┐
│                    TickDataAccumulator                      │
├─────────────────────────────────────────────────────────────┤
│ Responsibilities:                                           │
│ - Receive ticks from WebSocket                              │
│ - Update in-memory counters (thread-safe)                   │
│ - Persist to disk periodically                              │
│ - Load existing data on startup                             │
│ - Reset on new trading day                                  │
├─────────────────────────────────────────────────────────────┤
│ Public Methods:                                             │
│ - set_opening_oi(symbol, oi)                                │
│ - add_tick(symbol, size, aggressor_side)                    │
│ - get_adjusted_oi(symbol) -> int                            │
│ - get_volume_breakdown(symbol) -> dict                      │
│ - save_to_disk()                                            │
│ - load_from_disk()                                          │
└─────────────────────────────────────────────────────────────┘
```

### Integration Flow

```
Market Open
    │
    ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  dxFeed     │────▶│ TickAccumulator  │────▶│ data/tick_data/ │
│  WebSocket  │     │ (in-memory)      │     │ {expiry}.json   │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │
                            ▼
                    ┌──────────────────┐
                    │  GEX Calculator  │
                    │  (uses adj. OI)  │
                    └──────────────────┘
```

### WebSocket Changes

**Current (Trade event):**
```python
{"symbol": symbol, "type": "Trade"}  # Only gets total volume
```

**New (TimeAndSale event):**
```python
{"symbol": symbol, "type": "TimeAndSale"}  # Gets aggressor side
```

## Desktop App Requirement

**The desktop app should be used instead of browser** for tick accumulation:

| Feature | Browser | Desktop App |
|---------|---------|-------------|
| Persistent connection | No (closes with tab) | Yes |
| Background accumulation | No | Yes (minimized) |
| Survives page refresh | No | Yes |
| Full day coverage | Partial | Complete |

Users should:
1. Launch desktop app at/before market open
2. Keep it running (can minimize)
3. Data persists to disk for recovery

## Assumptions & Limitations

### Assumptions

1. **Buy-initiated ≈ Opening long position** (increases OI)
2. **Sell-initiated ≈ Closing long position** (decreases OI)
3. Net effect approximates actual OI change

### Limitations

1. **Estimate, not exact** - Some trades open shorts, close shorts, etc.
2. **Better near ATM** - Liquid strikes have more meaningful data
3. **Market maker activity** - May show opposite patterns
4. **Spread trades** - aggressorSide = UNDEFINED, excluded from estimate

### Accuracy Expectations

| Strike Distance | Liquidity | Estimate Quality |
|-----------------|-----------|------------------|
| ATM (±2%) | High | Good |
| Near (±5%) | Medium | Moderate |
| Far (>5%) | Low | Use opening OI |

## File Structure

```
data/
├── charm_history/
│   └── {expiry}.json
├── vanna_history/
│   └── {expiry}.json
├── vix_history/
│   └── {date}.json
└── tick_data/           # NEW
    └── {expiry}.json
```

## Implementation Phases

### Phase 1: Core Accumulator ✅
- [x] Create `utils/tick_accumulator.py`
- [x] Implement TickAccumulation dataclass
- [x] Implement TickDataAccumulator class
- [x] Add thread-safe locking
- [x] Add file persistence (save/load)

### Phase 2: WebSocket Integration ✅
- [x] Parse aggressorSide from events (`parse_time_and_sale_event`)
- [x] Process feed data with ticks (`process_feed_data`)
- [x] Generate TimeAndSale subscriptions (`generate_tick_subscriptions`)
- [x] Handle UNDEFINED side gracefully

### Phase 3: GEX Integration ✅
- [x] `get_effective_oi()` - returns adjusted OI or fallback
- [x] `get_oi_adjustment_info()` - detailed breakdown for display
- [x] `get_bulk_effective_oi()` - efficient batch retrieval
- [x] Wire into fetch_option_data in simple_dashboard.py
- [x] `TickDataManager` - lifecycle management (SOLID principle)
- [x] Session state persistence across refreshes

### Phase 4: UI Enhancements ✅
- [x] Show buy/sell volume breakdown (`format_volume_breakdown`, `render_volume_bar`)
- [x] Display OI adjustment indicator (`format_oi_adjustment`, `render_oi_adjustment_badge`)
- [x] Add per-strike flow visualization (`prepare_strike_flow_data`)
- [x] Tick data expander with summary metrics (`render_tick_data_expander`)

### Phase 5: Desktop App ✅
- [x] Update README for desktop app usage
- [x] Ensure accumulator starts with app (`auto_load=True`, `get_startup_summary`)
- [x] Lifecycle hooks (`save_on_shutdown`, `get_startup_summary`)
- [x] Periodic auto-save (`maybe_save`, `needs_save`)
- [x] Last save timestamp tracking (`get_last_save_time`)

## Testing

### Unit Tests

```python
def test_tick_accumulation_basic():
    acc = TickDataAccumulator(expiry="260312")
    acc.set_opening_oi(".SPXW260312C5700", 1000)

    acc.add_tick(".SPXW260312C5700", 50, "BUY")
    acc.add_tick(".SPXW260312C5700", 30, "SELL")

    assert acc.get_adjusted_oi(".SPXW260312C5700") == 1020  # 1000 + 50 - 30

def test_persistence():
    acc = TickDataAccumulator(expiry="260312")
    acc.add_tick(".SPXW260312C5700", 100, "BUY")
    acc.save_to_disk()

    acc2 = TickDataAccumulator(expiry="260312")
    acc2.load_from_disk()

    assert acc2.get_volume_breakdown(".SPXW260312C5700")["buy_volume"] == 100

def test_new_day_reset():
    # Simulate yesterday's data
    acc = TickDataAccumulator(expiry="260311")
    acc.add_tick(".SPXW260311C5700", 100, "BUY")
    acc.save_to_disk()

    # New day should not load old expiry
    acc2 = TickDataAccumulator(expiry="260312")
    acc2.load_from_disk()

    assert acc2.get_adjusted_oi(".SPXW260312C5700") is None
```

### Integration Tests

- Subscribe to TimeAndSale on live feed
- Verify aggressorSide values received correctly
- Compare estimated OI to next day's actual OI

## Success Metrics

1. **Data Quality**: Adjusted OI within 10% of next-day actual OI (liquid strikes)
2. **Performance**: No UI lag with 500 ticks/second
3. **Reliability**: Zero data loss during normal operation
4. **Recovery**: Correct data after app restart

## References

- [dxFeed TimeAndSale Documentation](https://docs.dxfeed.com/dxfeed/api/com/dxfeed/event/market/TimeAndSale.html)
- [dxFeed Side Enum](https://docs.dxfeed.com/dxfeed/api/com/dxfeed/event/market/Side.html)
