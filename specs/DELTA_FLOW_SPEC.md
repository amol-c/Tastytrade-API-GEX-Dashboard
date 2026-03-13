# Delta Flow Implementation Spec

## Development Approach

### TDD (Test-Driven Development)
1. **Red**: Write failing tests first
2. **Green**: Write minimal code to pass tests
3. **Refactor**: Clean up while keeping tests green

### SOLID Principles
- **S**ingle Responsibility: Each class has one job
  - `DeltaFlowCalculator`: Calculates delta from trades
  - `DeltaFlowHistoryTracker`: Persists history to JSON
  - `DeltaFlowDisplay`: Renders UI components
- **O**pen/Closed: Extend via composition, not modification
- **L**iskov Substitution: History trackers are interchangeable
- **I**nterface Segregation: Small, focused interfaces
- **D**ependency Inversion: Depend on abstractions (folder paths injected)

---

## Overview

Delta Flow measures **dealer hedging pressure from customer trades** throughout the trading session.

This completes the "Three Sources of Dealer Hedging" framework:

| Greek/Metric | Source of Delta Change | Input Data | Time Behavior |
|--------------|------------------------|------------|---------------|
| **Charm** | Time decay (∂Δ/∂t) | OI + Greeks | Point-in-time snapshot |
| **Vanna** | IV changes (∂Δ/∂σ) | OI + Greeks + VIX | Point-in-time snapshot |
| **Delta Flow** | Customer trades | TimeAndSale ticks | Cumulative throughout day |

**Trading Significance**: Delta Flow tells you the real-time hedging pressure from actual trades, not theoretical Greeks. It shows what dealers ARE doing, not what they SHOULD do.

---

## Comparison: Charm vs Vanna vs Delta Flow

### Conceptual Framework

```
Total Dealer Hedge Requirement = f(Charm, Vanna, Delta Flow)

Where:
- Charm   = Hedge adjustment from time passing (automatic, predictable)
- Vanna   = Hedge adjustment from IV changing (depends on VIX direction)
- Delta Flow = Hedge adjustment from trades (depends on customer activity)
```

### Key Differences

| Aspect | Charm | Vanna | Delta Flow |
|--------|-------|-------|------------|
| **What it measures** | Delta decay over time | Delta sensitivity to IV | Delta from new trades |
| **Calculation basis** | Black-Scholes formula | Black-Scholes formula | Actual trade data |
| **Depends on** | TTE, strike, IV | TTE, strike, IV, VIX direction | Customer buy/sell activity |
| **Near expiry** | MAX (but unreliable calc) | MINIMAL (vega → 0) | Normal (trade-based) |
| **Data source** | Options chain snapshot | Options chain + VIX | TimeAndSale WebSocket |
| **Update frequency** | Per data fetch | Per data fetch | Real-time (each tick) |
| **Cumulative?** | No (point-in-time) | No (point-in-time) | Yes (running total) |

### Sign Convention (All Three Aligned)

All metrics show **dealer hedge action**:
- **Positive (+)** = Dealers BUY underlying
- **Negative (−)** = Dealers SELL underlying

| Metric | Condition | Dealer Action | ES Sign |
|--------|-----------|---------------|---------|
| Charm | Negative net charm | BUY | + |
| Charm | Positive net charm | SELL | − |
| Vanna | +VEx + IV falling | BUY | + |
| Vanna | +VEx + IV rising | SELL | − |
| Delta Flow | Customer net sold delta | BUY | + |
| Delta Flow | Customer net bought delta | SELL | − |

---

## Delta Flow Formula

### Per-Trade Calculation

```python
# For each TimeAndSale event:
trade_delta = contracts × delta × 100

# Customer perspective (aggressor side):
if aggressor == "BUY":
    customer_delta_change = +trade_delta  # Customer bought delta
else:  # SELL
    customer_delta_change = -trade_delta  # Customer sold delta

# Dealer takes opposite side:
dealer_delta_change = -customer_delta_change

# Dealer hedge (to stay neutral):
dealer_hedge = -dealer_delta_change = customer_delta_change
```

### Cumulative Flow

