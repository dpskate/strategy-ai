#!/usr/bin/env python3
"""
Strategy AI - LLM Integration
用戶自然語言 → LLM 生成策略函數 → 回測 → 評估 → 優化建議 → 迭代
"""
import json, os, sys, traceback, textwrap
from datetime import datetime, timezone, timedelta
from backtest_engine import (
    BacktestEngine, StrategyConfig, evaluate, format_report,
    fetch_candles_extended, Candle,
    ema, sma, rsi, bollinger_bands, atr, macd,
    obv, stoch_rsi, donchian, vwap_ratio
)
from optimizer import (
    StrategyOptimizer, walk_forward,
    make_ema_cross_strategy, make_rsi_strategy,
    make_bb_strategy, make_trend_rsi_strategy, make_macd_strategy
)

WORK = os.path.dirname(os.path.abspath(__file__))
TZ8 = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════
# LLM STRATEGY PROMPT
# ═══════════════════════════════════════════════════

SYSTEM_PROMPT = """你是一個量化策略代碼生成器。用戶會用自然語言描述交易策略，你需要生成一個 Python 函數。

## 函數簽名（必須完全一致）
```python
def strategy(candles, i, indicators, open_trades):
    # candles: List[Candle] - 所有 K 線，Candle 有 .time, .open, .high, .low, .close, .volume, .bullish, .bearish, .body, .range
    # i: int - 當前 K 線索引
    # indicators: dict - 預計算指標（不用，自己算更靈活）
    # open_trades: list - 當前持倉，每個有 .side ("long"/"short"), .entry_price
    # return: list of dicts - [{"action": "buy"/"sell"/"close", "sl": float, "tp": float}]
```

## 可用指標函數（已 import，直接用）
- `ema(data, period)` → list[float|None]
- `sma(data, period)` → list[float|None]
- `rsi(closes, period=14)` → list[float|None]
- `bollinger_bands(closes, period=20, std_mult=2)` → (upper, middle, lower)
- `atr(candles, period=14)` → list[float|None]
- `macd(closes, fast=12, slow=26, signal=9)` → (macd_line, signal_line, histogram)

## 規則
1. 只輸出函數代碼，不要其他文字
2. 函數名必須是 `strategy`
3. 開頭先算 closes: `closes = [c.close for c in candles[:i+1]]`
4. 檢查數據長度：`if len(closes) < 需要的最小長度: return []`
5. 檢查指標值不是 None 再用
6. 用 candles[:i+1] 取歷史數據，不要用未來數據（look-ahead bias）
7. 返回 actions 列表，每個 action 是 dict
8. 可以在 action 裡指定 sl（止損價）和 tp（止盈價），不指定就用 config 預設
9. 做多用 "buy"，做空用 "sell"，平倉用 "close"
10. 不要 import 任何東西，所有指標函數已經可用
"""

def build_prompt(user_input):
    """Build the prompt for LLM"""
    return f"""{SYSTEM_PROMPT}

## 用戶策略描述
{user_input}

## 生成代碼
```python
"""


# ═══════════════════════════════════════════════════
# CODE EXTRACTION & EXECUTION
# ═══════════════════════════════════════════════════

def extract_code(llm_response):
    """Extract Python code from LLM response"""
    # Try to find code block
    if "```python" in llm_response:
        code = llm_response.split("```python")[1].split("```")[0].strip()
    elif "```" in llm_response:
        code = llm_response.split("```")[1].split("```")[0].strip()
    elif "def strategy" in llm_response:
        # Find the function definition
        lines = llm_response.split("\n")
        start = None
        for idx, line in enumerate(lines):
            if line.strip().startswith("def strategy"):
                start = idx
                break
        if start is not None:
            code = "\n".join(lines[start:])
        else:
            code = llm_response
    else:
        code = llm_response

    # Ensure it starts with def strategy
    if not code.strip().startswith("def strategy"):
        code = "def strategy(candles, i, indicators, open_trades):\n" + code

    return code


def compile_strategy(code):
    """Compile strategy code into callable function"""
    from derivatives_data import lookup_nearest as _lookup_nearest_fn
    # Create execution namespace with available functions
    namespace = {
        "ema": ema, "sma": sma, "rsi": rsi,
        "bollinger_bands": bollinger_bands, "atr": atr, "macd": macd,
        "obv": obv, "stoch_rsi": stoch_rsi, "donchian": donchian, "vwap_ratio": vwap_ratio,
        "_lookup_nearest": _lookup_nearest_fn,
    }

    try:
        exec(code, namespace)
        if "strategy" not in namespace:
            return None, "函數名必須是 'strategy'"
        return namespace["strategy"], None
    except SyntaxError as e:
        return None, f"語法錯誤: {e}"
    except Exception as e:
        return None, f"編譯錯誤: {e}"


