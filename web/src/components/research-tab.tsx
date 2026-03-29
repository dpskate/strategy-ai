"use client";

import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { api, ResearchJob, ResearchResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricsPanel } from "@/components/metrics-panel";
import { Separator } from "@/components/ui/separator";
import { Dna, Loader2, Trophy, Copy, Check, Settings, Play, Bookmark, ChevronDown, ChevronUp, Zap, LogOut, Wrench } from "lucide-react";
import { saveStrategy, genId } from "@/lib/storage";
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

export function ResearchTab({ onRunStrategy, onOptimizeStrategy }: {
  onRunStrategy?: (code: string, opts?: { sl?: number; tp?: number }) => void;
  onOptimizeStrategy?: (result: ResearchResult) => void;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  const [loading, setLoading] = useState(false);
  const [researchStartTime, setResearchStartTime] = useState<number | null>(null);
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [selected, setSelected] = useState<ResearchResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [showCrossValidate, setShowCrossValidate] = useState(false);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);

  // Restore completed job from sessionStorage after mount
  useEffect(() => {
    try {
      const v = sessionStorage.getItem("research_job");
      if (v) {
        const parsed = JSON.parse(v);
        if (parsed?.status === "done") setJob(parsed);
      }
    } catch {}
  }, []);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [wsProgress, setWsProgress] = useState<{
    status: string;
    progress?: { current: number; total: number; pct?: number; best_score?: number; valid: number; population: number; top_results?: { description: string; score: number; roi_pct: number; win_rate: number }[] };
    top_results?: { rank: number; score: number; description: string; roi_pct: number; win_rate: number }[];
  } | null>(null);

  // Gene library + selection
  const [geneLib, setGeneLib] = useState<{
    entry: Record<string, { desc: string; params: Record<string, number[]>; type: string }>;
    exit: Record<string, { params: Record<string, number[]> }>;
  } | null>(null);
  const [selectedEntryGenes, setSelectedEntryGenes] = useState<Set<string>>(new Set()); // empty = all
  const [selectedExitGenes, setSelectedExitGenes] = useState<Set<string>>(new Set());
  const [useGeneFilter, setUseGeneFilter] = useState(false);

  // Custom genes
  const [customGenes, setCustomGenes] = useState<{ name: string; code: string; setup: string; null_check: string; side: string; desc: string }[]>([]);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [cgName, setCgName] = useState("");
  const [cgDesc, setCgDesc] = useState("");
  const [cgCode, setCgCode] = useState("");
  const [cgSetup, setCgSetup] = useState("");
  const [cgSide, setCgSide] = useState("long");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiLoading, setAiLoading] = useState(false);

  const handleAiGenerate = async () => {
    if (!aiPrompt.trim()) return;
    try {
      const s = JSON.parse(localStorage.getItem("llm_settings") || "{}");
      if (!s.apiKey) return;
      setAiLoading(true);
      const res = await api.generateGene({
        prompt: aiPrompt,
        api_key: s.apiKey,
        base_url: s.baseUrl || "https://api.openai.com/v1",
        model: s.model || "gpt-4o-mini",
      });
      if (res.gene) {
        setCgName(res.gene.name);
        setCgDesc(res.gene.desc);
        setCgSide(res.gene.side);
        setCgSetup(res.gene.setup);
        setCgCode(res.gene.code);
        setAiPrompt("");
      }
    } catch {} finally { setAiLoading(false); }
  };

  useEffect(() => {
    api.genes().then(setGeneLib).catch(() => {});
  }, []);

  // Sort mode
  const [sortBy, setSortBy] = useState<"grade" | "roi" | "sharpe" | "winrate" | "drawdown">("grade");

  // Sorted results with grade info
  type RankedResult = ResearchResult & { _grade: string; _gradeScore: number; _rank: number };
  const rankedResults: RankedResult[] = useMemo(() => {
    if (!job?.results?.length) return [];
    return [...job.results]
      .map((r) => {
        const g = gradeStrategy(r.metrics, r.walk_forward);
        return { ...r, _grade: g.grade, _gradeScore: g.score, _rank: 0 };
      })
      .sort((a, b) => {
        switch (sortBy) {
          case "roi": return (b.metrics.roi_pct ?? 0) - (a.metrics.roi_pct ?? 0);
          case "sharpe": return (b.metrics.sharpe_ratio ?? 0) - (a.metrics.sharpe_ratio ?? 0);
          case "winrate": return (b.metrics.win_rate ?? 0) - (a.metrics.win_rate ?? 0);
          case "drawdown": return (a.metrics.max_drawdown_pct ?? 100) - (b.metrics.max_drawdown_pct ?? 100);
          default:
            if (a._gradeScore !== b._gradeScore) return b._gradeScore - a._gradeScore;
            return (b.metrics.roi_pct ?? 0) - (a.metrics.roi_pct ?? 0);
        }
      })
      .map((r, idx) => ({ ...r, _rank: idx + 1 }));
  }, [job?.results, sortBy]);

  // Auto-select top ranked result
  useEffect(() => {
    if (rankedResults.length && !selected) {
      setSelected(rankedResults[0]);
    }
  }, [rankedResults]);

  // Config
  const [generations, setGenerations] = useState(10);
  const [popSize, setPopSize] = useState(20);
  const [topK, setTopK] = useState(5);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [kInterval, setKInterval] = useState("4h");
  const [direction, setDirection] = useState<"both" | "long" | "short">("both");
  const [candles, setCandles] = useState(1000);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const startResearch = async () => {
    setLoading(true);
    setJob(null);
    setSelected(null);
    setWsProgress(null);
    setResearchStartTime(Date.now());
    try {
      const { job_id } = await api.startResearch({
        symbol,
        interval: kInterval,
        candles,
        generations,
        population_size: popSize,
        top_k: topK,
        direction,
        ...(useGeneFilter && selectedEntryGenes.size > 0 ? { allowed_entry: [...selectedEntryGenes] } : {}),
        ...(useGeneFilter && selectedExitGenes.size > 0 ? { allowed_exit: [...selectedExitGenes] } : {}),
        ...(customGenes.length > 0 ? {
          custom_genes: customGenes.map(cg => ({
            name: cg.name,
            code: cg.code,
            setup: cg.setup,
            null_check: cg.null_check || "False",
            side: cg.side,
            desc: cg.desc,
            min_bars: 50,
          }))
        } : {}),
        ...(startDate ? { start_date: startDate } : {}),
        ...(endDate ? { end_date: endDate } : {}),
      });

      // WebSocket for real-time progress
      const wsBase = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100").replace(/^http/, "ws");
      const ws = new WebSocket(`${wsBase}/ws/research/${job_id}`);
      wsRef.current = ws;
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          setWsProgress(data);
          if (data.status === "done" || data.status === "failed") ws.close();
        } catch {}
      };
      ws.onerror = () => ws.close();
      ws.onclose = () => { wsRef.current = null; };

      // Poll for results (fallback + final state)
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getResearch(job_id);
          setJob(status);
          if (status.status === "done" || status.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            setLoading(false);
            // Notify user
            if (status.status === "done" && document.hidden) {
              try { new Notification("策略 AI", { body: `研發完成！找到 ${status.results?.length ?? 0} 個策略`, icon: "/favicon.ico" }); } catch {}
            }
            // Persist completed job to sessionStorage
            if (status.status === "done") {
              try { sessionStorage.setItem("research_job", JSON.stringify(status)); } catch {}
            }
            // Auto-select handled by rankedResults effect
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          setLoading(false);
        }
      }, 2000);
    } catch {
      setLoading(false);
    }
  };

  const stopResearch = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setLoading(false);
  }, []);

  const copyCode = useCallback((code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  if (!mounted) return null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left: Config + Results list */}
      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Dna className="h-4 w-4" />
              研發設定
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
              <label className="text-xs text-muted-foreground">策略方向</label>
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value as "both" | "long" | "short")}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              >
                <option value="both">雙向（做多 + 做空）</option>
                <option value="long">僅做多</option>
                <option value="short">僅做空</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">K 線週期</label>
              <select
                value={kInterval}
                onChange={(e) => setKInterval(e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              >
                {INTERVALS.map((i) => (
                  <option key={i.value} value={i.value}>{i.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">K 線數量</label>
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
                ≈ {kInterval === "15m" ? Math.round(candles / 96) : kInterval === "1h" ? Math.round(candles / 24) : kInterval === "4h" ? Math.round(candles / 6) : candles} 天
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
                  指定日期後忽略 K 線數量，拉取該區間全部數據
                  <button className="text-red-400 ml-2" onClick={() => { setStartDate(""); setEndDate(""); }}>清除</button>
                </p>
              )}
            </div>
            <div className="border-t pt-3">
              <label className="text-xs text-muted-foreground">迭代輪數（越多越精，但越慢）</label>
              <input
                type="number"
                value={generations}
                onChange={(e) => setGenerations(+e.target.value)}
                min={1}
                max={50}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">每輪測試幾個策略</label>
              <input
                type="number"
                value={popSize}
                onChange={(e) => setPopSize(+e.target.value)}
                min={5}
                max={100}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">顯示前幾名</label>
              <input
                type="number"
                value={topK}
                onChange={(e) => setTopK(+e.target.value)}
                min={1}
                max={20}
                className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
              />
            </div>
            <Button onClick={startResearch} disabled={loading || (useGeneFilter && selectedEntryGenes.size === 0)} className="w-full bg-emerald-600 hover:bg-emerald-500 btn-glow">
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {(wsProgress?.progress ?? job?.progress)
                    ? `第 ${(wsProgress?.progress ?? job?.progress)!.current}/${(wsProgress?.progress ?? job?.progress)!.total} 輪`
                    : "啟動中..."}
                </>
              ) : (
                <>
                  <Dna className="mr-2 h-4 w-4" />
                  啟動自動研發
                </>
              )}
            </Button>
            {loading && (
              <Button variant="outline" className="w-full border-red-500/30 text-red-400 hover:bg-red-500/10" onClick={stopResearch}>
                停止研發
              </Button>
            )}
            {loading && (job?.progress || wsProgress?.progress) && (() => {
              const p = wsProgress?.progress ?? job?.progress!;
              return (
                <div className="space-y-2">
                  <div className="w-full bg-muted rounded-full h-2">
                    <div
                      className="bg-emerald-500 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${p.pct ?? Math.round((p.current / p.total) * 100)}%` }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground text-center">
                    第 {p.current}/{p.total} 輪 · 有效策略 {p.valid}/{p.population}
                    {researchStartTime && p.current > 0 && (() => {
                      const elapsed = (Date.now() - researchStartTime) / 1000;
                      const perRound = elapsed / p.current;
                      const remaining = Math.round(perRound * (p.total - p.current));
                      return remaining > 0 ? ` · 預估剩餘 ${remaining < 60 ? `${remaining}s` : `${Math.floor(remaining / 60)}m${remaining % 60}s`}` : "";
                    })()}
                  </p>
                  {p.best_score != null && (
                    <div className="flex items-center justify-between text-xs px-1">
                      <span className="text-muted-foreground">當前最佳</span>
                      <span className="text-emerald-400 font-mono font-medium">{p.best_score.toFixed(1)} 分</span>
                    </div>
                  )}
                  {p.top_results && p.top_results.length > 0 && (
                    <div className="space-y-1 border-t pt-2">
                      <p className="text-[10px] text-muted-foreground">本輪 Top {p.top_results.length}</p>
                      {p.top_results.slice(0, 3).map((r, i) => (
                        <div key={i} className="text-[10px] flex items-center justify-between gap-1">
                          <span className="text-muted-foreground truncate flex-1">{r.description}</span>
                          <span className="text-emerald-400 shrink-0">ROI {r.roi_pct}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </CardContent>
        </Card>

        {/* Gene selection */}
        <Card>
          <CardHeader className="pb-2 cursor-pointer" onClick={() => {
            const next = !useGeneFilter;
            setUseGeneFilter(next);
            // First open: select all genes
            if (next && geneLib && selectedEntryGenes.size === 0) {
              setSelectedEntryGenes(new Set(Object.keys(geneLib.entry)));
              setSelectedExitGenes(new Set(Object.keys(geneLib.exit)));
            }
          }}>
            <CardTitle className="text-sm flex items-center justify-between">
              <span className="flex items-center gap-2">
                <Dna className="h-3.5 w-3.5" />
                基因選擇
                <Badge variant="secondary" className="text-xs">
                  {useGeneFilter && geneLib
                    ? `${selectedEntryGenes.size}/${Object.keys(geneLib.entry).length} 入場 · ${selectedExitGenes.size}/${Object.keys(geneLib.exit).length} 出場`
                    : "全部基因"}
                </Badge>
                {customGenes.length > 0 && (
                  <Badge variant="outline" className="text-xs text-cyan-400 border-cyan-400/30">
                    +{customGenes.length} 自定義
                  </Badge>
                )}
              </span>
              {useGeneFilter ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </CardTitle>
          </CardHeader>
          {useGeneFilter && geneLib && (
            <CardContent className="pt-0 space-y-3">
              <p className="text-xs text-muted-foreground flex items-center justify-between">
                取消不需要的基因，只保留你想用的組合
                <button
                  className="text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => setSelectedEntryGenes(
                    selectedEntryGenes.size === Object.keys(geneLib.entry).length
                      ? new Set()
                      : new Set(Object.keys(geneLib.entry))
                  )}
                >
                  {selectedEntryGenes.size === Object.keys(geneLib.entry).length ? "取消全選" : "全選"}
                </button>
              </p>
              {/* Entry genes — grouped by type */}
              {[
                { label: "做多信號", icon: "📈", color: "text-emerald-400", activeClass: "bg-emerald-500/20 border-emerald-500/50 text-emerald-400", filter: (t: string) => t === "long" },
                { label: "做空信號", icon: "📉", color: "text-red-400", activeClass: "bg-red-500/20 border-red-500/50 text-red-400", filter: (t: string) => t === "short" },
                { label: "濾網（多空通用）", icon: "🔍", color: "text-violet-400", activeClass: "bg-violet-500/20 border-violet-500/50 text-violet-400", filter: (t: string) => t === "filter" },
              ].map(({ label, icon, color, activeClass, filter: typeFilter }) => {
                const genes = Object.entries(geneLib.entry).filter(([, info]) => typeFilter(info.type));
                if (!genes.length) return null;
                return (
                  <div key={label}>
                    <p className={`text-xs font-medium flex items-center gap-1.5 mb-2 ${color}`}>
                      <span>{icon}</span>
                      {label}
                      <span className="text-muted-foreground font-normal">({genes.filter(([n]) => selectedEntryGenes.has(n)).length}/{genes.length})</span>
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {genes.map(([name, info]) => (
                        <button
                          key={name}
                          onClick={() => {
                            const next = new Set(selectedEntryGenes);
                            next.has(name) ? next.delete(name) : next.add(name);
                            setSelectedEntryGenes(next);
                          }}
                          className={`text-xs px-2 py-1 rounded-md border transition-colors ${
                            selectedEntryGenes.has(name)
                              ? activeClass
                              : "border-border/50 text-muted-foreground hover:border-border"
                          }`}
                          title={name}
                        >
                          {info.desc || name}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
              {/* Exit genes */}
              <div>
                <p className="text-xs font-medium flex items-center gap-1.5 mb-2">
                  <LogOut className="h-3 w-3 text-red-400" />
                  出場信號
                </p>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(geneLib.exit).map(([name, info]) => (
                    <button
                      key={name}
                      onClick={() => {
                        const next = new Set(selectedExitGenes);
                        next.has(name) ? next.delete(name) : next.add(name);
                        setSelectedExitGenes(next);
                      }}
                      className={`text-xs px-2 py-1 rounded-md border transition-colors ${
                        selectedExitGenes.has(name)
                          ? "bg-blue-500/20 border-blue-500/50 text-blue-400"
                          : "border-border/50 text-muted-foreground hover:border-border"
                      }`}
                    >
                      {(info as { desc?: string }).desc || name}
                    </button>
                  ))}
                </div>
              </div>
              {/* Custom genes */}
              <Separator />
              <div>
                <p className="text-xs font-medium flex items-center gap-1.5 mb-2">
                  <Settings className="h-3 w-3 text-cyan-400" />
                  自定義基因
                  <button
                    className="text-xs text-cyan-400 hover:text-cyan-300 ml-auto"
                    onClick={() => setShowCustomForm(!showCustomForm)}
                  >
                    {showCustomForm ? "收起" : "+ 新增"}
                  </button>
                </p>
                {customGenes.map((cg, idx) => (
                  <div key={idx} className="flex items-center gap-2 text-xs py-1">
                    <Badge variant="outline" className="text-xs text-cyan-400 border-cyan-400/30">
                      {cg.side === "long" ? "做多" : cg.side === "short" ? "做空" : "出場"}
                    </Badge>
                    <span className="text-foreground">{cg.desc || cg.name}</span>
                    <button
                      className="text-red-400 hover:text-red-300 ml-auto text-xs"
                      onClick={() => setCustomGenes(customGenes.filter((_, i) => i !== idx))}
                    >
                      刪除
                    </button>
                  </div>
                ))}
                {showCustomForm && (
                  <div className="space-y-2 mt-2 p-3 rounded border border-cyan-500/20 bg-cyan-500/5">
                    {/* Quick templates */}
                    <div>
                      <label className="text-[10px] text-cyan-400 font-medium mb-1 block">💡 快速範例（選一個自動填入）</label>
                      <select
                        className="w-full px-2 py-1 rounded border bg-background text-xs"
                        value=""
                        onChange={(e) => {
                          const templates: Record<string, { name: string; desc: string; side: string; setup: string; code: string }> = {
                            rsi_low: { name: "rsi_extreme_low", desc: "RSI 極度超賣（< 15）", side: "long", setup: "rsi_vals = rsi(closes, 14)", code: "rsi_vals[i] is not None and rsi_vals[i] < 15" },
                            rsi_high: { name: "rsi_extreme_high", desc: "RSI 極度超買（> 85）", side: "short", setup: "rsi_vals = rsi(closes, 14)", code: "rsi_vals[i] is not None and rsi_vals[i] > 85" },
                            vol_surge: { name: "volume_surge_3x", desc: "成交量暴增 3 倍", side: "long", setup: "vol_sma = sma(volumes, 20)", code: "vol_sma[i] is not None and volumes[i] > vol_sma[i] * 3" },
                            price_gap: { name: "gap_up", desc: "跳空高開 > 1%", side: "long", setup: "pass", code: "opens[i] > closes[i-1] * 1.01" },
                            ema_fan: { name: "ema_fan_up", desc: "EMA 多頭排列（9>21>50）", side: "long", setup: "e9 = ema(closes, 9)\ne21 = ema(closes, 21)\ne50 = ema(closes, 50)", code: "e9[i] is not None and e21[i] is not None and e50[i] is not None and e9[i] > e21[i] > e50[i]" },
                            exit_rsi: { name: "exit_rsi_neutral", desc: "RSI 回到中性區出場", side: "exit", setup: "rsi_ex = rsi(closes, 14)", code: "rsi_ex[i] is not None and 45 < rsi_ex[i] < 55" },
                          };
                          const t = templates[e.target.value];
                          if (t) { setCgName(t.name); setCgDesc(t.desc); setCgSide(t.side); setCgSetup(t.setup); setCgCode(t.code); }
                        }}
                      >
                        <option value="">選擇範例...</option>
                        <optgroup label="做多信號">
                          <option value="rsi_low">RSI 極度超賣（&lt; 15）</option>
                          <option value="vol_surge">成交量暴增 3 倍</option>
                          <option value="price_gap">跳空高開 &gt; 1%</option>
                          <option value="ema_fan">EMA 多頭排列（9&gt;21&gt;50）</option>
                        </optgroup>
                        <optgroup label="做空信號">
                          <option value="rsi_high">RSI 極度超買（&gt; 85）</option>
                        </optgroup>
                        <optgroup label="出場信號">
                          <option value="exit_rsi">RSI 回到中性區出場</option>
                        </optgroup>
                      </select>
                    </div>

                    <Separator />

                    {/* AI Gene Generation */}
                    <div>
                      <label className="text-[10px] text-purple-400 font-medium mb-1 block">🤖 AI 生成（用中文描述你的想法）</label>
                      <div className="flex gap-1">
                        <input
                          placeholder="例：當價格跌破布林帶下軌且成交量放大 2 倍時做多"
                          value={aiPrompt}
                          onChange={(e) => setAiPrompt(e.target.value)}
                          className="flex-1 px-2 py-1 rounded border bg-background text-xs"
                          onKeyDown={(e) => { if (e.key === "Enter" && aiPrompt.trim()) { e.preventDefault(); handleAiGenerate(); } }}
                        />
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-xs border-purple-500/30 text-purple-400 px-3"
                          disabled={aiLoading || !aiPrompt.trim()}
                          onClick={handleAiGenerate}
                        >
                          {aiLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : "生成"}
                        </Button>
                      </div>
                      {(() => {
                        try {
                          const s = JSON.parse(localStorage.getItem("llm_settings") || "{}");
                          if (!s.apiKey) return <p className="text-[10px] text-amber-400 mt-1">⚠ 請先在「策略回測」tab 設定 API Key</p>;
                        } catch { return null; }
                        return null;
                      })()}
                    </div>

                    <Separator />

                    {/* Available variables hint */}
                    <div className="text-[10px] text-muted-foreground bg-muted/50 rounded p-2">
                      <p className="font-medium text-foreground mb-1">📖 可用變數</p>
                      <p><code className="text-cyan-400">closes[i]</code> 收盤價 · <code className="text-cyan-400">opens[i]</code> 開盤價 · <code className="text-cyan-400">highs[i]</code> 最高 · <code className="text-cyan-400">lows[i]</code> 最低 · <code className="text-cyan-400">volumes[i]</code> 成交量</p>
                      <p className="mt-1"><span className="font-medium text-foreground">指標函數：</span><code className="text-cyan-400">ema(data, period)</code> · <code className="text-cyan-400">sma(data, period)</code> · <code className="text-cyan-400">rsi(closes, period)</code> · <code className="text-cyan-400">bollinger_bands(closes, period, std)</code> · <code className="text-cyan-400">atr(highs, lows, closes, period)</code> · <code className="text-cyan-400">macd(closes, fast, slow, signal)</code> · <code className="text-cyan-400">stoch_rsi(closes, rsi_p, stoch_p)</code></p>
                      <p className="mt-1 text-amber-400">⚠ 條件必須用 <code>i</code> 索引，回傳 True/False。指標可能回傳 None，記得檢查。</p>
                    </div>

                    <input
                      placeholder="基因名稱（英文，如 my_rsi_signal）"
                      value={cgName}
                      onChange={(e) => setCgName(e.target.value)}
                      className="w-full px-2 py-1 rounded border bg-background text-xs font-mono"
                    />
                    <input
                      placeholder="描述"
                      value={cgDesc}
                      onChange={(e) => setCgDesc(e.target.value)}
                      className="w-full px-2 py-1 rounded border bg-background text-xs"
                    />
                    <select
                      value={cgSide}
                      onChange={(e) => setCgSide(e.target.value)}
                      className="w-full px-2 py-1 rounded border bg-background text-xs"
                    >
                      <option value="long">做多信號</option>
                      <option value="short">做空信號</option>
                      <option value="exit">出場信號</option>
                    </select>
                    <textarea
                      placeholder="指標計算代碼（如：rsi_vals = rsi(closes, 14)）"
                      value={cgSetup}
                      onChange={(e) => setCgSetup(e.target.value)}
                      className="w-full px-2 py-1 rounded border bg-background text-xs font-mono h-16"
                    />
                    <textarea
                      placeholder="條件代碼（返回 True 時入場，如：rsi_vals[i] < 20）"
                      value={cgCode}
                      onChange={(e) => setCgCode(e.target.value)}
                      className="w-full px-2 py-1 rounded border bg-background text-xs font-mono h-16"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full text-xs border-cyan-500/30 text-cyan-400"
                      disabled={!cgName || !cgCode}
                      onClick={() => {
                        setCustomGenes([...customGenes, {
                          name: cgName,
                          desc: cgDesc || cgName,
                          code: cgCode,
                          setup: cgSetup || "pass",
                          null_check: "False",
                          side: cgSide,
                        }]);
                        setCgName(""); setCgDesc(""); setCgCode(""); setCgSetup("");
                        setShowCustomForm(false);
                      }}
                    >
                      加入基因庫
                    </Button>
                  </div>
                )}
              </div>
            </CardContent>
          )}
        </Card>

        {/* Results list */}
        {job?.results && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Trophy className="h-4 w-4" />
                研發結果
                {job.progress && job.progress.current < job.progress.total && (
                  <Badge variant="outline" className="text-xs text-amber-400 border-amber-400/30">
                    早停 · {job.progress.current}/{job.progress.total} 輪
                  </Badge>
                )}
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                  className="ml-auto text-xs px-2 py-1 rounded border bg-background text-muted-foreground"
                >
                  <option value="grade">綜合評分</option>
                  <option value="roi">投報率</option>
                  <option value="sharpe">夏普比率</option>
                  <option value="winrate">勝率</option>
                  <option value="drawdown">最低回撤</option>
                </select>
                <button
                  className="ml-auto text-xs text-muted-foreground hover:text-red-400 transition-colors"
                  onClick={() => {
                    setJob(null);
                    setSelected(null);
                    try {
                      sessionStorage.removeItem("research_job");
                      // 連帶清除優化工作台的狀態
                      sessionStorage.removeItem("opt_dna");
                      sessionStorage.removeItem("opt_code");
                      sessionStorage.removeItem("opt_desc");
                      sessionStorage.removeItem("opt_job");
                      sessionStorage.removeItem("opt_src_genes");
                      sessionStorage.removeItem("opt_symbol");
                      sessionStorage.removeItem("opt_interval");
                      sessionStorage.removeItem("opt_genelib");
                    } catch {}
                    // 通知其他 tab 重置
                    window.dispatchEvent(new Event("optimize-reset"));
                  }}
                >
                  清除結果
                </button>
              </CardTitle>
              {job.progress && job.progress.current < job.progress.total && (
                <p className="text-xs text-muted-foreground mt-1">
                  策略已收斂，連續 3 輪無提升，提前結束以避免過擬合
                </p>
              )}
            </CardHeader>
            <CardContent className="space-y-2 max-h-[60vh] overflow-y-auto">
              {rankedResults.map((r) => {
                const grade = r._grade;
                const gradeBg: Record<string, string> = {
                  A: "bg-emerald-600", B: "bg-blue-600", C: "bg-yellow-600", D: "bg-orange-600", F: "bg-red-600",
                };
                return (
                <div
                  key={`res-${r._rank}`}
                  onClick={() => setSelected(r)}
                  className={`p-3 rounded-lg cursor-pointer transition-colors ${
                    selected && (selected as RankedResult)._rank === r._rank
                      ? "bg-emerald-500/10 border border-emerald-500/30"
                      : "bg-muted/50 hover:bg-muted"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className={`w-6 h-6 rounded text-xs font-bold flex items-center justify-center text-white ${gradeBg[grade] || "bg-gray-600"}`}>
                        {grade}
                      </span>
                      <span className="text-sm font-semibold">#{r._rank}</span>
                    </div>
                    <Badge variant="outline">分數: {r._gradeScore}/100</Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground truncate mt-0.5 mb-1">{r.description.length > 60 ? r.description.slice(0, 60) + "…" : r.description}</p>
                  {r.metrics.long_trades !== undefined && r.metrics.short_trades !== undefined && (
                    (r.metrics.long_trades === 0 || r.metrics.short_trades === 0) ? (
                      <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-400/30 mb-1">⚠️ 純{r.metrics.long_trades === 0 ? "做空" : "做多"}</Badge>
                    ) : r.metrics.long_trades + r.metrics.short_trades > 0 && Math.min(r.metrics.long_trades, r.metrics.short_trades) / Math.max(r.metrics.long_trades, r.metrics.short_trades) < 0.2 ? (
                      <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-400/30 mb-1">⚠️ 多空失衡</Badge>
                    ) : null
                  )}
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
                );
              })}
            </CardContent>
          </Card>
        )}

        {job?.status === "failed" && (
          <Card className="border-destructive">
            <CardContent className="pt-4">
              <p className="text-sm text-destructive">{job.error || "研發失敗"}</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Right: Selected strategy detail */}
      <div className="lg:col-span-2 space-y-4">
        {selected ? (
          <>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between">
                  策略詳情 — #{rankedResults.find(r => r.rank === selected.rank)?._rank ?? selected.rank}
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
                    {onOptimizeStrategy && selected.dna && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-blue-500/30 text-blue-400 hover:bg-blue-500/10"
                        onClick={() => onOptimizeStrategy(selected)}
                      >
                        <Wrench className="h-3 w-3 mr-1" />
                        優化
                      </Button>
                    )}
                    <CrossValidateButton onClick={() => setShowCrossValidate(!showCrossValidate)} />
                    <MonteCarloButton onClick={() => setShowMonteCarlo(!showMonteCarlo)} />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        const { grade, score } = gradeStrategy(selected.metrics, selected.walk_forward);
                        const displayRank = rankedResults.find(r => r.rank === selected.rank)?._rank ?? selected.rank;
                        const name = prompt("策略名稱", `研發 #${displayRank} — ${selected.description.slice(0, 30)}`);
                        if (!name) return;
                        saveStrategy({
                          id: genId(),
                          name,
                          code: selected.code,
                          grade,
                          score,
                          metrics: selected.metrics,
                          walkForward: selected.walk_forward,
                          settings: { symbol, interval: kInterval, sl: selected.dna?.sl, tp: selected.dna?.tp },
                          source: "research",
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
                      {copied ? (
                        <Check className="h-3 w-3 mr-1" />
                      ) : (
                        <Copy className="h-3 w-3 mr-1" />
                      )}
                      {copied ? "已複製" : "複製代碼"}
                    </Button>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground mb-3">{selected.description}</p>
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
            {showMonteCarlo && (
              <MonteCarloPanel
                code={selected.code}
                symbol={symbol}
                interval={kInterval}
                candles={candles}
                stopLoss={selected.dna?.sl}
                takeProfit={selected.dna?.tp}
                startDate={startDate || undefined}
                endDate={endDate || undefined}
                onClose={() => setShowMonteCarlo(false)}
              />
            )}
          </>
        ) : (
          <Card className="h-[500px] flex items-center justify-center">
            <div className="text-center text-muted-foreground">
              <Dna className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>設定參數後啟動自動研發</p>
              <p className="text-xs mt-1">AI 會自動生成、回測、進化策略</p>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