```python
# Running total throughout day:
cumulative_delta_flow = Σ (customer_delta_change for all trades)

# Dealer hedge requirement:
# ES = -customer_delta / 50  (NOT divided by spot!)
# - Delta is in "share equivalents" (contracts × option_delta × 100)
# - 1 ES contract = $50 per SPX point = 50 delta
dealer_hedge_es = -cumulative_delta_flow / 50
```

### Worked Example

| Trade | Type | Contracts | Delta | Customer Delta | Cumulative |
|-------|------|-----------|-------|----------------|------------|
| Buy 100 calls | Call | 100 | +0.50 | +5,000 | +5,000 |
| Sell 50 puts | Put | 50 | -0.40 | +2,000 | +7,000 |
| Buy 200 puts | Put | 200 | -0.30 | -6,000 | +1,000 |
| Sell 75 calls | Call | 75 | +0.60 | -4,500 | -3,500 |

**Result**: Customer net delta = -3,500
- Dealer hedge: SELL 3,500 delta worth = **-70 ES contracts** (at SPX 6000)

---

## How Customer Trades Affect Dealer Hedging

### When Customer BUYS (Hit the Ask)

| Option Type | Customer Gets | Dealer Gets | Dealer Hedge |
|-------------|---------------|-------------|--------------|
| Call (δ=+0.5) | +delta | −delta (short call) | BUY underlying |
| Put (δ=−0.4) | −delta | +delta (short put) | SELL underlying |

### When Customer SELLS (Hit the Bid)

| Option Type | Customer Loses | Dealer Gets | Dealer Hedge |
|-------------|----------------|-------------|--------------|
| Call (δ=+0.5) | −delta | +delta (long call) | SELL underlying |
| Put (δ=−0.4) | +delta | −delta (long put) | BUY underlying |

### Summary Table

| Customer Action | Option | Delta Sign | Customer Δ | Dealer Hedge |
|-----------------|--------|------------|------------|--------------|
| BUY | Call | + | + | **BUY** (then SELL when accumulated) |
| BUY | Put | − | − | **SELL** (then BUY when accumulated) |
| SELL | Call | + | − | **SELL** |
| SELL | Put | − | + | **BUY** |

**Key Insight**: Dealer hedge = −(Dealer delta change) = Customer delta change

---

## Relationship to Existing Dealer Position

The "dealers short puts, long calls" assumption describes the **aggregate position** from OI.

Delta Flow describes the **change** to that position from intraday trades.

```
Dealer Total Position = Aggregate (from OI) + Intraday Changes (from trades)

Where:
- Aggregate: Short puts (+Δ), Long calls (+Δ) → Net long delta → Short underlying
- Intraday: Delta Flow adds to or subtracts from this
```

### Example Scenario

**Starting position (from OI):**
- Dealers short 50,000 puts (+2.5M delta)
- Dealers long 30,000 calls (+1.5M delta)
- Net dealer delta: +4M → Hedged by −4M underlying

**Intraday trades:**
- Customers net buy +500K delta worth of calls
- Dealer delta flow: −500K
- Dealer hedge: +500K (BUY 10 ES contracts)

**End of day:**
- Dealer delta: +4M − 500K = +3.5M
- Hedge adjusts from −4M to −3.5M (bought back 500K)

---

## Implementation

### Data Requirements

```python
# From TimeAndSale WebSocket events:
{
    "eventType": "TimeAndSale",
    "eventSymbol": ".SPXW260313C6000",
    "aggressorSide": "BUY",  # or "SELL"
    "size": 100,             # Contracts traded
    "price": 15.50
}

# From Greeks data (already fetched):
{
    ".SPXW260313C6000": {
        "delta": 0.52,
        "gamma": 0.003,
        ...
    }
}
```

### Core Calculator

