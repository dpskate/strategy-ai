#!/usr/bin/env python3
"""
Strategy AI - Backtesting Engine
回測引擎：接收策略定義，跑歷史數據，輸出交易記錄
"""
import json, urllib.request, ssl, os, random
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

ssl_ctx = ssl.create_default_context()
TZ8 = timezone(timedelta(hours=8))
WORK = os.path.dirname(os.path.abspath(__file__))


# ═══════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════

@dataclass
class Candle:
    time: int          # ms timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def bullish(self): return self.close >= self.open
    @property
    def bearish(self): return self.close < self.open
    @property
    def body(self): return abs(self.close - self.open)
    @property
    def upper_wick(self): return self.high - max(self.open, self.close)
    @property
    def lower_wick(self): return min(self.open, self.close) - self.low
    @property
    def range(self): return self.high - self.low


@dataclass
class Trade:
    entry_time: int
    entry_price: float
    exit_time: int = 0
    exit_price: float = 0
    side: str = "long"       # long / short
    size: float = 1.0        # position size in units
    stop_loss: float = 0
    take_profit: float = 0
    exit_reason: str = ""    # signal / stop_loss / take_profit / timeout
    pnl: float = 0
    pnl_pct: float = 0
    fees: float = 0

    @property
    def closed(self): return self.exit_time > 0

    def close_trade(self, price, time, reason="signal", commission_pct=0.04):
        self.exit_price = price
        self.exit_time = time
        self.exit_reason = reason
        if self.side == "long":
            self.pnl_pct = (self.exit_price - self.entry_price) / self.entry_price * 100
        else:
            self.pnl_pct = (self.entry_price - self.exit_price) / self.entry_price * 100
        self.pnl = self.size * self.entry_price * self.pnl_pct / 100
        # Fees: commission per side x 2 (open + close)
        self.fees = self.size * self.entry_price * (commission_pct / 100) * 2
        self.pnl -= self.fees


