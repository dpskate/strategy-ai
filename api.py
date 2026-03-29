#!/usr/bin/env python3
"""
Strategy AI — FastAPI Backend
把 5 個模組包成 REST API
"""
import asyncio, json, os, time, uuid, traceback, math
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backtest_engine import (
    BacktestEngine, StrategyConfig, evaluate, format_report,
    fetch_candles_extended, Candle, monte_carlo, deflated_sharpe,
)
from llm_pipeline import compile_strategy, validate_strategy, run_pipeline, PRESETS, SYSTEM_PROMPT, extract_code
from optimizer import walk_forward, rolling_walk_forward, StrategyOptimizer
from auto_research import (
    run_research, format_research_results, create_strategy_dna,
    dna_to_code, dna_to_description, score_strategy, optimize_strategy,
    ENTRY_GENES, EXIT_GENES, LONG_GENES, SHORT_GENES, FILTER_GENES,
)
from advanced_optimizer import nsga2_optimize, bayesian_optimize
from derivatives_data import fetch_all_derivatives
from smc_genes import compute_smc_indicators

TZ8 = timezone(timedelta(hours=8))

app = FastAPI(
    title="Strategy AI",
    description="AI 驅動的交易策略研發平台",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── In-memory job store ───
jobs = {}


# ═══════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════

class BacktestRequest(BaseModel):
    code: str
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    candles: int = Field(default=1000, ge=100, le=5000)
    initial_capital: float = 10000
    position_size_pct: float = 10
    stop_loss_pct: float = 2
    take_profit_pct: float = 4
    commission_pct: float = 0.04
    slippage_pct: float = 0.02
    start_date: Optional[str] = None  # "2024-01-01"
    end_date: Optional[str] = None    # "2024-12-31"

class GenerateRequest(BaseModel):
    prompt: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"

class ResearchRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    candles: int = Field(default=1000, ge=100, le=5000)
    generations: int = Field(default=10, ge=1, le=50)
    population_size: int = Field(default=20, ge=5, le=100)
    top_k: int = Field(default=5, ge=1, le=20)
    direction: Optional[str] = "both"
    allowed_entry: Optional[list] = None
    allowed_exit: Optional[list] = None
    custom_genes: Optional[list] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class OptimizeRequest(BaseModel):
    code: str
    dna: Optional[dict] = None
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    candles: int = Field(default=1000, ge=100, le=5000)
    modifications: Optional[dict] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class MonteCarloRequest(BaseModel):
    code: str
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    candles: int = Field(default=1500, ge=100, le=5000)
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    n_simulations: int = Field(default=1000, ge=100, le=10000)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def _parse_date_ms(date_str):
    """Parse 'YYYY-MM-DD' to millisecond timestamp (UTC+8)."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ8)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _fetch_candles(symbol, interval, candles, start_date=None, end_date=None):
    """Fetch candles with optional date range."""
    start_ms = _parse_date_ms(start_date)
    end_ms = _parse_date_ms(end_date)
    return fetch_candles_extended(symbol, interval, candles, start_ms=start_ms, end_ms=end_ms)


def _sanitize(obj):
    """Replace inf/nan with safe values for JSON"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isinf(obj):
            return 9999 if obj > 0 else -9999
        if math.isnan(obj):
            return 0
    return obj


def _fetch_derivatives(symbol, period="4h", candles_data=None):
    """Fetch derivatives data + SMC indicators for a symbol. Returns dict for extra_indicators."""
    result = {}
    try:
        start_time = candles_data[0].time if candles_data else None
        end_time = candles_data[-1].time if candles_data else None
        result = fetch_all_derivatives(symbol, period, 500, start_time, end_time,
                                       candles=candles_data)
    except Exception:
        pass
    # Compute SMC indicators if candles available
    if candles_data and len(candles_data) >= 20:
        try:
            smc = compute_smc_indicators(candles_data)
            result.update(smc)
        except Exception:
            pass
    return result


# ═══════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(TZ8).isoformat()}


# ═══════════════════════════════════════════════════
# Generate Strategy (LLM)
# ═══════════════════════════════════════════════════

@app.post("/api/generate")
def generate_strategy(req: GenerateRequest):
    """用自然語言描述 → LLM 生成策略代碼"""
    import httpx

    try:
        resp = httpx.post(
            f"{req.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {req.api_key}"},
            json={
                "model": req.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": req.prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        code = extract_code(raw)

        # Validate syntax
        fn, err = compile_strategy(code)
        if err:
            return {"code": code, "error": f"生成的代碼有語法錯誤: {err}", "raw": raw}

        return {"code": code, "error": None}

    except httpx.TimeoutException:
        raise HTTPException(504, "LLM API 超時，請檢查 API 地址和網路")
    except httpx.ConnectError:
        raise HTTPException(502, "無法連接 LLM API，請檢查 API 地址")
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, f"LLM API 錯誤: {e.response.status_code} {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(500, f"生成失敗: {str(e)}")


GENE_SYSTEM_PROMPT = """你是一個量化交易基因生成器。用戶會用自然語言描述一個交易信號，你需要生成 Python 代碼片段。

可用變數（已預定義，直接用）：
- closes[i], opens[i], highs[i], lows[i], volumes[i] — 第 i 根 K 線的 OHLCV
- 所有指標函數：ema(data, period), sma(data, period), rsi(closes, period), bollinger_bands(closes, period, std), atr(highs, lows, closes, period), macd(closes, fast, slow, signal), stoch_rsi(closes, rsi_period, stoch_period)

你必須回傳一個 JSON 物件，格式如下（不要加任何其他文字）：
{
  "name": "英文蛇形命名",
  "desc": "中文描述",
  "side": "long 或 short 或 exit",
  "setup": "指標計算代碼（多行用 \\n 分隔）",
  "code": "條件判斷代碼（用 i 索引，回傳 True/False）"
}

規則：
1. setup 裡計算指標，code 裡寫條件判斷
2. 指標可能回傳 None，code 裡必須檢查 is not None
3. 只用上面列出的變數和函數，不要 import 任何東西
4. 保持簡潔，一個基因只做一件事"""


class GenerateGeneRequest(BaseModel):
    prompt: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@app.post("/api/generate-gene")
def generate_gene(req: GenerateGeneRequest):
    """用自然語言描述 → AI 生成自定義基因"""
    import httpx

    try:
        resp = httpx.post(
            f"{req.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {req.api_key}"},
            json={
                "model": req.model,
                "messages": [
                    {"role": "system", "content": GENE_SYSTEM_PROMPT},
                    {"role": "user", "content": req.prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 500,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]

        # Parse JSON from response
        import re
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            return {"gene": None, "error": "AI 回傳格式錯誤", "raw": raw}

        gene = json.loads(json_match.group())
        required = ["name", "desc", "side", "setup", "code"]
        for k in required:
            if k not in gene:
                return {"gene": None, "error": f"缺少欄位: {k}", "raw": raw}

        return {"gene": gene, "error": None}

    except httpx.TimeoutException:
        raise HTTPException(504, "LLM API 超時")
    except httpx.ConnectError:
        raise HTTPException(502, "無法連接 LLM API")
    except Exception as e:
        raise HTTPException(500, f"生成失敗: {str(e)}")


# ═══════════════════════════════════════════════════
# Backtest
# ═══════════════════════════════════════════════════

@app.post("/api/backtest")
def backtest(req: BacktestRequest):
    """編譯策略代碼 → 回測 → 返回績效"""
    # Compile
    strategy_fn, err = compile_strategy(req.code)
    if err:
        raise HTTPException(400, f"編譯失敗: {err}")

    # Fetch data
    candles = _fetch_candles(req.symbol, req.interval, req.candles, req.start_date, req.end_date)
    if not candles:
        raise HTTPException(500, "無法取得 K 線數據")

    # Validate
    ok, err = validate_strategy(strategy_fn, candles)
    if not ok:
        raise HTTPException(400, f"驗證失敗: {err}")

    # Run
    config = StrategyConfig(
        name="User Strategy",
        symbol=req.symbol, interval=req.interval,
        initial_capital=req.initial_capital,
        position_size_pct=req.position_size_pct,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
    )
    engine = BacktestEngine(config)
    deriv = _fetch_derivatives(req.symbol, req.interval, candles)
    trades = engine.run(candles, strategy_fn, extra_indicators=deriv)
    metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

    # Walk-forward
    wf = walk_forward(candles, strategy_fn, config, extra_indicators=deriv)

    # Rolling walk-forward
    rwf = rolling_walk_forward(candles, strategy_fn, config, extra_indicators=deriv)

    # Deflated Sharpe (manual backtest = 1 strategy tested)
    ds = deflated_sharpe(
        metrics.get("sharpe_ratio", 0),
        metrics.get("total_trades", 0),
        n_strategies_tested=1,
    )

    return {
        "metrics": _sanitize(metrics),
        "walk_forward": _sanitize({
            "train_roi": wf["train"].get("roi_pct", 0),
            "test_roi": wf["test"].get("roi_pct", 0),
            "overfit_ratio": wf["overfit_ratio"],
        }),
        "rolling_wf": _sanitize(rwf),
        "deflated_sharpe": _sanitize(ds),
        "trades": len(trades),
        "trade_list": [
            {
                "id": i + 1,
                "side": t.side,
                "entry_time": t.entry_time,
                "entry_price": round(t.entry_price, 2),
                "exit_time": t.exit_time,
                "exit_price": round(t.exit_price, 2),
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 2),
                "exit_reason": t.exit_reason,
            }
            for i, t in enumerate(trades) if t.closed
        ],
        "candle_data": [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
        "equity_curve": _sanitize(engine.equity_curve),
        "report": format_report(metrics, config),
    }


# ═══════════════════════════════════════════════════
# Presets
# ═══════════════════════════════════════════════════

@app.get("/api/presets")
def list_presets():
    """列出預設策略"""
    return {name: {"code": code} for name, code in PRESETS.items()}


# ═══════════════════════════════════════════════════
# Auto Research (async job)
# ═══════════════════════════════════════════════════

def _run_research_job(job_id: str, req: ResearchRequest):
    """Background task for research"""
    jobs[job_id]["status"] = "running"
    try:
        candles = _fetch_candles(req.symbol, req.interval, req.candles, req.start_date, req.end_date)
        if not candles:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "無法取得 K 線數據"
            return

        # Patch run_research to report progress
        from auto_research import run_research as _run_research
        import types

        total_gens = req.generations

        def progress_callback(gen, gen_results):
            top5 = gen_results[:5]
            jobs[job_id]["progress"] = {
                "current": gen + 1,
                "total": total_gens,
                "pct": round((gen + 1) / total_gens * 100),
                "valid": len(gen_results),
                "population": req.population_size,
                "best_score": round(top5[0]["score"], 2) if top5 else None,
                "top_results": [
                    {
                        "description": dna_to_description(r["dna"]),
                        "score": round(r["score"], 2),
                        "roi_pct": r["metrics"].get("roi_pct", 0),
                        "win_rate": r["metrics"].get("win_rate", 0),
                    }
                    for r in top5
                ] if top5 else [],
            }

        deriv = _fetch_derivatives(req.symbol, req.interval, candles)

        results = run_research(
            candles,
            generations=req.generations,
            population_size=req.population_size,
            top_k=req.top_k,
            verbose=False,
            on_progress=progress_callback,
            allowed_entry=set(req.allowed_entry) if req.allowed_entry else None,
            allowed_exit=set(req.allowed_exit) if req.allowed_exit else None,
            custom_genes=req.custom_genes,
            direction=req.direction or "both",
            extra_indicators=deriv,
        )

        n_strategies_tested = req.population_size * req.generations

        formatted = []
        for i, r in enumerate(results):
            # Walk-forward for each result
            wf_data = None
            rwf_data = None
            ds_data = None
            try:
                wf_fn, _ = compile_strategy(r["code"])
                if wf_fn:
                    wf_config = StrategyConfig(
                        initial_capital=10000, position_size_pct=10,
                        stop_loss_pct=r["dna"]["sl"], take_profit_pct=r["dna"]["tp"],
                    )
                    wf = walk_forward(candles, wf_fn, wf_config, extra_indicators=deriv)
                    wf_data = {
                        "train_roi": wf["train"].get("roi_pct", 0),
                        "test_roi": wf["test"].get("roi_pct", 0),
                        "overfit_ratio": wf["overfit_ratio"],
                    }
                    rwf_data = rolling_walk_forward(candles, wf_fn, wf_config, extra_indicators=deriv)
                    ds_data = deflated_sharpe(
                        r["metrics"].get("sharpe_ratio", 0),
                        r["metrics"].get("total_trades", 0),
                        n_strategies_tested=n_strategies_tested,
                    )
            except Exception:
                pass

            formatted.append({
                "rank": i + 1,
                "score": round(r["score"], 2) if not math.isinf(r["score"]) else 9999,
                "description": dna_to_description(r["dna"]),
                "metrics": _sanitize(r["metrics"]),
                "code": r["code"],
                "walk_forward": _sanitize(wf_data) if wf_data else None,
                "rolling_wf": _sanitize(rwf_data) if rwf_data else None,
                "deflated_sharpe": _sanitize(ds_data) if ds_data else None,
                "dna": {
                    "entry_genes": [(g, p) for g, p in r["dna"]["entry_genes"]],
                    "exit_gene": r["dna"]["exit_gene"],
                    "sl": r["dna"]["sl"],
                    "tp": r["dna"]["tp"],
                    "side": r["dna"].get("side", "long"),
                    **({"long_genes": [(g, p) for g, p in r["dna"]["long_genes"]]} if "long_genes" in r["dna"] else {}),
                    **({"short_genes": [(g, p) for g, p in r["dna"]["short_genes"]]} if "short_genes" in r["dna"] else {}),
                },
            })

        jobs[job_id]["status"] = "done"
        jobs[job_id]["results"] = formatted
        jobs[job_id]["finished_at"] = datetime.now(TZ8).isoformat()

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


@app.post("/api/research")
def start_research(req: ResearchRequest, bg: BackgroundTasks):
    """啟動自動研發（背景任務）"""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "params": req.model_dump(),
        "created_at": datetime.now(TZ8).isoformat(),
    }
    bg.add_task(_run_research_job, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/research/{job_id}")
def get_research(job_id: str):
    """查詢研發任務狀態"""
    if job_id not in jobs:
        raise HTTPException(404, "任務不存在")
    return jobs[job_id]


@app.websocket("/ws/research/{job_id}")
async def ws_research(websocket: WebSocket, job_id: str):
    """WebSocket 實時推送研發進度"""
    await websocket.accept()
    if job_id not in jobs:
        await websocket.close(code=4004)
        return
    last_gen = -1
    try:
        while True:
            job = jobs.get(job_id, {})
            status = job.get("status", "unknown")
            progress = job.get("progress")
            current_gen = progress.get("current", 0) if progress else 0

            if current_gen != last_gen or status in ("done", "failed"):
                payload: dict = {"status": status, "progress": progress}
                if status == "done" and job.get("results"):
                    top5 = job["results"][:5]
                    payload["top_results"] = [
                        {
                            "rank": r["rank"],
                            "score": r["score"],
                            "description": r["description"],
                            "roi_pct": r["metrics"].get("roi_pct", 0),
                            "win_rate": r["metrics"].get("win_rate", 0),
                        }
                        for r in top5
                    ]
                await websocket.send_json(payload)
                last_gen = current_gen

            if status in ("done", "failed"):
                break

            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ═══════════════════════════════════════════════════
# Walk-Forward Validation
# ═══════════════════════════════════════════════════

@app.post("/api/validate")
def validate(req: BacktestRequest):
    """Walk-forward 驗證策略"""
    strategy_fn, err = compile_strategy(req.code)
    if err:
        raise HTTPException(400, f"編譯失敗: {err}")

    candles = fetch_candles_extended(req.symbol, req.interval, req.candles)
    if not candles:
        raise HTTPException(500, "無法取得 K 線數據")

    config = StrategyConfig(
        initial_capital=req.initial_capital,
        position_size_pct=req.position_size_pct,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
    )
    wf = walk_forward(candles, strategy_fn, config)

    return {
        "train": wf["train"],
        "test": wf["test"],
        "overfit_ratio": wf["overfit_ratio"],
    }


# ═══════════════════════════════════════════════════
# Data
# ═══════════════════════════════════════════════════

@app.get("/api/candles")
def get_candles(symbol: str = "BTCUSDT", interval: str = "4h", limit: int = 500):
    """取得 K 線數據"""
    if limit > 5000:
        limit = 5000
    candles = fetch_candles_extended(symbol, interval, limit)
    if not candles:
        raise HTTPException(500, "無法取得數據")
    return {
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "candles": [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ],
    }


# ═══════════════════════════════════════════════════
# Gene Library
# ═══════════════════════════════════════════════════

@app.get("/api/genes")
def list_genes():
    """列出所有可用基因（入場 + 出場）"""
    entry = {}
    for name, gene in ENTRY_GENES.items():
        entry[name] = {
            "desc": gene.get("desc", name),
            "params": {k: v for k, v in gene.get("params", {}).items()},
            "type": "long" if name in LONG_GENES else "short" if name in SHORT_GENES else "filter",
        }
    exit_genes = {}
    for name, gene in EXIT_GENES.items():
        exit_genes[name] = {
            "desc": gene.get("desc", name),
            "params": {k: v for k, v in gene.get("params", {}).items()},
        }
    return {"entry": entry, "exit": exit_genes}


# ═══════════════════════════════════════════════════
# Strategy Optimizer (workbench)
# ═══════════════════════════════════════════════════

def _run_optimize_job(job_id: str, req: OptimizeRequest):
    """Background task for optimization"""
    jobs[job_id]["status"] = "running"
    try:
        candles = _fetch_candles(req.symbol, req.interval, req.candles, req.start_date, req.end_date)
        if not candles:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "無法取得 K 線數據"
            return

        dna = req.dna
        if not dna:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "缺少策略 DNA"
            return

        # Fix tuple format from JSON (lists → tuples internally)
        if "entry_genes" in dna:
            dna["entry_genes"] = [(g[0], g[1]) for g in dna["entry_genes"]]
        if "exit_gene" in dna and isinstance(dna["exit_gene"], list):
            dna["exit_gene"] = (dna["exit_gene"][0], dna["exit_gene"][1])

        def progress_callback(done, total):
            jobs[job_id]["progress"] = {"current": done, "total": total}

        deriv = _fetch_derivatives(req.symbol, req.interval, candles)

        results = optimize_strategy(
            candles, dna,
            modifications=req.modifications,
            on_progress=progress_callback,
            extra_indicators=deriv,
        )

        formatted = []
        for i, r in enumerate(results):
            formatted.append({
                "rank": i + 1,
                "score": round(r["score"], 2) if not math.isinf(r.get("score", 0)) else 9999,
                "description": r.get("description", ""),
                "metrics": _sanitize(r["metrics"]),
                "code": r["code"],
                "walk_forward": _sanitize(r["walk_forward"]) if r.get("walk_forward") else None,
                "dna": {
                    "entry_genes": [(g, p) for g, p in r["dna"]["entry_genes"]],
                    "exit_gene": r["dna"]["exit_gene"],
                    "sl": r["dna"]["sl"],
                    "tp": r["dna"]["tp"],
                    "side": r["dna"].get("side", "long"),
                    **({"long_genes": [(g, p) for g, p in r["dna"]["long_genes"]]} if "long_genes" in r["dna"] else {}),
                    **({"short_genes": [(g, p) for g, p in r["dna"]["short_genes"]]} if "short_genes" in r["dna"] else {}),
                },
            })

        jobs[job_id]["status"] = "done"
        jobs[job_id]["results"] = formatted
        jobs[job_id]["finished_at"] = datetime.now(TZ8).isoformat()

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        traceback.print_exc()


@app.post("/api/optimize")
def start_optimize(req: OptimizeRequest, bg: BackgroundTasks):
    """啟動策略優化（背景任務）"""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "params": {"symbol": req.symbol, "interval": req.interval, "candles": req.candles},
        "created_at": datetime.now(TZ8).isoformat(),
    }
    bg.add_task(_run_optimize_job, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/optimize/{job_id}")
def get_optimize(job_id: str):
    """查詢優化任務狀態"""
    if job_id not in jobs:
        raise HTTPException(404, "任務不存在")
    return jobs[job_id]


# ═══════════════════════════════════════════════════
# Advanced Optimization (NSGA-II + Bayesian)
# ═══════════════════════════════════════════════════

class AdvancedOptRequest(BaseModel):
    code: str
    dna: Optional[dict] = None
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    candles: int = 1000
    method: str = "nsga2"
    modifications: Optional[dict] = None
    pop_size: int = 40
    n_gen: int = 20
    n_trials: int = 100
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def _format_adv_result(r, i):
    """Format a single advanced result for API response."""
    return {
        "rank": i + 1,
        "score": round(r["score"], 2) if not math.isinf(r.get("score", 0)) else 9999,
        "description": r.get("description", ""),
        "metrics": _sanitize(r["metrics"]),
        "code": r["code"],
        "walk_forward": _sanitize(r["walk_forward"]) if r.get("walk_forward") else None,
        "dna": {
            "entry_genes": [(g, p) for g, p in r["dna"]["entry_genes"]],
            "exit_gene": r["dna"]["exit_gene"],
            "sl": r["dna"]["sl"],
            "tp": r["dna"]["tp"],
            "side": r["dna"].get("side", "long"),
            **({"long_genes": [(g, p) for g, p in r["dna"]["long_genes"]]} if "long_genes" in r["dna"] else {}),
            **({"short_genes": [(g, p) for g, p in r["dna"]["short_genes"]]} if "short_genes" in r["dna"] else {}),
        },
        "pareto_front": r.get("pareto_front", False),
        "convergence": r.get("convergence"),
    }


def _run_advanced_job(job_id: str, req: AdvancedOptRequest):
    """Background task for advanced optimization."""
    jobs[job_id]["status"] = "running"
    try:
        candles = _fetch_candles(req.symbol, req.interval, req.candles, req.start_date, req.end_date)
        if not candles:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "無法取得 K 線數據"
            return

        dna = req.dna
        if not dna:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = "缺少策略 DNA"
            return

        if "entry_genes" in dna:
            dna["entry_genes"] = [(g[0], g[1]) for g in dna["entry_genes"]]
        if "exit_gene" in dna and isinstance(dna["exit_gene"], list):
            dna["exit_gene"] = (dna["exit_gene"][0], dna["exit_gene"][1])

        def progress_callback(done, total):
            jobs[job_id]["progress"] = {"current": done, "total": total}

        if req.method == "bayesian":
            results = bayesian_optimize(
                candles, dna,
                modifications=req.modifications,
                n_trials=req.n_trials,
                on_progress=progress_callback,
            )
        else:
            results = nsga2_optimize(
                candles, dna,
                modifications=req.modifications,
                pop_size=req.pop_size,
                n_gen=req.n_gen,
                on_progress=progress_callback,
            )

        formatted = [_format_adv_result(r, i) for i, r in enumerate(results)]

        pareto_data = []
        for r in results:
            m = r["metrics"]
            pareto_data.append({
                "roi": m.get("roi_pct", 0),
                "sharpe": m.get("sharpe_ratio", 0),
                "drawdown": abs(m.get("max_drawdown_pct", 0)),
                "pareto": r.get("pareto_front", False),
            })

        jobs[job_id]["status"] = "done"
        jobs[job_id]["results"] = formatted
        jobs[job_id]["pareto_data"] = pareto_data
        jobs[job_id]["method"] = req.method
        jobs[job_id]["finished_at"] = datetime.now(TZ8).isoformat()

    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        traceback.print_exc()


@app.post("/api/advanced-optimize")
def start_advanced_optimize(req: AdvancedOptRequest, bg: BackgroundTasks):
    """啟動進階優化（NSGA-II 多目標 / 貝葉斯優化）"""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "method": req.method,
        "params": {
            "symbol": req.symbol, "interval": req.interval,
            "candles": req.candles, "method": req.method,
        },
        "created_at": datetime.now(TZ8).isoformat(),
    }
    bg.add_task(_run_advanced_job, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/advanced-optimize/{job_id}")
def get_advanced_optimize(job_id: str):
    """查詢進階優化任務狀態"""
    if job_id not in jobs:
        raise HTTPException(404, "任務不存在")
    return jobs[job_id]


# ═══════════════════════════════════════════════════
# Cross-Validation (multi-symbol / multi-interval)
# ═══════════════════════════════════════════════════

class CrossValidateRequest(BaseModel):
    code: str
    symbols: list[str] = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    intervals: list[str] = ["1h", "4h"]
    candles: int = Field(default=1000, ge=100, le=5000)
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@app.post("/api/cross-validate")
def cross_validate(req: CrossValidateRequest):
    """多標的 × 多時間框架交叉驗證"""
    strategy_fn, err = compile_strategy(req.code)
    if err:
        raise HTTPException(400, f"編譯失敗: {err}")

    results = []
    for symbol in req.symbols:
        for interval in req.intervals:
            entry = {"symbol": symbol, "interval": interval, "metrics": None, "walk_forward": None, "trades": 0, "error": None}
            try:
                candles = _fetch_candles(symbol, interval, req.candles, req.start_date, req.end_date)
                if not candles:
                    entry["error"] = "無法取得數據"
                    results.append(entry)
                    continue

                ok, verr = validate_strategy(strategy_fn, candles)
                if not ok:
                    entry["error"] = f"驗證失敗: {verr}"
                    results.append(entry)
                    continue

                config = StrategyConfig(
                    name="CrossVal",
                    symbol=symbol, interval=interval,
                    initial_capital=10000,
                    position_size_pct=10,
                    stop_loss_pct=req.stop_loss_pct,
                    take_profit_pct=req.take_profit_pct,
                )
                engine = BacktestEngine(config)
                trades = engine.run(candles, strategy_fn)
                metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

                wf = walk_forward(candles, strategy_fn, config)
                wf_data = {
                    "train_roi": wf["train"].get("roi_pct", 0),
                    "test_roi": wf["test"].get("roi_pct", 0),
                    "overfit_ratio": wf["overfit_ratio"],
                }

                entry["metrics"] = _sanitize(metrics)
                entry["walk_forward"] = _sanitize(wf_data)
                entry["trades"] = len([t for t in trades if t.closed])
            except Exception as e:
                entry["error"] = str(e)
            results.append(entry)

    # Build summary
    valid = [r for r in results if r["metrics"] is not None]
    total = len(results)
    if not valid:
        return {"results": results, "summary": {
            "total_combinations": total, "profitable": 0,
            "avg_roi": 0, "avg_win_rate": 0, "avg_sharpe": 0,
            "worst_drawdown": 0, "consistency_score": 0,
        }}

    rois = [r["metrics"]["roi_pct"] for r in valid]
    win_rates = [r["metrics"]["win_rate"] for r in valid]
    sharpes = [r["metrics"]["sharpe_ratio"] for r in valid]
    drawdowns = [abs(r["metrics"]["max_drawdown_pct"]) for r in valid]
    profitable = sum(1 for roi in rois if roi > 0)
    profitable_ratio = profitable / len(valid) if valid else 0

    avg_roi = sum(rois) / len(rois)
    avg_wr = sum(win_rates) / len(win_rates)
    avg_sharpe = sum(sharpes) / len(sharpes)
    worst_dd = max(drawdowns) if drawdowns else 0

    # Consistency score
    score = 50
    if profitable_ratio > 0.8:
        score += 20
    elif profitable_ratio > 0.6:
        score += 10
    if avg_roi > 5:
        score += 10
    elif avg_roi > 0:
        score += 5
    if all(d < 20 for d in drawdowns):
        score += 10
    if avg_sharpe > 0.5:
        score += 10
    roi_spread = max(rois) - min(rois) if rois else 0
    if roi_spread < 30:
        score += 10
    if any(roi < -20 for roi in rois):
        score -= 10
    score = max(0, min(100, score))

    return _sanitize({
        "results": results,
        "summary": {
            "total_combinations": total,
            "profitable": profitable,
            "avg_roi": round(avg_roi, 1),
            "avg_win_rate": round(avg_wr, 1),
            "avg_sharpe": round(avg_sharpe, 2),
            "worst_drawdown": round(worst_dd, 1),
            "consistency_score": score,
        },
    })


# ═══════════════════════════════════════════════════
# Monte Carlo Simulation
# ═══════════════════════════════════════════════════

@app.post("/api/monte-carlo")
def run_monte_carlo(req: MonteCarloRequest):
    """先跑一次回測拿到 trades，然後跑蒙地卡羅模擬"""
    strategy_fn, err = compile_strategy(req.code)
    if err:
        raise HTTPException(400, f"編譯失敗: {err}")

    candles = _fetch_candles(req.symbol, req.interval, req.candles, req.start_date, req.end_date)
    if not candles:
        raise HTTPException(500, "無法取得 K 線數據")

    ok, err = validate_strategy(strategy_fn, candles)
    if not ok:
        raise HTTPException(400, f"驗證失敗: {err}")

    config = StrategyConfig(
        name="MC Sim",
        symbol=req.symbol, interval=req.interval,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
    )
    engine = BacktestEngine(config)
    trades = engine.run(candles, strategy_fn)

    closed = [t for t in trades if t.closed]
    if len(closed) < 2:
        raise HTTPException(400, "交易數量不足（至少需要 2 筆已平倉交易）")

    result = monte_carlo(trades, config.initial_capital, req.n_simulations)
    return _sanitize(result)


# ═══════════════════════════════════════════════════
# Factor Research
# ═══════════════════════════════════════════════════

class FactorAnalysisRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    candles: int = Field(default=1500, ge=200, le=5000)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@app.post("/api/factor-analysis")
def factor_analysis(req: FactorAnalysisRequest):
    """分析所有因子的預測力"""
    from factor_research import analyze_all_factors, factor_correlation_matrix, filter_factors

    candles = _fetch_candles(req.symbol, req.interval, req.candles, req.start_date, req.end_date)
    if not candles:
        raise HTTPException(500, "無法取得 K 線數據")

    deriv = _fetch_derivatives(req.symbol, req.interval, candles)

    results = analyze_all_factors(candles, deriv)
    corr = factor_correlation_matrix(candles, deriv)
    recommended = filter_factors(results, correlation_matrix=corr)

    # Format correlation pairs for JSON
    corr_pairs = [
        {"a": a, "b": b, "corr": c}
        for (a, b), c in corr.items()
        if abs(c) >= 0.5
    ]
    corr_pairs.sort(key=lambda x: -abs(x["corr"]))

    return _sanitize({
        "factors": results,
        "recommended": recommended,
        "high_correlations": corr_pairs[:30],
        "total_factors": len(results),
        "grade_distribution": _count_grades(results),
    })


def _count_grades(results):
    counts = {}
    for r in results:
        g = r["grade"]
        counts[g] = counts.get(g, 0) + 1
    return counts


@app.get("/api/cache-stats")
def cache_stats():
    """數據緩存統計"""
    from data_pipeline import DataPipeline
    pipeline = DataPipeline()
    return pipeline.cache_stats()


# ═══════════════════════════════════════════════════
# Strategy Monitor
# ═══════════════════════════════════════════════════

class MonitorAddRequest(BaseModel):
    name: str
    code: str
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    thresholds: Optional[dict] = None


@app.post("/api/monitor/add")
def monitor_add(req: MonitorAddRequest):
    """加入策略監控"""
    from strategy_monitor import api_add_strategy
    result = api_add_strategy(
        req.name, req.code, req.symbol, req.interval,
        req.stop_loss_pct, req.take_profit_pct, req.thresholds,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.get("/api/monitor/list")
def monitor_list():
    """列出監控中的策略"""
    from strategy_monitor import list_strategies
    return {"strategies": list_strategies()}


@app.post("/api/monitor/check")
def monitor_check():
    """執行一次監控檢查"""
    from strategy_monitor import api_run_monitor
    return {"results": _sanitize(api_run_monitor())}


@app.delete("/api/monitor/{strategy_id}")
def monitor_remove(strategy_id: str):
    """移除策略監控"""
    from strategy_monitor import remove_strategy
    remove_strategy(strategy_id)
    return {"ok": True}


@app.get("/api/monitor/trend/{strategy_id}")
def monitor_trend(strategy_id: str, days: int = 30):
    """取得策略歷史趨勢"""
    from strategy_monitor import get_strategy_trend
    return {"trend": get_strategy_trend(strategy_id, days)}
