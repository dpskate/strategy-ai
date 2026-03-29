#!/usr/bin/env python3
"""
Strategy AI - Portfolio Backtester
多幣種/多商品池組合回測引擎。

解決單一策略在單一標的上觸發頻率過低的問題。
將同一個策略平鋪到多個標的，共享一個總資金池，計算整體資金曲線和 Sharpe。
"""

import json, os, copy, time, math
from datetime import datetime, timezone, timedelta

from backtest_engine import Trade, StrategyConfig, evaluate, fetch_candles_extended
from llm_pipeline import compile_strategy

WORK = os.path.dirname(os.path.abspath(__file__))
TZ8 = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════
# PORTFOLIO DATA MANAGER
# ═══════════════════════════════════════════════════

class SymbolData:
    def __init__(self, symbol, candles, indicators):
        self.symbol = symbol
        self.candles = candles
        self.indicators = indicators
        # 預建 index mapping，方便按 timestamp 查找
        self.ts_to_idx = {c.time: i for i, c in enumerate(candles)}


def fetch_universe_data(symbols, interval="4h", limit=1500):
    """序列拉取多個標的的 K 線與指標數據 (最穩做法)"""
    from derivatives_data import fetch_all_derivatives
    from smc_genes import compute_smc_indicators
    
    universe = {}
    print(f"📥 開始序列拉取 Universe 數據: {symbols} ({interval})")
    
    for sym in symbols:
        try:
            candles = fetch_candles_extended(sym, interval, limit)
            if not candles or len(candles) < 100:
                print(f"    ⚠️ {sym} 數據不足")
                continue
                
            start_t, end_t = candles[0].time, candles[-1].time
            extra = fetch_all_derivatives(sym, interval, 500, start_t, end_t, candles=candles)
            
            try:
                smc = compute_smc_indicators(candles)
                extra.update(smc)
            except Exception as e:
                print(f"    ⚠️ {sym} SMC 失敗: {e}")
                
            universe[sym] = SymbolData(sym, candles, extra)
            print(f"    ✅ {sym} 完成 ({len(candles)} 根 K 線)")
        except Exception as e:
            print(f"    ❌ {sym} 失敗: {e}")
            
    return universe


# ═══════════════════════════════════════════════════
# PORTFOLIO ENGINE
# ═══════════════════════════════════════════════════