@dataclass
class StrategyConfig:
    name: str = "Unnamed"
    description: str = ""
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    initial_capital: float = 10000
    position_size_pct: float = 10    # % of capital per trade
    max_positions: int = 1
    stop_loss_pct: float = 2.0       # default SL %
    take_profit_pct: float = 4.0     # default TP %
    max_hold_bars: int = 0           # 0 = no limit
    commission_pct: float = 0.04     # per side, e.g. 0.04% = Binance futures taker
    slippage_pct: float = 0.02       # per trade, simulates market impact
    # Strategy parameters (flexible dict for any strategy)
    params: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_candles(symbol="BTCUSDT", interval="4h", limit=500, end_time=None, start_time=None):
    """Fetch historical candles from Binance Futures"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if end_time:
        url += f"&endTime={end_time}"
    if start_time:
        url += f"&startTime={start_time}"
    raw = fetch(url)
    return [Candle(
        time=int(k[0]), open=float(k[1]), high=float(k[2]),
        low=float(k[3]), close=float(k[4]), volume=float(k[5])
    ) for k in raw]


def fetch_candles_extended(symbol="BTCUSDT", interval="4h", total=2000, start_ms=None, end_ms=None):
    """Fetch candles by paginating. Supports optional time range (ms timestamps)."""
    all_candles = []

    if start_ms and end_ms:
        # Forward pagination from start_ms
        cursor = start_ms
        while cursor < end_ms:
            batch = fetch_candles(symbol, interval, 1500, start_time=cursor, end_time=end_ms)
            if not batch:
                break
            all_candles.extend(batch)
            cursor = batch[-1].time + 1
            if len(batch) < 100:
                break
        return all_candles

    # Default: backward pagination (latest N candles)
    end_cursor = end_ms
    while len(all_candles) < total:
        batch = fetch_candles(symbol, interval, min(1500, total - len(all_candles)), end_time=end_cursor)
        if not batch:
            break
        all_candles = batch + all_candles
        end_cursor = batch[0].time - 1
        if len(batch) < 100:
            break
    return all_candles


# ═══════════════════════════════════════════════════
# INDICATORS (pure python, no deps)
# ═══════════════════════════════════════════════════

def ema(data, period):
    if len(data) < period:
        return [None] * len(data)
    result = [None] * (period - 1)
    sma = sum(data[:period]) / period
    result.append(sma)
    k = 2 / (period + 1)
    for i in range(period, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


def sma(data, period):
    result = [None] * (period - 1)
    for i in range(period - 1, len(data)):
        result.append(sum(data[i - period + 1:i + 1]) / period)
    return result


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return [None] * len(closes)
    result = [None] * (period + 1)  # +1: first diff eats one element
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(d if d > 0 else 0)
        losses.append(-d if d < 0 else 0)
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        result.append(100 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l))
    return result


def bollinger_bands(closes, period=20, std_mult=2):
    upper, middle, lower = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None); middle.append(None); lower.append(None)
            continue
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        std = (sum((x - m) ** 2 for x in window) / period) ** 0.5
        middle.append(m); upper.append(m + std_mult * std); lower.append(m - std_mult * std)
    return upper, middle, lower


def atr(candles, period=14):
    result = [None] * period
    trs = []
    for i in range(1, len(candles)):
        tr = max(candles[i].high - candles[i].low,
                 abs(candles[i].high - candles[i - 1].close),
                 abs(candles[i].low - candles[i - 1].close))
        trs.append(tr)
    if len(trs) < period:
        return [None] * len(candles)
    avg = sum(trs[:period]) / period
    result.append(avg)
    for i in range(period, len(trs)):
        avg = (avg * (period - 1) + trs[i]) / period
        result.append(avg)
    return result


def macd(closes, fast=12, slow=26, signal=9):
    ema_f = ema(closes, fast)
    ema_s = ema(closes, slow)
    macd_line = [None if f is None or s is None else f - s for f, s in zip(ema_f, ema_s)]
    valid = [v for v in macd_line if v is not None]
    sig = ema(valid, signal)
    sig_full = [None] * (len(macd_line) - len(sig)) + sig
    hist = [None if m is None or s is None else m - s for m, s in zip(macd_line, sig_full)]
    return macd_line, sig_full, hist


def obv(candles):
    """On-Balance Volume"""
    result = [0.0]
    for i in range(1, len(candles)):
        if candles[i].close > candles[i - 1].close:
            result.append(result[-1] + candles[i].volume)
        elif candles[i].close < candles[i - 1].close:
            result.append(result[-1] - candles[i].volume)
        else:
            result.append(result[-1])
    return result


def stoch_rsi(closes, rsi_period=14, stoch_period=14, k_smooth=3):
    """Stochastic RSI → returns %K line"""
    rsi_vals = rsi(closes, rsi_period)
    result = [None] * len(rsi_vals)
    for i in range(stoch_period + rsi_period, len(rsi_vals)):
        window = [v for v in rsi_vals[i - stoch_period + 1:i + 1] if v is not None]
        if len(window) < stoch_period:
            continue
        lo, hi = min(window), max(window)
        result[i] = ((rsi_vals[i] - lo) / (hi - lo) * 100) if hi != lo else 50
    # Smooth with SMA
    valid = [v for v in result if v is not None]
    if len(valid) >= k_smooth:
        smoothed = sma(valid, k_smooth)
        j = 0
        for i in range(len(result)):
            if result[i] is not None:
                result[i] = smoothed[j]
                j += 1
    return result


def donchian(candles, period=20):
    """Donchian Channel → (upper, lower)"""
    upper, lower = [None] * len(candles), [None] * len(candles)
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1:i + 1]
        upper[i] = max(c.high for c in window)
        lower[i] = min(c.low for c in window)
    return upper, lower


def vwap_ratio(candles, period=20):
    """Price / VWAP ratio (>1 = above VWAP, <1 = below)"""
    result = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1:i + 1]
        cum_vol = sum(c.volume for c in window)
        if cum_vol == 0:
            continue
        cum_pv = sum((c.high + c.low + c.close) / 3 * c.volume for c in window)
        vw = cum_pv / cum_vol
        result[i] = candles[i].close / vw if vw > 0 else None
    return result


# ═══════════════════════════════════════════════════
# BACKTESTING ENGINE
# ═══════════════════════════════════════════════════

class BacktestEngine:
    def __init__(self, config: StrategyConfig):
        self.config = config
        self.capital = config.initial_capital
        self.trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        self.equity_curve: List[float] = []
        self.candles: List[Candle] = []

    def _close(self, trade, price, time, reason):
        """Close a trade with config's commission rate"""
        # Apply slippage on exit too
        slip = self.config.slippage_pct / 100
        if trade.side == "long":
            price = price * (1 - slip)  # sell lower
        else:
            price = price * (1 + slip)  # buy back higher
        trade.close_trade(price, time, reason, self.config.commission_pct)

    def run(self, candles: List[Candle], signal_fn, extra_indicators: Dict[str, Any] = None):
        """
        Run backtest.
        signal_fn(candles, index, indicators, open_trades) -> list of actions
        Actions: {"action": "buy"/"sell"/"close", "price": float, "sl": float, "tp": float}
        extra_indicators: optional dict merged into indicators (e.g. derivatives data)
        """
        self.candles = candles
        self.capital = self.config.initial_capital
        self.trades = []
        self.open_trades = []
        self.equity_curve = []

        # Pre-compute common indicators
        closes = [c.close for c in candles]
        indicators = {
            "ema_9": ema(closes, 9),
            "ema_21": ema(closes, 21),
            "ema_50": ema(closes, 50),
            "ema_200": ema(closes, 200),
            "sma_20": sma(closes, 20),
            "rsi_14": rsi(closes, 14),
            "atr_14": atr(candles, 14),
            "macd": macd(closes),
            "bb": bollinger_bands(closes),
        }

        # Merge extra indicators (derivatives data, etc.)
        if extra_indicators:
            indicators.update(extra_indicators)

        # Walk forward
        warmup = 200  # skip first 200 bars for indicator warmup
        for i in range(warmup, len(candles)):
            c = candles[i]

            # Check stop loss / take profit on open trades
            self._check_exits(c, i)

            # Check max hold
            if self.config.max_hold_bars > 0:
                for t in self.open_trades[:]:
                    bars_held = i - self._bar_index(t.entry_time)
                    if bars_held >= self.config.max_hold_bars:
                        self._close(t, c.close, c.time, "timeout")
                        self.trades.append(t)
                        self.open_trades.remove(t)

            # Get signals
            actions = signal_fn(candles, i, indicators, self.open_trades)

            for act in actions:
                if act["action"] == "buy" and len(self.open_trades) < self.config.max_positions:
                    self._open_trade("long", c, i, act)
                elif act["action"] == "sell" and len(self.open_trades) < self.config.max_positions:
                    self._open_trade("short", c, i, act)
                elif act["action"] == "close":
                    for t in self.open_trades[:]:
                        self._close(t, c.close, c.time, "signal")
                        self.trades.append(t)
                        self.open_trades.remove(t)

            # Track equity
            unrealized = sum(self._unrealized_pnl(t, c) for t in self.open_trades)
            self.equity_curve.append(self.capital + unrealized)

        # Close remaining trades at last price
        last = candles[-1]
        for t in self.open_trades[:]:
            self._close(t, last.close, last.time, "end")
            self.trades.append(t)
        self.open_trades.clear()

        return self.trades

    def _open_trade(self, side, candle, index, action):
        price = action.get("price", candle.close)

        # Apply slippage: buy higher, sell lower
        slip = self.config.slippage_pct / 100
        if side == "long":
            price = price * (1 + slip)
        else:
            price = price * (1 - slip)

        sl = action.get("sl", 0)
        tp = action.get("tp", 0)

        # Default SL/TP from config
        if sl == 0 and self.config.stop_loss_pct > 0:
            if side == "long":
                sl = price * (1 - self.config.stop_loss_pct / 100)
            else:
                sl = price * (1 + self.config.stop_loss_pct / 100)
        if tp == 0 and self.config.take_profit_pct > 0:
            if side == "long":
                tp = price * (1 + self.config.take_profit_pct / 100)
            else:
                tp = price * (1 - self.config.take_profit_pct / 100)

        size = self.capital * self.config.position_size_pct / 100 / price
        trade = Trade(
            entry_time=candle.time, entry_price=price,
            side=side, size=size, stop_loss=sl, take_profit=tp
        )
        self.open_trades.append(trade)

    def _check_exits(self, candle, index):
        for t in self.open_trades[:]:
            if t.side == "long":
                if t.stop_loss > 0 and candle.low <= t.stop_loss:
                    self._close(t, t.stop_loss, candle.time, "stop_loss")
                    self.capital += t.pnl
                    self.trades.append(t)
                    self.open_trades.remove(t)
                elif t.take_profit > 0 and candle.high >= t.take_profit:
                    self._close(t, t.take_profit, candle.time, "take_profit")
                    self.capital += t.pnl
                    self.trades.append(t)
                    self.open_trades.remove(t)
            else:  # short
                if t.stop_loss > 0 and candle.high >= t.stop_loss:
                    self._close(t, t.stop_loss, candle.time, "stop_loss")
                    self.capital += t.pnl
                    self.trades.append(t)
                    self.open_trades.remove(t)
                elif t.take_profit > 0 and candle.low <= t.take_profit:
                    self._close(t, t.take_profit, candle.time, "take_profit")
                    self.capital += t.pnl
                    self.trades.append(t)
                    self.open_trades.remove(t)

    def _unrealized_pnl(self, trade, candle):
        if trade.side == "long":
            return trade.size * (candle.close - trade.entry_price)
        else:
            return trade.size * (trade.entry_price - candle.close)

    def _bar_index(self, timestamp):
        for i, c in enumerate(self.candles):
            if c.time >= timestamp:
                return i
        return len(self.candles) - 1


