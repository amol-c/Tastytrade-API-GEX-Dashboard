# Vanna Greek Implementation Spec

## Overview

Vanna is a second-order Greek that measures:
- **∂Δ/∂σ** - Sensitivity of Delta to changes in Implied Volatility
- **∂ν/∂S** - Equivalently: Sensitivity of Vega to changes in Spot Price

**Trading Significance**: Vanna exposure tells you how dealer delta hedges will change as IV moves. Critical for understanding post-event rallies (IV crush) and crash acceleration (IV spike).

---

## Formula (Black-Scholes)

```
Vanna = -e^(-qT) × N'(d1) × d2 / σ
```

Where:
- `d1 = (ln(S/K) + (r - q + σ²/2)T) / (σ√T)`
- `d2 = d1 - σ√T`
- `N'(d1)` = Standard normal PDF at d1
- `σ` = Implied volatility
- `T` = Time to expiration (years)
- `r` = Risk-free rate
- `q` = Dividend yield

**Note**: Same formula for calls and puts. Sign difference comes from d2.

---

## Sign Conventions (Raw Vanna)

| Option Type | Moneyness | d2 Sign | Vanna Sign |
|-------------|-----------|---------|------------|
| Call | OTM | Positive | **Negative** |
| Call | ATM | ~Zero | ~Zero |
| Call | ITM | Negative | **Positive** |
| Put | OTM | Negative | **Positive** |
| Put | ATM | ~Zero | ~Zero |
| Put | ITM | Positive | **Negative** |

**Key Insight**: Vanna is maximized at approximately 25-30 delta options, and approaches zero for deep ITM/OTM.

---

## Dealer Positioning Model (SpotGamma)

Based on industry research, SPX/SPY dealers typically hold:
- **LONG calls** (customers sell covered calls)
- **SHORT puts** (customers buy protection)

This creates **net LONG/POSITIVE Vanna exposure** for dealers.

---

## Vanna Exposure Calculation

```python
# Step 1: Calculate raw vanna for each option
vanna = calculate_vanna(spot, strike, tte, iv, r, q)

# Step 2: Calculate vanna exposure (dollar value)
vanna_exposure = vanna × OI × 100 × spot

# Step 3: Adjust for dealer positioning
if option_type == 'C':
    dealer_vanna = vanna_exposure      # Dealers LONG calls - keep sign
else:  # Put
    dealer_vanna = -vanna_exposure     # Dealers SHORT puts - negate

# Step 4: Sum across all options
net_vanna = sum(dealer_vanna for all options)
```

---

## How IV Changes Affect Dealer Flows

### When IV RISES (VIX up, fear increasing):

| Dealer Position | Effect | Action |
|-----------------|--------|--------|
| Long calls (+vanna) | Delta increases | SELL to hedge |
| Short puts (-vanna for dealer) | Delta exposure increases | SELL to hedge |
| **Net Effect** | | **SELL pressure (bearish)** |

### When IV FALLS (VIX down, post-event crush):

| Dealer Position | Effect | Action |
|-----------------|--------|--------|
| Long calls | Delta decreases | BUY to rebalance |
| Short puts | Delta exposure decreases | BUY back hedges |
| **Net Effect** | | **BUY pressure (bullish)** |

---

## Flow Direction Matrix

| Net Vanna | IV Direction | Dealer Action | Market Impact |
|-----------|--------------|---------------|---------------|
| **Positive** | Rising ↑ | SELL | Bearish |
| **Positive** | Falling ↓ | BUY | Bullish |
| **Negative** | Rising ↑ | BUY | Bullish |
| **Negative** | Falling ↓ | SELL | Bearish |

**Critical Difference from Charm**: Vanna flow depends on BOTH:
1. Sign of net vanna exposure
2. Direction of IV change

Unlike charm where time always moves forward, IV can rise or fall.

---

## The Moneyness Flip (Crash Dynamics)