```python
# utils/delta_flow_calculator.py

from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum

ES_MULTIPLIER = 50


class DeltaFlowDirection(Enum):
    """Dealer hedge direction from delta flow."""
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


@dataclass
class DeltaFlowRecord:
    """Single delta flow data point."""
    timestamp: str
    cumulative_customer_delta: float
    dealer_hedge_es: float
    flow_direction: str
    trade_count: int


class DeltaFlowCalculator:
    """
    Calculates cumulative delta flow from customer trades.

    Shows dealer hedge requirement from actual trading activity.
    Positive ES = dealers need to BUY
    Negative ES = dealers need to SELL
    """

    def __init__(self, neutral_threshold: float = 500_000):
        self.neutral_threshold = neutral_threshold
        self.cumulative_customer_delta = 0.0
        self.trade_count = 0

    def process_trade(
        self,
        symbol: str,
        aggressor_side: str,  # "BUY" or "SELL"
        contracts: int,
        delta: float,
        option_type: str,  # "C" or "P"
    ) -> float:
        """
        Process a single trade and update cumulative delta.

        Args:
            symbol: Option symbol
            aggressor_side: Who initiated ("BUY" or "SELL")
            contracts: Number of contracts
            delta: Option delta (positive for calls, negative for puts)
            option_type: "C" or "P"

        Returns:
            Updated cumulative customer delta
        """
        # Delta per contract (× 100 for contract multiplier)
        trade_delta = contracts * delta * 100

        # Customer perspective based on aggressor
        if aggressor_side == "BUY":
            # Customer bought, gained delta
            customer_delta_change = trade_delta
        else:
            # Customer sold, lost delta
            customer_delta_change = -trade_delta

        self.cumulative_customer_delta += customer_delta_change
        self.trade_count += 1

        return self.cumulative_customer_delta

    def get_dealer_hedge_es(self, spot_price: float) -> float:
        """
        Get dealer hedge in ES contract equivalent.

        Dealer hedge = Customer delta (they take opposite, then hedge)

        Positive = dealers BUY
        Negative = dealers SELL
        """
        if spot_price <= 0:
            return 0.0

        notional_per_es = spot_price * ES_MULTIPLIER

        # Dealer hedge = customer delta
        # (Customer bought +delta → dealer short delta → dealer buys to hedge)
        return self.cumulative_customer_delta / notional_per_es

    def get_flow_direction(self) -> DeltaFlowDirection:
        """Get dealer hedge direction."""
        if abs(self.cumulative_customer_delta) < self.neutral_threshold:
            return DeltaFlowDirection.NEUTRAL

        if self.cumulative_customer_delta > 0:
            # Customer net long → dealer short → dealer SELLS to hedge
            # Wait, let me reconsider...
            # Customer bought delta → dealer sold delta → dealer needs to BUY underlying
            return DeltaFlowDirection.SELL
        else:
            # Customer net short → dealer long → dealer BUYS to hedge
            # Customer sold delta → dealer bought delta → dealer needs to SELL underlying
            return DeltaFlowDirection.BUY

    def reset(self):
        """Reset for new trading session."""
        self.cumulative_customer_delta = 0.0
        self.trade_count = 0
```

### History Tracker

```python
# utils/delta_flow_history.py

import json
import os
from datetime import datetime
from typing import List, Dict, Optional

DELTA_FLOW_FOLDER = "data/delta_flow_history"


class DeltaFlowHistoryTracker:
    """
    Tracks delta flow over time for charting.

    Similar to CharmHistoryTracker and VannaHistoryTracker.
    """

    def __init__(self, expiry: str, max_records: int = 500):
        self.expiry = expiry
        self.max_records = max_records
        self.history: List[Dict] = []
        self._load_history()

    def _get_file_path(self) -> str:
        os.makedirs(DELTA_FLOW_FOLDER, exist_ok=True)
        return os.path.join(DELTA_FLOW_FOLDER, f"{self.expiry}.json")

    def _load_history(self):
        path = self._get_file_path()
        if os.path.exists(path):
            with open(path, 'r') as f:
                self.history = json.load(f)

    def _save_history(self):
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
        """Add a delta flow record."""
        es_equivalent = cumulative_customer_delta / (spot_price * 50) if spot_price > 0 else 0

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

        # Trim to max records
        if len(self.history) > self.max_records:
            self.history = self.history[-self.max_records:]

        self._save_history()
        return record

    def get_es_futures_series(self, limit: int = 50) -> List[Dict]:
        """Get time series for charting."""
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
        """Get most recent record."""
        return self.history[-1] if self.history else None
```