# ═══════════════════════════════════════════════════
# EVALUATION MODULE
# ═══════════════════════════════════════════════════

def evaluate(trades: List[Trade], initial_capital: float = 10000, equity_curve: List[float] = None):
    """Calculate comprehensive performance metrics"""
    if not trades:
        return {"error": "No trades"}

    closed = [t for t in trades if t.closed]
    if not closed:
        return {"error": "No closed trades"}

    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]

    total_pnl = sum(t.pnl for t in closed)
    total_fees = sum(t.fees for t in closed)
    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = sum(t.pnl for t in losses) if losses else 0

    win_rate = len(wins) / len(closed) * 100
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = abs(gross_loss) / len(losses) if losses else 0
    profit_factor = gross_profit / abs(gross_loss) if gross_loss != 0 else 9999
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 9999

    # Max drawdown
    max_dd = 0
    max_dd_pct = 0
    if equity_curve:
        peak = equity_curve[0]
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = dd / peak * 100 if peak > 0 else 0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
                max_dd = dd

    # Sharpe ratio (annualized, assuming 4h bars = 6 per day)
    pnl_list = [t.pnl_pct for t in closed]
    if len(pnl_list) > 1:
        avg_ret = sum(pnl_list) / len(pnl_list)
        std_ret = (sum((r - avg_ret) ** 2 for r in pnl_list) / (len(pnl_list) - 1)) ** 0.5
        sharpe = (avg_ret / std_ret) * (252 * 6) ** 0.5 if std_ret > 0 else 0
    else:
        sharpe = 0

    # Sortino ratio
    downside = [r for r in pnl_list if r < 0]
    if downside:
        down_std = (sum(r ** 2 for r in downside) / len(downside)) ** 0.5
        sortino = (sum(pnl_list) / len(pnl_list)) / down_std * (252 * 6) ** 0.5 if down_std > 0 else 0
    else:
        sortino = float('inf')

    # Consecutive wins/losses
    max_consec_wins = max_consec_losses = consec = 0
    last_win = None
    for t in closed:
        is_win = t.pnl > 0
        if is_win == last_win:
            consec += 1
        else:
            consec = 1
        if is_win:
            max_consec_wins = max(max_consec_wins, consec)
        else:
            max_consec_losses = max(max_consec_losses, consec)
        last_win = is_win

    # Hold time stats
    hold_times = [(t.exit_time - t.entry_time) / 3600000 for t in closed]  # hours
    avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0

    final_capital = initial_capital + total_pnl
    roi = (final_capital - initial_capital) / initial_capital * 100

    # Long/Short breakdown
    long_trades = [t for t in closed if t.side == "long"]
    short_trades = [t for t in closed if t.side == "short"]
    long_wins = len([t for t in long_trades if t.pnl > 0])
    short_wins = len([t for t in short_trades if t.pnl > 0])

    return {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "total_fees": round(total_fees, 2),
        "net_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_rr": round(avg_rr, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 1),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        "avg_hold_hours": round(avg_hold, 1),
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "long_trades": len(long_trades),
        "short_trades": len(short_trades),
        "long_win_rate": round(long_wins / len(long_trades) * 100, 1) if long_trades else 0,
        "short_win_rate": round(short_wins / len(short_trades) * 100, 1) if short_trades else 0,
    }


