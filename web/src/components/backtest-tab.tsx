"use client";

import { useState, useEffect, useImperativeHandle, forwardRef, useCallback, useRef } from "react";
import { api, BacktestResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { MetricsPanel } from "@/components/metrics-panel";
import { EquityChart } from "@/components/equity-chart";
import { TradeTable } from "@/components/trade-table";
import { KlineChart } from "@/components/kline-chart";
import { Play, Loader2, BookOpen, Settings, Sparkles, ChevronDown, ChevronUp, Bookmark } from "lucide-react";
import { SavedStrategiesPanel } from "@/components/saved-strategies";
import { saveStrategy, genId, SavedStrategy } from "@/lib/storage";
import { gradeStrategy } from "@/components/metrics-panel";
import { CrossValidateButton, CrossValidatePanel } from "@/components/cross-validate";
import { MonteCarloButton, MonteCarloPanel } from "@/components/monte-carlo";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"];
const INTERVALS = [
  { value: "15m", label: "15 分鐘" },
  { value: "1h", label: "1 小時" },
  { value: "4h", label: "4 小時" },
  { value: "1d", label: "1 天" },
];

function friendlyError(err: string): string {
  if (err.includes("編譯失敗") || err.includes("SyntaxError"))
    return "策略代碼有語法錯誤，請檢查括號、縮排和拼寫";
  if (err.includes("驗證失敗"))
    return "策略邏輯有問題 — 可能沒有回傳正確格式的交易信號";
  if (err.includes("K 線數據") || err.includes("candle"))
    return "無法取得行情數據，請稍後再試";
  if (err.includes("timeout") || err.includes("Timeout"))
    return "回測超時 — 策略可能太複雜，試試減少 K 線數量";
  if (err.includes("fetch") || err.includes("Failed to fetch") || err.includes("NetworkError"))
    return "無法連接後端 API — 請確認 API 服務是否啟動";
  if (err.includes("strategy") && err.includes("not defined"))
    return "找不到 strategy 函數 — 請確認代碼中有定義 def strategy(...)";
  if (err.includes("list index") || err.includes("IndexError"))
    return "策略存取了不存在的數據位置 — 可能需要更多歷史 K 線";
  return err;
}

export interface BacktestTabRef {
  loadAndRun: (code: string, opts?: { sl?: number; tp?: number }) => void;
}

export const BacktestTab = forwardRef<BacktestTabRef>(function BacktestTab(_, ref) {
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<number | null>(null);
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [showCrossValidate, setShowCrossValidate] = useState(false);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);
  const [error, setError] = useState("");
  const [presets, setPresets] = useState<Record<string, { code: string }>>({});

  // NL input
  const [nlPrompt, setNlPrompt] = useState("");

  // LLM settings
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [model, setModel] = useState("gpt-4o-mini");
  const [showLlmSettings, setShowLlmSettings] = useState(false);

  // Settings
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("4h");
  const [candles, setCandles] = useState(1000);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [stopLoss, setStopLoss] = useState(2);
  const [takeProfit, setTakeProfit] = useState(4);
  const [capital, setCapital] = useState(10000);
  const [posSize, setPosSize] = useState(10);
  const [commission, setCommission] = useState(0.04);
  const [slippage, setSlippage] = useState(0.02);

  useEffect(() => {
    api.presets().then(setPresets).catch(() => {});
    // Load saved LLM settings
    const saved = localStorage.getItem("llm_settings");
    if (saved) {
      const s = JSON.parse(saved);
      if (s.apiKey) setApiKey(s.apiKey);
      if (s.baseUrl) setBaseUrl(s.baseUrl);
      if (s.model) setModel(s.model);
    }
  }, []);

  const saveLlmSettings = () => {
    localStorage.setItem("llm_settings", JSON.stringify({ apiKey, baseUrl, model }));
  };

  const generateCode = async () => {
    if (!nlPrompt.trim() || !apiKey.trim()) return;
    setGenerating(true);
    setError("");
    saveLlmSettings();
    try {
      const res = await api.generate({ prompt: nlPrompt, api_key: apiKey, base_url: baseUrl, model });
      if (res.code) setCode(res.code);
      if (res.error) setError(res.error);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "生成失敗");
    } finally {
      setGenerating(false);
    }
  };

  const runBacktestWithCode = useCallback(async (codeToRun: string, overrides?: { sl?: number; tp?: number }) => {
    if (!codeToRun.trim()) return;
    setLoading(true);
    setElapsed(0);
    setError("");
    setResult(null);
    // Start timer
    const start = Date.now();
    timerRef.current = window.setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    try {
      const res = await api.backtest({
        code: codeToRun,
        symbol,
        interval,
        candles,
        stop_loss_pct: overrides?.sl ?? stopLoss,
        take_profit_pct: overrides?.tp ?? takeProfit,
        initial_capital: capital,
        position_size_pct: posSize,
        commission_pct: commission,
        slippage_pct: slippage,
        ...(startDate ? { start_date: startDate } : {}),
        ...(endDate ? { end_date: endDate } : {}),
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "回測失敗");
    } finally {
      if (timerRef.current) window.clearInterval(timerRef.current);
      setLoading(false);
    }
  }, [symbol, interval, candles, stopLoss, takeProfit, capital, posSize, commission, slippage]);

  const runBacktest = () => runBacktestWithCode(code);

  // Ctrl+Enter shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && code.trim() && !loading) {
        e.preventDefault();
        runBacktestWithCode(code);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [code, loading, runBacktestWithCode]);

  useImperativeHandle(ref, () => ({
    loadAndRun: (newCode: string, opts?: { sl?: number; tp?: number }) => {
      setCode(newCode);
      if (opts?.sl !== undefined) setStopLoss(opts.sl);
      if (opts?.tp !== undefined) setTakeProfit(opts.tp);
      setResult(null);
      setError("");
      // Pass overrides directly to avoid stale closure
      setTimeout(() => runBacktestWithCode(newCode, opts), 100);
    },
  }), [runBacktestWithCode]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left: NL Input + Code + Settings */}
      <div className="lg:col-span-2 space-y-4">
        {/* Natural Language Input */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              用白話描述你的策略
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              value={nlPrompt}
              onChange={(e) => setNlPrompt(e.target.value)}
              placeholder="例如：當 RSI 低於 30 而且價格在布林下軌以下時買入，RSI 超過 70 時賣出"
              className="text-sm min-h-[80px] resize-none"
            />
            <div className="flex items-center gap-2">
              <Button
                onClick={generateCode}
                disabled={generating || !nlPrompt.trim() || !apiKey.trim()}
                variant="outline"
                className="flex-1"
              >
                {generating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    AI 生成中...
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    AI 生成策略代碼
                  </>
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowLlmSettings(!showLlmSettings)}
              >
                {showLlmSettings ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              </Button>
            </div>
            {!apiKey.trim() && (
              <p className="text-xs text-muted-foreground">⚠️ 請先設定 API Key（點右邊箭頭展開）</p>
            )}
            {showLlmSettings && (
              <div className="space-y-2 pt-2 border-t">
                <div>
                  <label className="text-xs text-muted-foreground">API Key</label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-..."
                    className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">API 地址（支援 OpenAI 兼容格式）</label>
                  <input
                    type="text"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">模型</label>
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
                  />
                </div>
                <p className="text-xs text-muted-foreground">設定會保存在瀏覽器本地，不會上傳到伺服器</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Code editor */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center justify-between">
              策略代碼
              <div className="flex gap-2 flex-wrap">
                {Object.keys(presets).map((name) => (
                  <Badge
                    key={name}
                    variant="outline"
                    className="cursor-pointer hover:bg-muted"
                    onClick={() => setCode(presets[name].code)}
                  >
                    {name}
                  </Badge>
                ))}
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="relative font-mono text-sm border rounded-lg overflow-hidden bg-muted/30">
              <div className="flex">
                {/* Line numbers */}
                <div className="select-none text-right pr-3 pl-3 py-3 text-muted-foreground/50 bg-muted/50 border-r border-border/30 leading-[1.5rem] text-xs min-w-[3rem]" aria-hidden="true">
                  {(code || "\n").split("\n").map((_, i) => (
                    <div key={i}>{i + 1}</div>
                  ))}
                </div>
                {/* Code area */}
                <Textarea
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder={`def strategy(candles, i, indicators, open_trades):\n    # 在這裡寫你的策略邏輯\n    closes = [c.close for c in candles[:i+1]]\n    ...\n    return [{"action": "buy"}]`}
                  className="flex-1 font-mono text-sm min-h-[350px] resize-none border-0 rounded-none focus-visible:ring-0 leading-[1.5rem] py-3"
                  spellCheck={false}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Button onClick={runBacktest} disabled={loading || !code.trim()} className="w-full bg-emerald-600 hover:bg-emerald-500 btn-glow">
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              回測中...{elapsed > 0 && ` ${elapsed}s`}
            </>
          ) : (
            <>
              <Play className="mr-2 h-4 w-4" />
              執行回測
              <kbd className="ml-2 text-[10px] opacity-50 border border-current/20 rounded px-1">⌘↵</kbd>
            </>
          )}
        </Button>

        {error && (
          <Card className="border-destructive">
            <CardContent className="pt-4 space-y-2">
              <p className="text-sm font-medium text-destructive">❌ {friendlyError(error)}</p>
              {error !== friendlyError(error) && (
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer hover:text-foreground">查看原始錯誤</summary>
                  <pre className="mt-1 p-2 bg-muted rounded text-xs overflow-x-auto">{error}</pre>
                </details>
              )}
            </CardContent>
          </Card>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {/* Save button */}
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const { grade, score } = gradeStrategy(result.metrics, result.walk_forward);
                  const name = prompt("策略名稱", `策略 ${new Date().toLocaleString("zh-TW")}`);
                  if (!name) return;
                  saveStrategy({
                    id: genId(),
                    name,
                    code,
                    grade,
                    score,
                    metrics: result.metrics,
                    walkForward: result.walk_forward,
                    settings: { symbol, interval, sl: stopLoss, tp: takeProfit },
                    source: "backtest",
                    savedAt: Date.now(),
                  });
                  window.dispatchEvent(new Event("strategies-updated"));
                }}
              >
                <Bookmark className="h-3 w-3 mr-1" />
                儲存策略
              </Button>
              <CrossValidateButton onClick={() => setShowCrossValidate(!showCrossValidate)} />
              <MonteCarloButton onClick={() => setShowMonteCarlo(!showMonteCarlo)} />
            </div>
            <MetricsPanel metrics={result.metrics} walkForward={result.walk_forward} rollingWf={result.rolling_wf} deflatedSharpe={result.deflated_sharpe} />
            {showCrossValidate && (
              <CrossValidatePanel
                code={code}
                stopLoss={stopLoss}
                takeProfit={takeProfit}
                onClose={() => setShowCrossValidate(false)}
              />
            )}
            {showMonteCarlo && (
              <MonteCarloPanel
                code={code}
                symbol={symbol}
                interval={interval}
                candles={candles}
                stopLoss={stopLoss}
                takeProfit={takeProfit}
                startDate={startDate || undefined}
                endDate={endDate || undefined}
                onClose={() => setShowMonteCarlo(false)}
              />
            )}
            {result.candle_data?.length > 0 && (
              <KlineChart candles={result.candle_data} trades={result.trade_list || []} />
            )}
            {result.equity_curve.length > 0 && (
              <EquityChart data={result.equity_curve} />
            )}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">前推驗證</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground">訓練集投報率</p>
                    <p className="font-semibold">{result.walk_forward.train_roi}%</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">測試集投報率</p>
                    <p className="font-semibold">{result.walk_forward.test_roi}%</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">過擬合比</p>
                    <p className={`font-semibold ${result.walk_forward.overfit_ratio > 3 ? "text-red-500" : "text-green-500"}`}>
                      {result.walk_forward.overfit_ratio.toFixed(2)}
                    </p>
                  </div>
                </div>
                {result.rolling_wf && result.rolling_wf.splits.length > 1 && (
                  <div className="pt-3 border-t border-border/30 space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">滾動窗口（{result.rolling_wf.splits.length} 期）</p>
                    <div className="space-y-1">
                      {result.rolling_wf.splits.map((s) => (
                        <div key={s.split} className="flex items-center gap-2 text-xs font-mono">
                          <span className="text-muted-foreground w-6">#{s.split}</span>
                          <div className="flex-1 flex items-center gap-1">
                            <span className={s.train_roi >= 0 ? "text-emerald-400" : "text-red-400"}>
                              {s.train_roi >= 0 ? "+" : ""}{s.train_roi.toFixed(1)}%
                            </span>
                            <span className="text-muted-foreground">→</span>
                            <span className={`font-bold ${s.test_roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                              {s.test_roi >= 0 ? "+" : ""}{s.test_roi.toFixed(1)}%
                            </span>
                          </div>
                          <div className={`w-1.5 h-1.5 rounded-full ${s.test_roi > 0 ? "bg-emerald-400" : "bg-red-400"}`} />
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-4 text-xs pt-1">
                      <span className="text-muted-foreground">
                        一致性 <span className={`font-bold ${result.rolling_wf.consistency >= 0.6 ? "text-emerald-400" : "text-red-400"}`}>
                          {(result.rolling_wf.consistency * 100).toFixed(0)}%
                        </span>
                      </span>
                      <span className={`font-bold ${result.rolling_wf.robust ? "text-emerald-400" : "text-red-400"}`}>
                        {result.rolling_wf.robust ? "✅ 穩健" : "⚠️ 不穩健"}
                      </span>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
            {result.trade_list?.length > 0 && (
              <TradeTable trades={result.trade_list} />
            )}
          </div>
        )}

        {!result && null}
      </div>

      {/* Right: Settings panel */}
      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Settings className="h-4 w-4" />
              回測設定
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs text-muted-foreground">交易對</label>
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              >
                {SYMBOLS.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">K 線週期</label>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              >
                {INTERVALS.map((i) => (
                  <option key={i.value} value={i.value}>{i.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">K 線數量（越多回測越長）</label>
              <input
                type="number"
                value={candles}
                onChange={(e) => setCandles(+e.target.value)}
                min={100}
                max={5000}
                step={100}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
              <p className="text-xs text-muted-foreground mt-1">
                ≈ {interval === "15m" ? Math.round(candles / 96) : interval === "1h" ? Math.round(candles / 24) : interval === "4h" ? Math.round(candles / 6) : candles} 天
              </p>
            </div>
            {/* Date range */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-muted-foreground">開始日期</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full mt-1 px-2 py-1.5 rounded-md border bg-background text-xs"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">結束日期</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full mt-1 px-2 py-1.5 rounded-md border bg-background text-xs"
                />
              </div>
              {!(startDate || endDate) && (
                <p className="col-span-2 text-[10px] text-muted-foreground">不填 = 最近 {candles} 根 K 線（從今天往回推）</p>
              )}
              {(startDate || endDate) && (
                <p className="col-span-2 text-[10px] text-muted-foreground">
                  指定日期後拉取該區間數據
                  <button className="text-red-400 ml-2" onClick={() => { setStartDate(""); setEndDate(""); }}>清除</button>
                </p>
              )}
            </div>
            <div className="border-t pt-3">
              <label className="text-xs text-muted-foreground">初始資金 ($)</label>
              <input
                type="number"
                value={capital}
                onChange={(e) => setCapital(+e.target.value)}
                min={100}
                step={1000}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">每筆倉位 (%)</label>
              <input
                type="number"
                value={posSize}
                onChange={(e) => setPosSize(+e.target.value)}
                min={1}
                max={100}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">止損 (%)</label>
              <input
                type="number"
                value={stopLoss}
                onChange={(e) => setStopLoss(+e.target.value)}
                min={0.5}
                max={20}
                step={0.5}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">止盈 (%)</label>
              <input
                type="number"
                value={takeProfit}
                onChange={(e) => setTakeProfit(+e.target.value)}
                min={0.5}
                max={50}
                step={0.5}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <div className="border-t pt-3">
              <label className="text-xs text-muted-foreground">手續費 (% 每邊)</label>
              <input
                type="number"
                value={commission}
                onChange={(e) => setCommission(+e.target.value)}
                min={0}
                max={1}
                step={0.01}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
              <p className="text-xs text-muted-foreground mt-1">
                幣安合約 0.04% · 現貨 0.1%
              </p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">滑點 (% 每筆)</label>
              <input
                type="number"
                value={slippage}
                onChange={(e) => setSlippage(+e.target.value)}
                min={0}
                max={1}
                step={0.01}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
              <p className="text-xs text-muted-foreground mt-1">
                模擬市價單的價格偏移
              </p>
            </div>
          </CardContent>
        </Card>
        <SavedStrategiesPanel onLoad={(c, opts) => {
          setCode(c);
          if (opts?.sl !== undefined) setStopLoss(opts.sl);
          if (opts?.tp !== undefined) setTakeProfit(opts.tp);
          setResult(null);
          setError("");
          setTimeout(() => runBacktestWithCode(c, opts), 100);
        }} />
      </div>
    </div>
  );
});