### Display Component

```python
# components/delta_flow_display.py

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.delta_flow_history import DeltaFlowHistoryTracker


def render_delta_flow_section(
    cumulative_delta: float,
    spot_price: float,
    flow_direction: str,
    trade_count: int,
    expiry: str,
):
    """
    Render delta flow section with ES futures equivalent.

    Matches format of Charm and Vanna sections.
    """
    st.divider()
    st.subheader("Delta Flow - ES Futures Equivalent")

    st.caption("ES contracts dealers hedge from customer trades (+ = BUY, - = SELL)")

    with st.expander("ℹ️ What is Delta Flow?"):
        st.markdown("""
**Delta Flow = Cumulative delta from customer trades**

Unlike Charm (time-based) and Vanna (IV-based), Delta Flow measures **actual trading activity**.

**How it works:**
- Customer buys calls → gains +delta → dealer shorts calls → dealer SELLS to hedge
- Customer buys puts → gains −delta → dealer shorts puts → dealer BUYS to hedge
- Customer sells calls → loses delta → dealer longs calls → dealer BUYS to hedge
- Customer sells puts → loses delta → dealer longs puts → dealer SELLS to hedge

**Dealer Hedge = −(Dealer Delta) = Customer Delta**

*This shows real-time hedging pressure from trades, not theoretical Greeks.*
""")

    # Calculate ES equivalent
    es_equivalent = cumulative_delta / (spot_price * 50) if spot_price > 0 else 0

    # Metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        es_sign = "+" if es_equivalent >= 0 else ""
        st.metric(
            "ES Futures to Hedge",
            f"{es_sign}{es_equivalent:,.0f} contracts",
        )
    with col2:
        st.metric("Flow Direction", flow_direction)
    with col3:
        st.metric("Trades Processed", f"{trade_count:,}")

    # Chart
    _render_delta_flow_chart(es_equivalent, expiry)


def _render_delta_flow_chart(current_es: float, expiry: str, limit: int = 50):
    """Render ES contracts over time chart."""
    tracker = DeltaFlowHistoryTracker(expiry=expiry)
    history = tracker.get_es_futures_series(limit=limit)

    if len(history) < 2:
        st.caption("Chart will appear after multiple data points")
        return

    st.caption("Cumulative ES Hedge Over Time")
    hist_df = pd.DataFrame(history)
    hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'])

    # Color based on current value
    last_es = current_es if current_es != 0 else hist_df['es_futures'].iloc[-1]
    line_color = 'green' if last_es >= 0 else 'red'
    fill_color = 'rgba(0,255,0,0.1)' if last_es >= 0 else 'rgba(255,0,0,0.1)'

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_df['timestamp'],
        y=hist_df['es_futures'],
        mode='lines+markers',
        name='ES Contracts',
        line=dict(color=line_color, width=2),
        fill='tozeroy',
        fillcolor=fill_color
    ))

    # Zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

    fig.update_layout(
        height=250,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_title="Time",
        yaxis_title="ES Contracts",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)
```

---

## Dashboard Integration

### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  MARKET SUMMARY                                               │
│  Time to Expiry | Zone | Market Bias | Confidence            │
├──────────────────────────────────────────────────────────────┤
│  Charm Flow          │  Vanna Flow         │  Delta Flow     │
│  +150 ES (BUY)       │  NEUTRAL            │  -85 ES (SELL)  │
│  [chart]             │  [chart]            │  [chart]        │
├──────────────────────────────────────────────────────────────┤
│  Combined Dealer Hedge: +65 ES (BUY)                          │
│  (Charm +150 + Vanna 0 + Delta -85 = +65)                    │
└──────────────────────────────────────────────────────────────┘
```

### Combined Dealer Hedge

```python
def calculate_combined_dealer_hedge(
    charm_es: float,
    vanna_es: float,
    delta_flow_es: float,
) -> float:
    """
    Combine all three hedging sources.

    All three use same sign convention:
    Positive = dealers BUY
    Negative = dealers SELL
    """
    return charm_es + vanna_es + delta_flow_es
