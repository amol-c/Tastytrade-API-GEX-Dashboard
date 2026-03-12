"""
Market Analyzer
Combines GEX, Charm, and Sentiment data into a unified market analysis.
Generates AI-ready summaries for trading decisions.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import pytz

from utils.charm_calculator import CharmCalculator, FlowDirection
from utils.sentiment_calculator import SentimentCalculator


@dataclass
class KeyLevels:
    """Key price levels for trading."""
    gamma_flip: Optional[float]
    max_gex_strike: Optional[float]
    call_wall: Optional[float]       # Highest call GEX strike (SpotGamma style)
    put_wall: Optional[float]        # Highest put GEX strike (SpotGamma style)
    hg_resistance_1: Optional[float] # Highest |Net GEX| above price (within 10 strikes)
    hg_resistance_2: Optional[float] # 2nd highest |Net GEX| above price
    hg_support_1: Optional[float]    # Highest |Net GEX| below price (within 10 strikes)
    hg_support_2: Optional[float]    # 2nd highest |Net GEX| below price


@dataclass
class CharmFlowAnalysis:
    """Charm flow analysis results."""
    direction: str  # 'BUY', 'SELL', 'NEUTRAL'
    net_charm: Optional[float]  # None if data unavailable


@dataclass
class VannaFlowAnalysis:
    """Vanna flow analysis results."""
    direction: str  # 'BUY', 'SELL', 'NEUTRAL'
    net_vanna: Optional[float]  # None if data unavailable
    iv_direction: str  # 'RISING', 'FALLING', 'FLAT'


@dataclass
class SentimentAnalysis:
    """Sentiment analysis results."""
    dealer_stance: str  # 'STABILIZING', 'DESTABILIZING', 'NEUTRAL'
    dealer_ratio: float  # 0-1
    customer: str  # 'BULLISH', 'BEARISH', 'NEUTRAL'
    customer_ratio: float  # 0-1


@dataclass
class MarketAnalysis:
    """Complete market analysis result."""
    symbol: str
    timestamp: datetime
    current_price: float
    expiry: str

    # Overall bias
    bias: str  # 'BULLISH', 'BEARISH', 'NEUTRAL'
    bias_score: float  # 0-100 (0=very bearish, 100=very bullish)
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'

    # Component analyses
    key_levels: KeyLevels
    charm_flow: CharmFlowAnalysis
    vanna_flow: VannaFlowAnalysis
    sentiment: SentimentAnalysis

    # Raw metrics
    gex_metrics: Dict
    charm_metrics: Dict = field(default_factory=dict)
    vanna_metrics: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'current_price': self.current_price,
            'expiry': self.expiry,
            'bias': self.bias,
            'bias_score': self.bias_score,
            'confidence': self.confidence,
            'key_levels': {
                'gamma_flip': self.key_levels.gamma_flip,
                'max_gex_strike': self.key_levels.max_gex_strike,
                'call_wall': self.key_levels.call_wall,
                'put_wall': self.key_levels.put_wall,
                'hg_resistance_1': self.key_levels.hg_resistance_1,
                'hg_resistance_2': self.key_levels.hg_resistance_2,
                'hg_support_1': self.key_levels.hg_support_1,
                'hg_support_2': self.key_levels.hg_support_2,
            },
            'charm_flow': {
                'direction': self.charm_flow.direction,
                'net_charm': self.charm_flow.net_charm,
            },
            'vanna_flow': {
                'direction': self.vanna_flow.direction,
                'net_vanna': self.vanna_flow.net_vanna,
                'iv_direction': self.vanna_flow.iv_direction,
            },
            'sentiment': {
                'dealer_stance': self.sentiment.dealer_stance,
                'dealer_ratio': self.sentiment.dealer_ratio,
                'customer': self.sentiment.customer,
                'customer_ratio': self.sentiment.customer_ratio,
            },
            'gex_metrics': self.gex_metrics,
        }

    def to_ai_prompt(self) -> str:
        """Generate AI-ready prompt with market analysis."""
        price_vs_flip = "ABOVE" if self.key_levels.gamma_flip and self.current_price > self.key_levels.gamma_flip else "BELOW"

        # Format key levels
        gamma_flip_str = f"${self.key_levels.gamma_flip:,.2f}" if self.key_levels.gamma_flip else "N/A"
        max_gex_str = f"${self.key_levels.max_gex_strike:,.0f}" if self.key_levels.max_gex_strike else "N/A"
        call_wall_str = f"${self.key_levels.call_wall:,.0f}" if self.key_levels.call_wall else "N/A"
        put_wall_str = f"${self.key_levels.put_wall:,.0f}" if self.key_levels.put_wall else "N/A"
        hg_res1_str = f"${self.key_levels.hg_resistance_1:,.0f}" if self.key_levels.hg_resistance_1 else "N/A"
        hg_res2_str = f"${self.key_levels.hg_resistance_2:,.0f}" if self.key_levels.hg_resistance_2 else "N/A"
        hg_sup1_str = f"${self.key_levels.hg_support_1:,.0f}" if self.key_levels.hg_support_1 else "N/A"
        hg_sup2_str = f"${self.key_levels.hg_support_2:,.0f}" if self.key_levels.hg_support_2 else "N/A"

        prompt = f"""## Market Analysis for {self.symbol}
