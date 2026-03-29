#!/usr/bin/env python3
"""
Strategy AI - Factor Research
因子驗證模組：IC 分析、衰減曲線、分組回測、因子篩選

把「碰運氣」變成「有統計依據」。
"""
import math, os, sys
from backtest_engine import (
    Candle, fetch_candles_extended,
    ema, sma, rsi, bollinger_bands, atr, macd,
    obv, stoch_rsi, donchian, vwap_ratio,
)

WORK = os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════
# FACTOR VALUE EXTRACTORS
# ═══════════════════════════════════════════════════
# 每個因子需要連續值（不是 True/False）才能做 IC 分析。
# 這裡定義每個因子類別的值提取函數。

def _safe(arr, i):
    if arr is None or i >= len(arr) or i < 0:
        return None
    return arr[i]


def _lookup_nearest(data_dict, ts):
    """從 {timestamp: value} dict 找最近的值"""
    if not data_dict:
        return None
    if ts in data_dict:
        return data_dict[ts]
    keys = sorted(data_dict.keys())
    from bisect import bisect_right
    idx = bisect_right(keys, ts) - 1
    if idx < 0:
        return None
    return data_dict[keys[idx]]


def extract_all_factors(candles, indicators=None):
    """
    計算所有因子在每根 K 線的連續值。
    返回 {factor_name: [float|None, ...]}，長度 = len(candles)
    """
    n = len(candles)
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]
    ind = indicators or {}

    factors = {}

    # ── RSI 系列 ──
    for period in [7, 14, 21]:
        vals = rsi(closes, period)
        factors[f"rsi_{period}"] = vals

    # ── EMA 差值（快-慢 / 慢，標準化）──
    for fast, slow in [(9, 21), (12, 26), (9, 50)]:
        ef = ema(closes, fast)
        es = ema(closes, slow)
        factors[f"ema_diff_{fast}_{slow}"] = [
            (ef[i] - es[i]) / es[i] * 100 if ef[i] is not None and es[i] is not None and es[i] != 0 else None
            for i in range(n)
        ]

    # ── MACD histogram ──
    for fast, slow, sig in [(12, 26, 9)]:
        _, _, hist = macd(closes, fast, slow, sig)
        # 標準化：histogram / close * 10000
        factors[f"macd_hist_{fast}_{slow}"] = [
            hist[i] / closes[i] * 10000 if hist[i] is not None and closes[i] > 0 else None
            for i in range(n)
        ]

    # ── BB 位置（price 在 BB 中的相對位置，0=下軌，1=上軌）──
    for period in [20]:
        bu, bm, bl = bollinger_bands(closes, period)
        factors[f"bb_pct_{period}"] = [
            (closes[i] - bl[i]) / (bu[i] - bl[i]) if bu[i] is not None and bl[i] is not None and bu[i] != bl[i] else None
            for i in range(n)
        ]

    # ── ATR 標準化（ATR / close * 100）──
    atr_vals = atr(candles, 14)
    factors["atr_pct"] = [
        atr_vals[i] / closes[i] * 100 if atr_vals[i] is not None and closes[i] > 0 else None
        for i in range(n)
    ]

    # ── Volume ratio（volume / SMA(volume)）──
    vol_sma = sma(volumes, 20)
    factors["volume_ratio"] = [
        volumes[i] / vol_sma[i] if vol_sma[i] is not None and vol_sma[i] > 0 else None
        for i in range(n)
    ]

    # ── OBV 動量（OBV 的 EMA 斜率）──
    obv_vals = obv(candles)
    obv_ema = ema(obv_vals, 10)
    factors["obv_momentum"] = [
        (obv_ema[i] - obv_ema[i - 1]) / abs(obv_ema[i - 1]) * 100
        if i > 0 and obv_ema[i] is not None and obv_ema[i - 1] is not None and obv_ema[i - 1] != 0
        else None
        for i in range(n)
    ]

    # ── Stoch RSI ──
    srsi = stoch_rsi(closes, 14, 14)
    factors["stoch_rsi"] = srsi

    # ── VWAP ratio ──
    vr = vwap_ratio(candles, 20)
    factors["vwap_ratio"] = [
        (v - 1) * 100 if v is not None else None for v in vr
    ]

    # ── Donchian 位置（price 在通道中的相對位置）──
    dc_u, dc_l = donchian(candles, 20)
    factors["donchian_pct"] = [
        (closes[i] - dc_l[i]) / (dc_u[i] - dc_l[i])
        if dc_u[i] is not None and dc_l[i] is not None and dc_u[i] != dc_l[i]
        else None
        for i in range(n)
    ]

    # ── 連續陽/陰線計數 ──
    consec = [0.0] * n
    for i in range(1, n):
        if candles[i].close > candles[i].open:
            consec[i] = max(consec[i - 1], 0) + 1
        elif candles[i].close < candles[i].open:
            consec[i] = min(consec[i - 1], 0) - 1
    factors["consecutive_candles"] = consec

    # ── 衍生品因子（從 indicators dict）──
    deriv_keys = [
        ("funding_rate", "funding_rate"),
        ("long_short_ratio", "long_short_ratio"),
        ("oi_change", "oi_change"),
        ("fear_greed", "fear_greed"),
        ("top_trader_ratio", "top_trader_ratio"),
        ("taker_buy_sell", "taker_buy_sell"),
        ("dxy_proxy", "dxy_proxy"),
        ("basis", "basis"),
        ("spot_futures_ratio", "spot_futures_ratio"),
        ("eth_btc_divergence", "eth_btc_divergence"),
        ("altcoin_momentum", "altcoin_momentum"),
    ]
    for factor_name, ind_key in deriv_keys:
        d = ind.get(ind_key, {})
        if d and isinstance(d, dict):
            factors[factor_name] = [
                _lookup_nearest(d, candles[i].time) for i in range(n)
            ]

    # ── SMC 因子（離散 → 1/0/-1）──
    smc_keys = [
        ("smc_trend", lambda v: 1 if v == "bullish" else (-1 if v == "bearish" else 0)),
        ("smc_ob_bull", lambda v: 1 if v else 0),
        ("smc_ob_bear", lambda v: -1 if v else 0),
        ("smc_fvg_bull", lambda v: 1 if v else 0),
        ("smc_fvg_bear", lambda v: -1 if v else 0),
        ("smc_ssl_sweep", lambda v: 1 if v else 0),
        ("smc_bsl_sweep", lambda v: -1 if v else 0),
    ]
    for ind_key, transform in smc_keys:
        d = ind.get(ind_key, {})
        if d and isinstance(d, dict):
            factors[ind_key] = [
                transform(_lookup_nearest(d, candles[i].time)) for i in range(n)
            ]

    # ── 時間因子 ──
    from datetime import datetime, timezone, timedelta
    TZ8 = timezone(timedelta(hours=8))
    factors["hour_of_day"] = [
        datetime.fromtimestamp(c.time / 1000, TZ8).hour for c in candles
    ]
    factors["day_of_week"] = [
        datetime.fromtimestamp(c.time / 1000, TZ8).weekday() for c in candles
    ]

    # ── 波動率 regime ──
    realized_vol = [None] * n
    for i in range(20, n):
        rets = [(closes[j] - closes[j - 1]) / closes[j - 1] for j in range(i - 19, i + 1) if closes[j - 1] > 0]
        if len(rets) >= 10:
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
            realized_vol[i] = math.sqrt(var_r) * 100
    factors["realized_vol"] = realized_vol

    return factors


