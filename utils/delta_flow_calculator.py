"""
Delta Flow Calculator

Calculates cumulative delta from customer trades to determine dealer hedging.

Single Responsibility: Calculate delta flow from trades.

Sign Convention (aligned with Charm/Vanna):
- Positive ES = dealers BUY underlying
- Negative ES = dealers SELL underlying

Customer Action → Dealer Hedge:
- Customer buys call (+delta) → dealer SELLS to hedge → negative ES
- Customer buys put (-delta) → dealer BUYS to hedge → positive ES
- Customer sells call (-delta) → dealer BUYS to hedge → positive ES
- Customer sells put (+delta) → dealer SELLS to hedge → negative ES
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple

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

    Sign convention:
    - Positive ES = dealers BUY underlying
    - Negative ES = dealers SELL underlying
    """

    def __init__(self, neutral_threshold: float = 500_000):
        """
        Initialize calculator.

        Args:
            neutral_threshold: Delta threshold for NEUTRAL classification
        """
        self.neutral_threshold = neutral_threshold
        self.cumulative_customer_delta = 0.0
        self.trade_count = 0

    def process_trade(
        self,
        symbol: str,
        aggressor_side: str,
        contracts: int,
        delta: float,
    ) -> float:
        """
        Process a single trade and update cumulative delta.

        Args:
            symbol: Option symbol
            aggressor_side: Who initiated ("BUY" or "SELL")
            contracts: Number of contracts
            delta: Option delta (positive for calls, negative for puts)

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

        Formula: ES = delta / ES_MULTIPLIER
        - Delta = shares equivalent (from contracts × option_delta × 100)
        - 1 ES contract = $50 per SPX point = 50 delta

        Sign convention:
        - Customer long delta → dealer short → dealer SELLS → negative ES
        - Customer short delta → dealer long → dealer BUYS → positive ES

        Args:
            spot_price: Current underlying price (used for validation only)

        Returns:
            ES contracts (positive = BUY, negative = SELL)
        """
        if spot_price <= 0:
            return 0.0

        # ES = -customer_delta / 50
        # Customer long +delta → dealer SELLS → negative ES
        return -self.cumulative_customer_delta / ES_MULTIPLIER

    def get_flow_direction(self) -> DeltaFlowDirection:
        """
        Get dealer hedge direction.

        Returns:
            DeltaFlowDirection based on cumulative customer delta
        """
        if abs(self.cumulative_customer_delta) < self.neutral_threshold:
            return DeltaFlowDirection.NEUTRAL

        if self.cumulative_customer_delta > 0:
            # Customer net long → dealer short → dealer SELLS
            return DeltaFlowDirection.SELL
        else:
            # Customer net short → dealer long → dealer BUYS
            return DeltaFlowDirection.BUY

    def reset(self):
        """Reset for new trading session."""
        self.cumulative_customer_delta = 0.0
        self.trade_count = 0


def calculate_delta_weighted_flow(
    tick_data: Dict[str, Dict],
    greeks_data: Dict[str, Dict],
) -> Tuple[float, float]:
    """
    Calculate delta-weighted buy/sell volume from tick data.

    Args:
        tick_data: Dict mapping symbol -> {buy_volume, sell_volume}
        greeks_data: Dict mapping symbol -> {delta}

    Returns:
        Tuple of (delta_bought, delta_sold)
    """
    delta_bought = 0.0
    delta_sold = 0.0

    for symbol, data in tick_data.items():
        delta = greeks_data.get(symbol, {}).get('delta', 0)
        if delta == 0:
            continue

        buy_volume = data.get('buy_volume', 0)
        sell_volume = data.get('sell_volume', 0)

        # Delta per contract × 100 multiplier
        delta_per_contract = delta * 100

        delta_bought += buy_volume * delta_per_contract
        delta_sold -= sell_volume * delta_per_contract  # Negative for sold

    return delta_bought, delta_sold