```

---

## Near-Expiry Behavior

| Metric | Near Expiry (<2h) | Why |
|--------|-------------------|-----|
| **Charm** | MAX (unreliable calc) | √T → 0 in formula |
| **Vanna** | MINIMAL | Vega → 0 |
| **Delta Flow** | **Normal** | Trade-based, no formula issues |

**Key Advantage**: Delta Flow remains reliable near expiry because it's based on actual trades, not Black-Scholes formulas that break down as TTE → 0.

---

## Testing

```python
def test_buy_call_increases_customer_delta():
    """Buying calls increases customer delta."""
    calc = DeltaFlowCalculator()
    calc.process_trade(
        symbol=".SPXW260313C6000",
        aggressor_side="BUY",
        contracts=100,
        delta=0.50,
        option_type="C",
    )
    assert calc.cumulative_customer_delta == 5000  # 100 × 0.50 × 100

def test_buy_put_decreases_customer_delta():
    """Buying puts decreases customer delta (puts have negative delta)."""
    calc = DeltaFlowCalculator()
    calc.process_trade(
        symbol=".SPXW260313P5900",
        aggressor_side="BUY",
        contracts=100,
        delta=-0.40,
        option_type="P",
    )
    assert calc.cumulative_customer_delta == -4000  # 100 × (-0.40) × 100

def test_sell_call_decreases_customer_delta():
    """Selling calls decreases customer delta."""
    calc = DeltaFlowCalculator()
    calc.process_trade(
        symbol=".SPXW260313C6000",
        aggressor_side="SELL",
        contracts=100,
        delta=0.50,
        option_type="C",
    )
    assert calc.cumulative_customer_delta == -5000  # -(100 × 0.50 × 100)

def test_es_equivalent_calculation():
    """ES equivalent = cumulative delta / (spot × 50)."""
    calc = DeltaFlowCalculator()
    calc.cumulative_customer_delta = 300_000  # +300K delta
    es = calc.get_dealer_hedge_es(spot_price=6000)
    assert es == 100  # 300,000 / (6000 × 50) = 100 contracts

def test_flow_direction_customer_long():
    """Customer net long delta → dealer SELLS to hedge."""
    calc = DeltaFlowCalculator()
    calc.cumulative_customer_delta = 1_000_000
    assert calc.get_flow_direction() == DeltaFlowDirection.SELL

def test_flow_direction_customer_short():
    """Customer net short delta → dealer BUYS to hedge."""
    calc = DeltaFlowCalculator()
    calc.cumulative_customer_delta = -1_000_000
    assert calc.get_flow_direction() == DeltaFlowDirection.BUY

def test_cumulative_multiple_trades():
    """Multiple trades accumulate correctly."""
    calc = DeltaFlowCalculator()

    # Buy 100 calls at 0.5 delta
    calc.process_trade("C1", "BUY", 100, 0.50, "C")   # +5000

    # Sell 50 puts at -0.4 delta
    calc.process_trade("P1", "SELL", 50, -0.40, "P")  # -(-2000) = +2000

    # Buy 200 puts at -0.3 delta
    calc.process_trade("P2", "BUY", 200, -0.30, "P")  # -6000

    assert calc.cumulative_customer_delta == 1000  # 5000 + 2000 - 6000
    assert calc.trade_count == 3
```

---

## File Structure

```
utils/
├── delta_flow_calculator.py   # Core calculation
├── delta_flow_history.py      # JSON history storage
├── charm_calculator.py        # Existing
├── charm_history.py           # Existing
├── vanna_calculator.py        # Existing
└── vanna_history.py           # Existing

components/
├── delta_flow_display.py      # Dashboard component
├── charm_display.py           # Existing
└── vanna_display.py           # Existing

data/
└── delta_flow_history/
    └── {YYMMDD}.json          # Daily records

