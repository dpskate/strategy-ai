#!/usr/bin/env python3
"""
Strategy AI - Optimizer
AI 自動迭代優化策略：調參數、加濾網、改止損邏輯
"""
import json, os, copy, random, math
from datetime import datetime, timezone, timedelta
from backtest_engine import (
    BacktestEngine, StrategyConfig, evaluate, format_report,
    fetch_candles_extended, Candle,
    ema, sma, rsi, bollinger_bands, atr, macd
)

WORK = os.path.dirname(os.path.abspath(__file__))
TZ8 = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════
# PARAMETER SPACE
# ═══════════════════════════════════════════════════

PARAM_RANGES = {
    "ema_fast": [5, 7, 9, 12, 15],
    "ema_slow": [15, 21, 26, 30, 50],
    "rsi_period": [7, 10, 14, 21],
    "rsi_oversold": [20, 25, 30, 35],
    "rsi_overbought": [65, 70, 75, 80],
    "bb_period": [15, 20, 25, 30],
    "bb_std": [1.5, 2.0, 2.5, 3.0],
    "atr_period": [10, 14, 20],
    "stop_loss_pct": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
    "take_profit_pct": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
    "position_size_pct": [5, 10, 15, 20],
    "max_hold_bars": [0, 12, 24, 48, 72],
}


# ═══════════════════════════════════════════════════
# BUILT-IN STRATEGIES (parameterized)
# ═══════════════════════════════════════════════════

def make_ema_cross_strategy(fast=9, slow=21):
    """EMA crossover with configurable periods"""
    def strategy(candles, i, indicators, open_trades):
        actions = []
        closes = [c.close for c in candles[:i+1]]
        if len(closes) < slow + 10:
            return actions
        ema_f = ema(closes, fast)
        ema_s = ema(closes, slow)
        if ema_f[i] is None or ema_s[i] is None or ema_f[i-1] is None or ema_s[i-1] is None:
            return actions
        if ema_f[i-1] <= ema_s[i-1] and ema_f[i] > ema_s[i]:
            if not open_trades:
                actions.append({"action": "buy"})
            elif open_trades and open_trades[0].side == "short":
                actions.append({"action": "close"})
                actions.append({"action": "buy"})
        if ema_f[i-1] >= ema_s[i-1] and ema_f[i] < ema_s[i]:
            if not open_trades:
                actions.append({"action": "sell"})
            elif open_trades and open_trades[0].side == "long":
                actions.append({"action": "close"})
                actions.append({"action": "sell"})
        return actions
    strategy.__name__ = f"ema_{fast}_{slow}_cross"
    return strategy


def make_rsi_strategy(period=14, oversold=30, overbought=70):
    """RSI reversal with configurable levels"""
    def strategy(candles, i, indicators, open_trades):
        actions = []
        closes = [c.close for c in candles[:i+1]]
        if len(closes) < period + 10:
            return actions
        rsi_vals = rsi(closes, period)
        if i >= len(rsi_vals) or rsi_vals[i] is None or rsi_vals[i-1] is None:
            return actions
        if rsi_vals[i-1] <= oversold and rsi_vals[i] > oversold and not open_trades:
            actions.append({"action": "buy"})
        if rsi_vals[i-1] >= overbought and rsi_vals[i] < overbought and not open_trades:
            actions.append({"action": "sell"})
        if open_trades:
            t = open_trades[0]
            if t.side == "long" and rsi_vals[i] > overbought - 5:
                actions.append({"action": "close"})
            elif t.side == "short" and rsi_vals[i] < oversold + 5:
                actions.append({"action": "close"})
        return actions
    strategy.__name__ = f"rsi_{period}_{oversold}_{overbought}"
    return strategy


