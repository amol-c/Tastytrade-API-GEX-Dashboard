"""
Charm Calculator
Calculates charm (delta decay) using Black-Scholes model and projects forward in time.

Charm = rate of change of delta with respect to time
Used to predict hedging flows as time passes.

IMPORTANT: Near-Expiry Limitation
--------------------------------
Charm calculations become unreliable as time-to-expiry (TTE) approaches zero.
As TTE → 0, the charm formula produces extreme values because:
  - The √T term in the denominator approaches 0
  - Gamma becomes extremely large (options are binary)
  - Small changes in delta get amplified to unrealistic hedging flows

We apply a MIN_TTE cutoff of ~2 hours. When TTE < MIN_TTE:
  - Charm returns 0 (no signal)
  - This prevents false/extreme readings on 0DTE near close
  - Use gamma-based analysis instead for near-expiry hedging
"""
import math
import logging

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional, Tuple
import numpy as np
from scipy.stats import norm


class FlowDirection(Enum):
    """Predicted hedging flow direction."""
    BUY = "buy"      # Dealers will buy (UP pressure)
    SELL = "sell"    # Dealers will sell (DOWN pressure)
    NEUTRAL = "neutral"


@dataclass
class CharmResult:
    """Result for a single option's charm calculation."""
    symbol: str
    strike: float
    option_type: str  # 'C' or 'P'
    charm: float      # Raw charm value
    charm_exposure: float  # Charm × OI × 100 × Spot
    delta: float
    time_to_expiry: float  # In years


@dataclass
class CharmProjection:
    """Charm projection at a specific future time."""
    minutes_forward: int
    time_label: str  # e.g., "NOW", "+30m", "+1hr"
    charm_by_strike: Dict[float, float]  # strike -> charm exposure
    net_charm: float
    flow_direction: FlowDirection

    @property
    def flow_label(self) -> str:
        """Human-readable flow direction with emoji."""
        labels = {
            FlowDirection.BUY: "🟢 UP Pressure (Dealers BUY)",
            FlowDirection.SELL: "🔴 DOWN Pressure (Dealers SELL)",
            FlowDirection.NEUTRAL: "🟡 Neutral",
        }
        return labels[self.flow_direction]


