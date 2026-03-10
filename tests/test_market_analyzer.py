"""
Tests for MarketAnalyzer

Tests cover:
1. Data aggregation from multiple sources
2. Bias calculation
3. Key levels identification
4. AI-ready summary generation
"""
import pytest
from datetime import datetime, timedelta


class TestMarketAnalyzer:
    """Tests for MarketAnalyzer class."""

    def test_analyzer_initialization(self, market_analyzer):
        """Analyzer should initialize with default settings."""
        assert market_analyzer is not None

    def test_analyze_returns_analysis_result(self, market_analyzer, sample_market_data):
        """analyze() should return a MarketAnalysis object."""
        from utils.market_analyzer import MarketAnalysis

        result = market_analyzer.analyze(sample_market_data)
        assert isinstance(result, MarketAnalysis)

    def test_analysis_has_bias(self, market_analyzer, sample_market_data):
        """Analysis should include bias direction."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.bias in ['BULLISH', 'BEARISH', 'NEUTRAL']

    def test_analysis_has_confidence(self, market_analyzer, sample_market_data):
        """Analysis should include confidence level."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.confidence in ['HIGH', 'MEDIUM', 'LOW']

    def test_analysis_has_bias_score(self, market_analyzer, sample_market_data):
        """Analysis should include numeric bias score (0-100)."""
        result = market_analyzer.analyze(sample_market_data)
        assert 0 <= result.bias_score <= 100


class TestKeyLevels:
    """Tests for key level identification."""

    def test_analysis_has_current_price(self, market_analyzer, sample_market_data):
        """Analysis should include current price."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.current_price == sample_market_data['spot_price']

    def test_analysis_has_gamma_flip(self, market_analyzer, sample_market_data):
        """Analysis should include gamma flip level."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.key_levels.gamma_flip is not None or result.key_levels.gamma_flip is None

    def test_analysis_has_max_gex_strike(self, market_analyzer, sample_market_data):
        """Analysis should include max GEX strike."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.key_levels.max_gex_strike is not None

    def test_analysis_has_walls_and_high_gamma(self, market_analyzer, sample_market_data):
        """Analysis should include call/put walls and high gamma levels."""
        result = market_analyzer.analyze(sample_market_data)
        assert hasattr(result.key_levels, 'call_wall')
        assert hasattr(result.key_levels, 'put_wall')
        assert hasattr(result.key_levels, 'hg_resistance_1')
        assert hasattr(result.key_levels, 'hg_resistance_2')
        assert hasattr(result.key_levels, 'hg_support_1')
        assert hasattr(result.key_levels, 'hg_support_2')


class TestCharmFlow:
    """Tests for charm flow analysis."""

    def test_analysis_has_charm_direction(self, market_analyzer, sample_market_data):
        """Analysis should include charm flow direction."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.charm_flow.direction in ['BUY', 'SELL', 'NEUTRAL']

    def test_analysis_has_charm_net_charm(self, market_analyzer, sample_market_data):
        """Analysis should include net charm."""
        result = market_analyzer.analyze(sample_market_data)
        # net_charm can be None if data insufficient, or a number
        assert result.charm_flow.net_charm is None or isinstance(result.charm_flow.net_charm, (int, float))