### Normal Market (OTM Puts):
- Puts remain OTM
- Rising IV → Dealer BUYS underlying (stabilizing)
- "Volatility spikes become opportunities for reflexive rallies"

### Crash Mode (ITM Puts):
- Puts go ITM as market drops
- Rising IV → Dealer SELLS underlying (destabilizing)
- Vanna flips from supportive to destructive
- Creates self-reinforcing crash dynamics

**Key Level**: Track major put strikes. Breach into ITM = regime change.

---

## Python Implementation

```python
import math
from scipy.stats import norm
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class VannaFlowDirection(Enum):
    """Predicted dealer flow based on vanna + IV direction."""
    BUY = "BUY"      # Bullish pressure
    SELL = "SELL"    # Bearish pressure
    NEUTRAL = "NEUTRAL"


@dataclass
class VannaResult:
    """Vanna calculation result for a single option."""
    symbol: str
    strike: float
    option_type: str  # 'C' or 'P'
    vanna: float
    vanna_exposure: float  # Dollar value
    dealer_vanna: float    # Adjusted for positioning


class VannaCalculator:
    """
    Calculates Vanna using Black-Scholes.

    Vanna = -e^(-qT) × N'(d1) × d2 / σ

    Flow interpretation (with dealer positioning):
    - Positive net vanna + IV rising → SELL (bearish)
    - Positive net vanna + IV falling → BUY (bullish)
    - Negative net vanna + IV rising → BUY (bullish)
    - Negative net vanna + IV falling → SELL (bearish)
    """

    # Minimum TTE to avoid math instability
    MIN_TTE = 2 / (252 * 6.5)  # ~2 hours

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.015,
        neutral_threshold: float = 1_000_000,
    ):
        self.r = risk_free_rate
        self.q = dividend_yield
        self.neutral_threshold = neutral_threshold

    def _calculate_d1_d2(
        self,
        spot: float,
        strike: float,
        tte: float,
        iv: float,
    ) -> tuple[float, float]:
        """Calculate Black-Scholes d1 and d2."""
        if tte <= 0 or iv <= 0:
            return 0.0, 0.0

        sqrt_t = math.sqrt(tte)
        d1 = (math.log(spot / strike) + (self.r - self.q + 0.5 * iv**2) * tte) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t

        return d1, d2

    def calculate_vanna(
        self,
        spot: float,
        strike: float,
        tte: float,
        iv: float,
    ) -> float:
        """
        Calculate Vanna for a single option.

        Vanna = -e^(-qT) × N'(d1) × d2 / σ

        Args:
            spot: Current underlying price
            strike: Option strike price
            tte: Time to expiry in years
            iv: Implied volatility (decimal, e.g., 0.20 for 20%)

        Returns:
            Vanna value (same for calls and puts)
        """
        if tte <= self.MIN_TTE or iv <= 0 or spot <= 0:
            return 0.0

        d1, d2 = self._calculate_d1_d2(spot, strike, tte, iv)

        n_prime_d1 = norm.pdf(d1)

        vanna = -math.exp(-self.q * tte) * n_prime_d1 * d2 / iv

        return vanna

    def calculate_vanna_exposure(
        self,
        spot: float,
        strike: float,
        tte: float,
        iv: float,
        oi: int,
        option_type: str,
    ) -> float:
        """
        Calculate Vanna exposure adjusted for dealer positioning.

        Formula: Vanna × OI × 100 × Spot

        Dealer adjustment:
        - Calls: keep sign (dealers LONG)
        - Puts: negate (dealers SHORT)

        Args:
            spot: Current underlying price
            strike: Option strike price
            tte: Time to expiry in years
            iv: Implied volatility
            oi: Open interest
            option_type: 'C' or 'P'

        Returns:
            Dealer-adjusted vanna exposure in dollars
        """
        vanna = self.calculate_vanna(spot, strike, tte, iv)
        vanna_exposure = vanna * oi * 100 * spot

        # Adjust for dealer positioning
        if option_type == 'P':
            vanna_exposure = -vanna_exposure

        return vanna_exposure

    def get_flow_direction(
        self,
        net_vanna: float,
        iv_rising: bool,
    ) -> VannaFlowDirection:
        """
        Determine dealer flow direction based on vanna and IV direction.

        Args:
            net_vanna: Net vanna exposure (after dealer adjustment)
            iv_rising: True if IV is rising, False if falling

        Returns:
            VannaFlowDirection indicating dealer action
        """
        if abs(net_vanna) < self.neutral_threshold:
            return VannaFlowDirection.NEUTRAL

        # Positive vanna + IV rising = SELL
        # Positive vanna + IV falling = BUY
        # Negative vanna + IV rising = BUY
        # Negative vanna + IV falling = SELL

        if net_vanna > 0:
            return VannaFlowDirection.SELL if iv_rising else VannaFlowDirection.BUY
        else:
            return VannaFlowDirection.BUY if iv_rising else VannaFlowDirection.SELL
```