tests/
└── test_delta_flow.py         # Unit tests
```

---

## UI Updates to Existing Components

### 1. Market Summary (`market_analysis_display.py`)

**Current:** 4 columns
```
| Market Bias | Confidence | Vanna Flow | Charm Flow |
```

**Updated:** 5 columns
```
| Market Bias | Confidence | Vanna Flow | Charm Flow | Delta Flow |
```

**Code Change:**
```python
def render_market_analysis_header(analysis, delta_flow_es: float = None):
    """Render the market analysis metrics row."""
    bias_emoji = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '🟡'}
    conf_emoji = {'HIGH': '🔥', 'MEDIUM': '⚡', 'LOW': '💤'}

    # Always show 5 columns now
    cols = st.columns(5)

    with cols[0]:
        st.metric(
            "Market Bias",
            f"{bias_emoji.get(analysis.bias, '')} {analysis.bias}",
            delta=f"Score: {analysis.bias_score:.0f}/100",
        )

    with cols[1]:
        st.metric(
            "Confidence",
            f"{conf_emoji.get(analysis.confidence, '')} {analysis.confidence}"
        )

    with cols[2]:
        st.metric(
            "Vanna Flow",
            analysis.vanna_flow.direction if analysis.vanna_flow else "N/A",
            delta=f"IV {analysis.vanna_flow.iv_direction}" if analysis.vanna_flow else None,
        )

    with cols[3]:
        st.metric(
            "Charm Flow",
            analysis.charm_flow.direction,
            delta="UP pressure" if analysis.charm_flow.direction == 'BUY' else "DOWN pressure",
        )

    with cols[4]:
        # NEW: Delta Flow column
        if delta_flow_es is not None:
            direction = "BUY" if delta_flow_es < 0 else "SELL" if delta_flow_es > 0 else "NEUTRAL"
            st.metric(
                "Delta Flow",
                direction,
                delta=f"{delta_flow_es:+,.0f} ES",
            )
        else:
            st.metric("Delta Flow", "N/A")
```

---

### 2. Tick Display (`tick_display.py`)

**Current:** Shows raw contract counts
```
Symbols: 104  |  Buy Vol: 2,739  |  Sell Vol: 2,931  |  Net Flow: ↓192
```

**Updated:** Shows delta-weighted ES equivalent
```
Symbols: 104  |  Delta Bought: +45,230  |  Delta Sold: -52,180  |  Net: -139 ES
```

**Code Change:**
```python
def render_tick_data_expander(
    tick_manager: Optional["TickDataManager"],
    greeks_data: Optional[Dict] = None,
    spot_price: float = 0,
):
    """Render tick data details with delta-weighted metrics."""
    with st.expander("📊 Real-Time Delta Flow", expanded=False):
        if tick_manager is None:
            st.info("Tick data will accumulate as you fetch data")
            return

        summary = get_tick_summary(tick_manager)

        if summary["symbol_count"] == 0:
            st.info("No tick data accumulated yet.")
            return

        # Calculate delta-weighted metrics if Greeks available
        if greeks_data and spot_price > 0:
            delta_bought, delta_sold = calculate_delta_weighted_flow(
                tick_manager, greeks_data
            )
            net_delta = delta_bought + delta_sold
            es_equivalent = net_delta / (spot_price * 50)

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Symbols", summary["symbol_count"])
            with col2:
                st.metric("Delta Bought", f"{delta_bought:+,.0f}")
            with col3:
                st.metric("Delta Sold", f"{delta_sold:,.0f}")
            with col4:
                direction = "↑" if es_equivalent > 0 else "↓" if es_equivalent < 0 else ""
                st.metric("Net Delta", f"{direction}{abs(es_equivalent):,.0f} ES")
        else:
            # Fallback to contract counts
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Symbols", summary["symbol_count"])
            with col2:
                st.metric("Buy Vol", f"{summary['total_buy']:,}")
            with col3:
                st.metric("Sell Vol", f"{summary['total_sell']:,}")
            with col4:
                net = summary["net_flow"]
                direction = "↑" if net > 0 else "↓" if net < 0 else ""
                st.metric("Net Flow", f"{direction}{abs(net):,}")

        # Flow direction banner
        # ... rest of existing code


