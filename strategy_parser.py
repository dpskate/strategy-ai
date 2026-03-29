#!/usr/bin/env python3
"""
Strategy AI - Strategy Parser & Code Generator
自然語言 → 結構化策略定義 → 可執行回測代碼
"""
import json, os, re

WORK = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════════════
# STRATEGY SCHEMA
# ═══════════════════════════════════════════════════

STRATEGY_SCHEMA = {
    "name": "str",
    "description": "str",
    "symbol": "str",           # BTCUSDT, ETHUSDT...
    "interval": "str",         # 1m, 5m, 15m, 1h, 4h, 1d
    "initial_capital": "float",
    "position_size_pct": "float",
    "stop_loss_pct": "float",
    "take_profit_pct": "float",
    "max_positions": "int",
    "max_hold_bars": "int",
    "entry_conditions": [
        {
            "indicator": "str",    # ema, sma, rsi, macd, bb, atr, price, volume
            "params": "dict",      # {"period": 14} etc
            "operator": "str",     # crosses_above, crosses_below, above, below, between
            "value": "any",        # number, indicator ref, or [min, max]
        }
    ],
    "exit_conditions": [
        {
            "indicator": "str",
            "params": "dict",
            "operator": "str",
            "value": "any",
        }
    ],
    "side": "str",             # long, short, both
    "filters": [               # additional filters
        {
            "indicator": "str",
            "operator": "str",
            "value": "any",
        }
    ],
}

# ═══════════════════════════════════════════════════
# INDICATOR REGISTRY
# ═══════════════════════════════════════════════════

INDICATORS = {
    "ema": {"params": ["period"], "defaults": {"period": 21}},
    "sma": {"params": ["period"], "defaults": {"period": 20}},
    "rsi": {"params": ["period"], "defaults": {"period": 14}},
    "macd": {"params": ["fast", "slow", "signal"], "defaults": {"fast": 12, "slow": 26, "signal": 9}},
    "bb": {"params": ["period", "std"], "defaults": {"period": 20, "std": 2}},
    "atr": {"params": ["period"], "defaults": {"period": 14}},
    "volume": {"params": ["period"], "defaults": {"period": 20}},
}

OPERATORS = {
    "crosses_above": "前一根 <= 目標，當前 > 目標",
    "crosses_below": "前一根 >= 目標，當前 < 目標",
    "above": "當前 > 目標",
    "below": "當前 < 目標",
    "between": "在範圍內",
    "increases": "連續上升",
    "decreases": "連續下降",
}


# ═══════════════════════════════════════════════════
# NATURAL LANGUAGE PARSER
# ═══════════════════════════════════════════════════

def parse_natural_language(text):
    """
    Parse natural language strategy description into structured definition.
    Returns a strategy dict that can be used to generate code.
    
    This is a rule-based parser for common patterns.
    For production, this would be replaced by LLM parsing.
    """
    text_lower = text.lower()
    strategy = {
        "name": "",
        "description": text,
        "symbol": "BTCUSDT",
        "interval": "4h",
        "initial_capital": 10000,
        "position_size_pct": 10,
        "stop_loss_pct": 2,
        "take_profit_pct": 4,
        "max_positions": 1,
        "max_hold_bars": 0,
        "entry_conditions": [],
        "exit_conditions": [],
        "side": "both",
        "filters": [],
    }

    # Detect symbol
    for sym in ["ETHUSDT", "BTCUSDT", "SOLUSDT", "BNBUSDT"]:
        if sym.lower() in text_lower or sym[:3].lower() in text_lower:
            strategy["symbol"] = sym

    # Detect interval
    interval_map = {"1分": "1m", "5分": "5m", "15分": "15m", "1小時": "1h", "4小時": "4h",
                    "日線": "1d", "1h": "1h", "4h": "4h", "1d": "1d", "15m": "15m", "5m": "5m", "1m": "1m"}
    for k, v in interval_map.items():
        if k in text_lower:
            strategy["interval"] = v

    # Detect side
    if "做多" in text_lower or "買入" in text_lower or "long" in text_lower:
        if "做空" not in text_lower and "short" not in text_lower:
            strategy["side"] = "long"
    if "做空" in text_lower or "賣出" in text_lower or "short" in text_lower:
        if "做多" not in text_lower and "long" not in text_lower:
            strategy["side"] = "short"

    # Detect stop loss / take profit
    sl_match = re.search(r'止損[：:\s]*(\d+(?:\.\d+)?)\s*%', text)
    if sl_match:
        strategy["stop_loss_pct"] = float(sl_match.group(1))
    tp_match = re.search(r'止盈[：:\s]*(\d+(?:\.\d+)?)\s*%', text)
    if tp_match:
        strategy["take_profit_pct"] = float(tp_match.group(1))

    # Detect capital
    cap_match = re.search(r'本金[：:\s]*\$?(\d+(?:,\d+)*)', text)
    if cap_match:
        strategy["initial_capital"] = float(cap_match.group(1).replace(",", ""))

    # Parse indicator conditions
    strategy["entry_conditions"] = _parse_conditions(text_lower, "entry")
    strategy["exit_conditions"] = _parse_conditions(text_lower, "exit")

    # Auto-generate name
    indicators_used = [c["indicator"] for c in strategy["entry_conditions"]]
    if indicators_used:
        strategy["name"] = " + ".join(set(indicators_used)).upper() + " Strategy"
    else:
        strategy["name"] = "Custom Strategy"

    return strategy