def validate_strategy(strategy_fn, candles, n_bars=50):
    """Quick validation: run on a few bars to check for runtime errors"""
    try:
        for i in range(min(250, len(candles) - 1), min(250 + n_bars, len(candles))):
            result = strategy_fn(candles, i, {}, [])
            if not isinstance(result, list):
                return False, f"返回值必須是 list，得到 {type(result)}"
        return True, None
    except Exception as e:
        return False, f"運行錯誤: {e}\n{traceback.format_exc()}"


# ═══════════════════════════════════════════════════
# FULL PIPELINE
# ═══════════════════════════════════════════════════

def run_pipeline(strategy_code, config=None, candles=None, symbol="BTCUSDT", interval="4h", n_candles=2000):
    """
    Full pipeline: code → compile → validate → backtest → evaluate → report
    Returns (report_text, metrics, trades) or (error_text, None, None)
    """
    if config is None:
        config = StrategyConfig(
            name="LLM Strategy",
            symbol=symbol, interval=interval,
            initial_capital=10000, position_size_pct=10,
            stop_loss_pct=2, take_profit_pct=4,
        )

    # Compile
    strategy_fn, err = compile_strategy(strategy_code)
    if err:
        return f"❌ 編譯失敗: {err}", None, None

    # Fetch data if needed
    if candles is None:
        print("拉取歷史數據...")
        candles = fetch_candles_extended(symbol, interval, n_candles)
        print(f"  {len(candles)} 根 {interval} K 線")

    # Validate
    ok, err = validate_strategy(strategy_fn, candles)
    if not ok:
        return f"❌ 驗證失敗: {err}", None, None

    # Backtest
    print("回測中...")
    engine = BacktestEngine(config)
    trades = engine.run(candles, strategy_fn)
    metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

    if "error" in metrics:
        return f"❌ 回測失敗: {metrics['error']}", None, None

    # Walk-forward
    print("Walk-forward 驗證...")
    wf = walk_forward(candles, strategy_fn, config)

    # Report
    report = format_report(metrics, config)
    report += f"\n\n  ═══ Walk-Forward ═══"
    report += f"\n  訓練集 ROI: {wf['train'].get('roi_pct', 0)}%"
    report += f"\n  測試集 ROI: {wf['test'].get('roi_pct', 0)}%"
    report += f"\n  過擬合比: {wf['overfit_ratio']:.2f}"

    # Quality assessment
    report += "\n\n  ═══ 品質評估 ═══"
    issues = []
    if metrics["total_trades"] < 20:
        issues.append("⚠️ 交易次數太少，統計不可靠")
    if metrics["win_rate"] < 30:
        issues.append("⚠️ 勝率偏低")
    if metrics["max_drawdown_pct"] > 15:
        issues.append("⚠️ 最大回撤過大")
    if metrics["profit_factor"] < 1:
        issues.append("❌ 利潤因子 < 1，策略虧損")
    if wf["overfit_ratio"] > 3:
        issues.append("⚠️ 過擬合風險高（訓練/測試差距大）")
    if metrics["sharpe_ratio"] < 1:
        issues.append("⚠️ 夏普比率偏低")

    if not issues:
        report += "\n  ✅ 策略品質良好"
    else:
        for issue in issues:
            report += f"\n  {issue}"

    return report, metrics, trades


def generate_optimization_advice(metrics, wf_result=None):
    """Generate optimization suggestions based on metrics"""
    advice = []

    if metrics["win_rate"] < 35:
        advice.append("勝率低 → 考慮加入趨勢濾網（如 EMA200 方向過濾），只順勢交易")
    if metrics["avg_rr"] < 1.5:
        advice.append("盈虧比低 → 擴大止盈或縮小止損，目標 RR > 2")
    if metrics["max_drawdown_pct"] > 10:
        advice.append("回撤大 → 減小倉位比例，或加入波動率過濾（ATR 過大時不開倉）")
    if metrics["profit_factor"] < 1.2:
        advice.append("利潤因子低 → 策略邊際效益差，考慮加入成交量確認或多指標交叉驗證")
    if metrics["total_trades"] < 20:
        advice.append("交易太少 → 放寬入場條件，或縮短 K 線週期")
    if metrics["total_trades"] > 200:
        advice.append("交易太頻繁 → 加入冷卻期或更嚴格的入場條件，減少手續費損耗")

    if wf_result and wf_result.get("overfit_ratio", 1) > 2:
        advice.append("過擬合風險 → 減少參數數量，使用更簡單的邏輯，或增加訓練數據")

    if not advice:
        advice.append("策略表現不錯，可以嘗試微調止損止盈比例")

    return advice


# ═══════════════════════════════════════════════════
# PRESET STRATEGIES (for quick testing)
# ═══════════════════════════════════════════════════

