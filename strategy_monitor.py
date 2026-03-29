#!/usr/bin/env python3
"""
Strategy AI - Strategy Monitor
策略衰退監控：追蹤已上線策略的表現，偵測衰退，推送警報。

用法：
  python3 strategy_monitor.py                # 跑一次全部監控
  python3 strategy_monitor.py --add <file>   # 加入監控
  python3 strategy_monitor.py --list         # 列出監控中的策略
  python3 strategy_monitor.py --report       # 完整報告
"""
import json, os, sys, copy, time, math, argparse
from datetime import datetime, timezone, timedelta
from backtest_engine import (
    BacktestEngine, StrategyConfig, evaluate,
    fetch_candles_extended, Candle, deflated_sharpe,
)
from llm_pipeline import compile_strategy
from optimizer import walk_forward, rolling_walk_forward

WORK = os.path.dirname(os.path.abspath(__file__))
TZ8 = timezone(timedelta(hours=8))
MONITOR_FILE = os.path.join(WORK, "monitored_strategies.json")
HISTORY_FILE = os.path.join(WORK, "monitor_history.json")


# ═══════════════════════════════════════════════════
# STRATEGY REGISTRY
# ═══════════════════════════════════════════════════

def load_strategies():
    if os.path.exists(MONITOR_FILE):
        with open(MONITOR_FILE) as f:
            return json.load(f)
    return []


def save_strategies(strategies):
    with open(MONITOR_FILE, "w") as f:
        json.dump(strategies, f, indent=2, ensure_ascii=False)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {}


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def add_strategy(name, code, symbol="BTCUSDT", interval="4h",
                 sl=2.0, tp=4.0, thresholds=None):
    """加入監控"""
    strategies = load_strategies()

    # 驗證代碼能編譯
    fn, err = compile_strategy(code)
    if err:
        return {"error": f"編譯失敗: {err}"}

    entry = {
        "id": f"{name}_{int(time.time())}",
        "name": name,
        "code": code,
        "symbol": symbol,
        "interval": interval,
        "sl": sl,
        "tp": tp,
        "added_at": datetime.now(TZ8).isoformat(),
        "status": "active",  # active / warning / stopped
        "thresholds": thresholds or {
            "min_sharpe": 0.3,
            "max_drawdown_pct": 15,
            "max_consec_losses": 5,
            "min_win_rate": 30,
            "max_overfit_ratio": 5,
        },
    }

    # 跑一次 baseline
    baseline = _run_check(entry, label="baseline")
    if baseline:
        entry["baseline"] = {
            "sharpe": baseline["metrics"].get("sharpe_ratio", 0),
            "roi": baseline["metrics"].get("roi_pct", 0),
            "win_rate": baseline["metrics"].get("win_rate", 0),
            "drawdown": baseline["metrics"].get("max_drawdown_pct", 0),
            "trades": baseline["metrics"].get("total_trades", 0),
            "checked_at": datetime.now(TZ8).isoformat(),
        }

    strategies.append(entry)
    save_strategies(strategies)
    return {"ok": True, "id": entry["id"], "baseline": entry.get("baseline")}


def remove_strategy(strategy_id):
    strategies = load_strategies()
    strategies = [s for s in strategies if s["id"] != strategy_id]
    save_strategies(strategies)


def list_strategies():
    return load_strategies()


# ═══════════════════════════════════════════════════
# MONITORING ENGINE
# ═══════════════════════════════════════════════════

