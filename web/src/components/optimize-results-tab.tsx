"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { ResearchJob, ResearchResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricsPanel, gradeStrategy } from "@/components/metrics-panel";
import {
  Trophy, Copy, Check, Play, Bookmark, Wrench,
} from "lucide-react";
import { saveStrategy, genId } from "@/lib/storage";
import { CrossValidateButton, CrossValidatePanel } from "@/components/cross-validate";
import {
  ScatterChart, Scatter, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line,
} from "recharts";

type RankedResult = ResearchResult & { _grade: string; _gradeScore: number; _rank: number };

interface OptimizeResultsTabProps {
  job: ResearchJob | null;
  geneLib: {
    entry: Record<string, { desc: string; params: Record<string, number[]>; type: string }>;
    exit: Record<string, { desc: string; params: Record<string, number[]> }>;
  } | null;
  sourceGenes: string[];
  symbol: string;
  interval: string;
  onRunStrategy?: (code: string, opts?: { sl?: number; tp?: number }) => void;
  onClear?: () => void;
}

export function OptimizeResultsTab({
  job, geneLib, sourceGenes, symbol, interval, onRunStrategy, onClear,
}: OptimizeResultsTabProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  const [selected, setSelected] = useState<RankedResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [showCrossValidate, setShowCrossValidate] = useState(false);

  const rankedResults: RankedResult[] = useMemo(() => {
    if (!job?.results?.length) return [];
    return [...job.results]
      .map((r) => {
        const g = gradeStrategy(r.metrics, r.walk_forward);
        return { ...r, _grade: g.grade, _gradeScore: g.score, _rank: 0 };
      })
      .sort((a, b) => {
        if (a._gradeScore !== b._gradeScore) return b._gradeScore - a._gradeScore;
        return (b.metrics.roi_pct ?? 0) - (a.metrics.roi_pct ?? 0);
      })
      .map((r, idx) => ({ ...r, _rank: idx + 1 }));
  }, [job?.results]);

  // Auto-select first result
  useEffect(() => {
    if (rankedResults.length && !selected) {
      setSelected(rankedResults[0]);
    }
  }, [rankedResults]);

  const copyCode = useCallback((code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  if (!mounted) return null;

  if (!job || !rankedResults.length) {
    return (
      <Card className="h-[500px] flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <Trophy className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>還沒有優化結果</p>
          <p className="text-xs mt-1 max-w-xs mx-auto">在「自動研發」找到好策略 → 點「優化」帶到工作台 → 調整基因和參數 → 啟動優化</p>
        </div>
      </Card>
    );
  }

  if (job.status === "failed") {
    return (
      <Card className="border-destructive">
        <CardContent className="pt-4">
          <p className="text-sm text-destructive">{job.error || "優化失敗"}</p>
        </CardContent>
      </Card>
    );
  }

  const gradeBg: Record<string, string> = {
    A: "bg-emerald-600", B: "bg-blue-600", C: "bg-yellow-600", D: "bg-orange-600", F: "bg-red-600",
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* Left: Results list */}
      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Trophy className="h-4 w-4" />
              優化結果
              <Badge variant="outline" className="ml-1 text-xs">{rankedResults.length} 個</Badge>
              {job.method && (
                <Badge variant="outline" className={`text-[10px] ${
                  job.method === "nsga2" ? "text-purple-400 border-purple-400/30"
                    : job.method === "bayesian" ? "text-cyan-400 border-cyan-400/30"
                      : "text-blue-400 border-blue-400/30"
                }`}>
                  {job.method === "nsga2" ? "NSGA-II" : job.method === "bayesian" ? "貝葉斯" : "網格"}
                </Badge>
              )}
              {onClear && (
                <button
                  className="ml-auto text-xs text-muted-foreground hover:text-red-400 transition-colors"
                  onClick={onClear}
                >
                  清除
                </button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[70vh] overflow-y-auto">
            {rankedResults.map((r) => (
              <div
                key={r._rank}
                onClick={() => setSelected(r)}
                className={`p-3 rounded-lg cursor-pointer transition-colors ${
                  selected?._rank === r._rank
                    ? "bg-blue-500/10 border border-blue-500/30"
                    : "bg-muted/50 hover:bg-muted"
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className={`w-6 h-6 rounded text-xs font-bold flex items-center justify-center text-white ${gradeBg[r._grade] || "bg-gray-600"}`}>
                      {r._grade}
                    </span>
                    <span className="text-sm font-semibold">#{r._rank}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    {r.pareto_front && <Badge variant="outline" className="text-[10px] text-purple-400 border-purple-400/30">Pareto</Badge>}
                    <Badge variant="outline">分數: {r._gradeScore}/100</Badge>
                  </div>
                </div>
                <div className="text-xs text-muted-foreground grid grid-cols-3 gap-1">
                  <span className={r.metrics.roi_pct >= 0 ? "text-emerald-400" : "text-red-400"}>
                    投報: {r.metrics.roi_pct}%
                  </span>
                  <span>勝率: {r.metrics.win_rate}%</span>
                  <span>利潤因子: {r.metrics.profit_factor >= 9999 ? "∞" : r.metrics.profit_factor}</span>
                </div>
                {r.walk_forward && (
                  <div className="text-xs text-muted-foreground mt-1 flex gap-2">
                    <span>訓練: {r.walk_forward.train_roi}%</span>
                    <span>測試: <span className={r.walk_forward.test_roi >= 0 ? "text-emerald-400" : "text-red-400"}>{r.walk_forward.test_roi}%</span></span>
                    <span>過擬合: <span className={r.walk_forward.overfit_ratio > 3 ? "text-red-400" : r.walk_forward.overfit_ratio > 2 ? "text-yellow-400" : "text-emerald-400"}>{r.walk_forward.overfit_ratio >= 999 ? "∞" : r.walk_forward.overfit_ratio.toFixed(1)}</span></span>
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Right: Selected result detail */}
      <div className="lg:col-span-2 space-y-4">
        {selected ? (
          <>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between">
                  優化結果 — #{selected._rank}
                  <div className="flex gap-2">
                    {onRunStrategy && (
                      <Button
                        size="sm"
                        className="bg-emerald-600 hover:bg-emerald-500 btn-glow"
                        onClick={() => onRunStrategy(selected.code, { sl: selected.dna?.sl, tp: selected.dna?.tp })}
                      >
                        <Play className="h-3 w-3 mr-1" />
                        一鍵回測
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        const { grade, score } = gradeStrategy(selected.metrics, selected.walk_forward);
                        const name = prompt("策略名稱", `優化 #${selected._rank} — ${selected.description.slice(0, 30)}`);
                        if (!name) return;
                        saveStrategy({
                          id: genId(),
                          name,
                          code: selected.code,
                          grade,
                          score,
                          metrics: selected.metrics,
                          walkForward: selected.walk_forward,
                          settings: { symbol, interval, sl: selected.dna?.sl, tp: selected.dna?.tp },
                          source: "optimize",
                          savedAt: Date.now(),
                        });
                        window.dispatchEvent(new Event("strategies-updated"));
                      }}
                    >
                      <Bookmark className="h-3 w-3 mr-1" />
                      儲存
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => copyCode(selected.code)}
                    >
                      {copied ? <Check className="h-3 w-3 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
                      {copied ? "已複製" : "複製代碼"}
                    </Button>
                    <CrossValidateButton onClick={() => setShowCrossValidate(!showCrossValidate)} />
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-3">{selected.description}</p>
                {selected.dna && (
                  <div className="flex flex-wrap gap-1 mb-3">
                    {selected.dna.entry_genes.map(([name]) => (
                      <Badge key={name} variant="secondary" className="text-xs">
                        {sourceGenes.includes(name) ? (geneLib?.entry[name]?.desc || name) : `✨ ${geneLib?.entry[name]?.desc || name}`}
                      </Badge>
                    ))}
                    <Badge variant="outline" className="text-xs">
                      止損:{selected.dna.sl}% 止盈:{selected.dna.tp}%
                    </Badge>
                  </div>
                )}
                <pre className="bg-muted p-4 rounded-lg text-xs font-mono overflow-x-auto max-h-[300px]">
                  {selected.code}
                </pre>
              </CardContent>
            </Card>
            <MetricsPanel metrics={selected.metrics} walkForward={selected.walk_forward} rollingWf={selected.rolling_wf} deflatedSharpe={selected.deflated_sharpe} />
            {showCrossValidate && (
              <CrossValidatePanel
                code={selected.code}
                stopLoss={selected.dna?.sl}
                takeProfit={selected.dna?.tp}
                onClose={() => setShowCrossValidate(false)}
              />
            )}

            {/* Pareto Front Scatter (NSGA-II) */}
            {job?.pareto_data && job.pareto_data.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    🎯 Pareto 前沿（ROI vs Sharpe vs 回撤）
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="h-64 border rounded-lg bg-muted/10 p-3 flex flex-col">
                      <p className="text-xs text-muted-foreground mb-2 font-medium">ROI% vs Sharpe</p>
                      <div className="flex-1 min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                          <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                            <CartesianGrid stroke="#374151" vertical={false} />
                            <XAxis
                              type="number" dataKey="roi" name="ROI" unit="%"
                              stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false}
                              domain={['auto', 'auto']}
                              label={{ value: "ROI %", position: "insideBottom", offset: -10, fill: "#9ca3af", fontSize: 10 }}
                            />
                            <YAxis
                              type="number" dataKey="sharpe" name="Sharpe"
                              stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false}
                              domain={['auto', 'auto']}
                              tickFormatter={(v) => v.toFixed(1)}
                            />
                            <Tooltip
                              cursor={{ strokeDasharray: '3 3' }}
                              contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                              itemStyle={{ color: "#f8fafc" }}
                              formatter={(v: any) => typeof v === 'number' ? v.toFixed(2) : String(v)}
                            />
                            <Scatter data={job.pareto_data.filter(d => d.pareto)} fill="#d946ef" stroke="#fdf4ff" strokeWidth={1} name="Pareto 最優解" shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={6} fill={props.fill} stroke={props.stroke} strokeWidth={props.strokeWidth} />} />
                            <Scatter data={job.pareto_data.filter(d => !d.pareto)} fill="#334155" name="其他解" shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={3} fill={props.fill} />} />
                          </ScatterChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                    <div className="h-64 border rounded-lg bg-muted/10 p-3 flex flex-col">
                      <p className="text-xs text-muted-foreground mb-2 font-medium">ROI% vs 最大回撤%</p>
                      <div className="flex-1 min-h-0">
                        <ResponsiveContainer width="100%" height="100%">
                          <ScatterChart margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                            <CartesianGrid stroke="#374151" vertical={false} />
                            <XAxis
                              type="number" dataKey="roi" name="ROI" unit="%"
                              stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false}
                              domain={['auto', 'auto']}
                              label={{ value: "ROI %", position: "insideBottom", offset: -10, fill: "#9ca3af", fontSize: 10 }}
                            />
                            <YAxis
                              type="number" dataKey="drawdown" name="回撤" unit="%"
                              stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false}
                              domain={['auto', 'auto']}
                              tickFormatter={(v) => v.toFixed(1)}
                            />
                            <Tooltip
                              cursor={{ strokeDasharray: '3 3' }}
                              contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                              itemStyle={{ color: "#f8fafc" }}
                              formatter={(v: any) => typeof v === 'number' ? v.toFixed(2) : String(v)}
                            />
                            <Scatter data={job.pareto_data.filter(d => d.pareto)} fill="#d946ef" stroke="#fdf4ff" strokeWidth={1} name="Pareto 最優解" shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={6} fill={props.fill} stroke={props.stroke} strokeWidth={props.strokeWidth} />} />
                            <Scatter data={job.pareto_data.filter(d => !d.pareto)} fill="#334155" name="其他解" shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={3} fill={props.fill} />} />
                          </ScatterChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-6 mt-4 text-xs font-medium text-muted-foreground justify-center">
                    <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-purple-500 inline-block" /> Pareto 最優解</span>
                    <span className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-slate-500 inline-block" /> 其他解</span>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Convergence Curve (Bayesian) */}
            {selected.convergence && selected.convergence.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    🧠 貝葉斯收斂曲線
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-64 border rounded-lg bg-muted/10 p-3 flex flex-col">
                    <p className="text-xs text-muted-foreground mb-2 font-medium">最佳分數隨試驗次數提升</p>
                    <div className="flex-1 min-h-0">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={selected.convergence} margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
                          <CartesianGrid stroke="#374151" vertical={false} />
                          <XAxis
                            dataKey="trial"
                            stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false}
                            label={{ value: "試驗次數 (Trial)", position: "insideBottom", offset: -10, fill: "#9ca3af", fontSize: 10 }}
                          />
                          <YAxis
                            domain={[(dataMin: number) => Math.floor(dataMin - 5), (dataMax: number) => Math.ceil(dataMax + 5)]}
                            stroke="#9ca3af" fontSize={11} tickLine={false} axisLine={false}
                            tickFormatter={(v) => v.toFixed(1)}
                          />
                          <Tooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#334155", borderRadius: "8px", fontSize: "12px" }}
                            itemStyle={{ color: "#f8fafc" }}
                            labelStyle={{ color: "#9ca3af", marginBottom: "4px" }}
                            formatter={(v: any) => [typeof v === 'number' ? v.toFixed(2) : String(v), "最佳分數"]}
                            labelFormatter={(v) => `試驗第 ${v} 次`}
                          />
                          <defs>
                            <linearGradient id="colorScore" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4}/>
                              <stop offset="95%" stopColor="#06b6d4" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <Area
                            type="stepAfter" dataKey="best_score" stroke="#06b6d4" strokeWidth={2}
                            fillOpacity={1} fill="url(#colorScore)"
                            activeDot={{ r: 5, fill: "#06b6d4", stroke: "#1e293b", strokeWidth: 2 }}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                  <div className="text-xs text-muted-foreground text-center mt-4 font-medium">
                    共 {selected.convergence.length} 次試驗 · 最終最佳分數: <span className="text-cyan-400">{Math.max(...selected.convergence.map(d => d.best_score)).toFixed(2)}</span>
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        ) : (
          <Card className="h-[500px] flex items-center justify-center">
            <div className="text-center text-muted-foreground">
              <Trophy className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>點選左側結果查看詳情</p>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