# ═══════════════════════════════════════════════════
# STATISTICS HELPERS (pure Python, no numpy/scipy)
# ═══════════════════════════════════════════════════

def _rank(arr):
    """Rank values (1-based, average ties)"""
    indexed = [(v, i) for i, v in enumerate(arr)]
    indexed.sort(key=lambda x: x[0])
    ranks = [0.0] * len(arr)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][0] == indexed[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2  # 1-based average
        for k in range(i, j):
            ranks[indexed[k][1]] = avg_rank
        i = j
    return ranks


def _spearman(x, y):
    """Spearman rank correlation"""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx = _rank(x)
    ry = _rank(y)
    n = len(x)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    std_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    std_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


def _pearson(x, y):
    """Pearson correlation"""
    if len(x) != len(y) or len(x) < 3:
        return None
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((x[i] - mx) ** 2 for i in range(n)))
    sy = math.sqrt(sum((y[i] - my) ** 2 for i in range(n)))
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def _t_test(values):
    """One-sample t-test: is mean significantly != 0?"""
    n = len(values)
    if n < 3:
        return 0.0, 1.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 1e-10
    t_stat = mean / se
    # Approximate p-value using normal distribution (good for n > 30)
    p_value = 2 * (1 - _norm_cdf(abs(t_stat)))
    return t_stat, p_value