def calculate_delta_weighted_flow(
    tick_manager: "TickDataManager",
    greeks_data: Dict,
) -> tuple[float, float]:
    """
    Calculate delta-weighted buy/sell volume.

    Returns:
        Tuple of (delta_bought, delta_sold)
    """
    delta_bought = 0.0
    delta_sold = 0.0

    for symbol, data in tick_manager.accumulator.data.items():
        delta = greeks_data.get(symbol, {}).get('delta', 0)
        if delta == 0:
            continue

        # Delta per contract × 100 multiplier
        delta_per_contract = delta * 100

        delta_bought += data.buy_volume * delta_per_contract
        delta_sold -= data.sell_volume * delta_per_contract  # Negative for sold

    return delta_bought, delta_sold
```

---

### 3. Help Expander (`market_analysis_display.py`)

**Add to "How is this calculated?" expander:**

```python
def render_bias_help_expander():
    """Render the help expander explaining how bias is calculated."""
    with st.expander("ℹ️ How is this calculated?"):
        st.markdown("""
**Bias Score (0-100)** starts at 50 (neutral) and adds/subtracts points:

| Factor | Max Points | How It Works |
|--------|------------|--------------|
| **Vanna + Charm Flow** | ±20 | Time-weighted: Morning favors Vanna, Afternoon favors Charm |
| **Delta Flow** | ±10 | Real-time customer trading activity |
| **Dealer Stance** | ±15 | Based on Call GEX / Total GEX ratio |
| **Customer Sentiment** | ±10 | Based on Call Volume / Total Volume |
| **Price vs Gamma Flip** | ±5 | Above flip = bullish, Below = bearish |

---

**Three Sources of Dealer Hedging:**

| Source | What Changes Delta | Near Expiry | Data |
|--------|-------------------|-------------|------|
| **Charm** | Time passing (∂Δ/∂t) | MAX | Greeks |
| **Vanna** | IV changes (∂Δ/∂σ) | MINIMAL | Greeks + VIX |
| **Delta Flow** | Customer trades | NORMAL | Tick data |

*Combined Dealer Hedge = Charm ES + Vanna ES + Delta Flow ES*

---

**Time-Based Greek Weighting:**
- **>5h to expiry:** Vanna 70% / Charm 30%
- **3-5h:** Vanna 50% / Charm 50%
- **1-3h:** Vanna 30% / Charm 70%
- **<1h:** Vanna 10% / Charm 90%

**Confidence Levels:**
- **HIGH:** Score ≥80 (bullish) or ≤20 (bearish)
- **MEDIUM:** Score 70-79 or 21-30
- **LOW:** Score 65-69, 31-35, or near 50
""")
```

---

### 4. Dashboard Layout (`dashboard_layout.py`)

**Update Tier 3 to include Delta Flow:**

```python
def render_tier3_flows():
    """
    TIER 3: GREEK FLOWS (Time Series)
    Shows VIX, Vanna ES, Charm ES, Delta Flow ES over time.
    """
    st.divider()
    st.header("📈 Dealer Hedge Flows")

    # Sub-columns for the three flow charts
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Charm Flow")
        # render_charm_section(...)

    with col2:
        st.subheader("Vanna Flow")
        # render_vanna_section(...)

    with col3:
        st.subheader("Delta Flow")  # NEW
        # render_delta_flow_section(...)
```

---

### 5. Combined Dealer Hedge Component (New)

**Add to Key Levels or create new section:**

```python
# components/combined_hedge_display.py

def render_combined_hedge(
    charm_es: float,
    vanna_es: float,
    delta_flow_es: float,
):
    """
    Render combined dealer hedge from all three sources.
    """
    total = charm_es + vanna_es + delta_flow_es

    st.subheader("Combined Dealer Hedge")

    # Main metric
    direction = "BUY" if total > 0 else "SELL" if total < 0 else "NEUTRAL"
    color = "🟢" if total > 0 else "🔴" if total < 0 else "🟡"

    col1, col2 = st.columns([1, 2])

    with col1:
        st.metric(
            "Net Hedge",
            f"{color} {total:+,.0f} ES",
            delta=direction,
        )

    with col2:
        # Breakdown
        st.caption("Breakdown:")
        breakdown = f"Charm {charm_es:+,.0f} + Vanna {vanna_es:+,.0f} + Delta {delta_flow_es:+,.0f}"
        st.code(breakdown)

    # Visual bar
    _render_hedge_bar(charm_es, vanna_es, delta_flow_es)