**Generated:** {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
**Expiry:** {self.expiry}

### Current State
- **Price:** ${self.current_price:,.2f}
- **Bias:** {self.bias} (Score: {self.bias_score:.0f}/100)
- **Confidence:** {self.confidence}

### Key Levels
- **Gamma Flip:** {gamma_flip_str} (Price is {price_vs_flip} flip)
- **Call Wall:** {call_wall_str} (Highest call gamma)
- **Put Wall:** {put_wall_str} (Highest put gamma)
- **HG Resistance:** {hg_res1_str}, {hg_res2_str} (Above price, highest gamma)
- **HG Support:** {hg_sup1_str}, {hg_sup2_str} (Below price, highest gamma)

### Dealer Positioning (GEX)
- **Stance:** {self.sentiment.dealer_stance}
- **Dealer Gamma Ratio:** {self.sentiment.dealer_ratio:.2f} (1.0 = fully stabilizing)
- **Net GEX:** ${self.gex_metrics.get('net_gex', 0):,.0f}
- **Interpretation:** {"Dealers will dampen moves (buy dips, sell rallies)" if self.sentiment.dealer_stance == 'STABILIZING' else "Dealers will amplify moves (sell dips, buy rallies)"}

### Charm Flow (Delta Decay Prediction)
- **Current Flow Direction:** {self.charm_flow.direction}
- **Net Charm Exposure:** ${self.charm_flow.net_charm or 0:,.0f}
- **Interpretation:** {"Dealers will BUY as time passes → UP pressure" if self.charm_flow.direction == 'BUY' else "Dealers will SELL as time passes → DOWN pressure" if self.charm_flow.direction == 'SELL' else "Balanced, no directional pressure"}

"""
        # Format summary values
        magnet_summary = f"${self.key_levels.max_gex_strike:,.0f}" if self.key_levels.max_gex_strike else "N/A"

        customer_interp = "Customers are aggressively buying calls (risk-on)" if self.sentiment.customer == 'BULLISH' else "Customers are aggressively buying puts (hedging/bearish)" if self.sentiment.customer == 'BEARISH' else "Balanced customer activity"

        prompt += f"""
### Customer Sentiment
- **Sentiment:** {self.sentiment.customer}
- **Active Sentiment Ratio:** {self.sentiment.customer_ratio:.2f} (1.0 = very bullish)
- **Interpretation:** {customer_interp}

### Summary
Based on the combined analysis of GEX positioning, charm flow projections, and customer sentiment:

- **Direction:** {self.bias}
- **Confidence:** {self.confidence}
- **Call Wall:** {call_wall_str}
- **Put Wall:** {put_wall_str}
- **HG Resistance:** {hg_res1_str}, {hg_res2_str}
- **HG Support:** {hg_sup1_str}, {hg_sup2_str}

Please provide your assessment of the likely price direction and any trade setups.
"""
        return prompt

    def to_display(self) -> str:
        """Generate display-ready summary."""
        bias_emoji = {'BULLISH': '🟢', 'BEARISH': '🔴', 'NEUTRAL': '🟡'}
        conf_emoji = {'HIGH': '🔥', 'MEDIUM': '⚡', 'LOW': '💤'}

        return f"""
╔══════════════════════════════════════════════════════════════╗
║  {bias_emoji.get(self.bias, '🟡')} MARKET BIAS: {self.bias:<10} {conf_emoji.get(self.confidence, '')} Confidence: {self.confidence:<6} ║
║  Score: {self.bias_score:.0f}/100                                           ║
╠══════════════════════════════════════════════════════════════╣
║  📊 {self.symbol}: ${self.current_price:,.2f}                               ║
╠══════════════════════════════════════════════════════════════╣
║  KEY LEVELS                                                  ║
║  ─────────────────────────────────────────────────           ║
║  🔺 Call Wall:   ${self.key_levels.call_wall or 0:>7,.0f}                            ║
║  🔀 Gamma Flip:  ${self.key_levels.gamma_flip or 0:>7,.0f}                           ║
║  🔻 Put Wall:    ${self.key_levels.put_wall or 0:>7,.0f}                            ║
║  ⬆️ HG Resist:   ${self.key_levels.hg_resistance_1 or 0:>7,.0f}  ${self.key_levels.hg_resistance_2 or 0:>7,.0f}              ║
║  ⬇️ HG Support:  ${self.key_levels.hg_support_1 or 0:>7,.0f}  ${self.key_levels.hg_support_2 or 0:>7,.0f}              ║
╠══════════════════════════════════════════════════════════════╣
║  CHARM FLOW: {self.charm_flow.direction:<8}                                    ║
║  Net: {"N/A" if self.charm_flow.net_charm is None else f"${self.charm_flow.net_charm:>12,.0f}"} → {"UP pressure" if self.charm_flow.direction == 'BUY' else "DOWN pressure" if self.charm_flow.direction == 'SELL' else "Neutral":<14}        ║
╠══════════════════════════════════════════════════════════════╣
║  SENTIMENT                                                   ║
║  Dealer: {self.sentiment.dealer_stance:<15} ({self.sentiment.dealer_ratio:.2f})              ║
║  Customer: {self.sentiment.customer:<13} ({self.sentiment.customer_ratio:.2f})              ║
╚══════════════════════════════════════════════════════════════╝
"""


class MarketAnalyzer:
    """
    Analyzes market data from multiple sources to generate trading signals.

    Combines:
    - GEX (Gamma Exposure) - Dealer positioning
    - Charm - Delta decay / hedging flow prediction
    - Sentiment - Customer bullish/bearish positioning
    """

    def __init__(
        self,
        charm_calculator: Optional[CharmCalculator] = None,
        sentiment_calculator: Optional[SentimentCalculator] = None,
    ):
        """Initialize with calculators."""
        self.charm_calc = charm_calculator or CharmCalculator()
        self.sentiment_calc = sentiment_calculator or SentimentCalculator()

        # Bias weights
        self.weights = {
            'charm_flow': 0.40,
            'gex_stance': 0.30,
            'customer_sentiment': 0.20,
            'price_vs_flip': 0.10,
        }

    def analyze(self, market_data: Dict) -> MarketAnalysis:
        """
        Perform complete market analysis.

        Args:
            market_data: Dictionary containing:
                - symbol: str
                - spot_price: float
                - expiry: str (YYMMDD)
                - gex_metrics: dict
                - options_data: dict
                - volume_data: dict
                - vanna_data: dict (optional) with net_vanna, flow_direction, iv_direction

        Returns:
            MarketAnalysis object
        """
        symbol = market_data.get('symbol', 'SPX')
        spot_price = market_data['spot_price']
        expiry = market_data['expiry']
        gex_metrics = market_data.get('gex_metrics', {})
        options_data = market_data.get('options_data', {})
        volume_data = market_data.get('volume_data', {})
        vanna_data = market_data.get('vanna_data', {})

        # Calculate sentiment
        dealer_result = self.sentiment_calc.calculate_dealer_gamma_ratio(
            call_gex=gex_metrics.get('total_call_gex', 0),
            put_gex=gex_metrics.get('total_put_gex', 0),
        )

        customer_ratio = self._calculate_customer_sentiment(volume_data)

        # Calculate current charm
        current_charm = self.charm_calc.calculate_current_charm(
            options_data=options_data,
            spot=spot_price,
            expiry_str=expiry,
        )

        charm_projections = [current_charm] if current_charm else []
        charm_summary = self.charm_calc.get_flow_summary(charm_projections)

        # Build key levels
        key_levels = self._build_key_levels(gex_metrics, options_data, spot_price)

        # Build charm flow analysis
        charm_flow = self._build_charm_flow(charm_summary)

        # Build vanna flow analysis
        vanna_flow = self._build_vanna_flow(vanna_data)

        # Build sentiment analysis
        sentiment = self._build_sentiment(dealer_result, customer_ratio)

        # Calculate overall bias with time-based Greek weighting
        bias_score = self._calculate_bias_score(
            charm_flow=charm_flow,
            vanna_flow=vanna_flow,
            sentiment=sentiment,
            spot_price=spot_price,
            gamma_flip=key_levels.gamma_flip,
            expiry=expiry,
        )

        bias, confidence = self._score_to_bias(bias_score)

        # Calculate timestamp in NY
        ny_tz = pytz.timezone('US/Eastern')
        ny_now = datetime.now(ny_tz)

        return MarketAnalysis(
            symbol=symbol,
            timestamp=ny_now,
            current_price=spot_price,
            expiry=expiry,
            bias=bias,
            bias_score=bias_score,
            confidence=confidence,
            key_levels=key_levels,
            charm_flow=charm_flow,
            vanna_flow=vanna_flow,
            sentiment=sentiment,
            gex_metrics=gex_metrics,
        )

    def _calculate_customer_sentiment(self, volume_data: Dict) -> float:
        """Calculate customer sentiment ratio from volume."""
        call_vol = volume_data.get('total_call_volume', 0)
        put_vol = volume_data.get('total_put_volume', 0)
        total = call_vol + put_vol
        if total > 0:
            return call_vol / total
        return 0.5

    def _build_key_levels(
        self,
        gex_metrics: Dict,
        options_data: Dict,
        spot_price: float,
    ) -> KeyLevels:
        """Build key levels from data."""
        return KeyLevels(
            gamma_flip=gex_metrics.get('zero_gamma'),
            max_gex_strike=gex_metrics.get('max_gex_strike'),
            call_wall=gex_metrics.get('call_wall'),
            put_wall=gex_metrics.get('put_wall'),
            hg_resistance_1=gex_metrics.get('hg_resistance_1'),
            hg_resistance_2=gex_metrics.get('hg_resistance_2'),
            hg_support_1=gex_metrics.get('hg_support_1'),
            hg_support_2=gex_metrics.get('hg_support_2'),
        )

    def _build_charm_flow(self, charm_summary: Dict) -> CharmFlowAnalysis:
        """Build charm flow analysis from summary."""
        direction = charm_summary.get('current_flow', 'neutral').upper()
        net_charm = charm_summary.get('current_net_charm')  # None if no data

        return CharmFlowAnalysis(
            direction=direction,
            net_charm=net_charm,
        )

    def _build_vanna_flow(self, vanna_data: Dict) -> VannaFlowAnalysis:
        """Build vanna flow analysis from vanna data."""
        direction = vanna_data.get('flow_direction', 'NEUTRAL')
        net_vanna = vanna_data.get('net_vanna')
        iv_direction = vanna_data.get('iv_direction', 'FLAT')

        return VannaFlowAnalysis(
            direction=direction,
            net_vanna=net_vanna,
            iv_direction=iv_direction,
        )

    def _build_sentiment(self, dealer_result, customer_ratio: float) -> SentimentAnalysis:
        """Build sentiment analysis."""
        # Dealer stance
        if dealer_result.ratio >= 0.6:
            dealer_stance = 'STABILIZING'
        elif dealer_result.ratio <= 0.4:
            dealer_stance = 'DESTABILIZING'
        else:
            dealer_stance = 'NEUTRAL'

        # Customer sentiment
        if customer_ratio >= 0.6:
            customer = 'BULLISH'
        elif customer_ratio <= 0.4:
            customer = 'BEARISH'
        else:
            customer = 'NEUTRAL'

        return SentimentAnalysis(
            dealer_stance=dealer_stance,
            dealer_ratio=dealer_result.ratio,
            customer=customer,
            customer_ratio=customer_ratio,
        )

    def _get_greek_weights(self, expiry: str) -> tuple:
        """
        Get time-based weights for Vanna vs Charm based on NY market time.

        Returns (vanna_weight, charm_weight) as percentages that sum to 1.0

        Timeline (ET):
        - >5 hours: Vanna 70%, Charm 30%
        - 3-5 hours: Vanna 50%, Charm 50%
        - 1-3 hours: Vanna 30%, Charm 70%
        - <1 hour: Vanna 10%, Charm 90%
        """
        try:
            # Parse expiry date
            expiry_date_naive = datetime.strptime(expiry, "%y%m%d")
            
            # NY Timezone
            ny_tz = pytz.timezone('US/Eastern')
            
            # Market close is 16:00 ET
            expiry_ny = ny_tz.localize(datetime(
                expiry_date_naive.year, 
                expiry_date_naive.month, 
                expiry_date_naive.day, 
                16, 0, 0
            ))

            # Current time in NY
            now_ny = datetime.now(ny_tz)
            
            time_remaining = expiry_ny - now_ny
            hours_remaining = time_remaining.total_seconds() / 3600

            if hours_remaining <= 0:
                return (0.0, 1.0)  # Expired, charm only
            elif hours_remaining < 1:
                return (0.10, 0.90)
            elif hours_remaining < 3:
                return (0.30, 0.70)
            elif hours_remaining < 5:
                return (0.50, 0.50)
            else:
                return (0.70, 0.30)
        except Exception as e:
            logger.error(f"Error calculating Greek weights: {e}")
            return (0.50, 0.50)  # Default to equal weight

    def _calculate_bias_score(
        self,
        charm_flow: CharmFlowAnalysis,
        vanna_flow: VannaFlowAnalysis,
        sentiment: SentimentAnalysis,
        spot_price: float,
        gamma_flip: Optional[float],
        expiry: str,
    ) -> float:
        """
        Calculate overall bias score (0-100).

        Vanna and Charm are weighted based on time to expiry:
        - Morning (>5h): Vanna dominates (70/30)
        - Midday (3-5h): Equal weight (50/50)
        - Afternoon (1-3h): Charm dominates (30/70)
        - Final hour (<1h): Charm explosion (10/90)

        0 = Very Bearish
        50 = Neutral
        100 = Very Bullish
        """
        score = 50.0  # Start neutral

        # Get time-based weights for Greeks
        vanna_weight, charm_weight = self._get_greek_weights(expiry)

        # Max points for Greeks flow combined = 20
        max_greek_points = 20

        # Vanna flow contribution (weighted)
        vanna_points = 0
        if vanna_flow.direction == 'BUY':
            vanna_points = max_greek_points
        elif vanna_flow.direction == 'SELL':
            vanna_points = -max_greek_points

        # Charm flow contribution (weighted)
        charm_points = 0
        if charm_flow.direction == 'BUY':
            charm_points = max_greek_points
        elif charm_flow.direction == 'SELL':
            charm_points = -max_greek_points

        # Apply time-based weighting
        greek_contribution = (vanna_points * vanna_weight) + (charm_points * charm_weight)
        score += greek_contribution

        # Dealer stance contribution (±15 points max)
        # Use ratio directly: 0.5 = neutral, >0.5 = stabilizing = bullish
        dealer_contribution = (sentiment.dealer_ratio - 0.5) * 30  # -15 to +15
        score += dealer_contribution

        # Customer sentiment contribution (±10 points max)
        # Use ratio directly: 0.5 = neutral, >0.5 = bullish
        customer_contribution = (sentiment.customer_ratio - 0.5) * 20  # -10 to +10
        score += customer_contribution

        # Price vs gamma flip contribution (±5 points max)
        if gamma_flip:
            if spot_price > gamma_flip:
                score += 5
            else:
                score -= 5

        # Clamp to 0-100
        return max(0, min(100, score))

    def _score_to_bias(self, score: float) -> tuple:
        """Convert score to bias and confidence."""
        if score >= 65:
            bias = 'BULLISH'
            confidence = 'HIGH' if score >= 80 else 'MEDIUM' if score >= 70 else 'LOW'
        elif score <= 35:
            bias = 'BEARISH'
            confidence = 'HIGH' if score <= 20 else 'MEDIUM' if score <= 30 else 'LOW'
        else:
            bias = 'NEUTRAL'
            confidence = 'LOW' if 45 <= score <= 55 else 'MEDIUM'

        return bias, confidence