def _norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


# ═══════════════════════════════════════════════════
# IC ANALYSIS
# ═══════════════════════════════════════════════════

def compute_forward_returns(closes, horizon=1):
    """計算未來 N 根 K 線的收益率"""
    n = len(closes)
    returns = [None] * n
    for i in range(n - horizon):
        if closes[i] > 0:
            returns[i] = (closes[i + horizon] - closes[i]) / closes[i] * 100
    return returns


def compute_ic_series(factor_vals, returns, window=60):
    """
    滾動窗口計算 IC 序列。
    每個窗口內算 factor_vals 和 returns 的 Spearman 相關性。
    """
    n = len(factor_vals)
    ic_series = []
    timestamps = []

    for i in range(window, n):
        fv = []
        rv = []
        for j in range(i - window, i):
            if factor_vals[j] is not None and returns[j] is not None:
                fv.append(factor_vals[j])
                rv.append(returns[j])
        if len(fv) >= 20:
            ic = _spearman(fv, rv)
            if ic is not None:
                ic_series.append(ic)
                timestamps.append(i)

    return ic_series, timestamps


def analyze_factor(factor_name, factor_vals, candles, horizons=None):
    """
    完整分析單個因子。
    返回 IC、衰減曲線、分組回測、評分。
    """
    if horizons is None:
        horizons = [1, 2, 4, 8, 16, 32]

    closes = [c.close for c in candles]
    n = len(candles)

    # ── IC 分析（主要用 horizon=4，4 根 K 線後的收益）──
    primary_horizon = 4
    fwd_ret = compute_forward_returns(closes, primary_horizon)
    ic_series, _ = compute_ic_series(factor_vals, fwd_ret, window=60)

    if len(ic_series) < 10:
        return {
            "name": factor_name,
            "ic_mean": 0, "ic_std": 0, "ic_ir": 0,
            "t_stat": 0, "p_value": 1.0,
            "decay_curve": {}, "quintile_returns": [],
            "monotonicity": 0, "spread": 0,
            "grade": "F", "verdict": "數據不足",
            "n_valid": 0,
        }

    ic_mean = sum(ic_series) / len(ic_series)
    ic_std = math.sqrt(sum((v - ic_mean) ** 2 for v in ic_series) / len(ic_series)) if len(ic_series) > 1 else 0.01
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat, p_value = _t_test(ic_series)

    # ── 衰減曲線 ──
    decay = {}
    for h in horizons:
        h_ret = compute_forward_returns(closes, h)
        h_ic, _ = compute_ic_series(factor_vals, h_ret, window=60)
        if h_ic:
            decay[h] = round(sum(h_ic) / len(h_ic), 4)
        else:
            decay[h] = 0

    # ── 分組回測（Quintile Analysis）──
    # 收集有效的 (factor_value, forward_return) 對
    pairs = []
    for i in range(n):
        if factor_vals[i] is not None and fwd_ret[i] is not None:
            pairs.append((factor_vals[i], fwd_ret[i]))

    quintile_returns = []
    monotonicity = 0
    spread = 0

    if len(pairs) >= 50:
        pairs.sort(key=lambda x: x[0])
        q_size = len(pairs) // 5
        if q_size >= 5:
            q_rets = []
            for q in range(5):
                start = q * q_size
                end = start + q_size if q < 4 else len(pairs)
                group = pairs[start:end]
                avg_ret = sum(p[1] for p in group) / len(group)
                q_rets.append(round(avg_ret, 4))
            quintile_returns = q_rets
            spread = q_rets[-1] - q_rets[0]

            # Monotonicity: 相鄰組收益是否單調遞增
            increases = sum(1 for i in range(len(q_rets) - 1) if q_rets[i + 1] > q_rets[i])
            monotonicity = increases / (len(q_rets) - 1)

    # ── 評分 ──
    grade, verdict = _grade_factor(ic_mean, ic_ir, t_stat, p_value, monotonicity, spread, len(ic_series))

    return {
        "name": factor_name,
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_ir": round(ic_ir, 4),
        "t_stat": round(t_stat, 2),
        "p_value": round(p_value, 4),
        "decay_curve": decay,
        "quintile_returns": quintile_returns,
        "monotonicity": round(monotonicity, 2),
        "spread": round(spread, 4),
        "grade": grade,
        "verdict": verdict,
        "n_valid": len(ic_series),
    }