def _parse_conditions(text, cond_type):
    """Parse entry/exit conditions from text"""
    conditions = []

    # EMA crossover patterns
    ema_cross = re.search(r'ema\s*(\d+)\s*(?:穿越|交叉|cross|突破)\s*(?:上穿|向上|above)?\s*ema\s*(\d+)', text)
    if ema_cross:
        conditions.append({
            "indicator": "ema",
            "params": {"period": int(ema_cross.group(1))},
            "operator": "crosses_above",
            "value": {"indicator": "ema", "params": {"period": int(ema_cross.group(2))}},
        })

    # EMA above/below
    ema_above = re.search(r'(?:價格|price|收盤)\s*(?:在|>|above|高於)\s*ema\s*(\d+)', text)
    if ema_above:
        conditions.append({
            "indicator": "price",
            "params": {},
            "operator": "above",
            "value": {"indicator": "ema", "params": {"period": int(ema_above.group(1))}},
        })

    ema_below = re.search(r'(?:價格|price|收盤)\s*(?:在|<|below|低於)\s*ema\s*(\d+)', text)
    if ema_below:
        conditions.append({
            "indicator": "price",
            "params": {},
            "operator": "below",
            "value": {"indicator": "ema", "params": {"period": int(ema_below.group(1))}},
        })

    # RSI patterns
    rsi_below = re.search(r'rsi\s*(?:\(\s*(\d+)\s*\))?\s*(?:<|低於|below|跌破)\s*(\d+)', text)
    if rsi_below:
        period = int(rsi_below.group(1)) if rsi_below.group(1) else 14
        conditions.append({
            "indicator": "rsi",
            "params": {"period": period},
            "operator": "below" if cond_type == "entry" else "crosses_below",
            "value": int(rsi_below.group(2)),
        })

    rsi_above = re.search(r'rsi\s*(?:\(\s*(\d+)\s*\))?\s*(?:>|高於|above|突破)\s*(\d+)', text)
    if rsi_above:
        period = int(rsi_above.group(1)) if rsi_above.group(1) else 14
        conditions.append({
            "indicator": "rsi",
            "params": {"period": period},
            "operator": "above" if cond_type == "entry" else "crosses_above",
            "value": int(rsi_above.group(2)),
        })

    # Bollinger Band patterns
    if "布林" in text or "bollinger" in text or "bb" in text:
        if "下軌" in text or "lower" in text:
            conditions.append({
                "indicator": "price",
                "params": {},
                "operator": "below",
                "value": {"indicator": "bb_lower", "params": {"period": 20, "std": 2}},
            })
        if "上軌" in text or "upper" in text:
            conditions.append({
                "indicator": "price",
                "params": {},
                "operator": "above",
                "value": {"indicator": "bb_upper", "params": {"period": 20, "std": 2}},
            })

    # MACD patterns
    if "macd" in text:
        if "金叉" in text or "黃金交叉" in text or "golden" in text:
            conditions.append({
                "indicator": "macd_line",
                "params": {},
                "operator": "crosses_above",
                "value": {"indicator": "macd_signal", "params": {}},
            })
        if "死叉" in text or "死亡交叉" in text or "death" in text:
            conditions.append({
                "indicator": "macd_line",
                "params": {},
                "operator": "crosses_below",
                "value": {"indicator": "macd_signal", "params": {}},
            })

    # Volume patterns
    vol_match = re.search(r'(?:成交量|volume)\s*(?:>|超過|大於)\s*(\d+(?:\.\d+)?)\s*(?:倍|x)', text)
    if vol_match:
        conditions.append({
            "indicator": "volume",
            "params": {"period": 20},
            "operator": "above",
            "value": float(vol_match.group(1)),
            "note": "volume_multiplier",
        })

    return conditions


