#!/usr/bin/env python3
"""
多幣種 + 短週期批量研發
目標：增加交易次數，驗證策略泛化
"""
import json, time, sys, os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_engine import fetch_candles_extended, evaluate, monte_carlo, deflated_sharpe
from auto_research import run_research, dna_to_code, dna_to_description, format_research_results
from optimizer import walk_forward, rolling_walk_forward
from llm_pipeline import compile_strategy
from derivatives_data import fetch_all_derivatives
from smc_genes import compute_smc_indicators

TZ8 = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════
# 研發配置
# ═══════════════════════════════════════════════════
TASKS = [
    {
        "name": "BTC 15m（短週期增加交易次數）",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "candles": 3000,  # ~31 天的 15m 數據
        "generations": 12,
        "population_size": 25,
        "top_k": 5,
    },
    {
        "name": "ETH 1H（多幣種泛化驗證）",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "candles": 2000,  # ~83 天
        "generations": 12,
        "population_size": 25,
        "top_k": 5,
    },
    {
        "name": "ETH 4H（多幣種泛化驗證）",
        "symbol": "ETHUSDT",
        "interval": "4h",
        "candles": 1500,  # ~250 天
        "generations": 12,
        "population_size": 25,
        "top_k": 5,
    },
]


def run_task(task):
    """跑單個研發任務"""
    print(f"\n{'='*60}")
    print(f"🚀 {task['name']}")
    print(f"   {task['symbol']} | {task['interval']} | {task['candles']} 根 K 線")
    print(f"   {task['generations']} 代 x {task['population_size']} 個體")
    print(f"{'='*60}\n")

    # 1. 拉數據
    print("📊 拉取 K 線數據...")
    t0 = time.time()
    candles = fetch_candles_extended(
        symbol=task["symbol"],
        interval=task["interval"],
        total=task["candles"],
    )
    print(f"   ✅ {len(candles)} 根 K 線（{time.time()-t0:.1f}s）")

    # 2. 拉衍生品數據
    print("📈 拉取衍生品數據...")
    t0 = time.time()
    try:
        deriv = fetch_all_derivatives(task["symbol"])
        print(f"   ✅ 衍生品數據就緒（{time.time()-t0:.1f}s）")
    except Exception as e:
        print(f"   ⚠️ 衍生品數據失敗: {e}，繼續不帶衍生品")
        deriv = {}

    # 3. 計算 SMC 指標
    print("🔍 計算 SMC 指標...")
    t0 = time.time()
    try:
        smc = compute_smc_indicators(candles)
        deriv.update(smc)
        print(f"   ✅ SMC 指標就緒（{time.time()-t0:.1f}s）")
    except Exception as e:
        print(f"   ⚠️ SMC 計算失敗: {e}")

    # 4. 跑進化演算法
    print("\n🧬 開始進化研發...\n")
    t0 = time.time()
    results = run_research(
        candles,
        generations=task["generations"],
        population_size=task["population_size"],
        top_k=task["top_k"],
        direction="both",
        extra_indicators=deriv if deriv else None,
    )
    elapsed = time.time() - t0
    print(f"\n⏱️ 研發耗時: {elapsed:.0f}s")

    # 5. 對每個結果做深度驗證
    verified = []
    for r in results:
        code = r.get("code", "")
        strategy_fn, err = compile_strategy(code)
        if err or not strategy_fn:
            continue

        # Walk-forward
        try:
            wf = rolling_walk_forward(candles, strategy_fn, n_splits=5, extra_indicators=deriv if deriv else None)
            wf_consistency = wf.get("consistency", 0)
        except:
            wf_consistency = 0

        # Deflated Sharpe
        try:
            dsr = deflated_sharpe(r["metrics"], len(results))
            dsr_val = dsr.get("dsr", 0)
            dsr_p = dsr.get("p_value", 1)
        except:
            dsr_val = 0
            dsr_p = 1

        # Monte Carlo
        trades_for_mc = r.get("trades", [])
        mc_result = None
        if len(trades_for_mc) >= 5:
            try:
                mc_result = monte_carlo(trades_for_mc, n_simulations=500)
            except:
                pass

        r["wf_consistency"] = wf_consistency
        r["dsr"] = dsr_val
        r["dsr_p"] = dsr_p
        r["mc"] = mc_result
        verified.append(r)

    return {
        "task": task,
        "results": verified,
        "elapsed": elapsed,
        "candle_count": len(candles),
    }


