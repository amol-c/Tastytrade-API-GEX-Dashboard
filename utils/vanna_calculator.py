"""
Vanna Calculator
Calculates Vanna from API-provided Greeks (Delta, Vega).

Vanna ≈ Vega × d1 / (S × σ × √T)
Where d1 ≈ norm.ppf(abs(delta))

Flow interpretation (with dealer positioning):
- Positive net vanna + IV rising → SELL (bearish)
- Positive net vanna + IV falling → BUY (bullish)
- Negative net vanna + IV rising → BUY (bullish)
- Negative net vanna + IV falling → SELL (bearish)
"""
import math
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional
from scipy.stats import norm

logger = logging.getLogger(__name__)


class VannaFlowDirection(Enum):
    """Predicted dealer flow based on vanna + IV direction."""
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


@dataclass
class VannaProjection:
    """Vanna calculation result."""
    net_vanna: float
    flow_direction: VannaFlowDirection
    iv_direction: str  # "RISING", "FALLING", "FLAT"

    @property
    def flow_label(self) -> str:
        """Human-readable flow direction with emoji."""
        labels = {
            VannaFlowDirection.BUY: "🟢 BUY",
            VannaFlowDirection.SELL: "🔴 SELL",
            VannaFlowDirection.NEUTRAL: "🟡 NEUTRAL",
        }
        return labels[self.flow_direction]