# ═══════════════════════════════════════════════════
# CODE GENERATOR
# ═══════════════════════════════════════════════════

def generate_strategy_code(strategy_def):
    """Generate executable Python strategy function from structured definition"""
    
    name = strategy_def.get("name", "custom").replace(" ", "_").lower()
    conditions = strategy_def.get("entry_conditions", [])
    exit_conds = strategy_def.get("exit_conditions", [])
    side = strategy_def.get("side", "both")

    # Collect needed indicators
    needed_indicators = set()
    for c in conditions + exit_conds:
        ind = c.get("indicator", "")
        if ind.startswith("macd"):
            needed_indicators.add("macd")
        elif ind == "price":
            val = c.get("value", {})
            if isinstance(val, dict):
                vi = val.get("indicator", "")
                if vi.startswith("bb"):
                    needed_indicators.add("bb")
                elif vi.startswith("ema"):
                    needed_indicators.add(f"ema_{val['params']['period']}")
                elif vi.startswith("sma"):
                    needed_indicators.add(f"sma_{val['params']['period']}")
        elif ind in ("ema", "sma"):
            p = c.get("params", {}).get("period", 21)
            needed_indicators.add(f"{ind}_{p}")
            val = c.get("value", {})
            if isinstance(val, dict) and val.get("indicator") in ("ema", "sma"):
                vp = val["params"]["period"]
                needed_indicators.add(f"{val['indicator']}_{vp}")
        elif ind == "rsi":
            needed_indicators.add("rsi")
        elif ind == "volume":
            needed_indicators.add("volume")

    # Generate indicator computation code
    indicator_code = []
    for ind in needed_indicators:
        if ind.startswith("ema_"):
            p = ind.split("_")[1]
            indicator_code.append(f'    {ind} = ema(closes, {p})')
        elif ind.startswith("sma_"):
            p = ind.split("_")[1]
            indicator_code.append(f'    {ind} = sma(closes, {p})')
        elif ind == "rsi":
            indicator_code.append('    rsi_vals = rsi(closes, 14)')
        elif ind == "macd":
            indicator_code.append('    macd_l, macd_s, macd_h = macd(closes)')
        elif ind == "bb":
            indicator_code.append('    bb_u, bb_m, bb_l = bollinger_bands(closes)')
        elif ind == "volume":
            indicator_code.append('    volumes = [c.volume for c in candles]')
            indicator_code.append('    vol_sma = sma(volumes, 20)')

    # Generate condition checks
    entry_checks = _generate_condition_checks(conditions, "entry")
    exit_checks = _generate_condition_checks(exit_conds, "exit")

    # Build function
    code = f'''def strategy_{name}(candles, i, indicators, open_trades):
    """Auto-generated: {strategy_def.get('description', '')}"""
    actions = []
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < 200:
        return actions

{chr(10).join(indicator_code)}

    # Entry conditions
    entry_signal = False
    if not open_trades:
{_indent(entry_checks, 8) if entry_checks else "        entry_signal = False  # no conditions defined"}

    if entry_signal and not open_trades:
        actions.append({{"action": "{"buy" if side == "long" else "sell" if side == "short" else "buy"}"}})

    # Exit conditions
    if open_trades:
{_indent(exit_checks, 8) if exit_checks else "        pass  # use SL/TP only"}

    return actions
'''
    return code