PRESETS = {
    "均線交叉": '''def strategy(candles, i, indicators, open_trades):
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < 50:
        return []
    actions = []
    ema_f = ema(closes, 9)
    ema_s = ema(closes, 21)
    if ema_f[i] is None or ema_s[i] is None or ema_f[i-1] is None or ema_s[i-1] is None:
        return []
    if ema_f[i-1] <= ema_s[i-1] and ema_f[i] > ema_s[i] and not open_trades:
        actions.append({"action": "buy"})
    if ema_f[i-1] >= ema_s[i-1] and ema_f[i] < ema_s[i] and not open_trades:
        actions.append({"action": "sell"})
    if open_trades:
        t = open_trades[0]
        if t.side == "long" and ema_f[i] < ema_s[i]:
            actions.append({"action": "close"})
        elif t.side == "short" and ema_f[i] > ema_s[i]:
            actions.append({"action": "close"})
    return actions
''',

    "RSI布林": '''def strategy(candles, i, indicators, open_trades):
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < 30:
        return []
    actions = []
    rsi_vals = rsi(closes, 14)
    bb_u, bb_m, bb_l = bollinger_bands(closes, 20, 2)
    ri = len(rsi_vals) - 1
    bi = len(bb_l) - 1
    if ri < 0 or bi < 0 or rsi_vals[ri] is None or bb_l[bi] is None:
        return []
    price = closes[-1]
    if rsi_vals[ri] < 30 and price < bb_l[bi] and not open_trades:
        actions.append({"action": "buy"})
    if rsi_vals[ri] > 70 and price > bb_u[bi] and not open_trades:
        actions.append({"action": "sell"})
    if open_trades:
        t = open_trades[0]
        if t.side == "long" and price > bb_m[bi]:
            actions.append({"action": "close"})
        elif t.side == "short" and price < bb_m[bi]:
            actions.append({"action": "close"})
    return actions
''',

    "趨勢回調": '''def strategy(candles, i, indicators, open_trades):
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < 210:
        return []
    actions = []
    ema_200 = ema(closes, 200)
    rsi_vals = rsi(closes, 14)
    atr_vals = atr(candles[:i+1], 14)
    ei = len(ema_200) - 1
    ri = len(rsi_vals) - 1
    ai = len(atr_vals) - 1
    if ema_200[ei] is None or rsi_vals[ri] is None or atr_vals[ai] is None:
        return []
    price = closes[-1]
    if price > ema_200[ei] and rsi_vals[ri] < 40 and not open_trades:
        sl = price - 2 * atr_vals[ai]
        tp = price + 3 * atr_vals[ai]
        actions.append({"action": "buy", "sl": sl, "tp": tp})
    if price < ema_200[ei] and rsi_vals[ri] > 60 and not open_trades:
        sl = price + 2 * atr_vals[ai]
        tp = price - 3 * atr_vals[ai]
        actions.append({"action": "sell", "sl": sl, "tp": tp})
    return actions
''',

    "MACD動能": '''def strategy(candles, i, indicators, open_trades):
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < 50:
        return []
    actions = []
    macd_l, macd_s, macd_h = macd(closes, 12, 26, 9)
    ema_50 = ema(closes, 50)
    if macd_l[i] is None or macd_s[i] is None or ema_50[i] is None:
        return []
    if macd_l[i-1] is None or macd_s[i-1] is None:
        return []
    price = closes[i]
    # MACD golden cross + above EMA50 = strong buy
    if macd_l[i-1] <= macd_s[i-1] and macd_l[i] > macd_s[i] and price > ema_50[i] and not open_trades:
        actions.append({"action": "buy"})
    # MACD death cross + below EMA50 = strong sell
    if macd_l[i-1] >= macd_s[i-1] and macd_l[i] < macd_s[i] and price < ema_50[i] and not open_trades:
        actions.append({"action": "sell"})
    # Exit on opposite cross
    if open_trades:
        t = open_trades[0]
        if t.side == "long" and macd_l[i-1] >= macd_s[i-1] and macd_l[i] < macd_s[i]:
            actions.append({"action": "close"})
        elif t.side == "short" and macd_l[i-1] <= macd_s[i-1] and macd_l[i] > macd_s[i]:
            actions.append({"action": "close"})
    return actions
''',
}


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("🤖 Strategy AI - LLM Pipeline")
    print("拉取數據...")

    candles = fetch_candles_extended("BTCUSDT", "4h", 2000)
    start = datetime.fromtimestamp(candles[0].time / 1000, TZ8)
    end = datetime.fromtimestamp(candles[-1].time / 1000, TZ8)
    print(f"  {len(candles)} 根 4h K 線 | {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")

    # Run all presets
    for name, code in PRESETS.items():
        print(f"\n{'='*60}")
        print(f"  策略: {name}")
        print(f"{'='*60}")
        report, metrics, trades = run_pipeline(code, candles=candles)
        print(report)

        if metrics:
            advice = generate_optimization_advice(metrics)
            print("\n  ═══ 優化建議 ═══")
            for a in advice:
                print(f"  💡 {a}")

    print("\n✅ LLM Pipeline 就緒")