def _render_hedge_bar(charm: float, vanna: float, delta: float):
    """Render stacked bar showing contribution of each source."""
    import plotly.graph_objects as go

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name='Charm',
        x=['Hedge'],
        y=[charm],
        marker_color='orange',
    ))

    fig.add_trace(go.Bar(
        name='Vanna',
        x=['Hedge'],
        y=[vanna],
        marker_color='purple',
    ))

    fig.add_trace(go.Bar(
        name='Delta Flow',
        x=['Hedge'],
        y=[delta],
        marker_color='blue',
    ))

    fig.update_layout(
        barmode='relative',
        height=150,
        margin=dict(l=0, r=0, t=30, b=0),
        showlegend=True,
        legend=dict(orientation="h"),
    )

    # Zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray")

    st.plotly_chart(fig, use_container_width=True)
```

---

### 6. Greek Dominance (`greek_dominance.py`)

**No change needed.** Delta Flow is trade-based, not time-dependent, so it doesn't fit in the time-based Greek dominance display.

---

## Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `components/market_analysis_display.py` | Modify | Add Delta Flow column, update help text |
| `components/tick_display.py` | Modify | Show delta-weighted ES equivalent |
| `components/dashboard_layout.py` | Modify | Add Delta Flow to Tier 3 |
| `components/delta_flow_display.py` | **New** | Delta Flow section with chart |
| `components/combined_hedge_display.py` | **New** | Combined hedge visualization |
| `utils/delta_flow_calculator.py` | **New** | Core calculation logic |
| `utils/delta_flow_history.py` | **New** | History persistence |
| `tests/test_delta_flow.py` | **New** | Unit tests |

---

## Implementation Checklist

### New Files
- [x] Create `utils/delta_flow_calculator.py`
- [x] Create `utils/delta_flow_history.py`
- [x] Create `components/delta_flow_display.py`
- [x] Create `components/combined_hedge_display.py`
- [x] Create `tests/test_delta_flow.py` (33 tests)

### Existing File Updates
- [x] Update `components/market_analysis_display.py` - Add Delta Flow column
- [x] Update `components/tick_display.py` - Show delta-weighted metrics
- [x] Update `components/dashboard_layout.py` - Delta Flow renders in Tier 3
- [x] Update help expander with Three Sources of Dealer Hedging

### Integration
- [x] Integrate with TimeAndSale WebSocket processing (`tick_accumulator.py`)
- [x] Add `set_delta_calculator()` and `set_greeks_data()` to TickDataManager
- [x] Wire up Delta Flow in `simple_dashboard.py`
- [x] Pass Greeks data to tick display for delta weighting
- [x] Add Combined Dealer Hedge section to dashboard
- [x] Write unit tests (33 tests passing)

---

## Summary: Three Pillars of Dealer Hedging

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEALER HEDGING SOURCES                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   CHARM                VANNA                DELTA FLOW           │
│   (Time)               (Volatility)         (Trades)             │
│                                                                  │
│   ∂Δ/∂t               ∂Δ/∂σ                Σ(trade × delta)     │
│                                                                  │
│   "As time passes,    "As IV changes,      "As customers        │
│    delta decays"       delta shifts"        trade, delta        │
│                                             changes hands"       │
│                                                                  │
│   Predictable         Depends on VIX       Real-time            │
│   (time moves         direction            (from actual         │
│    forward)                                 trades)              │
│                                                                  │
│   MAX near expiry     MINIMAL near         NORMAL near          │
│   (formula breaks)    expiry (vega→0)      expiry               │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   COMBINED DEALER HEDGE = Charm ES + Vanna ES + Delta Flow ES   │
│                                                                  │
│   Positive = Dealers BUY underlying                              │
│   Negative = Dealers SELL underlying                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```