def make_bb_strategy(period=20, std_mult=2):
    """Bollinger Band mean reversion"""
    def strategy(candles, i, indicators, open_trades):
        actions = []
        closes = [c.close for c in candles[:i+1]]
        if len(closes) < period + 10:
            return actions
        bb_u, bb_m, bb_l = bollinger_bands(closes, period, std_mult)
        if bb_u[i] is None or bb_l[i] is None:
            return actions
        if closes[i] < bb_l[i] and not open_trades:
            actions.append({"action": "buy"})
        if closes[i] > bb_u[i] and not open_trades:
            actions.append({"action": "sell"})
        if open_trades:
            t = open_trades[0]
            if t.side == "long" and closes[i] > bb_m[i]:
                actions.append({"action": "close"})
            elif t.side == "short" and closes[i] < bb_m[i]:
                actions.append({"action": "close"})
        return actions
    strategy.__name__ = f"bb_{period}_{std_mult}"
    return strategy


def make_trend_rsi_strategy(trend_ema=200, rsi_period=14, rsi_entry=40, rsi_exit=60):
    """Trend following: EMA for direction + RSI for entry timing"""
    def strategy(candles, i, indicators, open_trades):
        actions = []
        closes = [c.close for c in candles[:i+1]]
        if len(closes) < trend_ema + 10:
            return actions
        ema_trend = ema(closes, trend_ema)
        rsi_vals = rsi(closes, rsi_period)
        if ema_trend[i] is None or i >= len(rsi_vals) or rsi_vals[i] is None:
            return actions
        # Uptrend: price above EMA, buy on RSI dip
        if closes[i] > ema_trend[i]:
            if rsi_vals[i] < rsi_entry and not open_trades:
                actions.append({"action": "buy"})
            if open_trades and open_trades[0].side == "long" and rsi_vals[i] > rsi_exit:
                actions.append({"action": "close"})
        # Downtrend: price below EMA, sell on RSI spike
        if closes[i] < ema_trend[i]:
            if rsi_vals[i] > 100 - rsi_entry and not open_trades:
                actions.append({"action": "sell"})
            if open_trades and open_trades[0].side == "short" and rsi_vals[i] < 100 - rsi_exit:
                actions.append({"action": "close"})
        return actions
    strategy.__name__ = f"trend_ema{trend_ema}_rsi{rsi_period}"
    return strategy


def make_macd_strategy(fast=12, slow=26, signal=9):
    """MACD crossover"""
    def strategy(candles, i, indicators, open_trades):
        actions = []
        closes = [c.close for c in candles[:i+1]]
        if len(closes) < slow + signal + 10:
            return actions
        macd_l, macd_s, macd_h = macd(closes, fast, slow, signal)
        if macd_l[i] is None or macd_s[i] is None or macd_l[i-1] is None or macd_s[i-1] is None:
            return actions
        if macd_l[i-1] <= macd_s[i-1] and macd_l[i] > macd_s[i]:
            if not open_trades:
                actions.append({"action": "buy"})
            elif open_trades[0].side == "short":
                actions.append({"action": "close"})
                actions.append({"action": "buy"})
        if macd_l[i-1] >= macd_s[i-1] and macd_l[i] < macd_s[i]:
            if not open_trades:
                actions.append({"action": "sell"})
            elif open_trades[0].side == "long":
                actions.append({"action": "close"})
                actions.append({"action": "sell"})
        return actions
    strategy.__name__ = f"macd_{fast}_{slow}_{signal}"
    return strategy


# ═══════════════════════════════════════════════════
# OPTIMIZER
# ═══════════════════════════════════════════════════