def _generate_condition_checks(conditions, cond_type):
    """Generate Python condition check code"""
    if not conditions:
        return ""

    checks = []
    for i, c in enumerate(conditions):
        ind = c.get("indicator", "")
        op = c.get("operator", "")
        val = c.get("value", 0)

        left = _resolve_indicator_ref(ind, c.get("params", {}))
        right = _resolve_value(val)

        if op == "crosses_above":
            checks.append(f"cond_{i} = {left}[i-1] is not None and {left}[i] is not None and {right}[i-1] is not None and {right}[i] is not None and {left}[i-1] <= {right}[i-1] and {left}[i] > {right}[i]")
        elif op == "crosses_below":
            checks.append(f"cond_{i} = {left}[i-1] is not None and {left}[i] is not None and {right}[i-1] is not None and {right}[i] is not None and {left}[i-1] >= {right}[i-1] and {left}[i] < {right}[i]")
        elif op == "above":
            if isinstance(val, (int, float)):
                checks.append(f"cond_{i} = {left}[i] is not None and {left}[i] > {val}")
            else:
                checks.append(f"cond_{i} = {left}[i] is not None and {right}[i] is not None and {left}[i] > {right}[i]")
        elif op == "below":
            if isinstance(val, (int, float)):
                checks.append(f"cond_{i} = {left}[i] is not None and {left}[i] < {val}")
            else:
                checks.append(f"cond_{i} = {left}[i] is not None and {right}[i] is not None and {left}[i] < {right}[i]")

    if checks:
        all_conds = " and ".join(f"cond_{i}" for i in range(len(checks)))
        checks.append(f"{'entry_signal' if cond_type == 'entry' else 'exit_signal'} = {all_conds}")
        if cond_type == "exit":
            checks.append("if exit_signal:")
            checks.append('    actions.append({"action": "close"})')

    return "\n".join(checks)


def _resolve_indicator_ref(indicator, params):
    """Resolve indicator name to variable reference"""
    if indicator == "price":
        return "closes"
    elif indicator == "rsi":
        return "rsi_vals"
    elif indicator == "ema":
        p = params.get("period", 21)
        return f"ema_{p}"
    elif indicator == "sma":
        p = params.get("period", 20)
        return f"sma_{p}"
    elif indicator == "macd_line":
        return "macd_l"
    elif indicator == "macd_signal":
        return "macd_s"
    elif indicator == "volume":
        return "volumes"
    return indicator


def _resolve_value(val):
    """Resolve value reference"""
    if isinstance(val, dict):
        ind = val.get("indicator", "")
        params = val.get("params", {})
        return _resolve_indicator_ref(ind, params)
    return str(val)


def _indent(text, spaces):
    """Indent text block"""
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.split("\n"))


# ═══════════════════════════════════════════════════
# STRATEGY LIBRARY (pre-built templates)
# ═══════════════════════════════════════════════════

STRATEGY_TEMPLATES = {
    "ema_cross": {
        "name": "EMA Crossover",
        "description": "EMA 快線穿越慢線",
        "params": {"fast": 9, "slow": 21},
    },
    "rsi_reversal": {
        "name": "RSI Reversal",
        "description": "RSI 超買超賣反轉",
        "params": {"oversold": 30, "overbought": 70},
    },
    "bb_squeeze": {
        "name": "Bollinger Squeeze",
        "description": "布林帶收窄後突破",
        "params": {"period": 20, "std": 2},
    },
    "macd_cross": {
        "name": "MACD Crossover",
        "description": "MACD 金叉死叉",
        "params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "trend_follow": {
        "name": "Trend Following",
        "description": "EMA200 趨勢 + RSI 回調入場",
        "params": {"trend_ema": 200, "rsi_entry": 40, "rsi_exit": 60},
    },
}


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    # Test: parse natural language
    test_inputs = [
        "BTC 4小時，EMA 9 穿越上穿 EMA 21 就做多，RSI 低於 30 加分，止損 3%，止盈 6%",
        "當 RSI 低於 25 且價格低於布林下軌就買入，RSI 高於 70 賣出",
        "MACD 金叉做多，死叉做空，成交量超過 2 倍",
    ]

    for text in test_inputs:
        print(f"\n{'='*60}")
        print(f"輸入: {text}")
        print(f"{'='*60}")
        strategy = parse_natural_language(text)
        print(f"策略: {strategy['name']}")
        print(f"方向: {strategy['side']}")
        print(f"入場條件: {len(strategy['entry_conditions'])} 個")
        for c in strategy["entry_conditions"]:
            print(f"  - {c['indicator']} {c['operator']} {c['value']}")
        print(f"出場條件: {len(strategy['exit_conditions'])} 個")

        code = generate_strategy_code(strategy)
        print(f"\n生成代碼:")
        print(code)

    print("\n✅ 策略解析器就緒")