def format_result(res):
    """格式化單個任務結果"""
    task = res["task"]
    results = res["results"]
    lines = []
    lines.append(f"\n{'━'*50}")
    lines.append(f"📋 {task['name']}")
    lines.append(f"   {task['symbol']} | {task['interval']} | {res['candle_count']} 根 K 線 | {res['elapsed']:.0f}s")
    lines.append(f"{'━'*50}")

    if not results:
        lines.append("   ❌ 沒有找到有效策略")
        return "\n".join(lines)

    for i, r in enumerate(results):
        m = r.get("metrics", {})
        lines.append(f"\n  🏆 #{i+1} | Score: {r.get('score', 0):.1f}")
        lines.append(f"     {r.get('description', 'N/A')[:80]}")
        lines.append(f"     交易: {m.get('total_trades', 0)} 筆 | WR: {m.get('win_rate', 0):.1f}% | PF: {m.get('profit_factor', 0):.2f}")
        lines.append(f"     ROI: {m.get('roi', 0):.2f}% | Sharpe: {m.get('sharpe', 0):.2f} | DD: {m.get('max_drawdown', 0):.2f}%")
        lines.append(f"     SL: {r.get('dna', {}).get('sl', '?')}% | TP: {r.get('dna', {}).get('tp', '?')}%")

        # 驗證結果
        wf = r.get("wf_consistency", 0)
        dsr = r.get("dsr", 0)
        dsr_p = r.get("dsr_p", 1)
        wf_icon = "✅" if wf >= 60 else "⚠️" if wf >= 40 else "❌"
        dsr_icon = "✅" if dsr_p < 0.05 else "⚠️" if dsr_p < 0.1 else "❌"
        lines.append(f"     WF: {wf:.0f}% {wf_icon} | DSR: {dsr:.2f} (p={dsr_p:.4f}) {dsr_icon}")

        mc = r.get("mc")
        if mc:
            lines.append(f"     MC: {mc.get('profit_probability', 0)*100:.0f}% 盈利 | 破產: {mc.get('ruin_probability', 0)*100:.1f}%")

    return "\n".join(lines)


if __name__ == "__main__":
    print(f"🕐 開始時間: {datetime.now(TZ8).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 共 {len(TASKS)} 個研發任務\n")

    all_results = []
    for task in TASKS:
        try:
            res = run_task(task)
            all_results.append(res)
            print(format_result(res))
        except Exception as e:
            print(f"\n❌ {task['name']} 失敗: {e}")
            import traceback
            traceback.print_exc()

    # 總結
    print(f"\n\n{'='*60}")
    print(f"📊 研發總結")
    print(f"{'='*60}")
    total_trades = 0
    for res in all_results:
        task = res["task"]
        best = res["results"][0] if res["results"] else None
        if best:
            m = best.get("metrics", {})
            trades = m.get("total_trades", 0)
            total_trades += trades
            print(f"  {task['name']}: 冠軍 {trades} 筆交易, ROI {m.get('roi', 0):.2f}%, WF {best.get('wf_consistency', 0):.0f}%")
        else:
            print(f"  {task['name']}: 無結果")
    print(f"\n  總交易次數: {total_trades}")
    print(f"🕐 結束時間: {datetime.now(TZ8).strftime('%Y-%m-%d %H:%M:%S')}")

    # 存結果
    output = {
        "timestamp": datetime.now(TZ8).isoformat(),
        "tasks": [],
    }
    for res in all_results:
        task_out = {
            "name": res["task"]["name"],
            "symbol": res["task"]["symbol"],
            "interval": res["task"]["interval"],
            "candle_count": res["candle_count"],
            "elapsed": res["elapsed"],
            "results": [],
        }
        for r in res["results"]:
            task_out["results"].append({
                "score": r.get("score", 0),
                "description": r.get("description", ""),
                "metrics": r.get("metrics", {}),
                "dna": r.get("dna", {}),
                "wf_consistency": r.get("wf_consistency", 0),
                "dsr": r.get("dsr", 0),
                "dsr_p": r.get("dsr_p", 1),
                "mc_profit_prob": r.get("mc", {}).get("profit_probability", 0) if r.get("mc") else None,
                "code": r.get("code", ""),
            })
        output["tasks"].append(task_out)

    with open(os.path.join(os.path.dirname(__file__), "multi_research_results.json"), "w") as f:
        json.dump(output, f, indent=2, default=str)
    print("\n💾 結果已存到 multi_research_results.json")
