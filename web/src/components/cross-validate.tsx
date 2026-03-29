"use client";

import { useState } from "react";
import { api, CrossValidateResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, ChevronDown, ChevronUp, Globe } from "lucide-react";

const DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"];
const DEFAULT_INTERVALS = ["1h", "4h"];
const ALL_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"];
const ALL_INTERVALS = [
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "4h", label: "4h" },
  { value: "1d", label: "1d" },
];

interface CrossValidateProps {
  code: string;
  stopLoss?: number;
  takeProfit?: number;
}

/** Button that triggers the cross-validate panel */
export function CrossValidateButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      size="sm"
      variant="outline"
      className="border-violet-500/30 text-violet-400 hover:bg-violet-500/10"
      onClick={onClick}
    >
      <Globe className="h-3 w-3 mr-1" />
      交叉驗證
    </Button>
  );
}

/** Inline panel for cross-validation results */
export function CrossValidatePanel({ code, stopLoss = 2, takeProfit = 4, onClose }: CrossValidateProps & { onClose: () => void }) {
  const [symbols, setSymbols] = useState<Set<string>>(new Set(DEFAULT_SYMBOLS));
  const [intervals, setIntervals] = useState<Set<string>>(new Set(DEFAULT_INTERVALS));
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [result, setResult] = useState<CrossValidateResult | null>(null);
  const [error, setError] = useState("");
  const [collapsed, setCollapsed] = useState(false);

  const toggleSymbol = (s: string) => {
    const next = new Set(symbols);
    next.has(s) ? next.delete(s) : next.add(s);
    setSymbols(next);
  };

  const toggleInterval = (v: string) => {
    const next = new Set(intervals);
    next.has(v) ? next.delete(v) : next.add(v);
    setIntervals(next);
  };

  const run = async () => {
    if (!symbols.size || !intervals.size) return;
    setLoading(true);
    setError("");
    setResult(null);
    const total = symbols.size * intervals.size;
    setProgress({ current: 0, total });

    const timer = window.setInterval(() => {
      setProgress((p) => p.current < p.total - 1 ? { ...p, current: p.current + 1 } : p);
    }, 1800);

    try {
      const res = await api.crossValidate({
        code,
        symbols: [...symbols],
        intervals: [...intervals],
        candles: 1000,
        stop_loss_pct: stopLoss,
        take_profit_pct: takeProfit,
      });
      setResult(res);
      setProgress({ current: total, total });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "交叉驗證失敗");
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  };

  const uniqueIntervals = result ? [...new Set(result.results.map((r) => r.interval))] : [];
  const uniqueSymbols = result ? [...new Set(result.results.map((r) => r.symbol))] : [];

  return (
    <Card className="border-violet-500/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-violet-400" />
            交叉驗證
          </span>
          <div className="flex items-center gap-2">
            {result && (
              <button onClick={() => setCollapsed(!collapsed)} className="text-muted-foreground hover:text-foreground">
                {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
              </button>
            )}
            <button onClick={onClose} className="text-xs text-muted-foreground hover:text-red-400">
              關閉
            </button>
          </div>
        </CardTitle>
      </CardHeader>
      {!collapsed && (
        <CardContent className="space-y-4">
          {!result && (
            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">交易對</label>
                <div className="flex flex-wrap gap-1">
                  {ALL_SYMBOLS.map((s) => (
                    <button
                      key={s}
                      onClick={() => toggleSymbol(s)}
                      className={`text-xs px-2 py-1 rounded-md border transition-colors ${
                        symbols.has(s)
                          ? "bg-violet-500/20 border-violet-500/50 text-violet-400"
                          : "border-border/50 text-muted-foreground hover:border-border"
                      }`}
                    >
                      {s.replace("USDT", "")}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">時間框架</label>
                <div className="flex flex-wrap gap-1">
                  {ALL_INTERVALS.map((i) => (
                    <button
                      key={i.value}
                      onClick={() => toggleInterval(i.value)}
                      className={`text-xs px-2 py-1 rounded-md border transition-colors ${
                        intervals.has(i.value)
                          ? "bg-violet-500/20 border-violet-500/50 text-violet-400"
                          : "border-border/50 text-muted-foreground hover:border-border"
                      }`}
                    >
                      {i.label}
                    </button>
                  ))}
                </div>
              </div>
              <Button
                onClick={run}
                disabled={loading || !symbols.size || !intervals.size}
                className="w-full bg-violet-600 hover:bg-violet-500"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    驗證中 {progress.current}/{progress.total}...
                  </>
                ) : (
                  <>
                    <Globe className="mr-2 h-4 w-4" />
                    開始驗證（{symbols.size} × {intervals.size} = {symbols.size * intervals.size} 組合）
                  </>
                )}
              </Button>
              {loading && (
                <div className="w-full bg-muted rounded-full h-1.5">
                  <div
                    className="bg-violet-500 h-1.5 rounded-full transition-all duration-500"
                    style={{ width: `${progress.total ? (progress.current / progress.total) * 100 : 0}%` }}
                  />
                </div>
              )}
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          {result && (
            <div className="space-y-4">
              {/* Consistency Score Circle */}
              <div className="flex items-center gap-6">
                <div className="relative w-20 h-20 flex-shrink-0">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="6" className="text-muted/30" />
                    <circle
                      cx="50" cy="50" r="42" fill="none" strokeWidth="6"
                      strokeDasharray={`${2 * Math.PI * 42}`}
                      strokeDashoffset={`${2 * Math.PI * 42 * (1 - result.summary.consistency_score / 100)}`}
                      strokeLinecap="round"
                      className={
                        result.summary.consistency_score >= 70 ? "text-emerald-500"
                          : result.summary.consistency_score >= 50 ? "text-yellow-500"
                            : "text-red-500"
                      }
                      stroke="currentColor"
                    />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className={`text-lg font-bold ${
                      result.summary.consistency_score >= 70 ? "text-emerald-400"
                        : result.summary.consistency_score >= 50 ? "text-yellow-400"
                          : "text-red-400"
                    }`}>
                      {result.summary.consistency_score}
                    </span>
                  </div>
                </div>
                <div className="space-y-1 text-sm">
                  <p className="font-medium">
                    一致性評分
                    <Badge variant="outline" className={`ml-2 text-xs ${
                      result.summary.consistency_score >= 70 ? "text-emerald-400 border-emerald-400/30"
                        : result.summary.consistency_score >= 50 ? "text-yellow-400 border-yellow-400/30"
                          : "text-red-400 border-red-400/30"
                    }`}>
                      {result.summary.consistency_score >= 70 ? "泛化良好" : result.summary.consistency_score >= 50 ? "一般" : "可能過擬合"}
                    </Badge>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {result.summary.profitable}/{result.summary.total_combinations} 組合盈利 · 平均 ROI {result.summary.avg_roi}% · 平均勝率 {result.summary.avg_win_rate}%
                  </p>
                </div>
              </div>

              {/* Heatmap */}
              <div>
                <p className="text-xs text-muted-foreground mb-2 font-medium">ROI 熱力圖</p>
                <div className="overflow-x-auto">
                  <div
                    className="grid gap-1"
                    style={{
                      gridTemplateColumns: `80px repeat(${uniqueIntervals.length}, minmax(80px, 1fr))`,
                    }}
                  >
                    <div className="text-xs text-muted-foreground font-medium p-1" />
                    {uniqueIntervals.map((iv) => (
                      <div key={iv} className="text-xs text-muted-foreground font-medium text-center p-1">
                        {iv}
                      </div>
                    ))}
                    {uniqueSymbols.map((sym) => (
                      <div key={`row-${sym}`} className="contents">
                        <div className="text-xs text-muted-foreground font-medium p-1 flex items-center">
                          {sym.replace("USDT", "")}
                        </div>
                        {uniqueIntervals.map((iv) => {
                          const entry = result.results.find((r) => r.symbol === sym && r.interval === iv);
                          if (!entry || entry.error || !entry.metrics) {
                            return (
                              <div key={`${sym}-${iv}`} className="rounded-md bg-muted/50 p-2 text-center text-xs text-muted-foreground">
                                {entry?.error ? "❌" : "—"}
                              </div>
                            );
                          }
                          const roi = entry.metrics.roi_pct;
                          const wr = entry.metrics.win_rate;
                          const intensity = Math.min(Math.abs(roi) / 20, 1);
                          const bg = roi >= 0
                            ? `rgba(16, 185, 129, ${0.1 + intensity * 0.5})`
                            : `rgba(239, 68, 68, ${0.1 + intensity * 0.5})`;
                          return (
                            <div
                              key={`${sym}-${iv}`}
                              className="rounded-md p-2 text-center border border-transparent hover:border-foreground/20 transition-colors"
                              style={{ backgroundColor: bg }}
                              title={`${sym} ${iv}: ROI ${roi}%, 勝率 ${wr}%, ${entry.trades} 筆交易`}
                            >
                              <p className={`text-sm font-bold ${roi >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                                {roi > 0 ? "+" : ""}{roi}%
                              </p>
                              <p className="text-[10px] text-muted-foreground">
                                勝率 {wr}%
                              </p>
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Summary stats */}
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-xs text-muted-foreground">平均 Sharpe</p>
                  <p className={`text-sm font-bold ${result.summary.avg_sharpe > 0.5 ? "text-emerald-400" : "text-muted-foreground"}`}>
                    {result.summary.avg_sharpe}
                  </p>
                </div>
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-xs text-muted-foreground">最大回撤</p>
                  <p className={`text-sm font-bold ${result.summary.worst_drawdown < 20 ? "text-emerald-400" : "text-red-400"}`}>
                    {result.summary.worst_drawdown}%
                  </p>
                </div>
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-xs text-muted-foreground">盈利組合</p>
                  <p className="text-sm font-bold">
                    {result.summary.profitable}/{result.summary.total_combinations}
                  </p>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                className="w-full border-violet-500/30 text-violet-400 hover:bg-violet-500/10"
                onClick={() => setResult(null)}
              >
                重新驗證
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