def _grade_factor(ic_mean, ic_ir, t_stat, p_value, monotonicity, spread, n_obs):
    """綜合評分"""
    score = 0
    abs_ic = abs(ic_mean)

    # IC 強度
    if abs_ic >= 0.05:
        score += 3
    elif abs_ic >= 0.03:
        score += 2
    elif abs_ic >= 0.02:
        score += 1

    # IC 穩定性（IR）
    if abs(ic_ir) >= 0.5:
        score += 3
    elif abs(ic_ir) >= 0.3:
        score += 2
    elif abs(ic_ir) >= 0.15:
        score += 1

    # 統計顯著性
    if p_value < 0.01:
        score += 2
    elif p_value < 0.05:
        score += 1

    # 單調性
    if monotonicity >= 0.75:
        score += 2
    elif monotonicity >= 0.5:
        score += 1

    # Spread
    if abs(spread) >= 0.5:
        score += 1

    # 樣本量懲罰
    if n_obs < 30:
        score -= 2

    if score >= 8:
        return "A", "強因子"
    elif score >= 6:
        return "B", "有效"
    elif score >= 4:
        return "C", "弱因子"
    elif score >= 2:
        return "D", "可疑"
    else:
        return "F", "垃圾"


# ═══════════════════════════════════════════════════
# BATCH ANALYSIS
# ═══════════════════════════════════════════════════

def analyze_all_factors(candles, indicators=None, horizons=None):
    """分析所有因子，返回排名列表"""
    factors = extract_all_factors(candles, indicators)
    results = []

    for name, vals in factors.items():
        # 跳過全 None 的因子
        valid_count = sum(1 for v in vals if v is not None)
        if valid_count < 50:
            continue
        result = analyze_factor(name, vals, candles, horizons)
        results.append(result)

    # 按 |IC_IR| 排序
    results.sort(key=lambda x: -abs(x["ic_ir"]))
    return results


def factor_correlation_matrix(candles, indicators=None, top_n=20):
    """
    計算因子間的相關性矩陣。
    只算 top_n 個因子（按 IC_IR 排名）。
    返回 {(factor_a, factor_b): correlation}
    """
    factors = extract_all_factors(candles, indicators)
    n = len(candles)

    # 只保留有足夠數據的因子
    valid_factors = {}
    for name, vals in factors.items():
        valid = [(i, v) for i, v in enumerate(vals) if v is not None]
        if len(valid) >= 50:
            valid_factors[name] = vals

    names = list(valid_factors.keys())[:top_n]
    matrix = {}

    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if j <= i:
                continue
            # 收集共同有效的點
            va, vb = [], []
            for k in range(n):
                if valid_factors[a][k] is not None and valid_factors[b][k] is not None:
                    va.append(valid_factors[a][k])
                    vb.append(valid_factors[b][k])
            if len(va) >= 20:
                corr = _pearson(va, vb)
                if corr is not None:
                    matrix[(a, b)] = round(corr, 3)

    return matrix