def _run_check(strategy_entry, label="check", candle_count=1500):
    """跑一次回測，返回完整結果"""
    code = strategy_entry["code"]
    fn, err = compile_strategy(code)
    if err:
        return {"error": err}

    try:
        candles = fetch_candles_extended(
            strategy_entry["symbol"],
            strategy_entry["interval"],
            candle_count,
        )
        if not candles or len(candles) < 200:
            return {"error": "數據不足"}

        config = StrategyConfig(
            name=strategy_entry["name"],
            symbol=strategy_entry["symbol"],
            interval=strategy_entry["interval"],
            initial_capital=10000,
            position_size_pct=10,
            stop_loss_pct=strategy_entry["sl"],
            take_profit_pct=strategy_entry["tp"],
        )

        # 衍生品數據
        extra = {}
        try:
            from derivatives_data import fetch_all_derivatives
            from smc_genes import compute_smc_indicators
            extra = fetch_all_derivatives(
                strategy_entry["symbol"],
                strategy_entry["interval"],
                500, candles[0].time, candles[-1].time,
                candles=candles,
            )
            smc = compute_smc_indicators(candles)
            extra.update(smc)
        except Exception:
            pass

        engine = BacktestEngine(config)
        trades = engine.run(candles, fn, extra_indicators=extra)
        metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

        if "error" in metrics:
            return {"error": metrics["error"]}

        # Rolling walk-forward
        rwf = rolling_walk_forward(candles, fn, config, extra_indicators=extra)

        # 最近 N 筆交易的表現（滾動窗口）
        closed = [t for t in trades if t.closed]
        recent_n = min(20, len(closed))
        recent_trades = closed[-recent_n:] if closed else []
        recent_wins = sum(1 for t in recent_trades if t.pnl > 0)
        recent_wr = recent_wins / len(recent_trades) * 100 if recent_trades else 0
        recent_pnl = sum(t.pnl for t in recent_trades)

        # 連虧計數
        consec_losses = 0
        if closed:
            for t in reversed(closed):
                if t.pnl <= 0:
                    consec_losses += 1
                else:
                    break

        # 滾動 Sharpe（最近 30 筆）
        recent_30 = closed[-30:] if len(closed) >= 30 else closed
        if len(recent_30) >= 5:
            rets = [t.pnl_pct for t in recent_30]
            avg_r = sum(rets) / len(rets)
            std_r = math.sqrt(sum((r - avg_r) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.01
            rolling_sharpe = (avg_r / std_r) * math.sqrt(252 * 6) if std_r > 0 else 0
        else:
            rolling_sharpe = 0

        return {
            "label": label,
            "timestamp": datetime.now(TZ8).isoformat(),
            "metrics": metrics,
            "rolling_sharpe": round(rolling_sharpe, 2),
            "recent_win_rate": round(recent_wr, 1),
            "recent_pnl": round(recent_pnl, 2),
            "consec_losses": consec_losses,
            "rolling_wf": {
                "consistency": rwf.get("consistency", 0),
                "avg_test_roi": rwf.get("avg_test_roi", 0),
                "robust": rwf.get("robust", False),
            },
            "data_range": {
                "from": candles[0].time,
                "to": candles[-1].time,
                "bars": len(candles),
            },
        }

    except Exception as e:
        return {"error": str(e)}


def check_alerts(strategy_entry, check_result):
    """檢查是否觸發警報"""
    if "error" in check_result:
        return [{"level": "error", "msg": f"檢查失敗: {check_result['error']}"}]

    alerts = []
    th = strategy_entry.get("thresholds", {})
    m = check_result["metrics"]
    baseline = strategy_entry.get("baseline", {})

    # 1. Sharpe 衰退
    min_sharpe = th.get("min_sharpe", 0.3)
    current_sharpe = check_result.get("rolling_sharpe", 0)
    if current_sharpe < min_sharpe:
        alerts.append({
            "level": "warning",
            "type": "sharpe_decay",
            "msg": f"Sharpe 衰退: {current_sharpe:.2f} < {min_sharpe}",
        })

    # 2. 回撤超標
    max_dd = th.get("max_drawdown_pct", 15)
    current_dd = m.get("max_drawdown_pct", 0)
    if current_dd > max_dd:
        alerts.append({
            "level": "critical",
            "type": "drawdown",
            "msg": f"回撤超標: {current_dd:.1f}% > {max_dd}%",
        })

    # 3. 連虧
    max_cl = th.get("max_consec_losses", 5)
    current_cl = check_result.get("consec_losses", 0)
    if current_cl >= max_cl:
        alerts.append({
            "level": "critical",
            "type": "consec_losses",
            "msg": f"連虧 {current_cl} 筆 (閾值 {max_cl})",
        })

    # 4. 勝率下滑
    min_wr = th.get("min_win_rate", 30)
    recent_wr = check_result.get("recent_win_rate", 0)
    if recent_wr < min_wr:
        alerts.append({
            "level": "warning",
            "type": "win_rate_drop",
            "msg": f"近期勝率: {recent_wr:.1f}% < {min_wr}%",
        })

    # 5. 跟 baseline 比較 — ROI 大幅衰退
    if baseline:
        base_sharpe = baseline.get("sharpe", 0)
        if base_sharpe > 0 and current_sharpe < base_sharpe * 0.3:
            alerts.append({
                "level": "critical",
                "type": "performance_collapse",
                "msg": f"表現崩塌: Sharpe {current_sharpe:.2f} vs baseline {base_sharpe:.2f} (跌 {(1 - current_sharpe / base_sharpe) * 100:.0f}%)",
            })

    # 6. Walk-forward 不穩健
    rwf = check_result.get("rolling_wf", {})
    if not rwf.get("robust", True):
        alerts.append({
            "level": "warning",
            "type": "wf_unstable",
            "msg": f"滾動 WF 不穩健 (一致性 {rwf.get('consistency', 0):.0%})",
        })

    return alerts


def run_monitor(verbose=True):
    """跑一次全部監控，返回結果 + 警報"""
    strategies = load_strategies()
    if not strategies:
        if verbose:
            print("  沒有監控中的策略")
        return []

    history = load_history()
    results = []

    for s in strategies:
        if s.get("status") == "stopped":
            continue

        if verbose:
            print(f"  檢查: {s['name']} ({s['symbol']} {s['interval']})...")

        check = _run_check(s)
        alerts = check_alerts(s, check)

        # 更新狀態
        if any(a["level"] == "critical" for a in alerts):
            s["status"] = "warning"
        elif not alerts:
            s["status"] = "active"

        # 存歷史
        sid = s["id"]
        if sid not in history:
            history[sid] = []
        history[sid].append({
            "timestamp": datetime.now(TZ8).isoformat(),
            "rolling_sharpe": check.get("rolling_sharpe", 0),
            "recent_wr": check.get("recent_win_rate", 0),
            "consec_losses": check.get("consec_losses", 0),
            "roi": check.get("metrics", {}).get("roi_pct", 0),
            "drawdown": check.get("metrics", {}).get("max_drawdown_pct", 0),
            "alerts": len(alerts),
        })
        # 只保留最近 90 天的歷史
        history[sid] = history[sid][-90:]

        result = {
            "strategy": s,
            "check": check,
            "alerts": alerts,
        }
        results.append(result)

        if verbose:
            m = check.get("metrics", {})
            print(f"    Sharpe: {check.get('rolling_sharpe', 0):.2f} | "
                  f"WR: {check.get('recent_win_rate', 0):.1f}% | "
                  f"DD: {m.get('max_drawdown_pct', 0):.1f}% | "
                  f"連虧: {check.get('consec_losses', 0)}")
            if alerts:
                for a in alerts:
                    icon = "🔴" if a["level"] == "critical" else "🟡"
                    print(f"    {icon} {a['msg']}")
            else:
                print(f"    ✅ 正常")

    save_strategies(strategies)
    save_history(history)
    return results


def format_monitor_report(results):
    """格式化監控報告（Telegram 推送用）"""
    if not results:
        return "📊 策略監控：沒有監控中的策略"

    lines = ["📊 策略衰退監控報告", ""]
    now = datetime.now(TZ8).strftime("%Y-%m-%d %H:%M")
    lines.append(f"⏰ {now}")
    lines.append("")

    critical_count = 0
    warning_count = 0

    for r in results:
        s = r["strategy"]
        check = r["check"]
        alerts = r["alerts"]
        m = check.get("metrics", {})

        status_icon = "✅" if not alerts else ("🔴" if any(a["level"] == "critical" for a in alerts) else "🟡")
        lines.append(f"{status_icon} {s['name']} ({s['symbol']} {s['interval']})")
        lines.append(f"  Sharpe: {check.get('rolling_sharpe', 0):.2f} | "
                     f"WR: {check.get('recent_win_rate', 0):.1f}% | "
                     f"DD: {m.get('max_drawdown_pct', 0):.1f}%")

        if alerts:
            for a in alerts:
                icon = "🔴" if a["level"] == "critical" else "🟡"
                lines.append(f"  {icon} {a['msg']}")
                if a["level"] == "critical":
                    critical_count += 1
                else:
                    warning_count += 1
        lines.append("")

    # 摘要
    total = len(results)
    healthy = total - sum(1 for r in results if r["alerts"])
    lines.append(f"總計: {total} 策略 | ✅{healthy} 🟡{warning_count} 🔴{critical_count}")

    return "\n".join(lines)


def get_strategy_trend(strategy_id, days=30):
    """取得策略的歷史趨勢（用於前端圖表）"""
    history = load_history()
    entries = history.get(strategy_id, [])
    return entries[-days:]


# ═══════════════════════════════════════════════════
# API HELPERS (供 api.py 調用)
# ═══════════════════════════════════════════════════

def api_add_strategy(name, code, symbol, interval, sl, tp, thresholds=None):
    return add_strategy(name, code, symbol, interval, sl, tp, thresholds)


def api_run_monitor():
    results = run_monitor(verbose=False)
    formatted = []
    for r in results:
        s = r["strategy"]
        check = r["check"]
        formatted.append({
            "id": s["id"],
            "name": s["name"],
            "symbol": s["symbol"],
            "interval": s["interval"],
            "status": s.get("status", "active"),
            "rolling_sharpe": check.get("rolling_sharpe", 0),
            "recent_win_rate": check.get("recent_win_rate", 0),
            "consec_losses": check.get("consec_losses", 0),
            "roi": check.get("metrics", {}).get("roi_pct", 0),
            "drawdown": check.get("metrics", {}).get("max_drawdown_pct", 0),
            "wf_robust": check.get("rolling_wf", {}).get("robust", False),
            "alerts": r["alerts"],
            "checked_at": check.get("timestamp"),
        })
    return formatted


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="策略衰退監控")
    parser.add_argument("--add", help="加入監控（JSON 檔案路徑）")
    parser.add_argument("--list", action="store_true", help="列出監控中的策略")
    parser.add_argument("--report", action="store_true", help="完整報告")
    parser.add_argument("--remove", help="移除策略（ID）")
    args = parser.parse_args()

    if args.list:
        strategies = list_strategies()
        if not strategies:
            print("沒有監控中的策略")
        else:
            for s in strategies:
                status = {"active": "✅", "warning": "🟡", "stopped": "⏹"}.get(s["status"], "?")
                print(f"  {status} {s['name']} ({s['symbol']} {s['interval']}) — {s['id']}")
                if s.get("baseline"):
                    b = s["baseline"]
                    print(f"     Baseline: Sharpe {b['sharpe']:.2f} | ROI {b['roi']:.1f}% | WR {b['win_rate']:.1f}%")

    elif args.add:
        if os.path.exists(args.add):
            with open(args.add) as f:
                data = json.load(f)
            result = add_strategy(
                data["name"], data["code"],
                data.get("symbol", "BTCUSDT"),
                data.get("interval", "4h"),
                data.get("sl", 2.0), data.get("tp", 4.0),
            )
            print(f"  加入監控: {result}")
        else:
            print(f"  檔案不存在: {args.add}")

    elif args.remove:
        remove_strategy(args.remove)
        print(f"  已移除: {args.remove}")

    elif args.report:
        print("📊 策略衰退監控")
        print("=" * 50)
        results = run_monitor(verbose=True)
        print()
        print(format_monitor_report(results))

    else:
        print("📊 策略衰退監控 — 執行檢查")
        print("=" * 50)
        results = run_monitor(verbose=True)
        if results:
            report = format_monitor_report(results)
            print()
            print(report)