---

## ES Futures Conversion

```python
ES_MULTIPLIER = 50  # $50 per point

def calculate_es_futures_from_vanna(
    net_vanna: float,
    spot_price: float,
    iv_rising: bool,
) -> float:
    """
    Convert vanna exposure to ES futures equivalent.

    Positive = dealers will BUY
    Negative = dealers will SELL

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
    if net_vanna > 0:
        # Positive vanna: IV rising = sell, IV falling = buy
        return es_contracts if not iv_rising else -es_contracts
    else:
        # Negative vanna: IV rising = buy, IV falling = sell
        return es_contracts if iv_rising else -es_contracts
```

---

## Dashboard Display

### Metrics to Show:
1. **Net Vanna Exposure** - Dollar value
2. **ES Futures Equivalent** - Contracts
3. **IV Direction** - Rising/Falling (from VIX or ATM IV change)
4. **Flow Direction** - BUY/SELL based on vanna + IV direction

### Caption:
```
"Vanna flow depends on IV direction. Rising IV + positive vanna = SELL. Falling IV + positive vanna = BUY."
```

### Help Text:
```markdown
**Vanna = How delta changes when IV changes**

- **Positive vanna + IV rising** → Dealers SELL → Bearish
- **Positive vanna + IV falling** → Dealers BUY → Bullish
- **Negative vanna + IV rising** → Dealers BUY → Bullish
- **Negative vanna + IV falling** → Dealers SELL → Bearish

*Post-event IV crush (FOMC, earnings) typically triggers bullish vanna flows.*
```

---

## VIX Tracking

### API Access (Verified Working)

```python
# Symbol: "VIX" (Trade event, not Quote)
# Returns: price (e.g., 24.93)

ws.send(json.dumps({
    "type": "FEED_SUBSCRIPTION",
    "channel": 1,
    "add": [{"symbol": "VIX", "type": "Trade"}]
}))
```

### VIX History Storage

```
vix_history/
└── {YYMMDD}.json   # e.g., 260309.json
```

```python
# Record structure
{
    "timestamp": "2026-03-09T14:30:00",
    "vix": 24.93,
    "direction": "RISING",  # or "FALLING", "FLAT"
    "change_pct": 1.2
}
```

### IV Direction Logic

```python
def determine_iv_direction(current_vix: float, previous_vix: float) -> str:
    """Returns 'RISING', 'FALLING', or 'FLAT'."""
    if previous_vix <= 0:
        return "FLAT"

    change_pct = ((current_vix - previous_vix) / previous_vix) * 100

    if change_pct > 0.5:    # 0.5% threshold
        return "RISING"
    elif change_pct < -0.5:
        return "FALLING"
    return "FLAT"
```

### Dashboard Display

**Add to existing Charm section:**

1. **VIX Chart** - above or beside Charm
2. **Vanna Chart** - beside Charm (same format)
3. **Charm Chart** - already exists