def deflated_sharpe(sharpe_ratio, n_trades, n_strategies_tested=1, skewness=0, kurtosis=3):
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)
    校正多重測試偏差。n_strategies_tested = 你總共測試了多少策略。
    """
    import math as _math

    def norm_cdf(x):
        return 0.5 * _math.erfc(-x / _math.sqrt(2))

    N = max(n_strategies_tested, 1)
    n = max(n_trades, 2)
    sr = sharpe_ratio

    # Expected max SR under null (all strategies are noise)
    if N <= 1:
        e_max_sr = 0.0
    else:
        log_n = _math.log(N)
        euler_gamma = 0.5772156649
        e_max_sr = (_math.sqrt(2 * log_n)
                    * (1 - euler_gamma / (2 * log_n))
                    + euler_gamma / _math.sqrt(2 * log_n))

    # DSR statistic
    skew = skewness
    kurt = kurtosis
    denom_sq = (1 - skew * sr + (kurt - 1) / 4 * sr * sr) / (n - 1)
    if denom_sq <= 0:
        denom_sq = 1e-10
    dsr = (sr - e_max_sr) / _math.sqrt(denom_sq)

    p_value = 1 - norm_cdf(dsr)

    # Haircut
    if abs(sr) > 1e-10:
        haircut = max(0, (1 - dsr / sr) * 100) if sr > 0 else 0
    else:
        haircut = 0

    return {
        "deflated_sharpe": round(dsr, 4),
        "p_value": round(p_value, 4),
        "significant": p_value < 0.05,
        "haircut_pct": round(haircut, 1),
    }


def format_report(metrics, config=None):
    """Format evaluation metrics into readable report"""
    lines = []
    lines.append("╔══════════════════════════════════════╗")
    lines.append("║       策略回測報告                   ║")
    lines.append("╚══════════════════════════════════════╝")
    if config:
        lines.append(f"  策略: {config.name}")
        lines.append(f"  標的: {config.symbol} | 週期: {config.interval}")
        lines.append(f"  本金: ${config.initial_capital:,.0f} | 倉位: {config.position_size_pct}%")
        lines.append(f"  止損: {config.stop_loss_pct}% | 止盈: {config.take_profit_pct}%")
        lines.append("")

    m = metrics
    lines.append(f"  總交易: {m['total_trades']} | 勝: {m['wins']} | 負: {m['losses']}")
    lines.append(f"  勝率: {m['win_rate']}%")
    lines.append(f"  盈虧比: {m['avg_rr']}")
    lines.append(f"  利潤因子: {m['profit_factor']}")
    lines.append("")
    lines.append(f"  淨利潤: ${m['net_pnl']:,.2f}")
    lines.append(f"  ROI: {m['roi_pct']}%")
    lines.append(f"  手續費: ${m['total_fees']:,.2f}")
    lines.append("")
    lines.append(f"  最大回撤: ${m['max_drawdown']:,.2f} ({m['max_drawdown_pct']}%)")
    lines.append(f"  夏普比率: {m['sharpe_ratio']}")
    lines.append(f"  Sortino: {m['sortino_ratio']}")
    lines.append("")
    lines.append(f"  平均持倉: {m['avg_hold_hours']:.0f}h")
    lines.append(f"  連勝: {m['max_consec_wins']} | 連敗: {m['max_consec_losses']}")
    lines.append("")
    lines.append(f"  ${m['initial_capital']:,.0f} → ${m['final_capital']:,.2f}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
# DEMO: Built-in strategy examples
# ═══════════════════════════════════════════════════

def strategy_ema_cross(candles, i, indicators, open_trades):
    """EMA 9/21 crossover strategy"""
    actions = []
    ema9 = indicators["ema_9"]
    ema21 = indicators["ema_21"]

    if ema9[i] is None or ema21[i] is None or ema9[i-1] is None or ema21[i-1] is None:
        return actions

    # Golden cross: EMA9 crosses above EMA21
    if ema9[i-1] <= ema21[i-1] and ema9[i] > ema21[i]:
        if not open_trades:
            actions.append({"action": "buy"})
        elif open_trades and open_trades[0].side == "short":
            actions.append({"action": "close"})
            actions.append({"action": "buy"})

    # Death cross: EMA9 crosses below EMA21
    if ema9[i-1] >= ema21[i-1] and ema9[i] < ema21[i]:
        if not open_trades:
            actions.append({"action": "sell"})
        elif open_trades and open_trades[0].side == "long":
            actions.append({"action": "close"})
            actions.append({"action": "sell"})

    return actions


def strategy_rsi_reversal(candles, i, indicators, open_trades):
    """RSI oversold/overbought reversal"""
    actions = []
    rsi_val = indicators["rsi_14"]

    if i >= len(rsi_val) or rsi_val[i] is None or rsi_val[i-1] is None:
        return actions

    # RSI crosses above 30 (oversold recovery)
    if rsi_val[i-1] <= 30 and rsi_val[i] > 30 and not open_trades:
        actions.append({"action": "buy"})

    # RSI crosses below 70 (overbought reversal)
    if rsi_val[i-1] >= 70 and rsi_val[i] < 70 and not open_trades:
        actions.append({"action": "sell"})

    # Exit: RSI back to neutral
    if open_trades:
        t = open_trades[0]
        if t.side == "long" and rsi_val[i] > 65:
            actions.append({"action": "close"})
        elif t.side == "short" and rsi_val[i] < 35:
            actions.append({"action": "close"})

    return actions


# ═══════════════════════════════════════════════════
# MONTE CARLO SIMULATION
# ═══════════════════════════════════════════════════

def monte_carlo(trades, initial_capital=10000, n_simulations=1000, confidence=0.95):
    """
    蒙地卡羅模擬 — 隨機打亂交易順序，跑 n_simulations 次，
    看策略在不同運氣下的表現分佈。
    """
    closed = [t for t in trades if t.closed]
    if len(closed) < 2:
        return {
            "median_roi": 0, "mean_roi": 0, "worst_roi": 0, "best_roi": 0,
            "p_profit": 0, "median_drawdown": 0, "worst_drawdown": 0,
            "ruin_probability": 0, "distribution": [], "drawdown_distribution": [],
        }

    pnl_pcts = [t.pnl_pct for t in closed]
    rois = []
    drawdowns = []
    tail = (1 - confidence) / 2  # 0.025 for 95%

    for _ in range(n_simulations):
        shuffled = pnl_pcts[:]
        random.shuffle(shuffled)
        equity = initial_capital
        peak = equity
        max_dd = 0
        for pct in shuffled:
            equity *= (1 + pct / 100)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        roi = (equity - initial_capital) / initial_capital * 100
        rois.append(round(roi, 2))
        drawdowns.append(round(max_dd, 2))

    rois.sort()
    drawdowns.sort()
    n = len(rois)
    lo = int(n * tail)
    hi = int(n * (1 - tail))

    p_profit = sum(1 for r in rois if r > 0) / n
    ruin_count = sum(1 for r in rois if r <= -50)

    return {
        "median_roi": round(rois[n // 2], 2),
        "mean_roi": round(sum(rois) / n, 2),
        "worst_roi": round(rois[max(lo, 0)], 2),
        "best_roi": round(rois[min(hi, n - 1)], 2),
        "p_profit": round(p_profit, 4),
        "median_drawdown": round(drawdowns[n // 2], 2),
        "worst_drawdown": round(drawdowns[min(hi, n - 1)], 2),
        "ruin_probability": round(ruin_count / n, 4),
        "distribution": rois,
        "drawdown_distribution": drawdowns,
    }


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("📊 Strategy AI - Backtesting Engine")
    print("拉取歷史數據...")

    candles = fetch_candles_extended("BTCUSDT", "4h", 2000)
    print(f"  {len(candles)} 根 4h K 線")
    start = datetime.fromtimestamp(candles[0].time / 1000, TZ8)
    end = datetime.fromtimestamp(candles[-1].time / 1000, TZ8)
    print(f"  {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")

    # Demo: EMA crossover
    print("\n═══ 策略 1: EMA 9/21 交叉 ═══")
    config1 = StrategyConfig(
        name="EMA 9/21 Cross",
        symbol="BTCUSDT", interval="4h",
        initial_capital=10000, position_size_pct=10,
        stop_loss_pct=3, take_profit_pct=6,
    )
    engine1 = BacktestEngine(config1)
    trades1 = engine1.run(candles, strategy_ema_cross)
    metrics1 = evaluate(trades1, config1.initial_capital, engine1.equity_curve)
    print(format_report(metrics1, config1))

    # Demo: RSI reversal
    print("\n═══ 策略 2: RSI 反轉 ═══")
    config2 = StrategyConfig(
        name="RSI Reversal",
        symbol="BTCUSDT", interval="4h",
        initial_capital=10000, position_size_pct=10,
        stop_loss_pct=2, take_profit_pct=5,
    )
    engine2 = BacktestEngine(config2)
    trades2 = engine2.run(candles, strategy_rsi_reversal)
    metrics2 = evaluate(trades2, config2.initial_capital, engine2.equity_curve)
    print(format_report(metrics2, config2))

    print("\n✅ 回測引擎就緒")
