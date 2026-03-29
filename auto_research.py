#!/usr/bin/env python3
"""
Strategy AI - Auto Research Loop
AI 全自動策略研發：生成假設 → 寫代碼 → 回測 → 分析 → 改進 → 迭代
不需要人類介入，自己跑到找出能賺錢的策略
"""
import json, os, copy, random, time, itertools
from datetime import datetime, timezone, timedelta
from backtest_engine import (
    BacktestEngine, StrategyConfig, evaluate, format_report,
    fetch_candles_extended, Candle,
    ema, sma, rsi, bollinger_bands, atr, macd,
    obv, stoch_rsi, donchian, vwap_ratio
)
from optimizer import walk_forward

WORK = os.path.dirname(os.path.abspath(__file__))
TZ8 = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════
# STRATEGY GENE POOL
# ═══════════════════════════════════════════════════

# Building blocks that AI combines
ENTRY_GENES = {
    "ema_cross_up": {
        "desc": "EMA 快線上穿慢線",
        "params": {"fast": [5, 7, 9, 12], "slow": [15, 21, 26, 30, 50]},
        "code": lambda p: f"ema_u_f[i-1] <= ema_u_s[i-1] and ema_u_f[i] > ema_u_s[i]",
        "setup": lambda p: f"ema_u_f = ema(closes, {p['fast']})\n    ema_u_s = ema(closes, {p['slow']})",
        "null_check": "ema_u_f[i] is None or ema_u_s[i] is None or ema_u_f[i-1] is None or ema_u_s[i-1] is None",
        "min_bars": lambda p: p["slow"] + 10,
    },
    "ema_cross_down": {
        "desc": "EMA 快線下穿慢線",
        "params": {"fast": [5, 7, 9, 12], "slow": [15, 21, 26, 30, 50]},
        "code": lambda p: f"ema_d_f[i-1] >= ema_d_s[i-1] and ema_d_f[i] < ema_d_s[i]",
        "setup": lambda p: f"ema_d_f = ema(closes, {p['fast']})\n    ema_d_s = ema(closes, {p['slow']})",
        "null_check": "ema_d_f[i] is None or ema_d_s[i] is None or ema_d_f[i-1] is None or ema_d_s[i-1] is None",
        "min_bars": lambda p: p["slow"] + 10,
    },
    "rsi_oversold": {
        "desc": "RSI 從超賣區回升",
        "params": {"period": [7, 10, 14], "level": [20, 25, 30, 35]},
        "code": lambda p: f"rsi_vals[i-1] <= {p['level']} and rsi_vals[i] > {p['level']}",
        "setup": lambda p: f"rsi_vals = rsi(closes, {p['period']})",
        "null_check": "i >= len(rsi_vals) or rsi_vals[i] is None or rsi_vals[i-1] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "rsi_overbought": {
        "desc": "RSI 從超買區回落",
        "params": {"period": [7, 10, 14], "level": [65, 70, 75, 80]},
        "code": lambda p: f"rsi_vals[i-1] >= {p['level']} and rsi_vals[i] < {p['level']}",
        "setup": lambda p: f"rsi_vals = rsi(closes, {p['period']})",
        "null_check": "i >= len(rsi_vals) or rsi_vals[i] is None or rsi_vals[i-1] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "price_above_ema": {
        "desc": "價格在 EMA 上方（趨勢濾網）",
        "params": {"period": [50, 100, 200]},
        "code": lambda p: f"closes[i] > ema_trend[i]",
        "setup": lambda p: f"ema_trend = ema(closes, {p['period']})",
        "null_check": "ema_trend[i] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "price_below_ema": {
        "desc": "價格在 EMA 下方（趨勢濾網）",
        "params": {"period": [50, 100, 200]},
        "code": lambda p: f"closes[i] < ema_trend[i]",
        "setup": lambda p: f"ema_trend = ema(closes, {p['period']})",
        "null_check": "ema_trend[i] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "bb_lower_touch": {
        "desc": "價格觸及布林下軌",
        "params": {"period": [15, 20, 25], "std": [1.5, 2.0, 2.5]},
        "code": lambda p: f"closes[i] < bb_l[i]",
        "setup": lambda p: f"bb_u, bb_m, bb_l = bollinger_bands(closes, {p['period']}, {p['std']})",
        "null_check": "bb_l[i] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "bb_upper_touch": {
        "desc": "價格觸及布林上軌",
        "params": {"period": [15, 20, 25], "std": [1.5, 2.0, 2.5]},
        "code": lambda p: f"closes[i] > bb_u[i]",
        "setup": lambda p: f"bb_u, bb_m, bb_l = bollinger_bands(closes, {p['period']}, {p['std']})",
        "null_check": "bb_u[i] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "macd_golden": {
        "desc": "MACD 金叉",
        "params": {"fast": [8, 12], "slow": [21, 26], "signal": [7, 9]},
        "code": lambda p: f"macd_g_l[i-1] <= macd_g_s[i-1] and macd_g_l[i] > macd_g_s[i]",
        "setup": lambda p: f"macd_g_l, macd_g_s, _ = macd(closes, {p['fast']}, {p['slow']}, {p['signal']})",
        "null_check": "macd_g_l[i] is None or macd_g_s[i] is None or macd_g_l[i-1] is None or macd_g_s[i-1] is None",
        "min_bars": lambda p: p["slow"] + p["signal"] + 10,
    },
    "macd_death": {
        "desc": "MACD 死叉",
        "params": {"fast": [8, 12], "slow": [21, 26], "signal": [7, 9]},
        "code": lambda p: f"macd_d_l[i-1] >= macd_d_s[i-1] and macd_d_l[i] < macd_d_s[i]",
        "setup": lambda p: f"macd_d_l, macd_d_s, _ = macd(closes, {p['fast']}, {p['slow']}, {p['signal']})",
        "null_check": "macd_d_l[i] is None or macd_d_s[i] is None or macd_d_l[i-1] is None or macd_d_s[i-1] is None",
        "min_bars": lambda p: p["slow"] + p["signal"] + 10,
    },
    "volume_spike": {
        "desc": "成交量突增",
        "params": {"period": [10, 20], "mult": [1.5, 2.0, 3.0]},
        "code": lambda p: f"vol_sma_val is not None and candles[i].volume > vol_sma_val * {p['mult']}",
        "setup": lambda p: f"_vols = [c.volume for c in candles[:i+1]]; _vs = sma(_vols, {p['period']}); vol_sma_val = _vs[-1] if _vs else None",
        "null_check": "vol_sma_val is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    # ── New genes ──
    "stoch_rsi_oversold": {
        "desc": "Stoch RSI 從超賣區回升",
        "params": {"rsi_period": [14], "stoch_period": [14], "level": [15, 20, 25]},
        "code": lambda p: f"srsi_vals[i-1] is not None and srsi_vals[i] is not None and srsi_vals[i-1] <= {p['level']} and srsi_vals[i] > {p['level']}",
        "setup": lambda p: f"srsi_vals = stoch_rsi(closes, {p['rsi_period']}, {p['stoch_period']})",
        "null_check": "srsi_vals[i] is None or srsi_vals[i-1] is None",
        "min_bars": lambda p: 50,
    },
    "stoch_rsi_overbought": {
        "desc": "Stoch RSI 從超買區回落",
        "params": {"rsi_period": [14], "stoch_period": [14], "level": [75, 80, 85]},
        "code": lambda p: f"srsi_vals[i-1] is not None and srsi_vals[i] is not None and srsi_vals[i-1] >= {p['level']} and srsi_vals[i] < {p['level']}",
        "setup": lambda p: f"srsi_vals = stoch_rsi(closes, {p['rsi_period']}, {p['stoch_period']})",
        "null_check": "srsi_vals[i] is None or srsi_vals[i-1] is None",
        "min_bars": lambda p: 50,
    },
    "donchian_breakout_up": {
        "desc": "突破唐奇安通道上軌",
        "params": {"period": [10, 20, 30]},
        "code": lambda p: f"dc_upper[i] is not None and closes[i] > dc_upper[i-1]",
        "setup": lambda p: f"dc_upper, dc_lower = donchian(candles[:i+1], {p['period']})",
        "null_check": "dc_upper[i] is None or dc_upper[i-1] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "donchian_breakout_down": {
        "desc": "跌破唐奇安通道下軌",
        "params": {"period": [10, 20, 30]},
        "code": lambda p: f"dc_lower[i] is not None and closes[i] < dc_lower[i-1]",
        "setup": lambda p: f"dc_upper, dc_lower = donchian(candles[:i+1], {p['period']})",
        "null_check": "dc_lower[i] is None or dc_lower[i-1] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "obv_rising": {
        "desc": "OBV 上升趨勢",
        "params": {"period": [10, 20]},
        "code": lambda p: f"obv_ema_val is not None and obv_ema_prev is not None and obv_ema_val > obv_ema_prev",
        "setup": lambda p: f"_obv = obv(candles[:i+1]); _obv_ema = ema(_obv, {p['period']}); obv_ema_val = _obv_ema[-1] if _obv_ema else None; obv_ema_prev = _obv_ema[-2] if len(_obv_ema) > 1 else None",
        "null_check": "obv_ema_val is None or obv_ema_prev is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "obv_falling": {
        "desc": "OBV 下降趨勢",
        "params": {"period": [10, 20]},
        "code": lambda p: f"obv_ema_val is not None and obv_ema_prev is not None and obv_ema_val < obv_ema_prev",
        "setup": lambda p: f"_obv = obv(candles[:i+1]); _obv_ema = ema(_obv, {p['period']}); obv_ema_val = _obv_ema[-1] if _obv_ema else None; obv_ema_prev = _obv_ema[-2] if len(_obv_ema) > 1 else None",
        "null_check": "obv_ema_val is None or obv_ema_prev is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "vwap_above": {
        "desc": "價格在 VWAP 上方",
        "params": {"period": [10, 20, 30]},
        "code": lambda p: f"vwap_r[i] is not None and vwap_r[i] > 1.005",
        "setup": lambda p: f"vwap_r = vwap_ratio(candles[:i+1], {p['period']})",
        "null_check": "vwap_r[i] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "vwap_below": {
        "desc": "價格在 VWAP 下方",
        "params": {"period": [10, 20, 30]},
        "code": lambda p: f"vwap_r[i] is not None and vwap_r[i] < 0.995",
        "setup": lambda p: f"vwap_r = vwap_ratio(candles[:i+1], {p['period']})",
        "null_check": "vwap_r[i] is None",
        "min_bars": lambda p: p["period"] + 10,
    },
    "atr_squeeze": {
        "desc": "ATR 收縮（低波動，蓄勢待發）",
        "params": {"period": [14], "lookback": [20, 30]},
        "code": lambda p: f"atr_now is not None and atr_avg is not None and atr_now < atr_avg * 0.7",
        "setup": lambda p: f"_atr = atr(candles[:i+1], {p['period']}); atr_now = _atr[-1] if _atr else None; _atr_recent = [v for v in _atr[-{p['lookback']}:] if v is not None]; atr_avg = sum(_atr_recent)/len(_atr_recent) if _atr_recent else None",
        "null_check": "atr_now is None or atr_avg is None",
        "min_bars": lambda p: p["lookback"] + p["period"] + 10,
    },
    "consecutive_bullish": {
        "desc": "連續陽線（動能確認）",
        "params": {"count": [3, 4, 5]},
        "code": lambda p: f"all(candles[i-j].close > candles[i-j].open for j in range({p['count']}))",
        "setup": lambda p: f"pass",
        "null_check": f"i < 5",
        "min_bars": lambda p: p["count"] + 10,
    },
    "consecutive_bearish": {
        "desc": "連續陰線（動能確認）",
        "params": {"count": [3, 4, 5]},
        "code": lambda p: f"all(candles[i-j].close < candles[i-j].open for j in range({p['count']}))",
        "setup": lambda p: f"pass",
        "null_check": f"i < 5",
        "min_bars": lambda p: p["count"] + 10,
    },
    # ── Derivatives genes ──
    "funding_negative": {
        "desc": "資金費率極度負值（空頭擁擠→做多）",
        "type": "long",
        "params": {"threshold": [-0.01, -0.005, -0.02]},
        "setup": lambda p: f"_fr = indicators.get('funding_rate', {{}})\n    _fr_val = _lookup_nearest(_fr, candles[i].time)",
        "code": lambda p: f"_fr_val is not None and _fr_val < {p['threshold']} / 100",
        "null_check": "_fr_val is None",
        "min_bars": lambda p: 50,
    },
    "funding_positive": {
        "desc": "資金費率極度正值（多頭擁擠→做空）",
        "type": "short",
        "params": {"threshold": [0.03, 0.02, 0.05]},
        "setup": lambda p: f"_fr = indicators.get('funding_rate', {{}})\n    _fr_val = _lookup_nearest(_fr, candles[i].time)",
        "code": lambda p: f"_fr_val is not None and _fr_val > {p['threshold']} / 100",
        "null_check": "_fr_val is None",
        "min_bars": lambda p: 50,
    },
    "lsr_extreme_low": {
        "desc": "多空比極低（空頭擁擠→反向做多）",
        "type": "long",
        "params": {"threshold": [0.8, 0.7, 0.9]},
        "setup": lambda p: f"_lsr = indicators.get('long_short_ratio', {{}})\n    _lsr_val = _lookup_nearest(_lsr, candles[i].time)",
        "code": lambda p: f"_lsr_val is not None and _lsr_val < {p['threshold']}",
        "null_check": "_lsr_val is None",
        "min_bars": lambda p: 50,
    },
    "lsr_extreme_high": {
        "desc": "多空比極高（多頭擁擠→反向做空）",
        "type": "short",
        "params": {"threshold": [1.5, 1.3, 1.8]},
        "setup": lambda p: f"_lsr = indicators.get('long_short_ratio', {{}})\n    _lsr_val = _lookup_nearest(_lsr, candles[i].time)",
        "code": lambda p: f"_lsr_val is not None and _lsr_val > {p['threshold']}",
        "null_check": "_lsr_val is None",
        "min_bars": lambda p: 50,
    },
    "oi_surge": {
        "desc": "未平倉合約突增（趨勢確認濾網）",
        "type": "filter",
        "params": {"threshold": [0.10, 0.08, 0.15]},
        "setup": lambda p: f"_oi_chg = indicators.get('oi_change', {{}})\n    _oi_chg_val = _lookup_nearest(_oi_chg, candles[i].time)",
        "code": lambda p: f"_oi_chg_val is not None and _oi_chg_val > {p['threshold']}",
        "null_check": "_oi_chg_val is None",
        "min_bars": lambda p: 50,
    },
    "oi_divergence": {
        "desc": "OI 背離（價格漲但 OI 跌→做空）",
        "type": "short",
        "params": {"price_bars": [3, 5, 8]},
        "setup": lambda p: f"_oi_chg = indicators.get('oi_change', {{}})\n    _oi_chg_val = _lookup_nearest(_oi_chg, candles[i].time)",
        "code": lambda p: f"_oi_chg_val is not None and closes[i] > closes[i-{p['price_bars']}] and _oi_chg_val < -0.03",
        "null_check": f"_oi_chg_val is None",
        "min_bars": lambda p: p["price_bars"] + 10,
    },
    # ── Extended Alternative Data genes ──
    "fear_extreme": {
        "desc": "極度恐懼（反向做多）",
        "type": "long",
        "params": {"threshold": [10, 15, 20, 25]},
        "setup": lambda p: f"_fg = indicators.get('fear_greed', {{}})\n    _fg_val = _lookup_nearest(_fg, candles[i].time)",
        "code": lambda p: f"_fg_val is not None and _fg_val < {p['threshold']}",
        "null_check": "_fg_val is None",
        "min_bars": lambda p: 50,
    },
    "greed_extreme": {
        "desc": "極度貪婪（反向做空）",
        "type": "short",
        "params": {"threshold": [75, 80, 85]},
        "setup": lambda p: f"_fg_s = indicators.get('fear_greed', {{}})\n    _fg_s_val = _lookup_nearest(_fg_s, candles[i].time)",
        "code": lambda p: f"_fg_s_val is not None and _fg_s_val > {p['threshold']}",
        "null_check": "_fg_s_val is None",
        "min_bars": lambda p: 50,
    },
    "top_trader_long": {
        "desc": "大戶偏多（跟隨聰明錢）",
        "type": "long",
        "params": {"threshold": [0.55, 0.6, 0.65]},
        "setup": lambda p: f"_ttr_l = indicators.get('top_trader_ratio', {{}})\n    _ttr_l_val = _lookup_nearest(_ttr_l, candles[i].time)",
        "code": lambda p: f"_ttr_l_val is not None and _ttr_l_val > {p['threshold']}",
        "null_check": "_ttr_l_val is None",
        "min_bars": lambda p: 50,
    },
    "top_trader_short": {
        "desc": "大戶偏空（跟隨聰明錢）",
        "type": "short",
        "params": {"threshold": [0.55, 0.6, 0.65]},
        "setup": lambda p: f"_ttr_s = indicators.get('top_trader_ratio', {{}})\n    _ttr_s_val = _lookup_nearest(_ttr_s, candles[i].time)",
        "code": lambda p: f"_ttr_s_val is not None and _ttr_s_val < 1.0 / {p['threshold']}",
        "null_check": "_ttr_s_val is None",
        "min_bars": lambda p: 50,
    },
    "taker_buy_surge": {
        "desc": "主動買入力量暴增",
        "type": "long",
        "params": {"threshold": [0.55, 0.6, 0.65]},
        "setup": lambda p: f"_tbs = indicators.get('taker_buy_sell', {{}})\n    _tbs_val = _lookup_nearest(_tbs, candles[i].time)",
        "code": lambda p: f"_tbs_val is not None and _tbs_val > {p['threshold']}",
        "null_check": "_tbs_val is None",
        "min_bars": lambda p: 50,
    },
    "taker_sell_surge": {
        "desc": "主動賣出力量暴增",
        "type": "short",
        "params": {"threshold": [0.55, 0.6, 0.65]},
        "setup": lambda p: f"_tss = indicators.get('taker_buy_sell', {{}})\n    _tss_val = _lookup_nearest(_tss, candles[i].time)",
        "code": lambda p: f"_tss_val is not None and _tss_val < 1.0 / {p['threshold']}",
        "null_check": "_tss_val is None",
        "min_bars": lambda p: 50,
    },
    "usd_weak": {
        "desc": "美元走弱（EURUSDT 上漲）",
        "type": "long",
        "params": {"lookback": [5, 10, 20], "threshold": [0.5, 1.0, 1.5]},
        "setup": lambda p: f"_dxy = indicators.get('dxy_proxy', {{}})\n    _dxy_now = _lookup_nearest(_dxy, candles[i].time)\n    _dxy_prev = _lookup_nearest(_dxy, candles[max(0, i-{p['lookback']})].time)",
        "code": lambda p: f"_dxy_now is not None and _dxy_prev is not None and _dxy_prev > 0 and (_dxy_prev - _dxy_now) / _dxy_prev * 100 > {p['threshold']}",
        "null_check": "_dxy_now is None or _dxy_prev is None",
        "min_bars": lambda p: p["lookback"] + 10,
    },
    "usd_strong": {
        "desc": "美元走強（EURUSDT 下跌）",
        "type": "short",
        "params": {"lookback": [5, 10, 20], "threshold": [0.5, 1.0, 1.5]},
        "setup": lambda p: f"_dxy_str = indicators.get('dxy_proxy', {{}})\n    _dxy_str_now = _lookup_nearest(_dxy_str, candles[i].time)\n    _dxy_str_prev = _lookup_nearest(_dxy_str, candles[max(0, i-{p['lookback']})].time)",
        "code": lambda p: f"_dxy_str_now is not None and _dxy_str_prev is not None and _dxy_str_prev > 0 and (_dxy_str_now - _dxy_str_prev) / _dxy_str_prev * 100 > {p['threshold']}",
        "null_check": "_dxy_str_now is None or _dxy_str_prev is None",
        "min_bars": lambda p: p["lookback"] + 10,
    },
    "spot_dominance": {
        "desc": "現貨成交量主導（非投機）",
        "type": "filter",
        "params": {"threshold": [0.3, 0.4, 0.5]},
        "setup": lambda p: f"_sfr = indicators.get('spot_futures_ratio', {{}})\n    _sfr_val = _lookup_nearest(_sfr, candles[i].time)",
        "code": lambda p: f"_sfr_val is not None and _sfr_val > {p['threshold']}",
        "null_check": "_sfr_val is None",
        "min_bars": lambda p: 50,
    },
    "basis_negative": {
        "desc": "永續負基差（空頭擁擠→做多）",
        "type": "long",
        "params": {"threshold": [-0.1, -0.2, -0.3]},
        "setup": lambda p: f"_basis_n = indicators.get('basis', {{}})\n    _basis_n_val = _lookup_nearest(_basis_n, candles[i].time)",
        "code": lambda p: f"_basis_n_val is not None and _basis_n_val < {p['threshold']}",
        "null_check": "_basis_n_val is None",
        "min_bars": lambda p: 50,
    },
    "basis_positive": {
        "desc": "永續正基差過大（多頭過熱→做空）",
        "type": "short",
        "params": {"threshold": [0.1, 0.2, 0.3]},
        "setup": lambda p: f"_basis_p = indicators.get('basis', {{}})\n    _basis_p_val = _lookup_nearest(_basis_p, candles[i].time)",
        "code": lambda p: f"_basis_p_val is not None and _basis_p_val > {p['threshold']}",
        "null_check": "_basis_p_val is None",
        "min_bars": lambda p: 50,
    },
    # ── SMC (Smart Money Concepts) genes ──
    "smc_trend_bullish": {
        "desc": "SMC 結構看漲（趨勢方向）",
        "type": "long",
        "params": {},
        "setup": lambda p: f"_smc_trend = indicators.get('smc_trend', {{}})\n    _smc_trend_val = _lookup_nearest(_smc_trend, candles[i].time)",
        "code": lambda p: f"_smc_trend_val is not None and _smc_trend_val == 'bullish'",
        "null_check": "_smc_trend_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_trend_bearish": {
        "desc": "SMC 結構看跌（趨勢方向）",
        "type": "short",
        "params": {},
        "setup": lambda p: f"_smc_trend_s = indicators.get('smc_trend', {{}})\n    _smc_trend_s_val = _lookup_nearest(_smc_trend_s, candles[i].time)",
        "code": lambda p: f"_smc_trend_s_val is not None and _smc_trend_s_val == 'bearish'",
        "null_check": "_smc_trend_s_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_choch_bullish": {
        "desc": "SMC 看漲 CHoCH（結構轉折做多）",
        "type": "long",
        "params": {"lookback": [1, 2, 3]},
        "setup": lambda p: f"_smc_choch = indicators.get('smc_choch', {{}})\n    _smc_choch_val = next((_lookup_nearest(_smc_choch, candles[i - _lb].time) for _lb in range({p['lookback']}) if i - _lb >= 0 and _lookup_nearest(_smc_choch, candles[i - _lb].time) is not None), None)",
        "code": lambda p: f"_smc_choch_val is not None and _smc_choch_val == 'bullish'",
        "null_check": "_smc_choch_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_choch_bearish": {
        "desc": "SMC 看跌 CHoCH（結構轉折做空）",
        "type": "short",
        "params": {"lookback": [1, 2, 3]},
        "setup": lambda p: f"_smc_choch_s = indicators.get('smc_choch', {{}})\n    _smc_choch_s_val = next((_lookup_nearest(_smc_choch_s, candles[i - _lb_s].time) for _lb_s in range({p['lookback']}) if i - _lb_s >= 0 and _lookup_nearest(_smc_choch_s, candles[i - _lb_s].time) is not None), None)",
        "code": lambda p: f"_smc_choch_s_val is not None and _smc_choch_s_val == 'bearish'",
        "null_check": "_smc_choch_s_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_ob_support": {
        "desc": "價格在看漲 Order Block 區域（支撐做多）",
        "type": "long",
        "params": {},
        "setup": lambda p: f"_smc_ob_b = indicators.get('smc_ob_bull', {{}})\n    _smc_ob_b_val = _lookup_nearest(_smc_ob_b, candles[i].time)",
        "code": lambda p: f"_smc_ob_b_val is not None and _smc_ob_b_val == True",
        "null_check": "_smc_ob_b_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_ob_resistance": {
        "desc": "價格在看跌 Order Block 區域（壓力做空）",
        "type": "short",
        "params": {},
        "setup": lambda p: f"_smc_ob_r = indicators.get('smc_ob_bear', {{}})\n    _smc_ob_r_val = _lookup_nearest(_smc_ob_r, candles[i].time)",
        "code": lambda p: f"_smc_ob_r_val is not None and _smc_ob_r_val == True",
        "null_check": "_smc_ob_r_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_fvg_bullish": {
        "desc": "價格在看漲 FVG 區域（公允價值缺口做多）",
        "type": "long",
        "params": {},
        "setup": lambda p: f"_smc_fvg_b = indicators.get('smc_fvg_bull', {{}})\n    _smc_fvg_b_val = _lookup_nearest(_smc_fvg_b, candles[i].time)",
        "code": lambda p: f"_smc_fvg_b_val is not None and _smc_fvg_b_val == True",
        "null_check": "_smc_fvg_b_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_fvg_bearish": {
        "desc": "價格在看跌 FVG 區域（公允價值缺口做空）",
        "type": "short",
        "params": {},
        "setup": lambda p: f"_smc_fvg_r = indicators.get('smc_fvg_bear', {{}})\n    _smc_fvg_r_val = _lookup_nearest(_smc_fvg_r, candles[i].time)",
        "code": lambda p: f"_smc_fvg_r_val is not None and _smc_fvg_r_val == True",
        "null_check": "_smc_fvg_r_val is None",
        "min_bars": lambda p: 50,
    },
    "smc_ssl_swept": {
        "desc": "SSL 被掃（流動性獵取後做多）",
        "type": "long",
        "params": {"lookback": [1, 2, 3]},
        "setup": lambda p: f"_smc_ssl = indicators.get('smc_ssl_sweep', {{}})\n    _smc_ssl_val = any(_lookup_nearest(_smc_ssl, candles[i - _ssl_lb].time) for _ssl_lb in range({p['lookback']}) if i - _ssl_lb >= 0)",
        "code": lambda p: f"_smc_ssl_val == True",
        "null_check": "False",
        "min_bars": lambda p: 50,
    },
    "smc_bsl_swept": {
        "desc": "BSL 被掃（流動性獵取後做空）",
        "type": "short",
        "params": {"lookback": [1, 2, 3]},
        "setup": lambda p: f"_smc_bsl = indicators.get('smc_bsl_sweep', {{}})\n    _smc_bsl_val = any(_lookup_nearest(_smc_bsl, candles[i - _bsl_lb].time) for _bsl_lb in range({p['lookback']}) if i - _bsl_lb >= 0)",
        "code": lambda p: f"_smc_bsl_val == True",
        "null_check": "False",
        "min_bars": lambda p: 50,
    },
    # ── Cross-asset genes ──
    "eth_divergence_bull": {
        "desc": "ETH 落後 BTC（BTC 相對強勢）",
        "type": "long",
        "params": {"threshold": [1, 2, 3]},
        "setup": lambda p: f"_eth_div = indicators.get('eth_btc_divergence', {{}})\n    _eth_div_val = _lookup_nearest(_eth_div, candles[i].time)",
        "code": lambda p: f"_eth_div_val is not None and _eth_div_val < -{p['threshold']}",
        "null_check": "_eth_div_val is None",
        "min_bars": lambda p: 50,
    },
    "eth_divergence_bear": {
        "desc": "ETH 領先 BTC（BTC 相對弱勢）",
        "type": "short",
        "params": {"threshold": [1, 2, 3]},
        "setup": lambda p: f"_eth_div_s = indicators.get('eth_btc_divergence', {{}})\n    _eth_div_s_val = _lookup_nearest(_eth_div_s, candles[i].time)",
        "code": lambda p: f"_eth_div_s_val is not None and _eth_div_s_val > {p['threshold']}",
        "null_check": "_eth_div_s_val is None",
        "min_bars": lambda p: 50,
    },
    "altcoin_risk_on": {
        "desc": "山寨幣動能強（風險偏好上升）",
        "type": "long",
        "params": {"threshold": [1, 2, 3]},
        "setup": lambda p: f"_alt_mom = indicators.get('altcoin_momentum', {{}})\n    _alt_mom_val = _lookup_nearest(_alt_mom, candles[i].time)",
        "code": lambda p: f"_alt_mom_val is not None and _alt_mom_val > {p['threshold']}",
        "null_check": "_alt_mom_val is None",
        "min_bars": lambda p: 50,
    },
    "altcoin_risk_off": {
        "desc": "山寨幣動能弱（風險偏好下降）",
        "type": "short",
        "params": {"threshold": [1, 2, 3]},
        "setup": lambda p: f"_alt_mom_s = indicators.get('altcoin_momentum', {{}})\n    _alt_mom_s_val = _lookup_nearest(_alt_mom_s, candles[i].time)",
        "code": lambda p: f"_alt_mom_s_val is not None and _alt_mom_s_val < -{p['threshold']}",
        "null_check": "_alt_mom_s_val is None",
        "min_bars": lambda p: 50,
    },
    # ── Time factor genes ──
    "asia_session": {
        "desc": "亞洲交易時段（UTC 0-8）",
        "type": "filter",
        "params": {},
        "setup": lambda p: f"_sess = indicators.get('session', {{}})\n    _sess_val = _lookup_nearest(_sess, candles[i].time)",
        "code": lambda p: f"_sess_val is not None and _sess_val == 'asia'",
        "null_check": "_sess_val is None",
        "min_bars": lambda p: 10,
    },
    "us_session": {
        "desc": "美洲交易時段（UTC 16-24）",
        "type": "filter",
        "params": {},
        "setup": lambda p: f"_sess_us = indicators.get('session', {{}})\n    _sess_us_val = _lookup_nearest(_sess_us, candles[i].time)",
        "code": lambda p: f"_sess_us_val is not None and _sess_us_val == 'us'",
        "null_check": "_sess_us_val is None",
        "min_bars": lambda p: 10,
    },
    "weekend_filter": {
        "desc": "工作日（排除週末低流動性）",
        "type": "filter",
        "params": {},
        "setup": lambda p: f"_dow = indicators.get('day_of_week', {{}})\n    _dow_val = _lookup_nearest(_dow, candles[i].time)",
        "code": lambda p: f"_dow_val is not None and _dow_val < 5",
        "null_check": "_dow_val is None",
        "min_bars": lambda p: 10,
    },
    # ── Volatility factor genes ──
    "vol_low_regime": {
        "desc": "低波動率環境（蓄勢待發）",
        "type": "filter",
        "params": {},
        "setup": lambda p: f"_vr = indicators.get('vol_regime', {{}})\n    _vr_val = _lookup_nearest(_vr, candles[i].time)",
        "code": lambda p: f"_vr_val is not None and _vr_val == 'low'",
        "null_check": "_vr_val is None",
        "min_bars": lambda p: 30,
    },
    "vol_expansion": {
        "desc": "波動率擴張（趨勢確認）",
        "type": "filter",
        "params": {},
        "setup": lambda p: f"_ve = indicators.get('vol_expansion', {{}})\n    _ve_val = _lookup_nearest(_ve, candles[i].time)",
        "code": lambda p: f"_ve_val is not None and _ve_val == 1",
        "null_check": "_ve_val is None",
        "min_bars": lambda p: 30,
    },
    # ── On-chain factor genes ──
    "active_addr_surge": {
        "desc": "鏈上活躍地址暴增（網路活躍度上升）",
        "type": "long",
        "params": {"threshold": [5, 10, 15]},
        "setup": lambda p: f"_aac = indicators.get('active_addresses_change', {{}})\n    _aac_val = _lookup_nearest(_aac, candles[i].time)",
        "code": lambda p: f"_aac_val is not None and _aac_val > {p['threshold']}",
        "null_check": "_aac_val is None",
        "min_bars": lambda p: 50,
    },
    "hashrate_drop": {
        "desc": "算力下降（礦工投降→反向做多）",
        "type": "long",
        "params": {"threshold": [3, 5, 10]},
        "setup": lambda p: f"_hrc = indicators.get('hashrate_change', {{}})\n    _hrc_val = _lookup_nearest(_hrc, candles[i].time)",
        "code": lambda p: f"_hrc_val is not None and _hrc_val < -{p['threshold']}",
        "null_check": "_hrc_val is None",
        "min_bars": lambda p: 50,
    },
    "fees_spike": {
        "desc": "鏈上手續費暴增（網路活躍）",
        "type": "filter",
        "params": {"threshold": [50, 100, 200]},
        "setup": lambda p: f"_fs = indicators.get('fees_spike', {{}})\n    _fs_val = _lookup_nearest(_fs, candles[i].time)",
        "code": lambda p: f"_fs_val is not None and _fs_val > {p['threshold']}",
        "null_check": "_fs_val is None",
        "min_bars": lambda p: 50,
    },
    # ── Correlation factor genes ──
    "corr_breakdown": {
        "desc": "BTC-美元相關性崩塌（regime change）",
        "type": "filter",
        "params": {"threshold": [0.2, 0.3, 0.4]},
        "setup": lambda p: f"_crc = indicators.get('corr_regime_change', {{}})\n    _crc_val = _lookup_nearest(_crc, candles[i].time)",
        "code": lambda p: f"_crc_val is not None and _crc_val > {p['threshold']}",
        "null_check": "_crc_val is None",
        "min_bars": lambda p: 50,
    },
}

EXIT_GENES = {
    "rsi_exit_high": {
        "desc": "RSI 高位出場",
        "code": lambda p: f"rsi_ex[i] is not None and rsi_ex[i] > {p['level']}",
        "setup": lambda p: f"rsi_ex = rsi(closes, {p.get('period', 14)})",
        "params": {"level": [60, 65, 70, 75], "period": [14]},
    },
    "rsi_exit_low": {
        "desc": "RSI 低位出場",
        "code": lambda p: f"rsi_ex[i] is not None and rsi_ex[i] < {p['level']}",
        "setup": lambda p: f"rsi_ex = rsi(closes, {p.get('period', 14)})",
        "params": {"level": [25, 30, 35, 40], "period": [14]},
    },
    "bb_middle": {
        "desc": "布林中軌出場",
        "code": lambda p: f"bb_mx[i] is not None and ((open_trades[0].side == 'long' and closes[i] > bb_mx[i]) or (open_trades[0].side == 'short' and closes[i] < bb_mx[i]))",
        "setup": lambda p: f"_, bb_mx, _ = bollinger_bands(closes, 20, 2)",
        "params": {},
    },
    "ema_cross_exit": {
        "desc": "EMA 反向交叉出場",
        "code": lambda p: f"ema_ex_f[i] is not None and ema_ex_s[i] is not None and ((open_trades[0].side == 'long' and ema_ex_f[i] < ema_ex_s[i]) or (open_trades[0].side == 'short' and ema_ex_f[i] > ema_ex_s[i]))",
        "setup": lambda p: f"ema_ex_f = ema(closes, {p.get('fast', 9)})\n    ema_ex_s = ema(closes, {p.get('slow', 21)})",
        "params": {"fast": [9], "slow": [21]},
    },
    "atr_trailing": {
        "desc": "ATR 追蹤止損",
        "code": lambda p: f"_atr_ex[-1] is not None and ((open_trades[0].side == 'long' and closes[i] < closes[i-1] - _atr_ex[-1] * {p.get('mult', 2)}) or (open_trades[0].side == 'short' and closes[i] > closes[i-1] + _atr_ex[-1] * {p.get('mult', 2)}))",
        "setup": lambda p: f"_atr_ex = atr(candles[:i+1], 14)",
        "params": {"mult": [1.5, 2, 3]},
    },
    "stoch_rsi_exit": {
        "desc": "Stoch RSI 極端值出場",
        "code": lambda p: f"srsi_ex[i] is not None and ((open_trades[0].side == 'long' and srsi_ex[i] > {p.get('high', 80)}) or (open_trades[0].side == 'short' and srsi_ex[i] < {p.get('low', 20)}))",
        "setup": lambda p: f"srsi_ex = stoch_rsi(closes, 14, 14)",
        "params": {"high": [75, 80, 85], "low": [15, 20, 25]},
    },
    "macd_cross_exit": {
        "desc": "MACD 反向交叉出場",
        "code": lambda p: f"macd_ex_l[i] is not None and macd_ex_s[i] is not None and macd_ex_l[i-1] is not None and macd_ex_s[i-1] is not None and ((open_trades[0].side == 'long' and macd_ex_l[i-1] >= macd_ex_s[i-1] and macd_ex_l[i] < macd_ex_s[i]) or (open_trades[0].side == 'short' and macd_ex_l[i-1] <= macd_ex_s[i-1] and macd_ex_l[i] > macd_ex_s[i]))",
        "setup": lambda p: f"macd_ex_l, macd_ex_s, _ = macd(closes, {p.get('fast', 12)}, {p.get('slow', 26)}, {p.get('signal', 9)})",
        "params": {"fast": [12], "slow": [26], "signal": [9]},
    },
    "donchian_exit": {
        "desc": "唐奇安通道反向突破出場",
        "code": lambda p: f"dc_ex_u[i] is not None and dc_ex_l[i] is not None and ((open_trades[0].side == 'long' and closes[i] < dc_ex_l[i-1]) or (open_trades[0].side == 'short' and closes[i] > dc_ex_u[i-1]))",
        "setup": lambda p: f"dc_ex_u, dc_ex_l = donchian(candles[:i+1], {p.get('period', 10)})",
        "params": {"period": [10, 15, 20]},
    },
    "profit_target_pct": {
        "desc": "固定百分比止盈",
        "code": lambda p: f"((open_trades[0].side == 'long' and (closes[i] - open_trades[0].entry_price) / open_trades[0].entry_price * 100 >= {p.get('pct', 3)}) or (open_trades[0].side == 'short' and (open_trades[0].entry_price - closes[i]) / open_trades[0].entry_price * 100 >= {p.get('pct', 3)}))",
        "setup": lambda p: f"pass",
        "params": {"pct": [2, 3, 5, 8]},
    },
    "time_exit": {
        "desc": "持倉超時出場",
        "code": lambda p: f"(candles[i].time - open_trades[0].entry_time) / 3600000 >= {p.get('hours', 96)}",
        "setup": lambda p: f"pass",
        "params": {"hours": [24, 48, 96, 168]},
    },
    "trailing_high_low": {
        "desc": "前高/前低追蹤出場",
        "code": lambda p: f"((open_trades[0].side == 'long' and closes[i] < min(c.low for c in candles[max(0,i-{p.get('lookback',5)}):i])) or (open_trades[0].side == 'short' and closes[i] > max(c.high for c in candles[max(0,i-{p.get('lookback',5)}):i])))",
        "setup": lambda p: f"pass",
        "params": {"lookback": [3, 5, 8, 10]},
    },
    "vwap_cross_exit": {
        "desc": "VWAP 反穿出場",
        "code": lambda p: f"vwap_ex[i] is not None and ((open_trades[0].side == 'long' and vwap_ex[i] < 0.998) or (open_trades[0].side == 'short' and vwap_ex[i] > 1.002))",
        "setup": lambda p: f"vwap_ex = vwap_ratio(candles[:i+1], {p.get('period', 20)})",
        "params": {"period": [10, 20]},
    },
    "consecutive_against": {
        "desc": "連續反向 K 線出場",
        "code": lambda p: f"((open_trades[0].side == 'long' and all(candles[i-j].close < candles[i-j].open for j in range({p.get('count', 3)}))) or (open_trades[0].side == 'short' and all(candles[i-j].close > candles[i-j].open for j in range({p.get('count', 3)}))))",
        "setup": lambda p: f"pass",
        "params": {"count": [2, 3, 4]},
    },
    "obv_divergence_exit": {
        "desc": "OBV 背離出場",
        "code": lambda p: f"obv_ex_ema is not None and obv_ex_prev is not None and ((open_trades[0].side == 'long' and closes[i] > closes[i-1] and obv_ex_ema < obv_ex_prev) or (open_trades[0].side == 'short' and closes[i] < closes[i-1] and obv_ex_ema > obv_ex_prev))",
        "setup": lambda p: f"_obv_ex = obv(candles[:i+1]); _obv_ex_ema = ema(_obv_ex, {p.get('period', 10)}); obv_ex_ema = _obv_ex_ema[-1] if _obv_ex_ema else None; obv_ex_prev = _obv_ex_ema[-2] if len(_obv_ex_ema) > 1 else None",
        "params": {"period": [10, 20]},
    },
}

SL_TP_RANGES = {
    "stop_loss_pct": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
    "take_profit_pct": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
}


# ═══════════════════════════════════════════════════
# STRATEGY DNA: combination of genes
# ═══════════════════════════════════════════════════

def random_params(param_ranges):
    """Pick random params from ranges"""
    return {k: random.choice(v) if isinstance(v, list) else v for k, v in param_ranges.items()}


LONG_GENES = {"ema_cross_up", "rsi_oversold", "bb_lower_touch", "macd_golden", "price_above_ema",
              "stoch_rsi_oversold", "donchian_breakout_up", "obv_rising", "vwap_above", "consecutive_bullish",
              "funding_negative", "lsr_extreme_low",
              "fear_extreme", "top_trader_long", "taker_buy_surge", "usd_weak", "basis_negative",
              "smc_trend_bullish", "smc_choch_bullish", "smc_ob_support", "smc_fvg_bullish", "smc_ssl_swept",
              "eth_divergence_bull", "altcoin_risk_on", "active_addr_surge", "hashrate_drop"}
SHORT_GENES = {"ema_cross_down", "rsi_overbought", "bb_upper_touch", "macd_death", "price_below_ema",
               "stoch_rsi_overbought", "donchian_breakout_down", "obv_falling", "vwap_below", "consecutive_bearish",
               "funding_positive", "lsr_extreme_high", "oi_divergence",
               "greed_extreme", "top_trader_short", "taker_sell_surge", "usd_strong", "basis_positive",
               "smc_trend_bearish", "smc_choch_bearish", "smc_ob_resistance", "smc_fvg_bearish", "smc_bsl_swept",
               "eth_divergence_bear", "altcoin_risk_off"}
FILTER_GENES = {"price_above_ema", "price_below_ema", "volume_spike", "atr_squeeze",
                "obv_rising", "obv_falling", "vwap_above", "vwap_below", "oi_surge",
                "spot_dominance",
                "asia_session", "us_session", "weekend_filter",
                "vol_low_regime", "vol_expansion",
                "fees_spike", "corr_breakdown"}


def create_strategy_dna(allowed_entry=None, allowed_exit=None, direction="both"):
    """Create a random strategy DNA by combining genes.
    allowed_entry: set of gene names to use (None = all)
    allowed_exit: set of exit gene names to use (None = all)
    direction: "both", "long", or "short"
    """
    if direction == "both":
        # Check if allowed genes support both directions
        if allowed_entry is not None:
            has_long = bool(allowed_entry & (LONG_GENES - FILTER_GENES))
            has_short = bool(allowed_entry & (SHORT_GENES - FILTER_GENES))
            if has_long and has_short:
                side = "both"
            elif has_long:
                side = "long"
            elif has_short:
                side = "short"
            else:
                side = "both"  # all filters, fallback
        else:
            side = "both"
    else:
        side = direction

    def _pick_signal(direction):
        if direction == "long":
            pool = list(LONG_GENES - FILTER_GENES)
            filters = ["price_above_ema", "volume_spike"]
        else:
            pool = list(SHORT_GENES - FILTER_GENES)
            filters = ["price_below_ema", "volume_spike"]
        if allowed_entry is not None:
            pool = [g for g in pool if g in allowed_entry]
            filters = [g for g in filters if g in allowed_entry]
        if not pool:
            fallback = list((allowed_entry or set()) & (LONG_GENES | SHORT_GENES) - FILTER_GENES)
            pool = fallback if fallback else list(ENTRY_GENES.keys())[:1]
        signal = random.choice(pool)
        genes = [(signal, random_params(ENTRY_GENES[signal]["params"]))]
        if random.random() < 0.5 and filters:
            f = random.choice(filters)
            genes.append((f, random_params(ENTRY_GENES[f]["params"])))
        return genes

    if side == "both":
        long_genes = _pick_signal("long")
        short_genes = _pick_signal("short")
        # Avoid variable name conflicts: remove filter genes from short if long already has same type
        long_names = {g[0] for g in long_genes}
        conflict_pairs = {
            "price_above_ema": "price_below_ema",
            "price_below_ema": "price_above_ema",
            "obv_rising": "obv_falling",
            "obv_falling": "obv_rising",
            "vwap_above": "vwap_below",
            "vwap_below": "vwap_above",
        }
        short_genes = [(g, p) for g, p in short_genes
                       if g not in conflict_pairs or conflict_pairs[g] not in long_names]
        if not short_genes:
            # Fallback: just keep signal gene
            short_genes = _pick_signal("short")[:1]
        entry_genes = long_genes + short_genes  # combined for fingerprint/description
    else:
        long_genes = None
        short_genes = None
        entry_genes = _pick_signal(side)

    # Pick exit
    exit_pool = list(EXIT_GENES.keys())
    if allowed_exit is not None:
        exit_pool = [g for g in exit_pool if g in allowed_exit]
    if not exit_pool:
        exit_pool = list(EXIT_GENES.keys())
    exit_gene = random.choice(exit_pool)

    # Random SL/TP
    sl = random.choice(SL_TP_RANGES["stop_loss_pct"])
    tp = random.choice(SL_TP_RANGES["take_profit_pct"])
    if tp <= sl:
        tp = sl * 2

    dna = {
        "entry_genes": entry_genes,
        "exit_gene": (exit_gene, random_params(EXIT_GENES[exit_gene].get("params", {}))),
        "side": side,
        "sl": sl,
        "tp": tp,
    }
    if side == "both":
        dna["long_genes"] = long_genes
        dna["short_genes"] = short_genes
    return dna


def _infer_side(entry_genes):
    """Infer trade direction from gene names"""
    names = {g[0] for g in entry_genes}
    signal_genes = names - FILTER_GENES
    has_long = bool(signal_genes & LONG_GENES)
    has_short = bool(signal_genes & SHORT_GENES)
    if has_long and not has_short:
        return "long"
    if has_short and not has_long:
        return "short"
    # Mixed or only filters — pick based on majority
    lc = len(names & LONG_GENES)
    sc = len(names & SHORT_GENES)
    if lc >= sc:
        return "long"
    return "short"


def _extract_var_names(setup_str):
    """Extract variable names assigned in setup code (left side of =)."""
    import re
    names = []
    for line in setup_str.split("\n"):
        line = line.strip()
        if not line or line == "pass":
            continue
        # Handle tuple unpacking: a, b, c = ... or (a, b, c) = ...
        m = re.match(r'^[\(]?([a-zA-Z_][\w]*(?:\s*,\s*[a-zA-Z_][\w]*)*)[\)]?\s*=', line)
        if m:
            for v in m.group(1).split(","):
                v = v.strip()
                if v and not v.startswith("_"):
                    names.append(v)
    return names


def _rename_vars(text, var_map):
    """Replace variable names in code text according to var_map."""
    import re
    for old, new in var_map.items():
        # Word-boundary replacement to avoid partial matches
        text = re.sub(r'\b' + re.escape(old) + r'\b', new, text)
    return text


def _collect_gene_code(genes, used_vars=None):
    """Collect setup, null checks, conditions from a list of genes.
    Handles variable name conflicts across ALL genes by suffixing when needed.
    used_vars: optional dict to share variable tracking across multiple calls
               (e.g., between long_genes and short_genes in bidirectional strategies).
    """
    setups = []
    setup_seen = set()
    null_checks = []
    conditions = []
    min_bars = 50
    if used_vars is None:
        used_vars = {}  # var_name -> count of times assigned

    for gene_name, params in genes:
        gene = ENTRY_GENES[gene_name]

        setup_raw = gene["setup"](params)
        code_raw = gene["code"](params)
        null_raw = gene["null_check"]

        # Check if any variable in this gene's setup conflicts with already-used vars
        var_names = _extract_var_names(setup_raw)
        conflicting = [v for v in var_names if v in used_vars]

        if conflicting:
            # Build rename map for ALL vars in this gene (to keep them consistent)
            var_map = {}
            for v in var_names:
                idx = used_vars.get(v, 0)
                var_map[v] = f"{v}_{idx}"
                used_vars[v] = idx + 1
            setup_raw = _rename_vars(setup_raw, var_map)
            code_raw = _rename_vars(code_raw, var_map)
            null_raw = _rename_vars(null_raw, var_map)
        else:
            # First time seeing these vars, just track them
            for v in var_names:
                used_vars[v] = 1

        for line in setup_raw.split("\n"):
            stripped = line.strip()
            if stripped and stripped not in setup_seen:
                setup_seen.add(stripped)
                setups.append(stripped)
        null_checks.append(null_raw)
        conditions.append(code_raw)
        min_bars = max(min_bars, gene["min_bars"](params))
    return setups, null_checks, conditions, min_bars


def dna_to_code(dna):
    """Convert strategy DNA to executable Python code"""
    # ── Dedup genes by name (last defense) ──
    def _dedup_genes(genes):
        seen = set()
        out = []
        for name, params in genes:
            if name not in seen:
                seen.add(name)
                out.append((name, params))
        return out

    dna = dict(dna)  # shallow copy to avoid mutating original
    dna["entry_genes"] = _dedup_genes(dna.get("entry_genes", []))
    if "long_genes" in dna:
        dna["long_genes"] = _dedup_genes(dna["long_genes"])
    if "short_genes" in dna:
        dna["short_genes"] = _dedup_genes(dna["short_genes"])

    exit_gene_name, exit_params = dna["exit_gene"]
    side = dna.get("side", _infer_side(dna["entry_genes"]))

    # Exit setup
    exit_gene = EXIT_GENES[exit_gene_name]
    exit_setup_raw = exit_gene["setup"](exit_params)
    exit_setup_lines = [line.strip() for line in exit_setup_raw.split("\n") if line.strip()]
    exit_setup = "\n        ".join(exit_setup_lines)
    exit_code = exit_gene["code"](exit_params)

    if side == "both" and "long_genes" in dna and "short_genes" in dna:
        # Bidirectional strategy — share used_vars to avoid cross-side variable conflicts
        shared_vars = {}
        l_setups, l_nulls, l_conds, l_min = _collect_gene_code(dna["long_genes"], shared_vars)
        s_setups, s_nulls, s_conds, s_min = _collect_gene_code(dna["short_genes"], shared_vars)
        # Merge setups preserving order, dedup
        seen = set()
        all_setups = []
        for line in l_setups + s_setups:
            if line not in seen:
                seen.add(line)
                all_setups.append(line)
        min_bars = max(l_min, s_min)

        setup_code = "\n    ".join(all_setups)
        l_null = " or ".join(l_nulls)
        s_null = " or ".join(s_nulls)
        l_entry = " and ".join(l_conds)
        s_entry = " and ".join(s_conds)

        code = f"""def strategy(candles, i, indicators, open_trades):
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < {min_bars}:
        return []
    actions = []
    {setup_code}
    if not open_trades:
        if not ({l_null}) and {l_entry}:
            actions.append({{"action": "buy"}})
        elif not ({s_null}) and {s_entry}:
            actions.append({{"action": "sell"}})
    if open_trades:
        {exit_setup}
        if {exit_code}:
            actions.append({{"action": "close"}})
    return actions
"""
    else:
        # Single direction
        entry_genes = dna["entry_genes"]
        setups, null_checks, conditions, min_bars = _collect_gene_code(entry_genes)

        setup_code = "\n    ".join(setups)
        null_code = " or ".join(null_checks)
        entry_code = " and ".join(conditions)
        inferred_side = _infer_side(entry_genes) if side != "both" else side
        action = "buy" if inferred_side == "long" else "sell"

        code = f"""def strategy(candles, i, indicators, open_trades):
    closes = [c.close for c in candles[:i+1]]
    if len(closes) < {min_bars}:
        return []
    actions = []
    {setup_code}
    if {null_code}:
        return []
    if not open_trades and {entry_code}:
        actions.append({{"action": "{action}"}})
    if open_trades:
        {exit_setup}
        if {exit_code}:
            actions.append({{"action": "close"}})
    return actions
"""
    return code


PARAM_NAMES_ZH = {
    "fast": "快線", "slow": "慢線", "period": "週期", "level": "閾值",
    "std": "標準差", "mult": "倍數", "count": "根數", "lookback": "回看",
    "rsi_period": "RSI週期", "stoch_period": "隨機週期",
    "high": "高位", "low": "低位", "pct": "百分比", "hours": "小時",
    "signal": "信號線", "bars": "K線數", "threshold": "閾值",
}


def dna_to_description(dna):
    """Human-readable description of strategy DNA"""
    side = dna.get("side", _infer_side(dna["entry_genes"]))
    exit_name, exit_params = dna["exit_gene"] if isinstance(dna["exit_gene"], (list, tuple)) else (dna["exit_gene"], {})
    exit_desc = EXIT_GENES.get(exit_name, {}).get("desc", exit_name)

    if side == "both" and "long_genes" in dna and "short_genes" in dna:
        long_parts = [ENTRY_GENES.get(g, {}).get("desc", g) for g, _ in dna["long_genes"]]
        short_parts = [ENTRY_GENES.get(g, {}).get("desc", g) for g, _ in dna["short_genes"]]
        return f"做多: {' + '.join(long_parts)} | 做空: {' + '.join(short_parts)} | 出場: {exit_desc} | 止損:{dna['sl']}% 止盈:{dna['tp']}%"
    else:
        parts = [ENTRY_GENES.get(g, {}).get("desc", g) for g, _ in dna["entry_genes"]]
        direction = "做多" if side == "long" else "做空"
        return f"{direction}: {' + '.join(parts)} | 出場: {exit_desc} | 止損:{dna['sl']}% 止盈:{dna['tp']}%"


# ═══════════════════════════════════════════════════
# GENETIC OPERATIONS
# ═══════════════════════════════════════════════════

def _compatible_pool(dna, allowed_entry=None, side_hint=None):
    """Get gene pool compatible with DNA's side.
    side_hint: force "long"/"short"/"both" pool. If None, infer from DNA.
    """
    side = side_hint or dna.get("side") or _infer_side(dna["entry_genes"])
    if side == "both":
        pool = list(LONG_GENES | SHORT_GENES | FILTER_GENES)
    elif side == "long":
        pool = list(LONG_GENES | FILTER_GENES)
    else:
        pool = list(SHORT_GENES | FILTER_GENES)
    if allowed_entry is not None:
        pool = [g for g in pool if g in allowed_entry]
    return pool if pool else list(ENTRY_GENES.keys())


def _sync_bidirectional(dna, allowed_entry=None):
    """Sync long_genes/short_genes from entry_genes for bidirectional strategies"""
    if dna.get("side") != "both" or "long_genes" not in dna:
        return
    long_g = []
    short_g = []
    for g, p in dna["entry_genes"]:
        if g in ENTRY_GENES:
            # Custom genes have explicit type
            gtype = ENTRY_GENES[g].get("type")
            if not gtype:
                # Infer type for built-in genes
                if g in FILTER_GENES and g not in LONG_GENES and g not in SHORT_GENES:
                    gtype = "filter"
                elif g in LONG_GENES:
                    gtype = "long"
                elif g in SHORT_GENES:
                    gtype = "short"
                else:
                    gtype = "filter"  # fallback

            if gtype == "long":
                long_g.append((g, p))
            elif gtype == "short":
                short_g.append((g, p))
            else:  # filter — add to both
                long_g.append((g, p))
                short_g.append((g, p))
    # Ensure at least one signal per side (respect allowed_entry)
    if not long_g:
        long_pool = list(LONG_GENES - FILTER_GENES)
        if allowed_entry is not None:
            long_pool = [g for g in long_pool if g in allowed_entry]
        if not long_pool:
            long_pool = list(LONG_GENES - FILTER_GENES)
        fallback = random.choice(long_pool)
        long_g = [(fallback, random_params(ENTRY_GENES[fallback]["params"]))]
    if not short_g:
        short_pool = list(SHORT_GENES - FILTER_GENES)
        if allowed_entry is not None:
            short_pool = [g for g in short_pool if g in allowed_entry]
        if not short_pool:
            short_pool = list(SHORT_GENES - FILTER_GENES)
        fallback = random.choice(short_pool)
        short_g = [(fallback, random_params(ENTRY_GENES[fallback]["params"]))]
    dna["long_genes"] = long_g
    dna["short_genes"] = short_g


def mutate(dna, allowed_entry=None, allowed_exit=None):
    """Mutate a strategy DNA"""
    new_dna = copy.deepcopy(dna)
    existing_names = {g[0] for g in new_dna["entry_genes"]}
    mutation = random.choice(["swap_gene", "tweak_params", "change_sl_tp", "add_gene", "remove_gene", "change_exit"])

    if mutation == "swap_gene" and new_dna["entry_genes"]:
        idx = random.randint(0, len(new_dna["entry_genes"]) - 1)
        old_gene = new_dna["entry_genes"][idx][0]
        # Pick from same-side pool for bidirectional strategies
        if new_dna.get("side") == "both":
            if old_gene in LONG_GENES:
                pool = _compatible_pool(new_dna, allowed_entry, side_hint="long")
                pool = [g for g in pool if g in LONG_GENES]
            elif old_gene in SHORT_GENES:
                pool = _compatible_pool(new_dna, allowed_entry, side_hint="short")
                pool = [g for g in pool if g in SHORT_GENES]
            else:
                pool = _compatible_pool(new_dna, allowed_entry, side_hint="both")
                pool = [g for g in pool if g in FILTER_GENES]
            if not pool:
                pool = _compatible_pool(new_dna, allowed_entry)
        else:
            pool = _compatible_pool(new_dna, allowed_entry)
        # Avoid duplicates: exclude genes already in DNA (except the one being replaced)
        others = existing_names - {old_gene}
        pool = [g for g in pool if g not in others]
        if pool:
            new_gene = random.choice(pool)
            new_dna["entry_genes"][idx] = (new_gene, random_params(ENTRY_GENES[new_gene]["params"]))

    elif mutation == "tweak_params" and new_dna["entry_genes"]:
        idx = random.randint(0, len(new_dna["entry_genes"]) - 1)
        gene_name, params = new_dna["entry_genes"][idx]
        new_params = random_params(ENTRY_GENES[gene_name]["params"])
        new_dna["entry_genes"][idx] = (gene_name, new_params)

    elif mutation == "change_sl_tp":
        new_dna["sl"] = random.choice(SL_TP_RANGES["stop_loss_pct"])
        new_dna["tp"] = random.choice(SL_TP_RANGES["take_profit_pct"])
        if new_dna["tp"] <= new_dna["sl"]:
            new_dna["tp"] = new_dna["sl"] * 2

    elif mutation == "add_gene" and len(new_dna["entry_genes"]) < 3:
        pool = _compatible_pool(new_dna, allowed_entry)
        # Avoid duplicates: exclude genes already in DNA
        pool = [g for g in pool if g not in existing_names]
        if pool:
            new_gene = random.choice(pool)
            new_dna["entry_genes"].append((new_gene, random_params(ENTRY_GENES[new_gene]["params"])))

    elif mutation == "remove_gene" and len(new_dna["entry_genes"]) > 1:
        idx = random.randint(0, len(new_dna["entry_genes"]) - 1)
        new_dna["entry_genes"].pop(idx)

    elif mutation == "change_exit":
        exit_pool = list(EXIT_GENES.keys())
        if allowed_exit is not None:
            exit_pool = [g for g in exit_pool if g in allowed_exit]
        if not exit_pool:
            exit_pool = list(EXIT_GENES.keys())
        new_exit = random.choice(exit_pool)
        new_dna["exit_gene"] = (new_exit, random_params(EXIT_GENES[new_exit].get("params", {})))

    _sync_bidirectional(new_dna, allowed_entry)
    return new_dna


def crossover(dna1, dna2, allowed_entry=None, allowed_exit=None):
    """Crossover two strategy DNAs"""
    child = copy.deepcopy(dna1)
    existing_names = {g[0] for g in child["entry_genes"]}
    # Take some genes from parent 2 (only if allowed and not duplicate)
    if dna2["entry_genes"]:
        donor_gene = random.choice(dna2["entry_genes"])
        gene_name = donor_gene[0]
        is_allowed = allowed_entry is None or gene_name in allowed_entry
        if is_allowed:
            if gene_name not in existing_names:
                if len(child["entry_genes"]) < 4:
                    child["entry_genes"].append(copy.deepcopy(donor_gene))
                else:
                    idx = random.randint(0, len(child["entry_genes"]) - 1)
                    child["entry_genes"][idx] = copy.deepcopy(donor_gene)
            else:
                # Already exists — just update params
                for idx, (n, _) in enumerate(child["entry_genes"]):
                    if n == gene_name:
                        child["entry_genes"][idx] = copy.deepcopy(donor_gene)
                        break
    # Maybe take exit from parent 2 (only if allowed)
    if random.random() > 0.5:
        exit_name = dna2["exit_gene"][0]
        if allowed_exit is None or exit_name in allowed_exit:
            child["exit_gene"] = copy.deepcopy(dna2["exit_gene"])
    # Maybe take SL/TP from parent 2
    if random.random() > 0.5:
        child["sl"] = dna2["sl"]
        child["tp"] = dna2["tp"]
    _sync_bidirectional(child, allowed_entry)
    return child


# ═══════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════

def score_strategy(metrics, wf_overfit=None):
    """Score a strategy for ranking. wf_overfit = walk_forward overfit_ratio if available."""
    if not metrics or "error" in metrics:
        return -999
    trades = metrics.get("total_trades", 0)
    if trades < 5:
        return -999

    roi = metrics.get("roi_pct", 0)
    sharpe = min(metrics.get("sharpe_ratio", 0), 10)
    pf = min(metrics.get("profit_factor", 0), 20)
    rr = min(metrics.get("avg_rr", 0), 10)       # cap RR too
    wr = metrics.get("win_rate", 0)
    dd = metrics.get("max_drawdown_pct", 100)

    dd_penalty = max(0, dd - 10) * 3

    base = round(
        roi * 0.3 +
        sharpe * 5 +
        pf * 10 +
        rr * 5 +
        wr * 0.2 -
        dd_penalty, 2
    )

    # Low trade count penalty: < 20 trades gets scaled down
    if trades < 20:
        base *= (0.5 + 0.5 * trades / 20)  # 5 trades → 0.625x, 10 → 0.75x, 15 → 0.875x

    # Walk-forward penalty/bonus
    if wf_overfit is not None:
        if wf_overfit >= 999:
            base *= 0.3   # test set lost money → slash 70%
        elif wf_overfit > 5:
            base *= 0.5   # heavy overfit → slash 50%
        elif wf_overfit > 3:
            base *= 0.7   # moderate overfit → slash 30%
        elif wf_overfit <= 2:
            base *= 1.2   # good generalization → bonus 20%

    # Long/Short balance penalty (for bidirectional strategies)
    long_t = metrics.get("long_trades", 0)
    short_t = metrics.get("short_trades", 0)
    if long_t + short_t >= 5:
        if long_t == 0 or short_t == 0:
            base *= 0.6   # pure single-side in "both" mode → slash 40%
        else:
            ratio = min(long_t, short_t) / max(long_t, short_t)
            if ratio < 0.1:
                base *= 0.7   # severe imbalance → slash 30%
            elif ratio < 0.25:
                base *= 0.85  # moderate imbalance → slash 15%

    return round(base, 2)


# ═══════════════════════════════════════════════════
# STRATEGY OPTIMIZER (workbench)
# ═══════════════════════════════════════════════════

def optimize_strategy(candles, dna, modifications=None, on_progress=None, extra_indicators=None):
    """
    Optimize a strategy by sweeping parameters and optionally adding/removing genes.
    
    modifications: {
        "add_genes": [{"name": "rsi_oversold", "params": {"period": [7,14], "level": [25,30]}}],
        "remove_genes": ["price_above_ema"],
        "param_overrides": {"ema_cross_up": {"fast": [5,7,9,12,15], "slow": [15,21,30,50]}},
        "sl_range": [1.0, 1.5, 2.0, 3.0],
        "tp_range": [2.0, 4.0, 6.0, 8.0],
        "exit_genes": ["rsi_exit_high", "atr_trailing"],  # try multiple exits
        "custom_genes": [{"name": "my_gene", "code": "...", "setup": "...", "null_check": "...", "min_bars": 50}],
    }
    """
    from llm_pipeline import compile_strategy, validate_strategy

    mods = modifications or {}
    base_dna = copy.deepcopy(dna)

    # Apply gene additions (sync to long_genes/short_genes for bidirectional)
    for gene_info in mods.get("add_genes", []):
        name = gene_info["name"]
        if name in ENTRY_GENES:
            params = random_params(ENTRY_GENES[name]["params"])
            base_dna["entry_genes"].append((name, params))
            # Sync to long_genes/short_genes for side=="both"
            if base_dna.get("side") == "both" and "long_genes" in base_dna:
                if name in LONG_GENES:
                    base_dna["long_genes"].append((name, params))
                elif name in SHORT_GENES:
                    base_dna["short_genes"].append((name, params))
                if name in FILTER_GENES:
                    # Filters go to both sides
                    if (name, params) not in base_dna.get("long_genes", []):
                        base_dna["long_genes"].append((name, params))
                    if (name, params) not in base_dna.get("short_genes", []):
                        base_dna["short_genes"].append((name, params))

    # Apply gene removals (sync to long_genes/short_genes for bidirectional)
    remove_set = set(mods.get("remove_genes", []))
    if remove_set:
        base_dna["entry_genes"] = [(n, p) for n, p in base_dna["entry_genes"] if n not in remove_set]
        if base_dna.get("side") == "both":
            if "long_genes" in base_dna:
                base_dna["long_genes"] = [(n, p) for n, p in base_dna["long_genes"] if n not in remove_set]
            if "short_genes" in base_dna:
                base_dna["short_genes"] = [(n, p) for n, p in base_dna["short_genes"] if n not in remove_set]
        if not base_dna["entry_genes"]:
            # Can't remove all genes, keep at least one
            side = dna.get("side", "long")
            pool = list(LONG_GENES - FILTER_GENES) if side == "long" else list(SHORT_GENES - FILTER_GENES)
            fallback = random.choice(pool)
            base_dna["entry_genes"] = [(fallback, random_params(ENTRY_GENES[fallback]["params"]))]

    # Register custom genes temporarily
    custom_gene_names = []
    for cg in mods.get("custom_genes", []):
        gname = f"custom_{cg['name']}"
        # Map side to gene type: long/short/filter
        cg_side = cg.get("side", "long")
        if cg_side == "做多" or cg_side == "long":
            gene_type = "long"
        elif cg_side == "做空" or cg_side == "short":
            gene_type = "short"
        else:
            gene_type = "filter"
        ENTRY_GENES[gname] = {
            "desc": cg.get("desc", cg["name"]),
            "params": cg.get("params", {}),
            "code": lambda p, c=cg: c["code"],
            "setup": lambda p, c=cg: c["setup"],
            "null_check": cg.get("null_check", "False"),
            "min_bars": lambda p, c=cg: c.get("min_bars", 50),
            "type": gene_type,
        }
        custom_gene_names.append(gname)
        base_dna["entry_genes"].append((gname, {}))

    # Sync custom genes into long_genes/short_genes for bidirectional strategies
    if base_dna.get("side") == "both" and "long_genes" in base_dna:
        for cg in mods.get("custom_genes", []):
            gname = f"custom_{cg['name']}"
            cg_side = cg.get("side", "long")
            if cg_side in ("做多", "long"):
                base_dna["long_genes"].append((gname, {}))
            elif cg_side in ("做空", "short"):
                base_dna["short_genes"].append((gname, {}))
            else:
                # Filter: add to both sides
                base_dna["long_genes"].append((gname, {}))
                base_dna["short_genes"].append((gname, {}))

    # Build parameter grid from DNA genes
    param_combos = [{}]

    # Gene parameter variations
    param_overrides = mods.get("param_overrides", {})
    for idx, (gene_name, gene_params) in enumerate(base_dna["entry_genes"]):
        if gene_name in param_overrides:
            ranges = param_overrides[gene_name]
        elif gene_name in ENTRY_GENES:
            ranges = ENTRY_GENES[gene_name]["params"]
        else:
            continue

        if not ranges:
            continue

        new_combos = []
        keys = list(ranges.keys())
        for combo in param_combos:
            for vals in itertools.product(*[ranges[k] if isinstance(ranges[k], list) else [ranges[k]] for k in keys]):
                c = combo.copy()
                c[f"gene_{idx}"] = dict(zip(keys, vals))
                new_combos.append(c)
        param_combos = new_combos

    # SL/TP variations
    sl_range = mods.get("sl_range", [base_dna["sl"]])
    tp_range = mods.get("tp_range", [base_dna["tp"]])
    exit_genes = mods.get("exit_genes", [base_dna["exit_gene"][0]])

    # Cap total combinations
    max_combos = 500
    total_combos = len(param_combos) * len(sl_range) * len(tp_range) * len(exit_genes)

    if total_combos > max_combos:
        # Switch to random sampling
        all_results = _optimize_random(
            candles, base_dna, param_combos, sl_range, tp_range, exit_genes,
            max_combos, on_progress, extra_indicators
        )
    else:
        all_results = _optimize_grid(
            candles, base_dna, param_combos, sl_range, tp_range, exit_genes,
            on_progress, extra_indicators
        )

    # Cleanup custom genes
    for gname in custom_gene_names:
        ENTRY_GENES.pop(gname, None)

    # Sort and deduplicate before returning
    all_results.sort(key=lambda x: -x["score"])
    seen_fingerprints = set()
    unique = []
    for r in all_results:
        m = r["metrics"]
        fp = (m.get("roi_pct", 0), m.get("win_rate", 0), m.get("total_trades", 0),
              m.get("profit_factor", 0), m.get("max_drawdown_pct", 0), r["dna"]["sl"], r["dna"]["tp"])
        if fp not in seen_fingerprints:
            seen_fingerprints.add(fp)
            unique.append(r)
        if len(unique) >= 10:
            break
    return unique


def _optimize_grid(candles, base_dna, param_combos, sl_range, tp_range, exit_genes, on_progress=None, extra_indicators=None):
    """Grid search all combinations"""
    from llm_pipeline import compile_strategy, validate_strategy

    results = []
    total = len(param_combos) * len(sl_range) * len(tp_range) * len(exit_genes)
    done = 0

    for combo in param_combos:
        for sl in sl_range:
            for tp in tp_range:
                if tp <= sl:
                    done += len(exit_genes)
                    continue
                for exit_name in exit_genes:
                    done += 1
                    trial_dna = copy.deepcopy(base_dna)
                    trial_dna["sl"] = sl
                    trial_dna["tp"] = tp

                    # Apply gene params from combo
                    for key, val in combo.items():
                        if key.startswith("gene_"):
                            idx = int(key.split("_")[1])
                            if idx < len(trial_dna["entry_genes"]):
                                gname = trial_dna["entry_genes"][idx][0]
                                trial_dna["entry_genes"][idx] = (gname, val)

                    # Set exit gene
                    if exit_name in EXIT_GENES:
                        trial_dna["exit_gene"] = (exit_name, random_params(EXIT_GENES[exit_name].get("params", {})))

                    _sync_bidirectional(trial_dna)

                    result = _evaluate_dna(candles, trial_dna, extra_indicators)
                    if result:
                        results.append(result)

                    if on_progress and done % 10 == 0:
                        on_progress(done, total)

    if on_progress:
        on_progress(total, total)
    return results


def _optimize_random(candles, base_dna, param_combos, sl_range, tp_range, exit_genes, n_trials, on_progress=None, extra_indicators=None):
    """Random sampling when grid is too large"""
    from llm_pipeline import compile_strategy, validate_strategy

    results = []
    for i in range(n_trials):
        trial_dna = copy.deepcopy(base_dna)
        trial_dna["sl"] = random.choice(sl_range)
        trial_dna["tp"] = random.choice(tp_range)
        if trial_dna["tp"] <= trial_dna["sl"]:
            trial_dna["tp"] = trial_dna["sl"] * 2

        # Random gene params
        combo = random.choice(param_combos) if param_combos else {}
        for key, val in combo.items():
            if key.startswith("gene_"):
                idx = int(key.split("_")[1])
                if idx < len(trial_dna["entry_genes"]):
                    gname = trial_dna["entry_genes"][idx][0]
                    trial_dna["entry_genes"][idx] = (gname, val)

        # Random exit
        exit_name = random.choice(exit_genes)
        if exit_name in EXIT_GENES:
            trial_dna["exit_gene"] = (exit_name, random_params(EXIT_GENES[exit_name].get("params", {})))

        _sync_bidirectional(trial_dna)

        result = _evaluate_dna(candles, trial_dna, extra_indicators)
        if result:
            results.append(result)

        if on_progress and (i + 1) % 10 == 0:
            on_progress(i + 1, n_trials)

    if on_progress:
        on_progress(n_trials, n_trials)
    return results


def _evaluate_dna(candles, dna, extra_indicators=None):
    """Evaluate a single DNA, return result dict or None"""
    from llm_pipeline import compile_strategy, validate_strategy

    try:
        code = dna_to_code(dna)
        strategy_fn, err = compile_strategy(code)
        if err:
            return None

        ok, err = validate_strategy(strategy_fn, candles, 20)
        if not ok:
            return None

        config = StrategyConfig(
            initial_capital=10000, position_size_pct=10,
            stop_loss_pct=dna["sl"], take_profit_pct=dna["tp"],
        )
        engine = BacktestEngine(config)
        trades = engine.run(candles, strategy_fn, extra_indicators=extra_indicators)
        metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

        wf_overfit = None
        try:
            wf = walk_forward(candles, strategy_fn, config)
            wf_overfit = wf["overfit_ratio"]
            wf_data = {
                "train_roi": wf["train"].get("roi_pct", 0),
                "test_roi": wf["test"].get("roi_pct", 0),
                "overfit_ratio": wf["overfit_ratio"],
            }
        except Exception:
            wf_data = None

        sc = score_strategy(metrics, wf_overfit)
        if sc <= -999:
            return None

        return {
            "dna": dna,
            "code": code,
            "metrics": metrics,
            "score": sc,
            "walk_forward": wf_data,
            "description": dna_to_description(dna),
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════
# AUTO RESEARCH LOOP
# ═══════════════════════════════════════════════════

def run_research(candles, generations=10, population_size=20, top_k=5, verbose=True, on_progress=None,
                  allowed_entry=None, allowed_exit=None, custom_genes=None, direction="both",
                  extra_indicators=None):
    """
    Evolutionary strategy research loop.
    
    allowed_entry: set of entry gene names to use (None = all)
    allowed_exit: set of exit gene names to use (None = all)
    custom_genes: list of custom gene dicts to register temporarily
    """
    # Register custom genes
    custom_gene_names = []
    if custom_genes:
        for cg in custom_genes:
            gname = f"custom_{cg['name']}"
            ENTRY_GENES[gname] = {
                "desc": cg.get("desc", cg["name"]),
                "params": cg.get("params", {}),
                "code": lambda p, c=cg: c["code"],
                "setup": lambda p, c=cg: c["setup"],
                "null_check": cg.get("null_check", "False"),
                "min_bars": lambda p, c=cg: c.get("min_bars", 50),
            }
            custom_gene_names.append(gname)
            # Add to allowed if filtering
            if allowed_entry is not None:
                allowed_entry = set(allowed_entry) | {gname}
            # Add to appropriate side pool
            side = cg.get("side", "long")
            if side == "long":
                LONG_GENES.add(gname)
            else:
                SHORT_GENES.add(gname)
    print(f"🧬 自動策略研發 | {generations} 代 x {population_size} 個體")
    print(f"   數據: {len(candles)} 根 K 線")
    print()

    # Initial population
    from llm_pipeline import compile_strategy, validate_strategy

    population = [create_strategy_dna(allowed_entry, allowed_exit, direction) for _ in range(population_size)]
    all_time_best = []
    prev_best_score = -999
    stagnant_gens = 0
    early_stop_patience = 3  # stop after N gens with no improvement

    def _fingerprint(dna):
        """Unique key based on gene names + params + exit gene + SL/TP"""
        entry = tuple(sorted((g[0], tuple(sorted(p.items()))) for g, p in dna["entry_genes"]))
        exit_name = dna["exit_gene"][0]
        exit_params = tuple(sorted(dna["exit_gene"][1].items()))
        long_g = tuple(sorted((g[0], tuple(sorted(p.items()))) for g, p in dna.get("long_genes", [])))
        short_g = tuple(sorted((g[0], tuple(sorted(p.items()))) for g, p in dna.get("short_genes", [])))
        return (entry, long_g, short_g, exit_name, exit_params, dna["sl"], dna["tp"])

    for gen in range(generations):
        gen_results = []
        errors = 0

        for dna in population:
            # Retry up to 5 times on compile/validate/no-trade failures
            for _attempt in range(5):
                try:
                    code = dna_to_code(dna)
                    strategy_fn, err = compile_strategy(code)
                    if err:
                        dna = mutate(dna, allowed_entry, allowed_exit)
                        continue

                    ok, err = validate_strategy(strategy_fn, candles, 20)
                    if not ok:
                        dna = mutate(dna, allowed_entry, allowed_exit)
                        continue

                    config = StrategyConfig(
                        initial_capital=10000, position_size_pct=10,
                        stop_loss_pct=dna["sl"], take_profit_pct=dna["tp"],
                    )
                    engine = BacktestEngine(config)
                    trades = engine.run(candles, strategy_fn, extra_indicators=extra_indicators)
                    metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

                    # Quick walk-forward for scoring
                    wf_overfit = None
                    try:
                        wf = walk_forward(candles, strategy_fn, config)
                        wf_overfit = wf["overfit_ratio"]
                    except Exception:
                        pass

                    sc = score_strategy(metrics, wf_overfit)

                    if sc <= -999:
                        # No trades or too few — mutate and retry
                        dna = mutate(dna, allowed_entry, allowed_exit)
                        continue

                    gen_results.append({
                        "dna": dna,
                        "code": code,
                        "metrics": metrics,
                        "score": sc,
                    })
                    break
                except Exception:
                    dna = mutate(dna, allowed_entry, allowed_exit)
            else:
                errors += 1

        # Sort by score
        gen_results.sort(key=lambda x: -x["score"])
        valid = [r for r in gen_results if r["score"] > -999]

        if verbose and valid:
            best = valid[0]
            m = best["metrics"]
            print(f"  Gen {gen+1:>2} | 有效: {len(valid)}/{population_size} | 錯誤: {errors}")
            print(f"         最佳 Score: {best['score']:.1f} | ROI: {m.get('roi_pct', 0)}% | "
                  f"WR: {m.get('win_rate', 0)}% | PF: {m.get('profit_factor', 0)} | "
                  f"Sharpe: {m.get('sharpe_ratio', 0)} | DD: {m.get('max_drawdown_pct', 0)}%")
            print(f"         {dna_to_description(best['dna'])}")

        if on_progress:
            on_progress(gen, valid)

        # Early stopping: check if best score improved
        current_best = valid[0]["score"] if valid else -999
        if current_best > prev_best_score + 0.5:  # meaningful improvement threshold
            prev_best_score = current_best
            stagnant_gens = 0
        else:
            stagnant_gens += 1

        if stagnant_gens >= early_stop_patience and gen >= 4:  # at least 5 gens before stopping
            if verbose:
                print(f"  ⏹ 早停: 連續 {stagnant_gens} 代無提升，停止進化")
            if on_progress:
                on_progress(gen, valid)  # final progress update
            break

        # Keep top performers (with diversity)
        for v in valid:
            fp = _fingerprint(v["dna"])
            m = v["metrics"]
            mk = (str(m.get("roi_pct", 0)), str(m.get("win_rate", 0)), str(m.get("total_trades", 0)), str(m.get("profit_factor", 0)))
            # Skip if same fingerprint or same metrics already in best
            fp_exists = any(_fingerprint(a["dna"]) == fp for a in all_time_best)
            mk_exists = any(
                (str(a["metrics"].get("roi_pct", 0)), str(a["metrics"].get("win_rate", 0)),
                 str(a["metrics"].get("total_trades", 0)), str(a["metrics"].get("profit_factor", 0))) == mk
                for a in all_time_best
            )
            if not fp_exists and not mk_exists:
                all_time_best.append(v)
        all_time_best.sort(key=lambda x: -x["score"])
        all_time_best = all_time_best[:top_k * 3]

        # Create next generation
        survivors = valid[:top_k] if valid else [{"dna": create_strategy_dna(allowed_entry, allowed_exit, direction)} for _ in range(top_k)]
        new_population = []

        # Elitism: keep top 2
        for s in survivors[:2]:
            new_population.append(copy.deepcopy(s["dna"]))

        # Mutations
        while len(new_population) < population_size * 0.5:
            parent = random.choice(survivors)["dna"]
            new_population.append(mutate(parent, allowed_entry, allowed_exit))

        # Crossovers
        while len(new_population) < population_size * 0.7:
            p1 = random.choice(survivors)["dna"]
            p2 = random.choice(survivors)["dna"]
            new_population.append(crossover(p1, p2, allowed_entry, allowed_exit))

        # Fresh blood (30%)
        while len(new_population) < population_size:
            new_population.append(create_strategy_dna(allowed_entry, allowed_exit, direction))

        population = new_population

    # Final results — deduplicate by strategy fingerprint
    all_time_best.sort(key=lambda x: -x["score"])

    seen_fp = set()
    seen_metrics = set()
    unique = []
    for r in all_time_best:
        fp = _fingerprint(r["dna"])
        m = r["metrics"]
        # Use string repr to avoid float precision issues
        metrics_key = (
            str(m.get("roi_pct", 0)),
            str(m.get("win_rate", 0)),
            str(m.get("total_trades", 0)),
            str(m.get("profit_factor", 0)),
            str(m.get("max_drawdown_pct", 0)),
        )
        # Skip if same DNA fingerprint OR same metrics output
        if fp in seen_fp or metrics_key in seen_metrics:
            continue
        seen_fp.add(fp)
        seen_metrics.add(metrics_key)
        unique.append(r)
        if len(unique) >= top_k:
            break

    # If not enough unique, fill with remaining (allow duplicates)
    if len(unique) < top_k:
        for r in all_time_best:
            if r not in unique:
                unique.append(r)
            if len(unique) >= top_k:
                break

    # Re-sort by score before returning
    unique.sort(key=lambda x: -x["score"])
    # Cleanup custom genes
    for gname in custom_gene_names:
        ENTRY_GENES.pop(gname, None)
        LONG_GENES.discard(gname)
        SHORT_GENES.discard(gname)

    return unique[:top_k]


def format_research_results(results, candles):
    """Format research results with walk-forward validation"""
    from llm_pipeline import compile_strategy

    lines = []
    lines.append("\n" + "=" * 60)
    lines.append("  🏆 自動研發結果")
    lines.append("=" * 60)

    for i, r in enumerate(results):
        m = r["metrics"]
        lines.append(f"\n  #{i+1} | Score: {r['score']:.1f}")
        lines.append(f"  {dna_to_description(r['dna'])}")
        lines.append(f"  交易: {m['total_trades']} | 勝率: {m['win_rate']}% | RR: {m['avg_rr']}")
        lines.append(f"  ROI: {m['roi_pct']}% | PF: {m['profit_factor']} | Sharpe: {m['sharpe_ratio']}")
        lines.append(f"  回撤: {m['max_drawdown_pct']}% | ${m['initial_capital']:,.0f} → ${m['final_capital']:,.2f}")

        # Walk-forward
        try:
            strategy_fn, _ = compile_strategy(r["code"])
            config = StrategyConfig(
                initial_capital=10000, position_size_pct=10,
                stop_loss_pct=r["dna"]["sl"], take_profit_pct=r["dna"]["tp"],
            )
            wf = walk_forward(candles, strategy_fn, config)
            lines.append(f"  WF: 訓練 {wf['train'].get('roi_pct', 0)}% → 測試 {wf['test'].get('roi_pct', 0)}%")
        except:
            lines.append(f"  WF: 驗證失敗")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("🧬 Strategy AI - Auto Research")
    print("拉取數據...")

    candles = fetch_candles_extended("BTCUSDT", "4h", 1000)
    start = datetime.fromtimestamp(candles[0].time / 1000, TZ8)
    end = datetime.fromtimestamp(candles[-1].time / 1000, TZ8)
    print(f"  {len(candles)} 根 4h K 線 | {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")
    print()

    # Run evolutionary research
    results = run_research(
        candles,
        generations=5,
        population_size=10,
        top_k=3,
    )

    # Format and print results
    report = format_research_results(results, candles)
    print(report)

    # Save best strategies
    output = {
        "timestamp": datetime.now(TZ8).isoformat(),
        "data_range": f"{start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}",
        "candles": len(candles),
        "results": [{
            "rank": i + 1,
            "score": r["score"],
            "description": dna_to_description(r["dna"]),
            "metrics": r["metrics"],
            "code": r["code"],
        } for i, r in enumerate(results)],
    }
    with open(os.path.join(WORK, "research_results.json"), "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n💾 結果已保存: research_results.json")