```
┌─────────────────────────────────────────────────────┐
│  VIX: 24.93  ↑ +1.2%  (RISING)                     │
│  [VIX line chart over time]                        │
├─────────────────────────────────────────────────────┤
│  Vanna: +500 ES (SELL)  │  Charm: +300 ES (BUY)   │
│  [Vanna ES chart]       │  [Charm ES chart]        │
└─────────────────────────────────────────────────────┘
```

**Chart specs:**
- VIX: Red when rising, Green when falling
- Vanna/Charm: Same format as existing Charm chart

### File Structure

```
utils/
└── vix_tracker.py      # VIX fetching and history

components/
└── vix_display.py      # VIX chart component

vix_history/
└── {YYMMDD}.json       # Daily VIX records
```

---

## File Structure

```
utils/
├── vanna_calculator.py     # Core vanna calculations
├── vanna_history.py        # JSON storage for vanna over time
├── charm_calculator.py     # Existing
├── charm_history.py        # Existing
└── greeks_common.py        # Shared d1/d2 calculations (refactor)

components/
├── vanna_display.py        # Dashboard component
├── charm_display.py        # Existing
└── greeks_combined.py      # Optional: combined vanna+charm view
```

---

## Testing

```python
def test_vanna_sign_otm_call():
    """OTM call should have negative vanna (d2 > 0)."""
    calc = VannaCalculator()
    vanna = calc.calculate_vanna(spot=6000, strike=6100, tte=7/365, iv=0.20)
    assert vanna < 0

def test_vanna_sign_otm_put():
    """OTM put should have positive vanna (d2 < 0)."""
    calc = VannaCalculator()
    vanna = calc.calculate_vanna(spot=6000, strike=5900, tte=7/365, iv=0.20)
    assert vanna > 0

def test_vanna_atm_near_zero():
    """ATM option should have vanna near zero."""
    calc = VannaCalculator()
    vanna = calc.calculate_vanna(spot=6000, strike=6000, tte=7/365, iv=0.20)
    assert abs(vanna) < 0.01

def test_dealer_adjustment_puts_negated():
    """Put vanna exposure should be negated for dealer positioning."""
    calc = VannaCalculator()
    call_exp = calc.calculate_vanna_exposure(6000, 6000, 7/365, 0.20, 1000, 'C')
    put_exp = calc.calculate_vanna_exposure(6000, 6000, 7/365, 0.20, 1000, 'P')
    assert call_exp == -put_exp  # Same magnitude, opposite sign

def test_flow_direction_positive_vanna_iv_rising():
    """Positive vanna + IV rising = SELL."""
    calc = VannaCalculator()
    flow = calc.get_flow_direction(net_vanna=5_000_000, iv_rising=True)
    assert flow == VannaFlowDirection.SELL

def test_flow_direction_positive_vanna_iv_falling():
    """Positive vanna + IV falling = BUY."""
    calc = VannaCalculator()
    flow = calc.get_flow_direction(net_vanna=5_000_000, iv_rising=False)
    assert flow == VannaFlowDirection.BUY
```

---

## Sources

- [SpotGamma - Options Vanna](https://spotgamma.com/options-vanna/)
- [SpotGamma - Vanna & Charm](https://spotgamma.com/options-vanna-charm/)
- [TradingVolatility - Understanding Charm and Vanna](https://tradingvolatility.substack.com/p/understanding-charm-and-vanna-hidden)
- [MenthorQ - When Vanna Turns Against You](https://menthorq.com/guide/when-vanna-turns-against-you/)
- [Gextron - VEX Vanna Exposure](https://www.gextron.com/learn/vanna-exposure)
- [AIFlowTrader - Vanna Exposure Guide](https://www.aiflowtrader.com/blog/vanna-exposure-explained)

---

## Implementation Checklist

- [ ] Create `utils/vanna_calculator.py`
- [ ] Create `utils/vanna_history.py`
- [ ] Create `components/vanna_display.py`
- [ ] Add VIX/IV tracking to determine IV direction
- [ ] Add vanna section to dashboard
- [ ] Write unit tests
- [ ] Update CLAUDE.md with vanna documentation