def filter_factors(analysis_results, min_abs_ic=0.02, min_abs_tstat=1.5, max_correlation=0.7,
                   correlation_matrix=None):
    """
    篩選有效因子。
    1. IC 和 t-stat 過門檻
    2. 高相關因子只保留最強的
    返回推薦的因子名列表
    """
    # Step 1: 基本篩選
    candidates = [
        r for r in analysis_results
        if abs(r["ic_mean"]) >= min_abs_ic and abs(r["t_stat"]) >= min_abs_tstat
    ]
    candidates.sort(key=lambda x: -abs(x["ic_ir"]))

    if not correlation_matrix:
        return [c["name"] for c in candidates]

    # Step 2: 去冗餘（高相關因子只保留 IC_IR 最高的）
    selected = []
    rejected = set()

    for c in candidates:
        if c["name"] in rejected:
            continue
        selected.append(c["name"])
        # 標記跟它高度相關的因子
        for (a, b), corr in correlation_matrix.items():
            if abs(corr) >= max_correlation:
                if a == c["name"] and b not in selected:
                    rejected.add(b)
                elif b == c["name"] and a not in selected:
                    rejected.add(a)

    return selected


def format_factor_report(results, top_n=20):
    """格式化因子分析報告"""
    lines = []
    lines.append("╔══════════════════════════════════════════════════════╗")
    lines.append("║           因子預測力分析報告                        ║")
    lines.append("╚══════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  分析因子數: {len(results)}")

    grade_counts = {}
    for r in results:
        grade_counts[r["grade"]] = grade_counts.get(r["grade"], 0) + 1
    lines.append(f"  評級分佈: " + " | ".join(f"{g}:{c}" for g, c in sorted(grade_counts.items())))
    lines.append("")

    for i, r in enumerate(results[:top_n]):
        ic_dir = "↑" if r["ic_mean"] > 0 else "↓"
        sig = "✓" if r["p_value"] < 0.05 else "✗"
        lines.append(
            f"  {i + 1:>2}. [{r['grade']}] {r['name']:<25} "
            f"IC={r['ic_mean']:>7.4f}{ic_dir} IR={r['ic_ir']:>6.3f} "
            f"t={r['t_stat']:>5.1f} p={r['p_value']:.3f}{sig} "
            f"mono={r['monotonicity']:.0%} — {r['verdict']}"
        )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("🔬 Factor Research — 因子預測力分析")
    print("拉取數據...")

    candles = fetch_candles_extended("BTCUSDT", "4h", 1500)
    print(f"  {len(candles)} 根 4h K 線")

    # 拉衍生品數據
    print("拉取衍生品 + SMC 數據...")
    try:
        from derivatives_data import fetch_all_derivatives
        from smc_genes import compute_smc_indicators
        indicators = fetch_all_derivatives("BTCUSDT", "4h", 500,
                                           candles[0].time, candles[-1].time,
                                           candles=candles)
        smc = compute_smc_indicators(candles)
        indicators.update(smc)
    except Exception as e:
        print(f"  ⚠️ 衍生品數據拉取失敗: {e}")
        indicators = {}

    print("\n分析因子...")
    results = analyze_all_factors(candles, indicators)

    print(format_factor_report(results))

    # 相關性矩陣
    print("\n計算因子相關性...")
    corr = factor_correlation_matrix(candles, indicators)
    high_corr = [(a, b, c) for (a, b), c in corr.items() if abs(c) >= 0.7]
    if high_corr:
        print(f"  高相關因子對 (|r| >= 0.7):")
        for a, b, c in sorted(high_corr, key=lambda x: -abs(x[2]))[:10]:
            print(f"    {a} ↔ {b}: {c:.3f}")

    # 篩選
    recommended = filter_factors(results, correlation_matrix=corr)
    print(f"\n推薦因子 ({len(recommended)} 個):")
    for f in recommended:
        print(f"  ✓ {f}")