class StrategyOptimizer:
    def __init__(self, candles, initial_capital=10000):
        self.candles = candles
        self.initial_capital = initial_capital
        self.results = []

    def grid_search(self, strategy_factory, param_grid, base_config=None):
        """
        Grid search over parameter combinations.
        strategy_factory: function(params) -> strategy_fn
        param_grid: dict of param_name -> [values]
        """
        if base_config is None:
            base_config = StrategyConfig(initial_capital=self.initial_capital)

        # Generate all combinations
        keys = list(param_grid.keys())
        combos = [{}]
        for key in keys:
            new_combos = []
            for combo in combos:
                for val in param_grid[key]:
                    c = combo.copy()
                    c[key] = val
                    new_combos.append(c)
            combos = new_combos

        print(f"  測試 {len(combos)} 個參數組合...")
        results = []

        for i, params in enumerate(combos):
            config = copy.deepcopy(base_config)
            # Apply config-level params
            for k in ["stop_loss_pct", "take_profit_pct", "position_size_pct", "max_hold_bars"]:
                if k in params:
                    setattr(config, k, params[k])

            strategy_fn = strategy_factory(params)
            engine = BacktestEngine(config)
            trades = engine.run(self.candles, strategy_fn)
            metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

            if "error" not in metrics:
                results.append({
                    "params": params,
                    "metrics": metrics,
                    "config": config,
                })

            if (i + 1) % 50 == 0:
                print(f"    {i+1}/{len(combos)} 完成")

        # Sort by composite score
        for r in results:
            r["score"] = self._score(r["metrics"])
        results.sort(key=lambda x: -x["score"])

        self.results = results
        return results

    def random_search(self, strategy_factory, param_ranges, n_trials=100, base_config=None):
        """Random search with n_trials random parameter combinations"""
        if base_config is None:
            base_config = StrategyConfig(initial_capital=self.initial_capital)

        print(f"  隨機搜索 {n_trials} 次...")
        results = []

        for i in range(n_trials):
            params = {k: random.choice(v) for k, v in param_ranges.items()}
            config = copy.deepcopy(base_config)
            for k in ["stop_loss_pct", "take_profit_pct", "position_size_pct", "max_hold_bars"]:
                if k in params:
                    setattr(config, k, params[k])

            strategy_fn = strategy_factory(params)
            engine = BacktestEngine(config)
            trades = engine.run(self.candles, strategy_fn)
            metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

            if "error" not in metrics:
                results.append({
                    "params": params,
                    "metrics": metrics,
                    "config": config,
                })

            if (i + 1) % 25 == 0:
                print(f"    {i+1}/{n_trials} 完成")

        for r in results:
            r["score"] = self._score(r["metrics"])
        results.sort(key=lambda x: -x["score"])

        self.results = results
        return results

    def _score(self, metrics):
        """
        Composite score for ranking strategies.
        Balances profitability, risk, and consistency.
        """
        if metrics.get("total_trades", 0) < 10:
            return -999  # Not enough trades

        roi = metrics.get("roi_pct", 0)
        sharpe = metrics.get("sharpe_ratio", 0)
        sortino = metrics.get("sortino_ratio", 0)
        win_rate = metrics.get("win_rate", 0)
        profit_factor = metrics.get("profit_factor", 0)
        max_dd = metrics.get("max_drawdown_pct", 100)
        avg_rr = metrics.get("avg_rr", 0)

        # Penalize high drawdown
        dd_penalty = max(0, max_dd - 10) * 2

        score = (
            roi * 0.3 +
            sharpe * 5 +
            sortino * 3 +
            profit_factor * 10 +
            avg_rr * 5 +
            win_rate * 0.2 -
            dd_penalty
        )
        return round(score, 2)

    def report_top(self, n=5):
        """Print top N results"""
        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"  🏆 Top {n} 策略參數組合")
        lines.append(f"{'='*60}")

        for i, r in enumerate(self.results[:n]):
            m = r["metrics"]
            lines.append(f"\n  #{i+1} | Score: {r['score']:.1f}")
            lines.append(f"  參數: {r['params']}")
            lines.append(f"  交易: {m['total_trades']} | 勝率: {m['win_rate']}% | 盈虧比: {m['avg_rr']}")
            lines.append(f"  ROI: {m['roi_pct']}% | PF: {m['profit_factor']} | Sharpe: {m['sharpe_ratio']}")
            lines.append(f"  回撤: {m['max_drawdown_pct']}% | ${m['initial_capital']:,.0f} → ${m['final_capital']:,.2f}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════
# WALK-FORWARD VALIDATION
# ═══════════════════════════════════════════════════

def rolling_walk_forward(candles, strategy_fn, config, n_splits=5, train_ratio=0.7, extra_indicators=None):
    """
    滾動窗口 walk-forward 驗證。
    把數據分成 n_splits 個重疊窗口，每個窗口內做 train/test 切割。
    """
    L = len(candles)
    window_size = int(L * 0.6)
    if window_size < 400 or n_splits < 2:
        # 數據太少，退化成單次
        wf = walk_forward(candles, strategy_fn, config, train_ratio, extra_indicators)
        train_roi = wf["train"].get("roi_pct", 0)
        test_roi = wf["test"].get("roi_pct", 0)
        train_sharpe = wf["train"].get("sharpe_ratio", 0)
        test_sharpe = wf["test"].get("sharpe_ratio", 0)
        overfit = wf["overfit_ratio"]
        split_data = {
            "split": 1,
            "train_start": candles[0].time,
            "train_end": candles[int(L * train_ratio) - 1].time,
            "test_start": candles[int(L * train_ratio)].time,
            "test_end": candles[-1].time,
            "train_roi": train_roi,
            "test_roi": test_roi,
            "train_sharpe": train_sharpe,
            "test_sharpe": test_sharpe,
            "train_trades": wf["train"].get("total_trades", 0),
            "test_trades": wf["test"].get("total_trades", 0),
            "overfit_ratio": overfit,
        }
        profitable = 1 if test_roi > 0 else 0
        return {
            "splits": [split_data],
            "avg_test_roi": test_roi,
            "avg_overfit_ratio": overfit,
            "consistency": float(profitable),
            "worst_test_roi": test_roi,
            "best_test_roi": test_roi,
            "robust": test_roi > 0,
        }

    splits = []
    for idx in range(n_splits):
        start_i = int(idx * (L - window_size) / (n_splits - 1))
        end_i = start_i + window_size
        window = candles[start_i:end_i]

        split_pt = int(len(window) * train_ratio)
        train_candles = window[:split_pt]
        test_candles = window[split_pt:]

        cfg_train = copy.deepcopy(config)
        engine_train = BacktestEngine(cfg_train)
        trades_train = engine_train.run(train_candles, strategy_fn, extra_indicators=extra_indicators)
        m_train = evaluate(trades_train, config.initial_capital, engine_train.equity_curve)

        cfg_test = copy.deepcopy(config)
        engine_test = BacktestEngine(cfg_test)
        trades_test = engine_test.run(test_candles, strategy_fn, extra_indicators=extra_indicators)
        m_test = evaluate(trades_test, config.initial_capital, engine_test.equity_curve)

        tr_roi = m_train.get("roi_pct", 0)
        te_roi = m_test.get("roi_pct", 0)
        if tr_roi <= 0 or te_roi <= 0:
            overfit = 999.0 if tr_roi > 0 else 0.0
        else:
            overfit = round(tr_roi / te_roi, 2)

        splits.append({
            "split": idx + 1,
            "train_start": train_candles[0].time,
            "train_end": train_candles[-1].time,
            "test_start": test_candles[0].time,
            "test_end": test_candles[-1].time,
            "train_roi": tr_roi,
            "test_roi": te_roi,
            "train_sharpe": m_train.get("sharpe_ratio", 0),
            "test_sharpe": m_test.get("sharpe_ratio", 0),
            "train_trades": m_train.get("total_trades", 0),
            "test_trades": m_test.get("total_trades", 0),
            "overfit_ratio": overfit,
        })

    test_rois = [s["test_roi"] for s in splits]
    overfit_ratios = [s["overfit_ratio"] for s in splits]
    profitable_count = sum(1 for r in test_rois if r > 0)
    consistency = profitable_count / len(splits) if splits else 0
    avg_test = sum(test_rois) / len(test_rois) if test_rois else 0
    avg_of = sum(overfit_ratios) / len(overfit_ratios) if overfit_ratios else 0

    return {
        "splits": splits,
        "avg_test_roi": round(avg_test, 2),
        "avg_overfit_ratio": round(avg_of, 2),
        "consistency": round(consistency, 2),
        "worst_test_roi": round(min(test_rois), 2) if test_rois else 0,
        "best_test_roi": round(max(test_rois), 2) if test_rois else 0,
        "robust": consistency >= 0.6 and avg_test > 0,
    }


def walk_forward(candles, strategy_fn, config, train_pct=0.7, extra_indicators=None):
    """
    Walk-forward validation: train on first 70%, test on last 30%.
    Prevents overfitting.
    """
    split = int(len(candles) * train_pct)
    train_candles = candles[:split]
    test_candles = candles[split:]

    # Train
    engine_train = BacktestEngine(copy.deepcopy(config))
    trades_train = engine_train.run(train_candles, strategy_fn, extra_indicators=extra_indicators)
    metrics_train = evaluate(trades_train, config.initial_capital, engine_train.equity_curve)

    # Test
    engine_test = BacktestEngine(copy.deepcopy(config))
    trades_test = engine_test.run(test_candles, strategy_fn, extra_indicators=extra_indicators)
    metrics_test = evaluate(trades_test, config.initial_capital, engine_test.equity_curve)

    train_roi = metrics_train.get("roi_pct", 0)
    test_roi = metrics_test.get("roi_pct", 0)

    # Overfit ratio logic:
    # - Both positive: train/test, closer to 1 = good
    # - Train positive, test negative/zero: bad, cap at 999
    # - Train negative: strategy sucks anyway, ratio = 999
    if train_roi <= 0 or test_roi <= 0:
        overfit = 999.0 if train_roi > 0 else 0.0
    else:
        overfit = round(train_roi / test_roi, 2)

    return {
        "train": metrics_train,
        "test": metrics_test,
        "overfit_ratio": overfit,
    }


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("🧪 Strategy AI - Optimizer")
    print("拉取歷史數據...")

    candles = fetch_candles_extended("BTCUSDT", "4h", 2000)
    print(f"  {len(candles)} 根 4h K 線")

    optimizer = StrategyOptimizer(candles)

    # Optimize EMA crossover
    print("\n═══ 優化 EMA Crossover ═══")
    def ema_factory(params):
        return make_ema_cross_strategy(params["ema_fast"], params["ema_slow"])

    ema_grid = {
        "ema_fast": [7, 9, 12],
        "ema_slow": [21, 30, 50],
        "stop_loss_pct": [2, 3],
        "take_profit_pct": [4, 6],
    }
    results = optimizer.grid_search(ema_factory, ema_grid)
    print(optimizer.report_top(3))

    # Optimize RSI
    print("\n═══ 優化 RSI Reversal ═══")
    def rsi_factory(params):
        return make_rsi_strategy(params["rsi_period"], params["rsi_oversold"], params["rsi_overbought"])

    rsi_grid = {
        "rsi_period": [10, 14],
        "rsi_oversold": [25, 30],
        "rsi_overbought": [70, 75],
        "stop_loss_pct": [2, 3],
        "take_profit_pct": [4, 6],
    }
    results = optimizer.grid_search(rsi_factory, rsi_grid)
    print(optimizer.report_top(3))

    # Walk-forward on best
    if optimizer.results:
        best = optimizer.results[0]
        print("\n═══ Walk-Forward 驗證（最佳參數）═══")
        best_fn = rsi_factory(best["params"])
        wf = walk_forward(candles, best_fn, best["config"])
        print(f"  訓練集 ROI: {wf['train'].get('roi_pct', 0)}%")
        print(f"  測試集 ROI: {wf['test'].get('roi_pct', 0)}%")
        print(f"  過擬合比: {wf['overfit_ratio']:.2f} (越接近 1 越好)")

    print("\n✅ 優化器就緒")