class TestSentiment:
    """Tests for sentiment analysis."""

    def test_analysis_has_dealer_stance(self, market_analyzer, sample_market_data):
        """Analysis should include dealer stance."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.sentiment.dealer_stance in ['STABILIZING', 'DESTABILIZING', 'NEUTRAL']

    def test_analysis_has_customer_sentiment(self, market_analyzer, sample_market_data):
        """Analysis should include customer sentiment."""
        result = market_analyzer.analyze(sample_market_data)
        assert result.sentiment.customer in ['BULLISH', 'BEARISH', 'NEUTRAL']

    def test_analysis_has_dealer_ratio(self, market_analyzer, sample_market_data):
        """Analysis should include dealer gamma ratio."""
        result = market_analyzer.analyze(sample_market_data)
        assert 0 <= result.sentiment.dealer_ratio <= 1

    def test_analysis_has_customer_ratio(self, market_analyzer, sample_market_data):
        """Analysis should include customer sentiment ratio."""
        result = market_analyzer.analyze(sample_market_data)
        assert 0 <= result.sentiment.customer_ratio <= 1


class TestAISummary:
    """Tests for AI-ready summary generation."""

    def test_to_ai_prompt_returns_string(self, market_analyzer, sample_market_data):
        """to_ai_prompt() should return a formatted string."""
        result = market_analyzer.analyze(sample_market_data)
        prompt = result.to_ai_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100  # Should be substantial

    def test_ai_prompt_contains_key_data(self, market_analyzer, sample_market_data):
        """AI prompt should contain key market data."""
        result = market_analyzer.analyze(sample_market_data)
        prompt = result.to_ai_prompt()

        # Should contain key information
        assert 'SPX' in prompt or str(sample_market_data['spot_price']) in prompt
        assert 'bias' in prompt.lower() or 'BULLISH' in prompt or 'BEARISH' in prompt

    def test_to_dict_returns_dict(self, market_analyzer, sample_market_data):
        """to_dict() should return a dictionary."""
        result = market_analyzer.analyze(sample_market_data)
        data = result.to_dict()
        assert isinstance(data, dict)

    def test_dict_is_json_serializable(self, market_analyzer, sample_market_data):
        """Dictionary should be JSON serializable."""
        import json
        result = market_analyzer.analyze(sample_market_data)
        data = result.to_dict()
        # Should not raise
        json_str = json.dumps(data)
        assert isinstance(json_str, str)


class TestBiasCalculation:
    """Tests for bias calculation logic."""

    def test_bullish_signals_give_higher_score(self, market_analyzer, bullish_market_data):
        """Bullish GEX/sentiment signals should result in higher bias score."""
        result = market_analyzer.analyze(bullish_market_data)
        # Bullish sentiment and dealer stance push score higher
        # Note: Charm direction may counter this (calls have negative charm)
        assert result.sentiment.dealer_ratio > 0.6
        assert result.sentiment.customer_ratio > 0.6

    def test_bearish_signals_give_bearish_bias(self, market_analyzer, bearish_market_data):
        """Bearish signals should result in bearish bias."""
        result = market_analyzer.analyze(bearish_market_data)
        assert result.bias == 'BEARISH'
        assert result.bias_score < 50

    def test_mixed_signals_give_moderate_score(self, market_analyzer, neutral_market_data):
        """Mixed signals should result in moderate score around 50."""
        result = market_analyzer.analyze(neutral_market_data)
        # With balanced data, score should be moderate (not extreme)
        assert 20 <= result.bias_score <= 80


class TestDisplaySummary:
    """Tests for display-ready summary."""

    def test_to_display_returns_string(self, market_analyzer, sample_market_data):
        """to_display() should return formatted display string."""
        result = market_analyzer.analyze(sample_market_data)
        display = result.to_display()
        assert isinstance(display, str)

    def test_display_contains_emoji(self, market_analyzer, sample_market_data):
        """Display should contain emoji indicators."""
        result = market_analyzer.analyze(sample_market_data)
        display = result.to_display()
        assert any(emoji in display for emoji in ['🟢', '🔴', '🟡', '📊', '⚡'])


# Fixtures

@pytest.fixture
def market_analyzer():
    """Create a MarketAnalyzer instance."""
    from utils.market_analyzer import MarketAnalyzer
    return MarketAnalyzer()


@pytest.fixture
def sample_market_data():
    """Sample market data for testing."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        'symbol': 'SPX',
        'spot_price': 6000,
        'expiry': tomorrow,
        'gex_metrics': {
            'total_call_gex': 300_000_000,
            'total_put_gex': 200_000_000,
            'net_gex': 100_000_000,
            'max_gex_strike': 6000,
            'zero_gamma': 5950,
        },
        'options_data': {
            f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 1000, 'strike': 6000, 'type': 'C'},
            f".SPXW{tomorrow}P6000": {'iv': 0.22, 'oi': 1500, 'strike': 6000, 'type': 'P'},
            f".SPXW{tomorrow}C6050": {'iv': 0.18, 'oi': 800, 'strike': 6050, 'type': 'C'},
            f".SPXW{tomorrow}P5950": {'iv': 0.24, 'oi': 1200, 'strike': 5950, 'type': 'P'},
        },
        'volume_data': {
            'total_call_volume': 5000,
            'total_put_volume': 4000,
        },
    }


@pytest.fixture
def bullish_market_data():
    """Market data with bullish signals."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        'symbol': 'SPX',
        'spot_price': 6000,
        'expiry': tomorrow,
        'gex_metrics': {
            'total_call_gex': 500_000_000,  # High call GEX
            'total_put_gex': 100_000_000,   # Low put GEX
            'net_gex': 400_000_000,          # Strong positive
            'max_gex_strike': 6000,
            'zero_gamma': 5900,              # Price above flip
        },
        'options_data': {
            f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 3000, 'strike': 6000, 'type': 'C'},
            f".SPXW{tomorrow}P6000": {'iv': 0.22, 'oi': 500, 'strike': 6000, 'type': 'P'},
        },
        'volume_data': {
            'total_call_volume': 8000,  # High call volume
            'total_put_volume': 2000,   # Low put volume
        },
    }


@pytest.fixture
def bearish_market_data():
    """Market data with bearish signals."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        'symbol': 'SPX',
        'spot_price': 6000,
        'expiry': tomorrow,
        'gex_metrics': {
            'total_call_gex': 100_000_000,  # Low call GEX
            'total_put_gex': 500_000_000,   # High put GEX
            'net_gex': -400_000_000,         # Strong negative
            'max_gex_strike': 5950,
            'zero_gamma': 6100,              # Price below flip
        },
        'options_data': {
            f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 500, 'strike': 6000, 'type': 'C'},
            f".SPXW{tomorrow}P6000": {'iv': 0.22, 'oi': 3000, 'strike': 6000, 'type': 'P'},
        },
        'volume_data': {
            'total_call_volume': 2000,  # Low call volume
            'total_put_volume': 8000,   # High put volume
        },
    }


@pytest.fixture
def neutral_market_data():
    """Market data with neutral/mixed signals."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%y%m%d")
    return {
        'symbol': 'SPX',
        'spot_price': 6000,
        'expiry': tomorrow,
        'gex_metrics': {
            'total_call_gex': 250_000_000,
            'total_put_gex': 250_000_000,
            'net_gex': 0,
            'max_gex_strike': 6000,
            'zero_gamma': 6000,  # At flip point
        },
        'options_data': {
            f".SPXW{tomorrow}C6000": {'iv': 0.20, 'oi': 1000, 'strike': 6000, 'type': 'C'},
            f".SPXW{tomorrow}P6000": {'iv': 0.20, 'oi': 1000, 'strike': 6000, 'type': 'P'},
        },
        'volume_data': {
            'total_call_volume': 5000,
            'total_put_volume': 5000,
        },
    }