class VannaCalculator:
    """
    Calculates Vanna from API Greeks.

    Uses: Vanna ≈ Vega × d1 / (S × σ × √T)

    Dealer positioning (SpotGamma model):
    - Dealers LONG calls → keep vanna sign
    - Dealers SHORT puts → negate vanna sign
    """

    MIN_TTE = 2 / (252 * 6.5)  # ~2 hours minimum

    def __init__(self, neutral_threshold: float = 1_000_000):
        self.neutral_threshold = neutral_threshold

    def calculate_vanna_from_greeks(
        self,
        spot: float,
        delta: float,
        vega: float,
        iv: float,
        tte: float,
    ) -> float:
        """
        Calculate Vanna from API-provided Greeks.

        Vanna ≈ Vega × d1 / (S × σ × √T)

        Args:
            spot: Current underlying price
            delta: Option delta from API
            vega: Option vega from API
            iv: Implied volatility (decimal)
            tte: Time to expiry in years

        Returns:
            Vanna value
        """
        if spot <= 0 or iv <= 0 or tte <= self.MIN_TTE:
            return 0.0

        if abs(delta) >= 0.99 or abs(delta) <= 0.01:
            return 0.0  # Deep ITM/OTM - vanna near zero

        if vega is None or vega == 0:
            return 0.0

        try:
            # Reconstruct d1 from delta
            # For calls: delta ≈ N(d1), so d1 ≈ N^(-1)(delta)
            d1 = norm.ppf(abs(delta))

            sqrt_t = math.sqrt(tte)
            vanna = vega * d1 / (spot * iv * sqrt_t)

            return vanna

        except Exception as e:
            logger.debug(f"Vanna calc error: {e}")
            return 0.0

    def calculate_vanna_exposure(
        self,
        spot: float,
        delta: float,
        vega: float,
        iv: float,
        tte: float,
        oi: int,
        option_type: str,
    ) -> float:
        """
        Calculate Vanna exposure adjusted for dealer positioning.

        Args:
            spot: Current underlying price
            delta: Option delta from API
            vega: Option vega from API
            iv: Implied volatility
            tte: Time to expiry in years
            oi: Open interest
            option_type: 'C' or 'P'

        Returns:
            Dealer-adjusted vanna exposure in dollars
        """
        vanna = self.calculate_vanna_from_greeks(spot, delta, vega, iv, tte)
        vanna_exposure = vanna * oi * 100 * spot

        # Dealer positioning: long calls, short puts
        if option_type == 'P':
            vanna_exposure = -vanna_exposure

        return vanna_exposure

    def calculate_tte_from_expiry(self, expiry_str: str) -> float:
        """Calculate time to expiry in years from YYMMDD string."""
        from datetime import datetime

        expiry_date = datetime.strptime(expiry_str, "%y%m%d")
        expiry_datetime = expiry_date.replace(hour=16, minute=0)

        now = datetime.now()
        time_remaining = expiry_datetime - now

        minutes_remaining = time_remaining.total_seconds() / 60
        trading_minutes_per_year = 252 * 6.5 * 60

        return max(0, minutes_remaining / trading_minutes_per_year)

    def calculate_current_vanna(
        self,
        options_data: Dict[str, dict],
        spot: float,
        expiry_str: str,
        iv_direction: str = "FLAT",
        min_valid_options: int = 50,
    ) -> Optional[VannaProjection]:
        """
        Calculate current vanna exposure from options chain.

        Args:
            options_data: Dict of symbol -> {delta, vega, iv, oi, strike, type}
            spot: Current underlying price
            expiry_str: Expiration in YYMMDD format
            iv_direction: "RISING", "FALLING", or "FLAT"
            min_valid_options: Minimum valid options required

        Returns:
            VannaProjection or None if insufficient data
        """
        # Check data quality - need delta, vega, iv, oi
        valid_count = sum(1 for data in options_data.values()
                         if data.get('delta') is not None
                         and data.get('vega') is not None
                         and data.get('iv') and data.get('oi')
                         and data.get('iv') > 0 and data.get('oi') > 0)

        if valid_count < min_valid_options:
            logger.warning(f"Vanna skipped: only {valid_count}/{len(options_data)} options have valid Greeks (min={min_valid_options})")
            # Log a sample of why they are invalid for debugging
            invalid_samples = []
            for s, d in list(options_data.items())[:10]:
                reasons = []
                if d.get('delta') is None: reasons.append("delta=None")
                if d.get('vega') is None: reasons.append("vega=None")
                if not d.get('iv') or d.get('iv') <= 0: reasons.append(f"iv={d.get('iv')}")
                if not d.get('oi') or d.get('oi') <= 0: reasons.append(f"oi={d.get('oi')}")
                if reasons:
                    invalid_samples.append(f"{s}: {', '.join(reasons)}")
            if invalid_samples:
                logger.debug(f"Sample invalid options: {'; '.join(invalid_samples)}")
            return None

        tte = self.calculate_tte_from_expiry(expiry_str)
        if tte <= 0:
            return None

        net_vanna = 0.0

        for symbol, data in options_data.items():
            delta = data.get('delta')
            vega = data.get('vega')
            iv = data.get('iv')
            oi = data.get('oi')

            if delta is None or vega is None or iv is None or oi is None:
                continue
            if iv <= 0 or oi <= 0:
                continue

            strike = data.get('strike')
            opt_type = data.get('type')

            if strike is None or opt_type is None:
                from utils.gex_calculator import parse_option_symbol
                parsed = parse_option_symbol(symbol)
                if parsed:
                    strike = parsed['strike']
                    opt_type = parsed['type']
                else:
                    continue

            vanna_exp = self.calculate_vanna_exposure(
                spot=spot,
                delta=delta,
                vega=vega,
                iv=iv,
                tte=tte,
                oi=int(oi),
                option_type=opt_type,
            )

            net_vanna += vanna_exp

        logger.info(f"Vanna calc: {valid_count} options, net_vanna=${net_vanna:,.0f}, iv={iv_direction}")

        flow = self.get_flow_direction(net_vanna, iv_direction)

        return VannaProjection(
            net_vanna=net_vanna,
            flow_direction=flow,
            iv_direction=iv_direction,
        )

    def get_flow_direction(
        self,
        net_vanna: float,
        iv_direction: str,
    ) -> VannaFlowDirection:
        """
        Determine dealer flow based on vanna + IV direction.

        - Positive vanna + IV rising = SELL
        - Positive vanna + IV falling = BUY
        - Negative vanna + IV rising = BUY
        - Negative vanna + IV falling = SELL
        """
        if abs(net_vanna) < self.neutral_threshold:
            return VannaFlowDirection.NEUTRAL

        if iv_direction == "FLAT":
            return VannaFlowDirection.NEUTRAL

        iv_rising = (iv_direction == "RISING")

        if net_vanna > 0:
            return VannaFlowDirection.SELL if iv_rising else VannaFlowDirection.BUY
        else:
            return VannaFlowDirection.BUY if iv_rising else VannaFlowDirection.SELL

    def calculate_vex_by_strike(
        self,
        options_data: Dict[str, dict],
        spot: float,
        expiry_str: str,
    ) -> Dict[float, Dict[str, float]]:
        """
        Calculate VEx (Vanna Exposure) per strike.

        Returns:
            Dict of strike -> {call_vex, put_vex, net_vex}
        """
        tte = self.calculate_tte_from_expiry(expiry_str)
        if tte <= 0:
            return {}

        strike_vex = {}

        for symbol, data in options_data.items():
            delta = data.get('delta')
            vega = data.get('vega')
            iv = data.get('iv')
            oi = data.get('oi')

            strike = data.get('strike')
            opt_type = data.get('type')

            if strike is None or opt_type is None:
                from utils.gex_calculator import parse_option_symbol
                parsed = parse_option_symbol(symbol)
                if parsed:
                    strike = parsed['strike']
                    opt_type = parsed['type']
                else:
                    logger.debug(f"VEx skip {symbol}: could not parse strike/type")
                    continue

            if delta is None or vega is None or iv is None or oi is None:
                logger.debug(f"VEx skip {symbol}: missing required field (delta={delta}, vega={vega}, iv={iv}, oi={oi})")
                continue
            if iv <= 0 or oi <= 0:
                logger.debug(f"VEx skip {symbol}: non-positive iv({iv}) or oi({oi})")
                continue
            if vega == 0:
                logger.debug(f"VEx skip {symbol}: vega is 0")
                continue

            vanna_exp = self.calculate_vanna_exposure(
                spot=spot,
                delta=delta,
                vega=vega,
                iv=iv,
                tte=tte,
                oi=int(oi),
                option_type=opt_type,
            )

            if strike not in strike_vex:
                strike_vex[strike] = {'call_vex': 0.0, 'put_vex': 0.0, 'net_vex': 0.0}

            if opt_type == 'C':
                strike_vex[strike]['call_vex'] += vanna_exp
            else:
                strike_vex[strike]['put_vex'] += vanna_exp

            strike_vex[strike]['net_vex'] += vanna_exp

        return strike_vex

    def get_vex_metrics(
        self,
        strike_vex: Dict[float, Dict[str, float]],
    ) -> Dict[str, float]:
        """
        Calculate VEx metrics from per-strike data.

        Returns:
            Dict with total_call_vex, total_put_vex, net_vex, max_vex_strike
        """
        if not strike_vex:
            return {}

        total_call_vex = sum(v['call_vex'] for v in strike_vex.values())
        total_put_vex = sum(v['put_vex'] for v in strike_vex.values())
        net_vex = total_call_vex + total_put_vex

        # Max VEx strike (highest absolute net VEx)
        max_vex_strike = max(strike_vex.keys(), key=lambda s: abs(strike_vex[s]['net_vex']))

        return {
            'total_call_vex': total_call_vex,
            'total_put_vex': total_put_vex,
            'net_vex': net_vex,
            'max_vex_strike': max_vex_strike,
        }
