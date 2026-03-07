"""
Sentiment Calculator
Calculates dealer and customer sentiment ratios from GEX and volume data.

Follows SOLID principles:
- Single Responsibility: Only handles sentiment ratio calculations
- Open/Closed: Extensible via new ratio methods without modifying existing ones
- Dependency Inversion: Depends on data abstractions (dicts/DataFrames), not concrete implementations
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import pandas as pd


class SentimentLevel(Enum):
    """Sentiment classification levels."""
    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


class DealerStance(Enum):
    """Dealer gamma positioning classification."""
    STABILIZING = "stabilizing"
    NEUTRAL = "neutral"
    DESTABILIZING = "destabilizing"


@dataclass
class DealerGammaResult:
    """Result of dealer gamma ratio calculation."""
    ratio: float  # 0.0 to 1.0
    stance: DealerStance
    positive_gamma: float  # Call GEX
    negative_gamma: float  # Put GEX
    net_gamma: float

    @property
    def label(self) -> str:
        """Human-readable label with emoji."""
        labels = {
            DealerStance.STABILIZING: "🟢 Stabilizing",
            DealerStance.NEUTRAL: "🟡 Neutral",
            DealerStance.DESTABILIZING: "🔴 Destabilizing",
        }
        return labels[self.stance]


@dataclass
class ActiveSentimentResult:
    """Result of active sentiment (customer) calculation."""
    ratio: float  # 0.0 to 1.0
    level: SentimentLevel
    call_volume: int
    put_volume: int
    total_volume: int

    @property
    def label(self) -> str:
        """Human-readable label with emoji."""
        labels = {
            SentimentLevel.VERY_BULLISH: "🟢 Very Bullish",
            SentimentLevel.BULLISH: "🟢 Bullish",
            SentimentLevel.NEUTRAL: "🟡 Neutral",
            SentimentLevel.BEARISH: "🔴 Bearish",
            SentimentLevel.VERY_BEARISH: "🔴 Very Bearish",
        }
        return labels[self.level]


class SentimentCalculator:
    """
    Calculates sentiment ratios for dealers and customers.

    Dealer Gamma Ratio: Call GEX / Total GEX (0-1, higher = stabilizing)
    Active Sentiment: Call Volume / Total Volume (0-1, higher = bullish)
    """

    def __init__(
        self,
        stabilizing_threshold: float = 0.6,
        destabilizing_threshold: float = 0.4,
        bullish_threshold: float = 0.6,
        bearish_threshold: float = 0.4,
        very_bullish_threshold: float = 0.75,
        very_bearish_threshold: float = 0.25,
    ):
        """
        Initialize with configurable thresholds.

        Args:
            stabilizing_threshold: Ratio above this = stabilizing (default 0.6)
            destabilizing_threshold: Ratio below this = destabilizing (default 0.4)
            bullish_threshold: Ratio above this = bullish (default 0.6)
            bearish_threshold: Ratio below this = bearish (default 0.4)
            very_bullish_threshold: Ratio above this = very bullish (default 0.75)
            very_bearish_threshold: Ratio below this = very bearish (default 0.25)
        """
        self.stabilizing_threshold = stabilizing_threshold
        self.destabilizing_threshold = destabilizing_threshold
        self.bullish_threshold = bullish_threshold
        self.bearish_threshold = bearish_threshold
        self.very_bullish_threshold = very_bullish_threshold
        self.very_bearish_threshold = very_bearish_threshold

    def calculate_dealer_gamma_ratio(
        self,
        call_gex: float,
        put_gex: float,
    ) -> DealerGammaResult:
        """
        Calculate dealer gamma ratio.

        Formula: Call GEX / (Call GEX + Put GEX)

        Args:
            call_gex: Total call gamma exposure (positive gamma)
            put_gex: Total put gamma exposure (negative gamma)

        Returns:
            DealerGammaResult with ratio, stance, and component values
        """
        total_gex = call_gex + put_gex

        if total_gex > 0:
            ratio = call_gex / total_gex
        else:
            ratio = 0.5  # Default to neutral if no data

        # Clamp ratio to 0-1
        ratio = max(0.0, min(1.0, ratio))

        # Determine stance
        if ratio >= self.stabilizing_threshold:
            stance = DealerStance.STABILIZING
        elif ratio <= self.destabilizing_threshold:
            stance = DealerStance.DESTABILIZING
        else:
            stance = DealerStance.NEUTRAL

        return DealerGammaResult(
            ratio=ratio,
            stance=stance,
            positive_gamma=call_gex,
            negative_gamma=put_gex,
            net_gamma=call_gex - put_gex,
        )

    def calculate_active_sentiment(
        self,
        call_volume: int,
        put_volume: int,
    ) -> ActiveSentimentResult:
        """
        Calculate active sentiment from volume data.

        Formula: Call Volume / (Call Volume + Put Volume)

        Args:
            call_volume: Total call volume
            put_volume: Total put volume

        Returns:
            ActiveSentimentResult with ratio, level, and component values
        """
        total_volume = call_volume + put_volume

        if total_volume > 0:
            ratio = call_volume / total_volume
        else:
            ratio = 0.5  # Default to neutral if no data

        # Clamp ratio to 0-1
        ratio = max(0.0, min(1.0, ratio))

        # Determine sentiment level
        if ratio >= self.very_bullish_threshold:
            level = SentimentLevel.VERY_BULLISH
        elif ratio >= self.bullish_threshold:
            level = SentimentLevel.BULLISH
        elif ratio <= self.very_bearish_threshold:
            level = SentimentLevel.VERY_BEARISH
        elif ratio <= self.bearish_threshold:
            level = SentimentLevel.BEARISH
        else:
            level = SentimentLevel.NEUTRAL

        return ActiveSentimentResult(
            ratio=ratio,
            level=level,
            call_volume=call_volume,
            put_volume=put_volume,
            total_volume=total_volume,
        )

    def calculate_from_strike_df(
        self,
        strike_df: pd.DataFrame,
    ) -> Optional[ActiveSentimentResult]:
        """
        Calculate active sentiment from a strike DataFrame.

        Args:
            strike_df: DataFrame with 'call_volume' and 'put_volume' columns

        Returns:
            ActiveSentimentResult or None if DataFrame is empty/invalid
        """
        if strike_df.empty:
            return None

        if 'call_volume' not in strike_df.columns or 'put_volume' not in strike_df.columns:
            return None

        call_volume = int(strike_df['call_volume'].sum())
        put_volume = int(strike_df['put_volume'].sum())

        return self.calculate_active_sentiment(call_volume, put_volume)

    def calculate_from_gex_metrics(
        self,
        metrics: dict,
    ) -> DealerGammaResult:
        """
        Calculate dealer gamma ratio from GEX metrics dict.

        Args:
            metrics: Dict with 'total_call_gex' and 'total_put_gex' keys

        Returns:
            DealerGammaResult
        """
        call_gex = metrics.get('total_call_gex', 0.0)
        put_gex = metrics.get('total_put_gex', 0.0)

        return self.calculate_dealer_gamma_ratio(call_gex, put_gex)


if __name__ == "__main__":
    """Test sentiment calculator."""
    print("Testing Sentiment Calculator...\n")

    calc = SentimentCalculator()

    # Test dealer gamma ratio
    print("1. Dealer Gamma Ratio Tests:")
    test_cases = [
        (300_000_000, 100_000_000, "Should be stabilizing"),
        (100_000_000, 100_000_000, "Should be neutral"),
        (100_000_000, 300_000_000, "Should be destabilizing"),
    ]

    for call_gex, put_gex, expected in test_cases:
        result = calc.calculate_dealer_gamma_ratio(call_gex, put_gex)
        print(f"  Call: ${call_gex:,}, Put: ${put_gex:,}")
        print(f"  Ratio: {result.ratio:.2f}, Stance: {result.label}")
        print(f"  Expected: {expected}\n")

    # Test active sentiment
    print("2. Active Sentiment Tests:")
    test_cases = [
        (8000, 2000, "Should be bullish"),
        (5000, 5000, "Should be neutral"),
        (2000, 8000, "Should be bearish"),
    ]

    for call_vol, put_vol, expected in test_cases:
        result = calc.calculate_active_sentiment(call_vol, put_vol)
        print(f"  Call Vol: {call_vol:,}, Put Vol: {put_vol:,}")
        print(f"  Ratio: {result.ratio:.2f}, Level: {result.label}")
        print(f"  Expected: {expected}\n")

    print("✅ All tests completed!")
