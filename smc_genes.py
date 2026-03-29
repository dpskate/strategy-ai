#!/usr/bin/env python3
"""
SMC (Smart Money Concepts) 基因模組
把 smc_analyzer.py 的結構信號轉換成策略基因可用的格式

smc_analyzer.py 用 dict candles: {"time", "open", "high", "low", "close", "volume"}
Strategy AI 用 dataclass Candle: .time, .open, .high, .low, .close, .volume
這裡做適配。
"""
import sys, os

# smc_analyzer.py 在 workspace 根目錄
_workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _workspace not in sys.path:
    sys.path.insert(0, _workspace)

from smc_analyzer import find_swings, analyze_structure, find_order_blocks, find_fvg, find_liquidity_pools


def _candles_to_dicts(candles):
    """Strategy AI Candle dataclass → smc_analyzer dict 格式"""
    return [
        {
            "time": c.time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]


def compute_smc_indicators(candles, swing_left=3, swing_right=3):
    """
    從 K 線數據計算 SMC 指標，返回 dict 供基因使用。
    candles: list of Candle dataclass (Strategy AI 格式)

    Returns dict with keys (all keyed by candle timestamp ms):
        'smc_trend':      {ts: 'bullish'|'bearish'|'neutral'}
        'smc_choch':      {ts: 'bullish'|'bearish'|None}
        'smc_bos':        {ts: 'bullish'|'bearish'|None}
        'smc_ob_bull':    {ts: True/False}
        'smc_ob_bear':    {ts: True/False}
        'smc_fvg_bull':   {ts: True/False}
        'smc_fvg_bear':   {ts: True/False}
        'smc_ssl_sweep':  {ts: True/False}
        'smc_bsl_sweep':  {ts: True/False}
    """
    if len(candles) < 20:
        # 數據太少，返回空 dict
        empty = {}
        return {k: empty for k in [
            'smc_trend', 'smc_choch', 'smc_bos',
            'smc_ob_bull', 'smc_ob_bear',
            'smc_fvg_bull', 'smc_fvg_bear',
            'smc_ssl_sweep', 'smc_bsl_sweep',
        ]}

    dicts = _candles_to_dicts(candles)

    # 1. Swing detection
    swing_highs, swing_lows = find_swings(dicts, swing_left, swing_right)

    # 2. Structure analysis (trend + CHoCH/BOS events)
    structure = analyze_structure(dicts, swing_highs, swing_lows)

    # 3. Order Blocks
    order_blocks = find_order_blocks(dicts, swing_highs, swing_lows)

    # 4. FVG
    fvgs = find_fvg(dicts, order_blocks)

    # 5. Liquidity pools (need current price for each bar — we'll use last bar)
    current_price = dicts[-1]["close"]
    liquidity = find_liquidity_pools(swing_highs, swing_lows, current_price, dicts)

    # ── Build per-bar indicator maps ──
    smc_trend = {}
    smc_choch = {}
    smc_bos = {}
    smc_ob_bull = {}
    smc_ob_bear = {}
    smc_fvg_bull = {}
    smc_fvg_bear = {}
    smc_ssl_sweep = {}
    smc_bsl_sweep = {}

    # -- Trend: replay structure events to assign trend per bar --
    # Build event timeline: list of (index, event_type)
    events_by_idx = []
    for evt in structure.get("events", []):
        events_by_idx.append((evt["index"], evt["type"]))
    events_by_idx.sort(key=lambda x: x[0])

    # Walk through candles, track current trend
    current_trend = structure.get("trend", "UNKNOWN")
    # Determine initial trend before first event
    if events_by_idx:
        # Before first event, use initial trend guess
        first_evt_idx = events_by_idx[0][0]
    else:
        first_evt_idx = len(candles)

    # Replay: assign trend based on events
    evt_ptr = 0
    running_trend = "neutral"
    # Try to infer initial trend from early structure
    if structure.get("trend") == "BULLISH":
        running_trend = "bullish"
    elif structure.get("trend") == "BEARISH":
        running_trend = "bearish"

    # Build a full event list including all events (not just last 5)
    # analyze_structure returns last 5 events, but we need all for per-bar mapping
    # We'll re-derive from the events we have
    all_events = structure.get("events", [])

    # Create index→event map
    event_at_idx = {}
    for evt in all_events:
        idx = evt.get("index", -1)
        if idx >= 0:
            event_at_idx[idx] = evt["type"]

    # Walk candles
    trend_state = running_trend
    for i, c in enumerate(dicts):
        ts = c["time"]

        # Check if a structure event happened at this bar
        if i in event_at_idx:
            etype = event_at_idx[i]
            if "BULLISH" in etype:
                trend_state = "bullish"
            elif "BEARISH" in etype:
                trend_state = "bearish"

            if "CHOCH" in etype:
                smc_choch[ts] = "bullish" if "BULLISH" in etype else "bearish"
            elif "BOS" in etype:
                smc_bos[ts] = "bullish" if "BULLISH" in etype else "bearish"

        smc_trend[ts] = trend_state

    # -- Order Blocks: check if price is in an active OB zone --
    bull_obs = [ob for ob in order_blocks if ob["type"] == "BULLISH_OB"]
    bear_obs = [ob for ob in order_blocks if ob["type"] == "BEARISH_OB"]

    for c in dicts:
        ts = c["time"]
        price = c["close"]

        # Check bullish OB: price near or in the OB zone
        in_bull_ob = False
        for ob in bull_obs:
            if ob["time"] < ts and ob["bottom"] <= price <= ob["top"] * 1.005:
                in_bull_ob = True
                break
        smc_ob_bull[ts] = in_bull_ob

        # Check bearish OB
        in_bear_ob = False
        for ob in bear_obs:
            if ob["time"] < ts and ob["bottom"] * 0.995 <= price <= ob["top"]:
                in_bear_ob = True
                break
        smc_ob_bear[ts] = in_bear_ob

    # -- FVG: check if price is in an active FVG zone --
    bull_fvgs = [f for f in fvgs if f["type"] == "BULLISH_FVG"]
    bear_fvgs = [f for f in fvgs if f["type"] == "BEARISH_FVG"]

    for c in dicts:
        ts = c["time"]
        price = c["close"]

        in_bull_fvg = False
        for fvg in bull_fvgs:
            if fvg["time"] < ts and fvg["bottom"] <= price <= fvg["top"]:
                in_bull_fvg = True
                break
        smc_fvg_bull[ts] = in_bull_fvg

        in_bear_fvg = False
        for fvg in bear_fvgs:
            if fvg["time"] < ts and fvg["bottom"] <= price <= fvg["top"]:
                in_bear_fvg = True
                break
        smc_fvg_bear[ts] = in_bear_fvg

    # -- Liquidity sweeps --
    # SSL swept: a candle wicked below SSL then closed above
    ssl_pools = liquidity.get("below", [])
    bsl_pools = liquidity.get("above", [])

    # Build sweep events from pool data
    ssl_sweep_candles = set()
    for pool in ssl_pools:
        if pool.get("swept") and pool.get("sweep_candle") is not None:
            idx = pool["sweep_candle"]
            if 0 <= idx < len(dicts):
                ssl_sweep_candles.add(dicts[idx]["time"])

    bsl_sweep_candles = set()
    for pool in bsl_pools:
        if pool.get("swept") and pool.get("sweep_candle") is not None:
            idx = pool["sweep_candle"]
            if 0 <= idx < len(dicts):
                bsl_sweep_candles.add(dicts[idx]["time"])

    for c in dicts:
        ts = c["time"]
        smc_ssl_sweep[ts] = ts in ssl_sweep_candles
        smc_bsl_sweep[ts] = ts in bsl_sweep_candles

    return {
        'smc_trend': smc_trend,
        'smc_choch': smc_choch,
        'smc_bos': smc_bos,
        'smc_ob_bull': smc_ob_bull,
        'smc_ob_bear': smc_ob_bear,
        'smc_fvg_bull': smc_fvg_bull,
        'smc_fvg_bear': smc_fvg_bear,
        'smc_ssl_sweep': smc_ssl_sweep,
        'smc_bsl_sweep': smc_bsl_sweep,
    }