class CharmCalculator:
    """
    Calculates charm using Black-Scholes and projects forward in time.

    Charm formula:
    Charm = -e^(-q*t) * N'(d1) * (2(r-q)t - d2*σ*√t) / (2t*σ*√t)

    For predicting hedging flows (per SpotGamma/industry convention):
    - Negative charm exposure → Dealers will BUY → UP pressure (bullish)
    - Positive charm exposure → Dealers will SELL → DOWN pressure (bearish)

    Dealer positioning adjustment:
    - Dealers are LONG calls → keep charm sign
    - Dealers are SHORT puts → negate charm sign

    Near-Expiry Cutoff:
    - MIN_TTE = ~2 hours (same as vanna)
    - Returns 0 when TTE < MIN_TTE to avoid extreme/unreliable values
    """

    # Minimum time-to-expiry: ~2 hours in trading year terms
    # Formula: 2 hours / (252 trading days × 6.5 hours per day)
    # Below this threshold, charm values may be unreliable
    MIN_TTE = 2 / (252 * 6.5)

    def is_near_expiry(self, expiry_str: str) -> bool:
        """Check if we're within 2 hours of expiry (charm unreliable)."""
        tte = self.calculate_tte_from_expiry(expiry_str, 0)
        return tte <= self.MIN_TTE and tte > 0

    def __init__(
        self,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.015,
        neutral_threshold: float = 1_000_000,
    ):
        """
        Initialize charm calculator.

        Args:
            risk_free_rate: Annual risk-free rate (default 5%)
            dividend_yield: Annual dividend yield (default 1.5% for SPX)
            neutral_threshold: Threshold for neutral flow classification
        """
        self.r = risk_free_rate
        self.q = dividend_yield
        self.neutral_threshold = neutral_threshold

    def _calculate_d1_d2(
        self,
        spot: float,
        strike: float,
        tte: float,
        iv: float,
    ) -> Tuple[float, float]:
        """Calculate d1 and d2 for Black-Scholes."""
        if tte <= 0 or iv <= 0:
            return 0.0, 0.0

        sqrt_t = math.sqrt(tte)
        d1 = (math.log(spot / strike) + (self.r - self.q + 0.5 * iv ** 2) * tte) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t

        return d1, d2

    def calculate_charm(
        self,
        spot: float,
        strike: float,
        tte: float,
        iv: float,
        option_type: str = 'C',
    ) -> float:
        """
        Calculate charm for a single option.

        Args:
            spot: Current underlying price
            strike: Option strike price
            tte: Time to expiry in years
            iv: Implied volatility (decimal)
            option_type: 'C' for call, 'P' for put

        Returns:
            Charm value (delta change per day)
            Note: Values become unreliable when TTE < MIN_TTE (~2 hours)
        """
        if tte <= 0 or iv <= 0:
            return 0.0

        d1, d2 = self._calculate_d1_d2(spot, strike, tte, iv)
        sqrt_t = math.sqrt(tte)

        # N'(d1) - standard normal PDF
        n_prime_d1 = norm.pdf(d1)

        # Charm formula
        exp_qt = math.exp(-self.q * tte)

        term1 = n_prime_d1 * (2 * (self.r - self.q) * tte - d2 * iv * sqrt_t) / (2 * tte * iv * sqrt_t)

        if option_type == 'C':
            charm = -exp_qt * (term1 + self.q * norm.cdf(d1))
        else:  # Put
            charm = -exp_qt * (term1 - self.q * norm.cdf(-d1))

        # Convert from per-year to per-day
        charm_per_day = charm / 365.0

        return charm_per_day

    def calculate_charm_exposure(
        self,
        spot: float,
        strike: float,
        tte: float,
        iv: float,
        oi: int,
        option_type: str = 'C',
    ) -> float:
        """
        Calculate charm exposure (dollar value of hedging flow).

        Formula: Charm × OI × 100 × Spot

        Args:
            spot: Current underlying price
            strike: Option strike price
            tte: Time to expiry in years
            iv: Implied volatility (decimal)
            oi: Open interest
            option_type: 'C' for call, 'P' for put

        Returns:
            Charm exposure in dollars
        """
        charm = self.calculate_charm(spot, strike, tte, iv, option_type)
        return charm * oi * 100 * spot

    def calculate_tte_from_expiry(
        self,
        expiry_str: str,
        minutes_forward: int = 0,
        market_close_hour: int = 16,
    ) -> float:
        """
        Calculate time to expiry in years.

        Args:
            expiry_str: Expiration date in YYMMDD format
            minutes_forward: Minutes into the future to project from now
            market_close_hour: Market close hour (default 4 PM)

        Returns:
            Time to expiry in years
        """
        from datetime import datetime, timedelta

        # Parse expiry
        expiry_date = datetime.strptime(expiry_str, "%y%m%d")
        expiry_datetime = expiry_date.replace(hour=market_close_hour, minute=0)

        # Current time + forward projection
        now = datetime.now() + timedelta(minutes=minutes_forward)

        # Time remaining
        time_remaining = expiry_datetime - now

        # Convert to years (trading days basis)
        minutes_remaining = time_remaining.total_seconds() / 60
        trading_minutes_per_year = 252 * 6.5 * 60

        tte = max(0, minutes_remaining / trading_minutes_per_year)

        return tte

    def calculate_current_charm(
        self,
        options_data: Dict[str, dict],
        spot: float,
        expiry_str: str,
        min_valid_options: int = 50,
    ) -> Optional[CharmProjection]:
        """
        Calculate current charm exposure (NOW only).

        Args:
            options_data: Dict of symbol -> {gamma, delta, iv, oi, strike, type}
            spot: Current underlying price
            expiry_str: Expiration in YYMMDD format
            min_valid_options: Minimum options with valid IV+OI required

        Returns:
            CharmProjection for NOW, or None if data insufficient
        """
        # Check data quality first
        valid_count = sum(1 for data in options_data.values()
                         if data.get('iv') and data.get('oi')
                         and data.get('iv') > 0 and data.get('oi') > 0)

        if valid_count < min_valid_options:
            logger.warning(f"Charm skipped: only {valid_count}/{len(options_data)} options have valid IV+OI (min={min_valid_options})")
            return None

        tte = self.calculate_tte_from_expiry(expiry_str, 0)
        if tte <= 0:
            return None

        # Log warning if near expiry (data may be unreliable)
        if tte <= self.MIN_TTE:
            logger.warning(f"Charm WARNING: TTE ({tte:.6f}) < MIN_TTE ({self.MIN_TTE:.6f}) - values may be unreliable near expiry")

        charm_by_strike = {}

        for symbol, data in options_data.items():
            iv = data.get('iv')
            oi = data.get('oi')

            if iv is None or oi is None or iv <= 0 or oi <= 0:
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

            charm_exp = self.calculate_charm_exposure(
                spot=spot,
                strike=strike,
                tte=tte,
                iv=iv,
                oi=int(oi),
                option_type=opt_type,
            )

            # Adjust for dealer positioning (SpotGamma model):
            # - Dealers are LONG calls → keep sign
            # - Dealers are SHORT puts → negate sign
            if opt_type == 'P':
                charm_exp = -charm_exp

            if strike not in charm_by_strike:
                charm_by_strike[strike] = 0.0
            charm_by_strike[strike] += charm_exp

        net_charm = sum(charm_by_strike.values())

        logger.info(f"Charm calc: {valid_count}/{len(options_data)} options, "
                   f"net_charm=${net_charm:,.0f}, strikes={len(charm_by_strike)}")

        # Negative charm = bullish (dealers buy), Positive charm = bearish (dealers sell)
        if net_charm < -self.neutral_threshold:
            flow = FlowDirection.BUY
        elif net_charm > self.neutral_threshold:
            flow = FlowDirection.SELL
        else:
            flow = FlowDirection.NEUTRAL

        return CharmProjection(
            minutes_forward=0,
            time_label="NOW",
            charm_by_strike=charm_by_strike,
            net_charm=net_charm,
            flow_direction=flow,
        )

    def project_charm_forward(
        self,
        options_data: Dict[str, dict],
        spot: float,
        expiry_str: str,
        time_points: List[int] = None,
        min_valid_options: int = 50,
    ) -> List[CharmProjection]:
        """
        Project charm exposure at multiple future time points.
        DEPRECATED: Use calculate_current_charm() for NOW only.
        """
        # Just return current charm as single-item list for backwards compatibility
        result = self.calculate_current_charm(options_data, spot, expiry_str, min_valid_options)
        return [result] if result else []

    def _project_charm_forward_legacy(
        self,
        options_data: Dict[str, dict],
        spot: float,
        expiry_str: str,
        time_points: List[int] = None,
        min_valid_options: int = 50,
    ) -> List[CharmProjection]:
        """Legacy projection method - kept for reference."""
        if time_points is None:
            time_points = [0]

        # Check data quality first
        valid_count = sum(1 for data in options_data.values()
                         if data.get('iv') and data.get('oi')
                         and data.get('iv') > 0 and data.get('oi') > 0)

        if valid_count < min_valid_options:
            logger.warning(f"Charm skipped: only {valid_count}/{len(options_data)} options have valid IV+OI (min={min_valid_options})")
            return []

        projections = []

        for minutes in time_points:
            tte = self.calculate_tte_from_expiry(expiry_str, minutes)

            if tte <= 0:
                continue

            charm_by_strike = {}

            for symbol, data in options_data.items():
                iv = data.get('iv')
                oi = data.get('oi')

                if iv is None or oi is None or iv <= 0 or oi <= 0:
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

                charm_exp = self.calculate_charm_exposure(
                    spot=spot,
                    strike=strike,
                    tte=tte,
                    iv=iv,
                    oi=int(oi),
                    option_type=opt_type,
                )

                if strike not in charm_by_strike:
                    charm_by_strike[strike] = 0.0
                charm_by_strike[strike] += charm_exp

            net_charm = sum(charm_by_strike.values())

            # Log stats for debugging
            if minutes == 0:
                valid_options = len([s for s, data in options_data.items()
                                    if data.get('iv') and data.get('oi') and data.get('iv') > 0 and data.get('oi') > 0])
                logger.info(f"Charm calc: {valid_options}/{len(options_data)} options with valid IV+OI, "
                           f"net_charm=${net_charm:,.0f}, strikes={len(charm_by_strike)}")

            if net_charm > self.neutral_threshold:
                flow = FlowDirection.BUY
            elif net_charm < -self.neutral_threshold:
                flow = FlowDirection.SELL
            else:
                flow = FlowDirection.NEUTRAL

            if minutes == 0:
                label = "NOW"
            elif minutes < 60:
                label = f"+{minutes}m"
            else:
                hours = minutes // 60
                mins = minutes % 60
                if mins == 0:
                    label = f"+{hours}hr"
                else:
                    label = f"+{hours}h{mins}m"

            projections.append(CharmProjection(
                minutes_forward=minutes,
                time_label=label,
                charm_by_strike=charm_by_strike,
                net_charm=net_charm,
                flow_direction=flow,
            ))

        return projections

    def create_heatmap_data(
        self,
        projections: List[CharmProjection],
        strikes: List[float] = None,
    ) -> Tuple[List[str], List[float], np.ndarray]:
        """
        Create data for heatmap visualization.

        Args:
            projections: List of CharmProjection objects
            strikes: List of strikes to include

        Returns:
            Tuple of (time_labels, strikes, charm_matrix)
        """
        if not projections:
            return [], [], np.array([])

        if strikes is None:
            all_strikes = set()
            for proj in projections:
                all_strikes.update(proj.charm_by_strike.keys())
            strikes = sorted(all_strikes)

        time_labels = [p.time_label for p in projections]
        charm_matrix = np.zeros((len(strikes), len(projections)))

        for j, proj in enumerate(projections):
            for i, strike in enumerate(strikes):
                charm_matrix[i, j] = proj.charm_by_strike.get(strike, 0.0)

        return time_labels, strikes, charm_matrix

    def get_flow_summary(
        self,
        projections: List[CharmProjection],
    ) -> Dict:
        """
        Get summary of predicted flows.

        Returns:
            Dict with flow predictions
        """
        if not projections:
            return {}

        now = projections[0] if projections else None

        return {
            'current_net_charm': now.net_charm if now else 0,
            'current_flow': now.flow_direction.value if now else 'neutral',
            'current_flow_label': now.flow_label if now else '',
            'projections': [
                {
                    'time': p.time_label,
                    'net_charm': p.net_charm,
                    'flow': p.flow_direction.value,
                    'flow_label': p.flow_label,
                }
                for p in projections
            ]
        }