class PortfolioTrade(Trade):
    def __init__(self, symbol, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.symbol = symbol


class PortfolioConfig:
    def __init__(self, initial_capital=10000, max_open_positions=5, position_size_pct=20,
                 stop_loss_pct=2.0, take_profit_pct=4.0, commission_pct=0.04, slippage_pct=0.02):
        self.initial_capital = initial_capital
        self.max_open_positions = max_open_positions
        self.position_size_pct = position_size_pct / 100.0  # 每次動用當前總資金的百分比
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.commission_pct = commission_pct / 100.0
        self.slippage_pct = slippage_pct / 100.0


class PortfolioEngine:
    def __init__(self, config: PortfolioConfig):
        self.config = config
        self.equity_curve = []
        self.trades = []
        
    def run(self, strategy_fn, universe_data: dict):
        """
        執行組合回測。
        universe_data: dict of {symbol: SymbolData}
        """
        # 建立全局時間軸 (Global Timeline)
        all_timestamps = set()
        for sym, sd in universe_data.items():
            all_timestamps.update(sd.ts_to_idx.keys())
        timeline = sorted(list(all_timestamps))
        
        cash = self.config.initial_capital
        open_trades = [] # list of PortfolioTrade
        closed_trades = []
        
        print(f"🚀 開始組合回測... 總時間節點數: {len(timeline)}")
        
        for ts in timeline:
            # 1. 更新每個持倉的當前價格，並檢查固定止盈止損
            current_equity = cash
            active_symbols = set()
            
            for t in open_trades:
                sym = t.symbol
                sd = universe_data[sym]
                idx = sd.ts_to_idx.get(ts)
                
                if idx is None:
                    # 當前時間點該幣種無數據，用上一個價格估算權益
                    current_equity += t.size * t.entry_price * (1 if t.side == "long" else -1) # Simplified, uses raw entry val
                    # Actually, better to track last known close price per symbol
                    continue 
                    
                candle = sd.candles[idx]
                t.exit_time = candle.time
                active_symbols.add(sym)
                
                # 計算未實現盈虧加入當前權益
                unrealized_pnl = 0
                if t.side == "long":
                    unrealized_pnl = (candle.close - t.entry_price) * t.size
                else:
                    unrealized_pnl = (t.entry_price - candle.close) * t.size
                current_equity += (t.size * t.entry_price) + unrealized_pnl
                
                # 檢查止盈止損
                price_change_pct = ((candle.close - t.entry_price) / t.entry_price) * 100
                if t.side == "short":
                    price_change_pct = -price_change_pct
                    
                exit_price = None
                reason = None
                
                if price_change_pct <= -self.config.stop_loss_pct:
                    exit_price = t.entry_price * (1 - self.config.stop_loss_pct / 100) if t.side == "long" else t.entry_price * (1 + self.config.stop_loss_pct / 100)
                    reason = "SL"
                elif price_change_pct >= self.config.take_profit_pct:
                    exit_price = t.entry_price * (1 + self.config.take_profit_pct / 100) if t.side == "long" else t.entry_price * (1 - self.config.take_profit_pct / 100)
                    reason = "TP"
                    
                if exit_price is not None:
                    # 執行平倉
                    t.exit_price = exit_price * (1 - self.config.slippage_pct if t.side == "long" else 1 + self.config.slippage_pct)
                    t.closed = True
                    t.exit_reason = reason
                    # 計算 PnL
                    gross_pnl = (t.exit_price - t.entry_price) * t.size if t.side == "long" else (t.entry_price - t.exit_price) * t.size
                    fee = (t.entry_price * t.size + t.exit_price * t.size) * self.config.commission_pct
                    t.pnl = gross_pnl - fee
                    t.pnl_pct = (t.pnl / (t.entry_price * t.size)) * 100
                    
                    cash += (t.entry_price * t.size) + t.pnl
                    closed_trades.append(t)
            
            # 移除已平倉的交易
            open_trades = [t for t in open_trades if not t.closed]
            
            # 2. 跑策略函數，尋找新信號或策略平倉信號
            for sym, sd in universe_data.items():
                idx = sd.ts_to_idx.get(ts)
                if idx is None: continue
                
                sym_open_trades = [t for t in open_trades if t.symbol == sym]
                
                try:
                    # 執行策略 (注意：策略需要 global namespace 的 _lookup_nearest, 這裡通過 indicators 傳遞或者策略自帶)
                    actions = strategy_fn(sd.candles, idx, sd.indicators, sym_open_trades)
                except Exception as e:
                    actions = []
                    
                for action in actions:
                    act = action.get("action")
                    candle = sd.candles[idx]
                    
                    # 策略平倉
                    if act == "close" and sym_open_trades:
                        t = sym_open_trades[0]
                        t.exit_price = candle.close * (1 - self.config.slippage_pct if t.side == "long" else 1 + self.config.slippage_pct)
                        t.exit_time = candle.time
                        t.closed = True
                        t.exit_reason = "Strategy"
                        
                        gross_pnl = (t.exit_price - t.entry_price) * t.size if t.side == "long" else (t.entry_price - t.exit_price) * t.size
                        fee = (t.entry_price * t.size + t.exit_price * t.size) * self.config.commission_pct
                        t.pnl = gross_pnl - fee
                        t.pnl_pct = (t.pnl / (t.entry_price * t.size)) * 100
                        
                        cash += (t.entry_price * t.size) + t.pnl
                        closed_trades.append(t)
                        open_trades.remove(t)
                        sym_open_trades.remove(t)
                        
                    # 開倉
                    elif act in ("buy", "sell") and not sym_open_trades:
                        if len(open_trades) < self.config.max_open_positions:
                            # 計算倉位
                            trade_val = current_equity * self.config.position_size_pct
                            if cash >= trade_val * 0.1:  # 假設有槓桿，這裡簡化處理，要求至少有10%現金
                                entry_price = candle.close * (1 + self.config.slippage_pct if act == "buy" else 1 - self.config.slippage_pct)
                                size = trade_val / entry_price
                                
                                new_trade = PortfolioTrade(
                                    symbol=sym,
                                    side="long" if act == "buy" else "short",
                                    entry_time=candle.time,
                                    entry_price=entry_price,
                                    size=size
                                )
                                open_trades.append(new_trade)
                                cash -= trade_val # 扣除佔用保證金/現貨
                                
            # 記錄總權益 (包含未實現)
            total_equity = cash
            for t in open_trades:
                sym = t.symbol
                idx = universe_data[sym].ts_to_idx.get(ts)
                current_price = universe_data[sym].candles[idx].close if idx is not None else t.entry_price
                
                unrealized = (current_price - t.entry_price) * t.size if t.side == "long" else (t.entry_price - current_price) * t.size
                total_equity += (t.entry_price * t.size) + unrealized
                
            self.equity_curve.append(total_equity)
            
        self.trades = closed_trades
        return closed_trades


def evaluate_portfolio(trades, initial_capital, equity_curve):
    """計算組合層級績效"""
    if not trades:
        return {"error": "沒有交易"}
        
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    roi_pct = (final_capital - initial_capital) / initial_capital * 100
    
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    
    win_rate = len(wins) / len(trades) * 100
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 9999
    
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 0
    
    # Drawdown
    max_dd = 0
    peak = initial_capital
    for eq in equity_curve:
        if eq > peak: peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd: max_dd = dd
        
    # Sharpe Ratio (Daily)
    # Assume timeline is e.g. 4H, so 6 bars per day. Approximate returns.
    if len(equity_curve) > 1:
        rets = [(equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1] for i in range(1, len(equity_curve))]
        avg_ret = sum(rets) / len(rets)
        std_ret = math.sqrt(sum((r - avg_ret)**2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.01
        # Convert period sharpe to annualized (assuming 4H = 6 periods/day * 365 = 2190)
        sharpe_ratio = (avg_ret / std_ret) * math.sqrt(2190) if std_ret > 0 else 0
    else:
        sharpe_ratio = 0
        
    # 按幣種統計
    symbol_stats = {}
    for t in trades:
        if t.symbol not in symbol_stats:
            symbol_stats[t.symbol] = {"trades": 0, "wins": 0, "pnl": 0}
        symbol_stats[t.symbol]["trades"] += 1
        if t.pnl > 0: symbol_stats[t.symbol]["wins"] += 1
        symbol_stats[t.symbol]["pnl"] += t.pnl
        
    for sym, stats in symbol_stats.items():
        stats["win_rate"] = stats["wins"] / stats["trades"] * 100
        stats["pnl"] = round(stats["pnl"], 2)

    return {
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "roi_pct": round(roi_pct, 2),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_rr": round(avg_rr, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "symbol_breakdown": symbol_stats
    }


# ═══════════════════════════════════════════════════
# TEST SCRIPT
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    print("🌍 Strategy AI - Portfolio Backtester")
    
    # 測試幣種池 (Universe)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    
    # 獲取數據
    universe_data = fetch_universe_data(symbols, "4h", 1500)
    
    # 定義一個策略 (純粹的 SMC OB 策略)
    code = """def strategy(candles, i, indicators, open_trades):
    def _lookup_nearest(data_dict, ts):
        if not data_dict: return None
        if ts in data_dict: return data_dict[ts]
        keys = sorted(data_dict.keys())
        from bisect import bisect_right
        idx = bisect_right(keys, ts) - 1
        if idx < 0: return None
        return data_dict[keys[idx]]

    closes = [c.close for c in candles[:i+1]]
    if len(closes) < 50:
        return []
        
    actions = []
    _smc_ob_b = indicators.get('smc_ob_bull', {})
    _smc_ob_b_val = _lookup_nearest(_smc_ob_b, candles[i].time)
    
    _smc_ob_r = indicators.get('smc_ob_bear', {})
    _smc_ob_r_val = _lookup_nearest(_smc_ob_r, candles[i].time)
    
    if not open_trades:
        if _smc_ob_b_val == True:
            actions.append({"action": "buy"})
        elif _smc_ob_r_val == True:
            actions.append({"action": "sell"})
            
    if open_trades:
        from backtest_engine import rsi
        rsi_ex = rsi(closes, 14)
        if rsi_ex[i] is not None:
            if open_trades[0].side == 'long' and rsi_ex[i] > 75:
                actions.append({"action": "close"})
            elif open_trades[0].side == 'short' and rsi_ex[i] < 25:
                actions.append({"action": "close"})
                
    return actions
"""
    print("\n編譯策略...")
    fn, err = compile_strategy(code)
    if err:
        print(f"編譯失敗: {err}")
        exit(1)
        
    # 組合配置：資金 10000，最多同時開 5 單，每單用總資金 20%
    config = PortfolioConfig(
        initial_capital=10000,
        max_open_positions=5,
        position_size_pct=20,
        stop_loss_pct=4.0,
        take_profit_pct=8.0
    )
    
    engine = PortfolioEngine(config)
    trades = engine.run(fn, universe_data)
    
    print("\n📊 組合回測績效:")
    metrics = evaluate_portfolio(trades, config.initial_capital, engine.equity_curve)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
