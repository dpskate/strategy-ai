#!/usr/bin/env python3
"""
Strategy AI - Derivatives Data
從幣安 Futures API 拉取衍生品數據，對齊到 K 線時間供回測引擎使用。

每個函數返回 dict: {timestamp_ms: value}
回測時用 bisect 找最近的 <= 當前 K 線時間的值。
"""
import json, urllib.request, ssl, time
from bisect import bisect_right

import httpx

ssl_ctx = ssl.create_default_context()
BASE = "https://fapi.binance.com"
SPOT_BASE = "https://api.binance.com"


def _get(path, params=None, retries=2):
    """GET request to Binance Futures API (no key needed)."""
    url = BASE + path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        url += "?" + qs
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            if attempt < retries:
                time.sleep(1)
            else:
                return []


def _httpx_get(url, params=None, retries=2):
    """GET request using httpx (for non-Binance APIs or spot)."""
    for attempt in range(retries + 1):
        try:
            r = httpx.get(url, params=params, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt < retries:
                time.sleep(1)
            else:
                return []


# ═══════════════════════════════════════════════════
# Data Fetchers
# ═══════════════════════════════════════════════════

def fetch_funding_rate(symbol="BTCUSDT", limit=500, start_time=None, end_time=None):
    """
    資金費率歷史。每 8 小時一筆。
    Returns: {timestamp_ms: funding_rate_float}
    """
    params = {"symbol": symbol, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    data = _get("/fapi/v1/fundingRate", params)
    result = {}
    for item in data:
        ts = int(item["fundingTime"])
        rate = float(item["fundingRate"])
        result[ts] = rate
    return result


def fetch_long_short_ratio(symbol="BTCUSDT", period="4h", limit=500, start_time=None, end_time=None):
    """
    全網多空比歷史。
    Returns: {timestamp_ms: long_short_ratio_float}
    """
    params = {"symbol": symbol, "period": period, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    data = _get("/futures/data/globalLongShortAccountRatio", params)
    result = {}
    for item in data:
        ts = int(item["timestamp"])
        ratio = float(item["longShortRatio"])
        result[ts] = ratio
    return result


def fetch_open_interest_hist(symbol="BTCUSDT", period="4h", limit=500, start_time=None, end_time=None):
    """
    未平倉合約歷史。
    Returns: {timestamp_ms: open_interest_value_float}
    """
    params = {"symbol": symbol, "period": period, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    data = _get("/futures/data/openInterestHist", params)
    result = {}
    for item in data:
        ts = int(item["timestamp"])
        oi = float(item["sumOpenInterestValue"])
        result[ts] = oi
    return result


# ═══════════════════════════════════════════════════
# Time Alignment Helper
# ═══════════════════════════════════════════════════

def lookup_nearest(data_dict, candle_time):
    """
    在 data_dict 中找最近的 <= candle_time 的值。
    data_dict: {timestamp_ms: value}
    Returns: value or None
    """
    if not data_dict:
        return None
    timestamps = sorted(data_dict.keys())
    idx = bisect_right(timestamps, candle_time) - 1
    if idx < 0:
        return None
    return data_dict[timestamps[idx]]


def build_oi_change_map(oi_dict):
    """
    從 OI 歷史計算變化率 dict。
    Returns: {timestamp_ms: pct_change}  (e.g. 0.12 = +12%)
    """
    if len(oi_dict) < 2:
        return {}
    timestamps = sorted(oi_dict.keys())
    result = {}
    for i in range(1, len(timestamps)):
        prev_val = oi_dict[timestamps[i - 1]]
        curr_val = oi_dict[timestamps[i]]
        if prev_val > 0:
            result[timestamps[i]] = (curr_val - prev_val) / prev_val
    return result


# ═══════════════════════════════════════════════════
# Extended Data Fetchers (Free APIs)
# ═══════════════════════════════════════════════════

def fetch_fear_greed(limit=500):
    """
    恐懼貪婪指數 (0-100)。日線數據。
    Returns: {timestamp_ms: int_value}
    """
    try:
        data = _httpx_get(f"https://api.alternative.me/fng/?limit={limit}&format=json")
        if not data or "data" not in data:
            return {}
        result = {}
        for item in data["data"]:
            ts = int(item["timestamp"]) * 1000  # API returns seconds
            val = int(item["value"])
            result[ts] = val
        return result
    except Exception:
        return {}


def fetch_coinbase_premium(symbol="BTCUSDT", interval="4h", limit=500):
    """
    永續 vs 現貨基差（Premium Index）。
    正值 = 永續溢價（多頭情緒），負值 = 永續折價（空頭情緒）。
    Returns: {timestamp_ms: basis_pct}
    """
    try:
        # 用 premiumIndex 拿即時基差
        # 歷史數據用 mark price klines vs spot klines 計算
        spot_url = f"{SPOT_BASE}/api/v3/klines"
        futures_url = f"{BASE}/fapi/v1/klines"
        spot_params = {"symbol": symbol, "interval": interval, "limit": limit}
        fut_params = {"symbol": symbol, "interval": interval, "limit": limit}

        spot_data = _httpx_get(spot_url, spot_params)
        fut_data = _httpx_get(futures_url, fut_params)

        if not spot_data or not fut_data:
            return {}

        # Build spot price map {open_time: close_price}
        spot_map = {}
        for k in spot_data:
            ts = int(k[0])
            spot_map[ts] = float(k[4])  # close price

        result = {}
        for k in fut_data:
            ts = int(k[0])
            fut_close = float(k[4])
            spot_close = spot_map.get(ts)
            if spot_close and spot_close > 0:
                basis_pct = (fut_close - spot_close) / spot_close * 100
                result[ts] = round(basis_pct, 4)
        return result
    except Exception:
        return {}


def fetch_top_trader_ratio(symbol="BTCUSDT", period="4h", limit=500,
                           start_time=None, end_time=None):
    """
    大戶持倉多空比（Top Traders Position Ratio）。
    跟 globalLongShortAccountRatio（散戶）不同，這是大戶的。
    Returns: {timestamp_ms: long_short_ratio}
    """
    try:
        params = {"symbol": symbol, "period": period, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        data = _get("/futures/data/topLongShortPositionRatio", params)
        result = {}
        for item in data:
            ts = int(item["timestamp"])
            ratio = float(item["longShortRatio"])
            result[ts] = ratio
        return result
    except Exception:
        return {}


def fetch_taker_buy_sell(symbol="BTCUSDT", period="4h", limit=500,
                         start_time=None, end_time=None):
    """
    Taker 買賣比（主動買入 vs 主動賣出）。
    > 1 = 買方主導，< 1 = 賣方主導。
    Returns: {timestamp_ms: buy_sell_ratio}
    """
    try:
        params = {"symbol": symbol, "period": period, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        data = _get("/futures/data/takerlongshortRatio", params)
        result = {}
        for item in data:
            ts = int(item["timestamp"])
            ratio = float(item["buySellRatio"])
            result[ts] = ratio
        return result
    except Exception:
        return {}


def fetch_dxy_proxy(interval="4h", limit=500):
    """
    美元強弱代理：1 / EURUSDT close。
    越高 = 美元越強。
    Returns: {timestamp_ms: dxy_proxy_value}
    """
    try:
        url = f"{SPOT_BASE}/api/v3/klines"
        params = {"symbol": "EURUSDT", "interval": interval, "limit": limit}
        data = _httpx_get(url, params)
        if not data:
            return {}
        result = {}
        for k in data:
            ts = int(k[0])
            close = float(k[4])
            if close > 0:
                result[ts] = round(1.0 / close, 6)
        return result
    except Exception:
        return {}


def fetch_exchange_netflow_proxy(symbol="BTCUSDT", interval="4h", limit=500):
    """
    現貨/合約成交量比（Spot-Futures Volume Ratio）。
    高值 = 現貨主導（真實買賣），低值 = 合約主導（投機）。
    Returns: {timestamp_ms: spot_futures_ratio}
    """
    try:
        spot_url = f"{SPOT_BASE}/api/v3/klines"
        futures_url = f"{BASE}/fapi/v1/klines"
        spot_params = {"symbol": symbol, "interval": interval, "limit": limit}
        fut_params = {"symbol": symbol, "interval": interval, "limit": limit}

        spot_data = _httpx_get(spot_url, spot_params)
        fut_data = _httpx_get(futures_url, fut_params)

        if not spot_data or not fut_data:
            return {}

        # Build futures volume map
        fut_vol_map = {}
        for k in fut_data:
            ts = int(k[0])
            fut_vol_map[ts] = float(k[5])  # volume

        result = {}
        for k in spot_data:
            ts = int(k[0])
            spot_vol = float(k[5])
            fut_vol = fut_vol_map.get(ts, 0)
            total = spot_vol + fut_vol
            if total > 0:
                result[ts] = round(spot_vol / total, 4)
        return result
    except Exception:
        return {}


# ═══════════════════════════════════════════════════
# Unified Indicator Fetcher
# ═══════════════════════════════════════════════════

def fetch_cross_asset_data(base_symbol="BTCUSDT", compare_symbols=None, interval="4h", limit=500):
    """
    拉取多個幣對的 K 線，計算跨幣種因子：
    - btc_eth_ratio: BTC/ETH 價格比（比值上升 = BTC 相對強勢）
    - eth_btc_divergence: ETH 漲跌幅 vs BTC 漲跌幅的差值（正 = ETH 更強）
    - altcoin_momentum: SOL 等山寨幣的平均漲跌幅（山寨強 = 風險偏好高）
    Returns: {指標名: {timestamp_ms: float}}
    """
    if compare_symbols is None:
        compare_symbols = ["ETHUSDT", "SOLUSDT"]
    try:
        url = f"{SPOT_BASE}/api/v3/klines"
        # Fetch base (BTC)
        base_data = _httpx_get(url, {"symbol": base_symbol, "interval": interval, "limit": limit})
        if not base_data:
            return {}
        base_map = {}  # ts -> close
        base_returns = {}  # ts -> pct change from prev
        prev_close = None
        for k in base_data:
            ts = int(k[0])
            close = float(k[4])
            base_map[ts] = close
            if prev_close and prev_close > 0:
                base_returns[ts] = (close - prev_close) / prev_close * 100
            prev_close = close

        # Fetch compare symbols
        sym_data = {}
        for sym in compare_symbols:
            try:
                d = _httpx_get(url, {"symbol": sym, "interval": interval, "limit": limit})
                if d:
                    sym_data[sym] = d
            except Exception:
                pass
            time.sleep(0.1)

        result = {}

        # BTC/ETH ratio
        if "ETHUSDT" in sym_data:
            eth_map = {int(k[0]): float(k[4]) for k in sym_data["ETHUSDT"]}
            btc_eth_ratio = {}
            eth_returns = {}
            prev_eth = None
            for k in sym_data["ETHUSDT"]:
                ts = int(k[0])
                c = float(k[4])
                if prev_eth and prev_eth > 0:
                    eth_returns[ts] = (c - prev_eth) / prev_eth * 100
                prev_eth = c

            for ts, btc_close in base_map.items():
                eth_close = eth_map.get(ts)
                if eth_close and eth_close > 0:
                    btc_eth_ratio[ts] = round(btc_close / eth_close, 4)
            result["btc_eth_ratio"] = btc_eth_ratio

            # ETH-BTC divergence
            divergence = {}
            for ts in base_returns:
                eth_ret = eth_returns.get(ts)
                if eth_ret is not None:
                    divergence[ts] = round(eth_ret - base_returns[ts], 4)
            result["eth_btc_divergence"] = divergence

        # Altcoin momentum (average return of non-BTC symbols)
        alt_returns_all = {}
        for sym, data in sym_data.items():
            if sym == base_symbol:
                continue
            prev_c = None
            for k in data:
                ts = int(k[0])
                c = float(k[4])
                if prev_c and prev_c > 0:
                    ret = (c - prev_c) / prev_c * 100
                    if ts not in alt_returns_all:
                        alt_returns_all[ts] = []
                    alt_returns_all[ts].append(ret)
                prev_c = c
        altcoin_momentum = {}
        for ts, rets in alt_returns_all.items():
            altcoin_momentum[ts] = round(sum(rets) / len(rets), 4)
        result["altcoin_momentum"] = altcoin_momentum

        return result
    except Exception:
        return {}


def compute_time_factors(candles_raw):
    """
    從 K 線時間戳計算時間因子（純計算，不需要 API）。
    candles_raw: list of kline data (each has [0]=open_time_ms)
                 or list of objects with .time attribute
    Returns: {指標名: {timestamp_ms: value}}
    """
    from datetime import datetime as _dt, timezone as _tz
    result = {"hour_of_day": {}, "day_of_week": {}, "is_month_start": {},
              "is_month_end": {}, "session": {}}
    for c in candles_raw:
        ts = c.time if hasattr(c, 'time') else int(c[0])
        dt = _dt.fromtimestamp(ts / 1000, tz=_tz.utc)
        result["hour_of_day"][ts] = dt.hour
        result["day_of_week"][ts] = dt.weekday()  # 0=Mon, 6=Sun
        result["is_month_start"][ts] = 1 if dt.day <= 3 else 0
        result["is_month_end"][ts] = 1 if dt.day >= 28 else 0
        h = dt.hour
        if 0 <= h < 8:
            result["session"][ts] = "asia"
        elif 8 <= h < 16:
            result["session"][ts] = "europe"
        else:
            result["session"][ts] = "us"
    return result


def compute_volatility_factors(candles_raw, lookback=20):
    """
    波動率因子（純計算）。
    candles_raw: list of objects with .close, .high, .low attributes
    Returns: {指標名: {timestamp_ms: value}}
    """
    import math
    result = {"realized_vol": {}, "vol_regime": {}, "vol_expansion": {},
              "vol_contraction": {}, "range_pct": {}}
    closes = [c.close for c in candles_raw]
    # Compute log returns
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))
        else:
            log_returns.append(0.0)

    # 4h candles: 6 per day, 365 days
    annualize = math.sqrt(6 * 365)
    all_vols = []

    for i in range(len(candles_raw)):
        ts = candles_raw[i].time if hasattr(candles_raw[i], 'time') else int(candles_raw[i][0])
        # range_pct
        c = candles_raw[i]
        if c.close > 0:
            result["range_pct"][ts] = round((c.high - c.low) / c.close * 100, 4)

        # realized_vol (need at least lookback returns)
        ret_idx = i - 1  # index into log_returns
        if ret_idx >= lookback - 1:
            window = log_returns[ret_idx - lookback + 1: ret_idx + 1]
            if len(window) == lookback:
                mean_r = sum(window) / len(window)
                var = sum((r - mean_r) ** 2 for r in window) / (len(window) - 1)
                vol = math.sqrt(var) * annualize * 100  # as percentage
                result["realized_vol"][ts] = round(vol, 2)
                all_vols.append(vol)

    # vol_regime: percentile-based
    if all_vols:
        sorted_vols = sorted(all_vols)
        p25 = sorted_vols[len(sorted_vols) // 4]
        p75 = sorted_vols[3 * len(sorted_vols) // 4]
        vol_ts_list = sorted(result["realized_vol"].keys())
        prev_vol = None
        for ts in vol_ts_list:
            vol = result["realized_vol"][ts]
            if vol < p25:
                result["vol_regime"][ts] = "low"
            elif vol > p75:
                result["vol_regime"][ts] = "high"
            else:
                result["vol_regime"][ts] = "normal"
            # expansion / contraction
            if prev_vol is not None:
                result["vol_expansion"][ts] = 1 if vol > prev_vol else 0
                result["vol_contraction"][ts] = 1 if vol < prev_vol else 0
            prev_vol = vol

    return result


def fetch_blockchain_data(lookback_days=90):
    """
    blockchain.info 免費 API（不需要 key）。
    日線數據，對齊到 4h K 線（同一天用同一個值）。
    Returns: {指標名: {timestamp_ms: value}}
    """
    charts = {
        "n-unique-addresses": "active_addresses",
        "n-transactions": "tx_count",
        "transaction-fees": "fees",
        "hash-rate": "hashrate",
    }
    raw = {}
    timespan = f"{lookback_days}days"
    for chart_name, label in charts.items():
        try:
            url = f"https://api.blockchain.info/charts/{chart_name}"
            data = _httpx_get(url, {"timespan": timespan, "format": "json"})
            if data and "values" in data:
                raw[label] = [(int(v["x"]) * 1000, float(v["y"])) for v in data["values"]]
            time.sleep(0.5)  # rate limit
        except Exception:
            pass

    result = {}
    change_period = 7  # 7-day change rate

    for label, values in raw.items():
        if len(values) < change_period + 1:
            continue
        change_key = f"{label}_change"
        result[change_key] = {}
        for i in range(change_period, len(values)):
            ts, val = values[i]
            _, prev_val = values[i - change_period]
            if prev_val > 0:
                pct = (val - prev_val) / prev_val * 100
                result[change_key][ts] = round(pct, 2)

    # fees_spike: special — use shorter lookback (3 days)
    if "fees" in raw and len(raw["fees"]) > 3:
        fees_spike = {}
        vals = raw["fees"]
        for i in range(3, len(vals)):
            ts, val = vals[i]
            _, prev_val = vals[i - 3]
            if prev_val > 0:
                pct = (val - prev_val) / prev_val * 100
                fees_spike[ts] = round(pct, 2)
        result["fees_spike"] = fees_spike

    return result


def compute_correlation_factors(candles_raw, interval="4h", limit=500):
    """
    BTC 跟美元的滾動相關性。
    Uses EURUSDT (already have fetch_dxy_proxy).
    Returns: {指標名: {timestamp_ms: value}}
    """
    import math
    try:
        # Get BTC returns
        btc_returns = {}
        prev_close = None
        for c in candles_raw:
            ts = c.time if hasattr(c, 'time') else int(c[0])
            close = c.close if hasattr(c, 'close') else float(c[4])
            if prev_close and prev_close > 0:
                btc_returns[ts] = (close - prev_close) / prev_close
            prev_close = close

        # Get DXY proxy returns
        dxy = fetch_dxy_proxy(interval, limit)
        if not dxy:
            return {}
        dxy_sorted = sorted(dxy.items())
        dxy_returns = {}
        for i in range(1, len(dxy_sorted)):
            ts, val = dxy_sorted[i]
            _, prev_val = dxy_sorted[i - 1]
            if prev_val > 0:
                dxy_returns[ts] = (val - prev_val) / prev_val

        # Align timestamps
        common_ts = sorted(set(btc_returns.keys()) & set(dxy_returns.keys()))
        if len(common_ts) < 25:
            return {}

        window = 20
        result = {"btc_usd_corr": {}, "corr_regime_change": {}}
        prev_corr = None

        for i in range(window, len(common_ts)):
            ts = common_ts[i]
            w_ts = common_ts[i - window: i]
            bx = [btc_returns[t] for t in w_ts]
            dx = [dxy_returns[t] for t in w_ts]

            n = len(bx)
            mean_b = sum(bx) / n
            mean_d = sum(dx) / n
            cov = sum((bx[j] - mean_b) * (dx[j] - mean_d) for j in range(n)) / n
            std_b = math.sqrt(sum((b - mean_b) ** 2 for b in bx) / n)
            std_d = math.sqrt(sum((d - mean_d) ** 2 for d in dx) / n)

            if std_b > 0 and std_d > 0:
                corr = cov / (std_b * std_d)
                result["btc_usd_corr"][ts] = round(corr, 4)

                if prev_corr is not None:
                    change = abs(corr - prev_corr)
                    result["corr_regime_change"][ts] = round(change, 4)
                prev_corr = corr

        return result
    except Exception:
        return {}


def fetch_all_indicators(symbol="BTCUSDT", interval="4h", limit=500,
                         start_time=None, end_time=None, candles=None):
    """
    一次拉取所有另類數據指標。
    每個 key 是指標名，value 是 {timestamp_ms: float_value}。
    任何 API 失敗不影響其他指標。
    candles: optional list of candle objects for pure-computation factors.
    """
    result = {}

    try:
        result["fear_greed"] = fetch_fear_greed(limit)
    except Exception:
        pass

    try:
        result["basis"] = fetch_coinbase_premium(symbol, interval, limit)
    except Exception:
        pass

    try:
        result["top_trader_ratio"] = fetch_top_trader_ratio(
            symbol, interval, limit, start_time, end_time)
    except Exception:
        pass

    try:
        result["taker_buy_sell"] = fetch_taker_buy_sell(
            symbol, interval, limit, start_time, end_time)
    except Exception:
        pass

    try:
        result["dxy_proxy"] = fetch_dxy_proxy(interval, limit)
    except Exception:
        pass

    try:
        result["spot_futures_ratio"] = fetch_exchange_netflow_proxy(
            symbol, interval, limit)
    except Exception:
        pass

    # ── Cross-asset factors ──
    try:
        cross = fetch_cross_asset_data(symbol, ["ETHUSDT", "SOLUSDT"], interval, limit)
        result.update(cross)
    except Exception:
        pass

    # ── Blockchain on-chain factors ──
    try:
        chain = fetch_blockchain_data(lookback_days=90)
        result.update(chain)
    except Exception:
        pass

    # ── Pure-computation factors (need candles) ──
    if candles:
        try:
            tf = compute_time_factors(candles)
            result.update(tf)
        except Exception:
            pass

        try:
            vf = compute_volatility_factors(candles)
            result.update(vf)
        except Exception:
            pass

        try:
            cf = compute_correlation_factors(candles, interval, limit)
            result.update(cf)
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════
# All-in-one Fetcher (Original)
# ═══════════════════════════════════════════════════

def fetch_all_derivatives(symbol="BTCUSDT", period="4h", limit=500,
                          start_time=None, end_time=None, candles=None):
    """
    一次拉取所有衍生品數據，返回可直接放進 indicators dict 的格式。
    candles: optional list of candle objects for pure-computation factors.
    Returns: {
        "funding_rate": {ts: rate},
        "long_short_ratio": {ts: ratio},
        "open_interest": {ts: oi_value},
        "oi_change": {ts: pct_change},
        ... plus all extended indicators
    }
    """
    fr = fetch_funding_rate(symbol, limit, start_time, end_time)
    lsr = fetch_long_short_ratio(symbol, period, limit, start_time, end_time)
    oi = fetch_open_interest_hist(symbol, period, limit, start_time, end_time)
    oi_chg = build_oi_change_map(oi)

    result = {
        "funding_rate": fr,
        "long_short_ratio": lsr,
        "open_interest": oi,
        "oi_change": oi_chg,
    }

    # Merge extended indicators (including cross-asset, time, vol, chain, corr)
    try:
        extended = fetch_all_indicators(symbol, period, limit, start_time, end_time,
                                        candles=candles)
        result.update(extended)
    except Exception:
        pass

    return result


if __name__ == "__main__":
    print("📊 Derivatives Data Test")
    d = fetch_all_derivatives("BTCUSDT", "4h", 10)
    for k, v in d.items():
        print(f"  {k}: {len(v)} records")
        if v:
            sample_ts = list(v.keys())[-1]
            print(f"    latest: ts={sample_ts}, val={v[sample_ts]}")
