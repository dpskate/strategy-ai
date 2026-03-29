#!/usr/bin/env python3
"""
Strategy AI - Data Pipeline
統一數據管線 + SQLite 本地緩存

不用每次都打 API，歷史數據存本地，只拉缺的部分。
"""
import json, os, sqlite3, time, ssl, math
from datetime import datetime, timezone, timedelta
from bisect import bisect_right

import httpx

from backtest_engine import Candle, fetch_candles as _api_fetch_candles

WORK = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(WORK, "data_cache.db")
TZ8 = timezone(timedelta(hours=8))
ssl_ctx = ssl.create_default_context()

# Cache expiry: derivatives/onchain/macro data expires after 4 hours
CACHE_EXPIRY_MS = 4 * 3600 * 1000


class DataPipeline:
    def __init__(self, cache_path=None):
        self.db_path = cache_path or DEFAULT_DB
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT, interval TEXT, time_ms INTEGER,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, interval, time_ms)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS indicators (
            symbol TEXT, indicator TEXT, time_ms INTEGER, value REAL,
            PRIMARY KEY (symbol, indicator, time_ms)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY, value TEXT
        )""")
        conn.commit()
        conn.close()

    # ─── Candles ───

    def get_candles(self, symbol="BTCUSDT", interval="4h", count=1000,
                    start_ms=None, end_ms=None):
        """取得 K 線。先查緩存，缺的從 API 補。"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        if start_ms and end_ms:
            c.execute(
                "SELECT time_ms, open, high, low, close, volume FROM candles "
                "WHERE symbol=? AND interval=? AND time_ms>=? AND time_ms<=? "
                "ORDER BY time_ms",
                (symbol, interval, start_ms, end_ms)
            )
        else:
            c.execute(
                "SELECT time_ms, open, high, low, close, volume FROM candles "
                "WHERE symbol=? AND interval=? ORDER BY time_ms DESC LIMIT ?",
                (symbol, interval, count)
            )

        rows = c.fetchall()
        conn.close()

        cached = [Candle(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                  for r in rows]
        if not start_ms:
            cached.sort(key=lambda x: x.time)

        # Check if we have enough
        if start_ms and end_ms:
            if len(cached) >= 10:  # rough check
                return cached
        elif len(cached) >= count * 0.9:
            return cached[-count:]

        # Fetch from API and cache
        try:
            from backtest_engine import fetch_candles_extended
            candles = fetch_candles_extended(symbol, interval, count,
                                            start_ms=start_ms, end_ms=end_ms)
            if candles:
                self._cache_candles(symbol, interval, candles)
                return candles
        except Exception:
            pass

        return cached if cached else []

    def _cache_candles(self, symbol, interval, candles):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        data = [(symbol, interval, cd.time, cd.open, cd.high, cd.low, cd.close, cd.volume)
                for cd in candles]
        c.executemany(
            "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", data
        )
        conn.commit()
        conn.close()

    # ─── Indicators ───

    def get_indicator(self, symbol, indicator_name, start_ms=None, end_ms=None):
        """取得單個指標的緩存數據。返回 {time_ms: value}"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        if start_ms and end_ms:
            c.execute(
                "SELECT time_ms, value FROM indicators "
                "WHERE symbol=? AND indicator=? AND time_ms>=? AND time_ms<=?",
                (symbol, indicator_name, start_ms, end_ms)
            )
        else:
            c.execute(
                "SELECT time_ms, value FROM indicators "
                "WHERE symbol=? AND indicator=?",
                (symbol, indicator_name)
            )

        rows = c.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}

    def cache_indicator(self, symbol, indicator_name, data_dict):
        """緩存指標數據。data_dict = {time_ms: value}"""
        if not data_dict:
            return
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        rows = [(symbol, indicator_name, ts, val) for ts, val in data_dict.items()
                if val is not None]
        c.executemany(
            "INSERT OR REPLACE INTO indicators VALUES (?,?,?,?)", rows
        )
        # Update metadata
        c.execute(
            "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
            (f"last_update:{symbol}:{indicator_name}", str(int(time.time() * 1000)))
        )
        conn.commit()
        conn.close()

    def _is_expired(self, symbol, indicator_name):
        """檢查指標緩存是否過期"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT value FROM metadata WHERE key=?",
                  (f"last_update:{symbol}:{indicator_name}",))
        row = c.fetchone()
        conn.close()
        if not row:
            return True
        last_update = int(row[0])
        return (time.time() * 1000 - last_update) > CACHE_EXPIRY_MS

    # ─── All Indicators ───

    def get_all_indicators(self, symbol="BTCUSDT", interval="4h",
                           candles=None, lookback_days=90):
        """
        一次拉全部數據，合併成 extra_indicators dict。
        先查緩存，過期的才從 API 拉。
        """
        result = {}

        # 衍生品數據
        try:
            from derivatives_data import fetch_all_derivatives
            start_t = candles[0].time if candles else None
            end_t = candles[-1].time if candles else None
            deriv = fetch_all_derivatives(symbol, interval, 500, start_t, end_t,
                                          candles=candles)
            result.update(deriv)

            # 緩存數值型指標
            for key, data in deriv.items():
                if isinstance(data, dict) and data:
                    # 只緩存數值型
                    sample = next(iter(data.values()), None)
                    if isinstance(sample, (int, float)):
                        self.cache_indicator(symbol, key, data)
        except Exception:
            # API 失敗，嘗試用緩存兜底
            for ind_name in ["funding_rate", "long_short_ratio", "oi_change",
                             "fear_greed", "top_trader_ratio", "taker_buy_sell",
                             "dxy_proxy", "basis", "spot_futures_ratio"]:
                cached = self.get_indicator(symbol, ind_name)
                if cached:
                    result[ind_name] = cached

        # SMC 指標
        if candles and len(candles) >= 20:
            try:
                from smc_genes import compute_smc_indicators
                smc = compute_smc_indicators(candles)
                result.update(smc)
            except Exception:
                pass

        return result

    # ─── Cache Stats ───

    def cache_stats(self):
        """返回緩存統計"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("SELECT symbol, interval, COUNT(*), MIN(time_ms), MAX(time_ms) "
                  "FROM candles GROUP BY symbol, interval")
        candle_stats = []
        for row in c.fetchall():
            candle_stats.append({
                "symbol": row[0], "interval": row[1], "count": row[2],
                "from": datetime.fromtimestamp(row[3] / 1000, TZ8).strftime("%Y-%m-%d") if row[3] else None,
                "to": datetime.fromtimestamp(row[4] / 1000, TZ8).strftime("%Y-%m-%d") if row[4] else None,
            })

        c.execute("SELECT symbol, indicator, COUNT(*) FROM indicators GROUP BY symbol, indicator")
        ind_stats = [{"symbol": r[0], "indicator": r[1], "count": r[2]} for r in c.fetchall()]

        c.execute("SELECT COUNT(*) FROM candles")
        total_candles = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM indicators")
        total_indicators = c.fetchone()[0]

        # DB file size
        conn.close()
        db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

        return {
            "db_path": self.db_path,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "total_candles": total_candles,
            "total_indicators": total_indicators,
            "candles": candle_stats,
            "indicators": ind_stats,
        }

    def update_cache(self, symbol="BTCUSDT", interval="4h", count=3000):
        """手動更新緩存到最新"""
        print(f"  更新 {symbol} {interval} K 線...")
        candles = self.get_candles(symbol, interval, count)
        print(f"  緩存 {len(candles)} 根 K 線")

        print(f"  更新指標...")
        indicators = self.get_all_indicators(symbol, interval, candles)
        ind_count = sum(1 for v in indicators.values() if isinstance(v, dict) and v)
        print(f"  緩存 {ind_count} 個指標")

        return {"candles": len(candles), "indicators": ind_count}


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("📦 Data Pipeline — 數據緩存測試")

    pipeline = DataPipeline()

    # Test: fetch and cache candles
    print("\n1. 拉取 + 緩存 K 線...")
    candles = pipeline.get_candles("BTCUSDT", "4h", 500)
    print(f"   取得 {len(candles)} 根 K 線")

    # Test: second fetch should be from cache
    print("\n2. 再次拉取（應該從緩存）...")
    t0 = time.time()
    candles2 = pipeline.get_candles("BTCUSDT", "4h", 500)
    t1 = time.time()
    print(f"   取得 {len(candles2)} 根 K 線，耗時 {(t1-t0)*1000:.0f}ms")

    # Test: indicators
    print("\n3. 拉取指標...")
    indicators = pipeline.get_all_indicators("BTCUSDT", "4h", candles)
    print(f"   取得 {len(indicators)} 個指標")

    # Stats
    print("\n4. 緩存統計:")
    stats = pipeline.cache_stats()
    print(f"   DB 大小: {stats['db_size_mb']} MB")
    print(f"   K 線: {stats['total_candles']} 條")
    print(f"   指標: {stats['total_indicators']} 條")
    for cs in stats["candles"]:
        print(f"   {cs['symbol']} {cs['interval']}: {cs['count']} 根 ({cs['from']} → {cs['to']})")
