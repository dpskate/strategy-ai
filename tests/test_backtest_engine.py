"""
Unit tests for backtest_engine.py
測試技術指標、交易執行邏輯、績效計算
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import (
    Candle, Trade, StrategyConfig, BacktestEngine,
    ema, sma, rsi, bollinger_bands, atr, macd, obv,
    stoch_rsi, donchian, vwap_ratio,
    evaluate, deflated_sharpe, monte_carlo, format_report,
)


# ─── Helpers ───────────────────────────────────────────────────────────────

def make_candles(closes, base_time=1_000_000):
    """Build synthetic candles from a list of close prices."""
    candles = []
    for i, c in enumerate(closes):
        candles.append(Candle(
            time=base_time + i * 3_600_000,
            open=c * 0.999,
            high=c * 1.005,
            low=c * 0.995,
            close=c,
            volume=1000.0 + i,
        ))
    return candles


def make_rising_candles(n=300, start=100.0, step=0.5):
    closes = [start + i * step for i in range(n)]
    return make_candles(closes)


def make_falling_candles(n=300, start=200.0, step=0.5):
    closes = [start - i * step for i in range(n)]
    return make_candles(closes)


def make_flat_candles(n=300, price=100.0):
    return make_candles([price] * n)


def closed_trade(entry=100.0, exit_=110.0, side="long", size=1.0,
                 entry_time=0, exit_time=3_600_000):
    t = Trade(entry_time=entry_time, entry_price=entry, side=side, size=size)
    t.close_trade(exit_, exit_time, reason="signal", commission_pct=0.04)
    return t


# ─── Candle dataclass ──────────────────────────────────────────────────────

class TestCandle:
    def test_bullish(self):
        c = Candle(0, 100, 110, 95, 105, 1000)
        assert c.bullish is True
        assert c.bearish is False

    def test_bearish(self):
        c = Candle(0, 105, 110, 90, 95, 1000)
        assert c.bearish is True
        assert c.bullish is False

    def test_body(self):
        c = Candle(0, 100, 110, 90, 108, 1000)
        assert abs(c.body - 8.0) < 1e-9

    def test_range(self):
        c = Candle(0, 100, 115, 85, 110, 1000)
        assert abs(c.range - 30.0) < 1e-9

    def test_upper_wick(self):
        c = Candle(0, 100, 115, 90, 110, 1000)
        assert abs(c.upper_wick - 5.0) < 1e-9   # high(115) - max(open,close)(110)

    def test_lower_wick(self):
        c = Candle(0, 100, 115, 90, 110, 1000)
        assert abs(c.lower_wick - 10.0) < 1e-9  # min(open,close)(100) - low(90)


# ─── Trade dataclass ───────────────────────────────────────────────────────

class TestTrade:
    def test_not_closed_initially(self):
        t = Trade(entry_time=0, entry_price=100.0)
        assert not t.closed

    def test_closed_after_close_trade(self):
        t = Trade(entry_time=0, entry_price=100.0)
        t.close_trade(110.0, 3600000, "signal", 0.04)
        assert t.closed

    def test_long_profit(self):
        t = Trade(entry_time=0, entry_price=100.0, side="long", size=1.0)
        t.close_trade(110.0, 3600000, "take_profit", 0.04)
        assert t.pnl_pct == pytest.approx(10.0, abs=0.01)
        assert t.pnl > 0

    def test_long_loss(self):
        t = Trade(entry_time=0, entry_price=100.0, side="long", size=1.0)
        t.close_trade(90.0, 3600000, "stop_loss", 0.04)
        assert t.pnl_pct == pytest.approx(-10.0, abs=0.01)
        assert t.pnl < 0

    def test_short_profit(self):
        t = Trade(entry_time=0, entry_price=100.0, side="short", size=1.0)
        t.close_trade(90.0, 3600000, "take_profit", 0.04)
        assert t.pnl_pct == pytest.approx(10.0, abs=0.01)
        assert t.pnl > 0

    def test_short_loss(self):
        t = Trade(entry_time=0, entry_price=100.0, side="short", size=1.0)
        t.close_trade(110.0, 3600000, "stop_loss", 0.04)
        assert t.pnl_pct == pytest.approx(-10.0, abs=0.01)
        assert t.pnl < 0

    def test_fees_applied(self):
        t = Trade(entry_time=0, entry_price=100.0, side="long", size=1.0)
        t.close_trade(100.0, 3600000, "signal", 0.04)
        # Zero price move → pnl < 0 due to fees
        assert t.pnl < 0
        assert t.fees > 0

    def test_exit_reason_stored(self):
        t = Trade(entry_time=0, entry_price=100.0, side="long", size=1.0)
        t.close_trade(105.0, 3600000, "stop_loss", 0.04)
        assert t.exit_reason == "stop_loss"


# ─── EMA ──────────────────────────────────────────────────────────────────

class TestEMA:
    def test_length_preserved(self):
        data = list(range(1, 31))
        result = ema(data, 10)
        assert len(result) == len(data)

    def test_none_for_warmup(self):
        result = ema(list(range(1, 21)), 10)
        assert all(v is None for v in result[:9])
        assert result[9] is not None

    def test_constant_series(self):
        result = ema([50.0] * 30, 10)
        for v in result[9:]:
            assert v == pytest.approx(50.0, abs=1e-6)

    def test_short_data_returns_none(self):
        result = ema([1, 2, 3], 10)
        assert all(v is None for v in result)

    def test_trending_up(self):
        closes = [i * 1.0 for i in range(1, 51)]
        result = ema(closes, 10)
        # EMA should be positive and increasing at end
        valid = [v for v in result if v is not None]
        assert valid[-1] > valid[0]


# ─── SMA ──────────────────────────────────────────────────────────────────

class TestSMA:
    def test_length_preserved(self):
        result = sma(list(range(1, 21)), 5)
        assert len(result) == 20

    def test_none_for_warmup(self):
        result = sma([1.0] * 10, 5)
        assert all(v is None for v in result[:4])
        assert result[4] is not None

    def test_correct_average(self):
        result = sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        # index 2: avg(1,2,3)=2, index 3: avg(2,3,4)=3, index 4: avg(3,4,5)=4
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_constant_series(self):
        result = sma([7.0] * 20, 5)
        for v in result[4:]:
            assert v == pytest.approx(7.0)


# ─── RSI ──────────────────────────────────────────────────────────────────

class TestRSI:
    def test_length_preserved(self):
        result = rsi(list(range(1, 31)), 14)
        assert len(result) == 30

    def test_none_for_warmup(self):
        result = rsi(list(range(1, 31)), 14)
        # first period+1 values should be None
        assert all(v is None for v in result[:15])

    def test_all_gains_rsi_100(self):
        # Strictly increasing: all gains, no losses → RSI = 100
        closes = [100 + i for i in range(30)]
        result = rsi(closes, 14)
        valid = [v for v in result if v is not None]
        assert all(v == pytest.approx(100.0, abs=1e-4) for v in valid)

    def test_all_losses_rsi_0(self):
        closes = [100 - i for i in range(30)]
        result = rsi(closes, 14)
        valid = [v for v in result if v is not None]
        assert all(v == pytest.approx(0.0, abs=1e-4) for v in valid)

    def test_range_0_to_100(self):
        import random
        random.seed(42)
        closes = [50 + random.gauss(0, 5) for _ in range(100)]
        result = rsi(closes, 14)
        for v in result:
            if v is not None:
                assert 0 <= v <= 100

    def test_too_short_returns_none_list(self):
        result = rsi([1, 2, 3], 14)
        assert all(v is None for v in result)


# ─── Bollinger Bands ──────────────────────────────────────────────────────

class TestBollingerBands:
    def test_returns_three_lists(self):
        upper, middle, lower = bollinger_bands([50.0] * 30, 20)
        assert len(upper) == len(middle) == len(lower) == 30

    def test_none_for_warmup(self):
        upper, middle, lower = bollinger_bands(list(range(1, 31)), 20)
        assert all(v is None for v in upper[:19])
        assert upper[19] is not None

    def test_upper_above_middle_above_lower(self):
        closes = [50 + (i % 10) for i in range(50)]
        upper, middle, lower = bollinger_bands(closes, 20)
        for u, m, l in zip(upper, middle, lower):
            if u is not None:
                assert u >= m >= l

    def test_constant_series_zero_bandwidth(self):
        upper, middle, lower = bollinger_bands([100.0] * 30, 20)
        for u, m, l in zip(upper[19:], middle[19:], lower[19:]):
            assert u == pytest.approx(100.0)
            assert m == pytest.approx(100.0)
            assert l == pytest.approx(100.0)

    def test_std_mult_affects_band_width(self):
        closes = [50 + (i % 5) for i in range(50)]
        u1, m1, l1 = bollinger_bands(closes, 20, 1)
        u2, m2, l2 = bollinger_bands(closes, 20, 2)
        for u_1, l_1, u_2, l_2 in zip(u1[19:], l1[19:], u2[19:], l2[19:]):
            if u_1 is not None:
                assert u_2 >= u_1
                assert l_2 <= l_1


# ─── ATR ──────────────────────────────────────────────────────────────────

class TestATR:
    def test_length_preserved(self):
        candles = make_rising_candles(30)
        result = atr(candles, 14)
        assert len(result) == 30

    def test_positive_values(self):
        candles = make_rising_candles(30)
        result = atr(candles, 14)
        for v in result:
            if v is not None:
                assert v > 0

    def test_too_short_returns_none_list(self):
        candles = make_rising_candles(5)
        result = atr(candles, 14)
        assert all(v is None for v in result)


# ─── MACD ─────────────────────────────────────────────────────────────────

class TestMACD:
    def test_returns_three_lists(self):
        closes = [float(i) for i in range(1, 51)]
        ml, sig, hist = macd(closes)
        assert len(ml) == len(sig) == len(hist) == 50

    def test_histogram_is_diff(self):
        closes = [100 + (i % 20) * 0.5 for i in range(80)]
        ml, sig, hist = macd(closes)
        for m, s, h in zip(ml, sig, hist):
            if m is not None and s is not None and h is not None:
                assert h == pytest.approx(m - s, abs=1e-9)


# ─── OBV ──────────────────────────────────────────────────────────────────

class TestOBV:
    def test_length_preserved(self):
        candles = make_rising_candles(20)
        result = obv(candles)
        assert len(result) == 20

    def test_rising_market_positive_obv(self):
        candles = make_rising_candles(30)
        result = obv(candles)
        assert result[-1] > result[0]

    def test_falling_market_negative_obv(self):
        candles = make_falling_candles(30)
        result = obv(candles)
        assert result[-1] < result[0]

    def test_flat_market_zero_change(self):
        candles = make_flat_candles(10)
        result = obv(candles)
        # All closes equal → no OBV change after first
        assert all(v == result[0] for v in result)


# ─── Donchian Channel ─────────────────────────────────────────────────────

class TestDonchian:
    def test_returns_two_lists(self):
        candles = make_rising_candles(30)
        upper, lower = donchian(candles, 10)
        assert len(upper) == len(lower) == 30

    def test_none_for_warmup(self):
        candles = make_rising_candles(30)
        upper, lower = donchian(candles, 10)
        assert all(v is None for v in upper[:9])
        assert upper[9] is not None

    def test_upper_above_lower(self):
        candles = make_rising_candles(30)
        upper, lower = donchian(candles, 10)
        for u, l in zip(upper, lower):
            if u is not None:
                assert u >= l


# ─── VWAP Ratio ───────────────────────────────────────────────────────────

class TestVWAPRatio:
    def test_length_preserved(self):
        candles = make_flat_candles(30)
        result = vwap_ratio(candles, 10)
        assert len(result) == 30

    def test_flat_price_ratio_near_one(self):
        candles = make_flat_candles(30, price=100.0)
        result = vwap_ratio(candles, 10)
        for v in result[9:]:
            if v is not None:
                assert v == pytest.approx(1.0, abs=0.01)


# ─── evaluate() ───────────────────────────────────────────────────────────

class TestEvaluate:
    def test_empty_trades_returns_error(self):
        result = evaluate([])
        assert "error" in result

    def test_no_closed_trades_returns_error(self):
        t = Trade(entry_time=0, entry_price=100.0)
        result = evaluate([t])
        assert "error" in result

    def test_basic_metrics_present(self):
        trades = [
            closed_trade(100, 110, "long"),
            closed_trade(110, 105, "long"),
            closed_trade(105, 115, "long"),
        ]
        result = evaluate(trades)
        for key in ("total_trades", "wins", "losses", "win_rate",
                    "total_pnl", "roi_pct", "profit_factor", "sharpe_ratio"):
            assert key in result

    def test_win_rate_calculation(self):
        wins = [closed_trade(100, 110, "long") for _ in range(3)]
        losses = [closed_trade(100, 90, "long") for _ in range(1)]
        result = evaluate(wins + losses)
        assert result["total_trades"] == 4
        assert result["wins"] == 3
        assert result["losses"] == 1
        assert result["win_rate"] == pytest.approx(75.0, abs=0.1)

    def test_all_wins_profit_factor_high(self):
        trades = [closed_trade(100, 110, "long") for _ in range(5)]
        result = evaluate(trades)
        assert result["profit_factor"] == 9999  # no losses

    def test_all_losses(self):
        trades = [closed_trade(100, 90, "long") for _ in range(5)]
        result = evaluate(trades)
        assert result["win_rate"] == 0.0
        assert result["total_pnl"] < 0

    def test_single_trade(self):
        trades = [closed_trade(100, 110, "long")]
        result = evaluate(trades)
        assert result["total_trades"] == 1

    def test_roi_positive_on_profit(self):
        trades = [closed_trade(100, 110, "long", size=10) for _ in range(5)]
        result = evaluate(trades, initial_capital=10000)
        assert result["roi_pct"] > 0

    def test_long_short_breakdown(self):
        longs = [closed_trade(100, 110, "long") for _ in range(3)]
        shorts = [closed_trade(100, 90, "short") for _ in range(2)]
        result = evaluate(longs + shorts)
        assert result["long_trades"] == 3
        assert result["short_trades"] == 2

    def test_max_drawdown_with_equity_curve(self):
        equity = [10000, 11000, 10500, 9500, 10200]
        trades = [closed_trade(100, 110, "long") for _ in range(5)]
        result = evaluate(trades, equity_curve=equity)
        assert result["max_drawdown_pct"] > 0

    def test_consecutive_wins_losses(self):
        trades = [
            closed_trade(100, 110, "long"),
            closed_trade(100, 110, "long"),
            closed_trade(100, 110, "long"),
            closed_trade(100, 90, "long"),
            closed_trade(100, 90, "long"),
        ]
        result = evaluate(trades)
        assert result["max_consec_wins"] == 3
        assert result["max_consec_losses"] == 2


# ─── deflated_sharpe() ────────────────────────────────────────────────────

class TestDeflatedSharpe:
    def test_returns_dict_with_required_keys(self):
        result = deflated_sharpe(1.5, 50, n_strategies_tested=10)
        assert "deflated_sharpe" in result
        assert "p_value" in result
        assert "significant" in result
        assert "haircut_pct" in result

    def test_high_sharpe_single_strategy(self):
        result = deflated_sharpe(3.0, 100, n_strategies_tested=1)
        assert result["p_value"] < 0.05
        assert result["significant"] is True

    def test_many_strategies_reduces_significance(self):
        # Same Sharpe with many strategies tested → less significant
        r1 = deflated_sharpe(1.0, 50, n_strategies_tested=1)
        r100 = deflated_sharpe(1.0, 50, n_strategies_tested=100)
        assert r100["p_value"] >= r1["p_value"]

    def test_zero_sharpe(self):
        result = deflated_sharpe(0.0, 50)
        assert result["deflated_sharpe"] <= 0


# ─── monte_carlo() ────────────────────────────────────────────────────────

class TestMonteCarlo:
    def test_too_few_trades_returns_zeros(self):
        result = monte_carlo([closed_trade(100, 110, "long")], n_simulations=10)
        assert result["median_roi"] == 0

    def test_keys_present(self):
        trades = [closed_trade(100, 105 + i, "long") for i in range(10)]
        result = monte_carlo(trades, n_simulations=50)
        for key in ("median_roi", "mean_roi", "worst_roi", "best_roi",
                    "p_profit", "worst_drawdown", "ruin_probability"):
            assert key in result

    def test_all_winning_trades_high_p_profit(self):
        trades = [closed_trade(100, 110, "long") for _ in range(20)]
        result = monte_carlo(trades, n_simulations=100)
        assert result["p_profit"] == pytest.approx(1.0)

    def test_all_losing_trades_zero_p_profit(self):
        trades = [closed_trade(100, 90, "long") for _ in range(20)]
        result = monte_carlo(trades, n_simulations=100)
        assert result["p_profit"] == 0.0


# ─── BacktestEngine ───────────────────────────────────────────────────────

class TestBacktestEngine:
    def _config(self, **kwargs):
        defaults = dict(
            name="Test", symbol="BTCUSDT", interval="4h",
            initial_capital=10000, position_size_pct=10,
            stop_loss_pct=5.0, take_profit_pct=10.0,
            commission_pct=0.04, slippage_pct=0.0,
        )
        defaults.update(kwargs)
        return StrategyConfig(**defaults)

    def test_no_signal_no_trades(self):
        candles = make_rising_candles(300)
        config = self._config()
        engine = BacktestEngine(config)
        trades = engine.run(candles, lambda c, i, ind, ot: [])
        assert trades == []

    def test_single_buy_signal_opens_trade(self):
        candles = make_rising_candles(300)
        config = self._config(stop_loss_pct=0, take_profit_pct=0)
        engine = BacktestEngine(config)

        fired = [False]
        def signal_fn(candles, i, ind, open_trades):
            if i == 210 and not fired[0] and not open_trades:
                fired[0] = True
                return [{"action": "buy"}]
            return []

        trades = engine.run(candles, signal_fn)
        assert len(trades) >= 1
        assert trades[0].side == "long"

    def test_stop_loss_triggers(self):
        # Falling candles → long trade hits stop loss
        closes = [200.0] * 210 + [200.0] + [100.0] * 90  # sharp drop after entry
        candles = make_candles(closes)
        config = self._config(stop_loss_pct=10.0, take_profit_pct=50.0, slippage_pct=0.0)
        engine = BacktestEngine(config)

        fired = [False]
        def signal_fn(candles, i, ind, open_trades):
            if i == 210 and not fired[0] and not open_trades:
                fired[0] = True
                return [{"action": "buy"}]
            return []

        trades = engine.run(candles, signal_fn)
        stopped = [t for t in trades if t.exit_reason == "stop_loss"]
        assert len(stopped) >= 1

    def test_take_profit_triggers(self):
        # Rising candles → long trade hits take profit
        closes = [100.0] * 210 + [100.0] + [200.0] * 90
        candles = make_candles(closes)
        config = self._config(stop_loss_pct=50.0, take_profit_pct=5.0, slippage_pct=0.0)
        engine = BacktestEngine(config)

        fired = [False]
        def signal_fn(candles, i, ind, open_trades):
            if i == 210 and not fired[0] and not open_trades:
                fired[0] = True
                return [{"action": "buy"}]
            return []

        trades = engine.run(candles, signal_fn)
        tps = [t for t in trades if t.exit_reason == "take_profit"]
        assert len(tps) >= 1

    def test_max_hold_bars_timeout(self):
        candles = make_flat_candles(300)
        config = self._config(stop_loss_pct=0, take_profit_pct=0, max_hold_bars=5)
        engine = BacktestEngine(config)

        fired = [False]
        def signal_fn(candles, i, ind, open_trades):
            if i == 210 and not fired[0] and not open_trades:
                fired[0] = True
                return [{"action": "buy"}]
            return []

        trades = engine.run(candles, signal_fn)
        timeouts = [t for t in trades if t.exit_reason == "timeout"]
        assert len(timeouts) >= 1

    def test_max_positions_respected(self):
        candles = make_rising_candles(300)
        config = self._config(max_positions=1, stop_loss_pct=0, take_profit_pct=0)
        engine = BacktestEngine(config)

        def signal_fn(candles, i, ind, open_trades):
            if i >= 210:
                return [{"action": "buy"}]
            return []

        engine.run(candles, signal_fn)
        assert len(engine.open_trades) <= 1

    def test_equity_curve_populated(self):
        candles = make_rising_candles(300)
        config = self._config()
        engine = BacktestEngine(config)
        engine.run(candles, lambda c, i, ind, ot: [])
        assert len(engine.equity_curve) > 0

    def test_fewer_than_warmup_candles(self):
        candles = make_rising_candles(100)  # < warmup=200
        config = self._config()
        engine = BacktestEngine(config)
        trades = engine.run(candles, lambda c, i, ind, ot: [{"action": "buy"}])
        assert trades == []

    def test_short_trade_profits_on_decline(self):
        closes = [200.0] * 210 + [200.0] + [100.0] * 90
        candles = make_candles(closes)
        config = self._config(stop_loss_pct=0, take_profit_pct=0, slippage_pct=0.0)
        engine = BacktestEngine(config)

        fired = [False]
        def signal_fn(candles, i, ind, open_trades):
            if i == 210 and not fired[0] and not open_trades:
                fired[0] = True
                return [{"action": "sell"}]
            return []

        trades = engine.run(candles, signal_fn)
        assert any(t.side == "short" for t in trades)
        short_trades = [t for t in trades if t.side == "short"]
        assert short_trades[0].pnl > 0


# ─── format_report() ──────────────────────────────────────────────────────

class TestFormatReport:
    def test_returns_string(self):
        trades = [closed_trade(100, 110, "long") for _ in range(5)]
        metrics = evaluate(trades)
        report = format_report(metrics)
        assert isinstance(report, str)
        assert len(report) > 0

    def test_includes_key_fields(self):
        trades = [closed_trade(100, 110, "long") for _ in range(5)]
        metrics = evaluate(trades)
        report = format_report(metrics)
        assert "勝率" in report
        assert "ROI" in report
