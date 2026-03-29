"use client";

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { api, ResearchJob, ResearchResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Wrench, Loader2, Zap, Settings, Dna, LogOut,
} from "lucide-react";

interface GeneInfo {
  desc: string;
  params: Record<string, number[]>;
  type: string;
}

export interface OptimizeJobState {
  job: ResearchJob | null;
  geneLib: {
    entry: Record<string, GeneInfo>;
    exit: Record<string, { desc: string; params: Record<string, number[]> }>;
  } | null;
  sourceGenes: string[];
  symbol: string;
  interval: string;
}

interface OptimizeTabProps {
  onRunStrategy?: (code: string, opts?: { sl?: number; tp?: number }) => void;
  onJobComplete?: (state: OptimizeJobState) => void;
  onReset?: () => void;
  initialDna?: ResearchResult["dna"];
  initialCode?: string;
  initialDescription?: string;
}

export function OptimizeTab({ onRunStrategy, onJobComplete, onReset, initialDna, initialCode, initialDescription }: OptimizeTabProps) {
  const [geneLib, setGeneLib] = useState<{
    entry: Record<string, GeneInfo>;
    exit: Record<string, { desc: string; params: Record<string, number[]> }>;
  } | null>(null);

  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    api.genes().then(setGeneLib).catch(() => {});
  }, []);

  const [sourceDna, setSourceDna] = useState<ResearchResult["dna"] | null>(initialDna ?? null);
  const [sourceCode, setSourceCode] = useState(initialCode ?? "");
  const [sourceDesc, setSourceDesc] = useState(initialDescription ?? "");

  useEffect(() => {
    if (initialDna) {
      setSourceDna(initialDna);
      const exitName = initialDna.exit_gene?.[0] ?? (initialDna as Record<string, unknown>).exit_gene;
      if (typeof exitName === "string") setExitGenes(prev => prev.length === 0 ? [exitName] : prev);
    }
    if (initialCode) setSourceCode(initialCode);
    if (initialDescription) setSourceDesc(initialDescription);
  }, [initialDna, initialCode, initialDescription]);

  const [addGenes, setAddGenes] = useState<string[]>([]);
  const [removeGenes, setRemoveGenes] = useState<string[]>([]);
  const [slRange, setSlRange] = useState("1,1.5,2,3");
  const [tpRange, setTpRange] = useState("2,4,6,8");
  const [exitGenes, setExitGenes] = useState<string[]>([]);
  const [paramOverrides, setParamOverrides] = useState<Record<string, Record<string, number[]>>>({});

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

  const [symbol, setSymbol] = useState("BTCUSDT");
  const [kInterval, setKInterval] = useState("4h");
  const [kCandles, setKCandles] = useState(1000);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [method, setMethod] = useState<"grid" | "nsga2" | "bayesian">("grid");
  const [nsgaPopSize, setNsgaPopSize] = useState(40);
  const [nsgaGens, setNsgaGens] = useState(20);
  const [bayesTrials, setBayesTrials] = useState(100);

  const [loading, setLoading] = useState(false);
  const [jobProgress, setJobProgress] = useState<{ current: number; total: number } | null>(null);
  const [optStartTime, setOptStartTime] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const currentGenes = useMemo(() => {
    if (!sourceDna?.entry_genes) return [];
    return sourceDna.entry_genes.map(g => g[0]);
  }, [sourceDna]);

  const activeGenes = useMemo(() => {
    const kept = currentGenes.filter(n => !removeGenes.includes(n));
    return [...new Set([...kept, ...addGenes])];
  }, [currentGenes, removeGenes, addGenes]);

  const startOptimize = async () => {
    if (!sourceDna) return;
    
    // 確保清掉上一次的任務
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    
    setLoading(true);
    setJobProgress(null);
    setOptStartTime(Date.now());

    const modifications: Record<string, unknown> = {};
    if (addGenes.length) modifications.add_genes = addGenes.map(n => ({ name: n }));
    if (removeGenes.length) modifications.remove_genes = removeGenes;
    if (slRange.trim()) modifications.sl_range = slRange.split(",").map(Number).filter(n => !isNaN(n));
    if (tpRange.trim()) modifications.tp_range = tpRange.split(",").map(Number).filter(n => !isNaN(n));
    if (exitGenes.length) modifications.exit_genes = exitGenes;
    const filteredOverrides: Record<string, Record<string, number[]>> = {};
    for (const [gene, params] of Object.entries(paramOverrides)) {
      const nonEmpty: Record<string, number[]> = {};
      for (const [k, v] of Object.entries(params)) {
        if (v.length > 0) nonEmpty[k] = v;
      }
      if (Object.keys(nonEmpty).length) filteredOverrides[gene] = nonEmpty;
    }
    if (Object.keys(filteredOverrides).length) modifications.param_overrides = filteredOverrides;
    if (customGenes.length) {
      modifications.custom_genes = customGenes.map(cg => ({
        name: cg.name, code: cg.code, setup: cg.setup,
        null_check: cg.null_check || "False", side: cg.side, desc: cg.desc, min_bars: 50,
      }));
    }

    const modsPayload = Object.keys(modifications).length ? modifications : undefined;

    try {
      let job_id: string;
      let pollFn: (id: string) => Promise<ResearchJob>;

      if (method === "nsga2" || method === "bayesian") {
        const resp = await api.startAdvancedOptimize({
          code: sourceCode,
          dna: sourceDna as unknown as Record<string, unknown>,
          method,
          symbol,
          interval: kInterval,
          candles: kCandles,
          modifications: modsPayload,
          pop_size: nsgaPopSize,
          n_gen: nsgaGens,
          n_trials: bayesTrials,
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate ? { end_date: endDate } : {}),
        });
        job_id = resp.job_id;
        pollFn = api.getAdvancedOptimize;
      } else {
        const resp = await api.startOptimize({
          code: sourceCode,
          dna: sourceDna as unknown as Record<string, unknown>,
          symbol,
          interval: kInterval,
          candles: kCandles,
          modifications: modsPayload,
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate ? { end_date: endDate } : {}),
        });
        job_id = resp.job_id;
        pollFn = api.getOptimize;
      }

      pollRef.current = setInterval(async () => {
        try {
          const status = await pollFn(job_id);
          if (status.progress) setJobProgress(status.progress);
          if (status.status === "done" || status.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            setLoading(false);
            setJobProgress(null);
            if (status.status === "done" && onJobComplete) {
              onJobComplete({
                job: status,
                geneLib,
                sourceGenes: currentGenes,
                symbol,
                interval: kInterval,
              });
            }
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

  const toggleGene = (list: string[], setList: (v: string[]) => void, name: string) => {
    setList(list.includes(name) ? list.filter(n => n !== name) : [...list, name]);
  };

  if (!sourceDna) {
    return (
      <Card className="h-[500px] flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <Wrench className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>從「自動研發」選一個策略，點「優化」送到這裡</p>
          <p className="text-xs mt-1">或從已儲存的策略載入</p>
        </div>
      </Card>
    );
  }

  if (!mounted) return null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Left: Source + Gene Selection */}
      <div className="space-y-4 lg:sticky lg:top-24 lg:self-start">
        {/* Source strategy */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Dna className="h-3.5 w-3.5" />
              原始策略
              {onReset && (
                <button
                  className="ml-auto text-xs text-muted-foreground hover:text-red-400 transition-colors"
                  onClick={() => {
                    setSourceDna(null);
                    setSourceCode("");
                    setSourceDesc("");
                    setAddGenes([]);
                    setRemoveGenes([]);
                    setExitGenes([]);
                    setParamOverrides({});
                    setCustomGenes([]);
                    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                    setLoading(false);
                    setJobProgress(null);
                    try {
                      sessionStorage.removeItem("opt_dna");
                      sessionStorage.removeItem("opt_code");
                      sessionStorage.removeItem("opt_desc");
                    } catch {}
                    onReset();
                  }}
                >
                  重置
                </button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground mb-2">{sourceDesc}</p>
            <div className="flex flex-wrap gap-1">
              {currentGenes.map((g, idx) => (
                <Badge key={`${g}-${idx}`} variant="secondary" className="text-xs">{geneLib?.entry[g]?.desc || g}</Badge>
              ))}
            </div>
            <div className="text-xs text-muted-foreground mt-2">
              止損: {sourceDna.sl}% | 止盈: {sourceDna.tp}% | 出場: {(() => { const eName = sourceDna.exit_gene?.[0] ?? (sourceDna as Record<string, unknown>).exit_gene; return geneLib?.exit[eName as string]?.desc || eName; })()}
            </div>
          </CardContent>
        </Card>

        {/* Gene modifications */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Settings className="h-3.5 w-3.5" />
              基因選擇
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="text-xs text-muted-foreground flex items-center justify-between mb-2">
                入場基因
                <button
                  className="text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    const allNames = geneLib ? Object.keys(geneLib.entry) : [];
                    if (addGenes.length === allNames.filter(n => !currentGenes.includes(n)).length && removeGenes.length === 0) {
                      setAddGenes([]);
                    } else {
                      setAddGenes(allNames.filter(n => !currentGenes.includes(n)));
                      setRemoveGenes([]);
                    }
                  }}
                >
                  {geneLib && addGenes.length === Object.keys(geneLib.entry).filter(n => !currentGenes.includes(n)).length && removeGenes.length === 0 ? "重置" : "全選"}
                </button>
              </p>
              {[
                { label: "做多信號", icon: "📈", color: "text-emerald-400", activeClass: "bg-emerald-500/20 border-emerald-500/50 text-emerald-400", filter: (t: string) => t === "long" },
                { label: "做空信號", icon: "📉", color: "text-red-400", activeClass: "bg-red-500/20 border-red-500/50 text-red-400", filter: (t: string) => t === "short" },
                { label: "濾網（多空通用）", icon: "🔍", color: "text-violet-400", activeClass: "bg-violet-500/20 border-violet-500/50 text-violet-400", filter: (t: string) => t === "filter" },
              ].map(({ label, icon, color, activeClass, filter: typeFilter }) => {
                if (!geneLib) return null;
                const genes = Object.entries(geneLib.entry).filter(([, info]) => typeFilter(info.type));
                if (!genes.length) return null;
                const activeCount = genes.filter(([n]) => currentGenes.includes(n) ? !removeGenes.includes(n) : addGenes.includes(n)).length;
                return (
                  <div key={label} className="mb-2">
                    <p className={`text-xs font-medium flex items-center gap-1.5 mb-1.5 ${color}`}>
                      <span>{icon}</span>
                      {label}
                      <span className="text-muted-foreground font-normal">({activeCount}/{genes.length})</span>
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {genes.map(([name, info]) => {
                        const isCurrent = currentGenes.includes(name);
                        const isActive = isCurrent ? !removeGenes.includes(name) : addGenes.includes(name);
                        const isRemoved = isCurrent && removeGenes.includes(name);
                        return (
                          <button
                            key={name}
                            onClick={() => {
                              if (isCurrent) toggleGene(removeGenes, setRemoveGenes, name);
                              else toggleGene(addGenes, setAddGenes, name);
                            }}
                            className={`text-xs px-2 py-1 rounded-md border transition-colors ${
                              isRemoved
                                ? "bg-red-500/20 border-red-500/50 text-red-400 line-through"
                                : isActive
                                  ? activeClass
                                  : "border-border/50 text-muted-foreground hover:border-border"
                            }`}
                            title={`${name}${isCurrent ? "（原始）" : ""}`}
                          >
                            {isCurrent && "● "}{info.desc || name}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            <Separator />

            {/* Exit genes */}
            <div>
              <p className="text-xs font-medium flex items-center gap-1.5 mb-1.5">
                <LogOut className="h-3 w-3 text-red-400" />
                出場策略（可多選）
                <span className="text-muted-foreground font-normal">
                  ({exitGenes.length}/{geneLib ? Object.keys(geneLib.exit).length : 0})
                </span>
              </p>
              <div className="flex flex-wrap gap-1">
                {geneLib && Object.entries(geneLib.exit).map(([name, info]) => (
                  <button
                    key={name}
                    onClick={() => toggleGene(exitGenes, setExitGenes, name)}
                    className={`text-xs px-2 py-1 rounded-md border transition-colors ${
                      exitGenes.includes(name)
                        ? "bg-blue-500/20 border-blue-500/50 text-blue-400"
                        : "border-border/50 text-muted-foreground hover:border-border"
                    }`}
                  >
                    {(info as { desc?: string }).desc || name}
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            {/* Custom genes */}
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
                  <div>
                    <label className="text-[10px] text-cyan-400 font-medium mb-1 block">💡 快速範例</label>
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
                        <option value="rsi_low">RSI 極度超賣</option>
                        <option value="vol_surge">成交量暴增 3 倍</option>
                        <option value="price_gap">跳空高開</option>
                        <option value="ema_fan">EMA 多頭排列</option>
                      </optgroup>
                      <optgroup label="做空信號">
                        <option value="rsi_high">RSI 極度超買</option>
                      </optgroup>
                      <optgroup label="出場信號">
                        <option value="exit_rsi">RSI 回到中性區</option>
                      </optgroup>
                    </select>
                  </div>

                  <Separator />

                  <div>
                    <label className="text-[10px] text-purple-400 font-medium mb-1 block">🤖 AI 生成</label>
                    <div className="flex gap-1">
                      <input
                        placeholder="例：當 RSI 低於 20 且 MACD 金叉時做多"
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

                  <div className="text-[10px] text-muted-foreground bg-muted/50 rounded p-2">
                    <p className="font-medium text-foreground mb-1">📖 可用變數</p>
                    <p><code className="text-cyan-400">closes[i]</code> 收盤價 · <code className="text-cyan-400">opens[i]</code> 開盤價 · <code className="text-cyan-400">highs[i]</code> 最高 · <code className="text-cyan-400">lows[i]</code> 最低 · <code className="text-cyan-400">volumes[i]</code> 成交量</p>
                    <p className="mt-1"><span className="font-medium text-foreground">指標函數：</span><code className="text-cyan-400">ema</code> · <code className="text-cyan-400">sma</code> · <code className="text-cyan-400">rsi</code> · <code className="text-cyan-400">bollinger_bands</code> · <code className="text-cyan-400">atr</code> · <code className="text-cyan-400">macd</code> · <code className="text-cyan-400">stoch_rsi</code></p>
                    <p className="mt-1 text-amber-400">⚠ 條件用 <code>i</code> 索引，回傳 True/False。指標可能回傳 None，記得檢查。</p>
                  </div>

                  <input placeholder="基因名稱（英文）" value={cgName} onChange={(e) => setCgName(e.target.value)} className="w-full px-2 py-1 rounded border bg-background text-xs font-mono" />
                  <input placeholder="描述" value={cgDesc} onChange={(e) => setCgDesc(e.target.value)} className="w-full px-2 py-1 rounded border bg-background text-xs" />
                  <select value={cgSide} onChange={(e) => setCgSide(e.target.value)} className="w-full px-2 py-1 rounded border bg-background text-xs">
                    <option value="long">做多信號</option>
                    <option value="short">做空信號</option>
                    <option value="exit">出場信號</option>
                  </select>
                  <textarea placeholder="指標計算代碼" value={cgSetup} onChange={(e) => setCgSetup(e.target.value)} className="w-full px-2 py-1 rounded border bg-background text-xs font-mono h-16" />
                  <textarea placeholder="條件代碼" value={cgCode} onChange={(e) => setCgCode(e.target.value)} className="w-full px-2 py-1 rounded border bg-background text-xs font-mono h-16" />
                  <Button
                    size="sm" variant="outline" className="w-full text-xs border-cyan-500/30 text-cyan-400"
                    disabled={!cgName || !cgCode}
                    onClick={() => {
                      setCustomGenes([...customGenes, { name: cgName, desc: cgDesc || cgName, code: cgCode, setup: cgSetup || "pass", null_check: "False", side: cgSide }]);
                      setCgName(""); setCgDesc(""); setCgCode(""); setCgSetup(""); setShowCustomForm(false);
                    }}
                  >
                    加入基因庫
                  </Button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Right: Parameters + Engine + Start */}
      <div className="space-y-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Zap className="h-4 w-4 text-amber-400" />
              參數與引擎
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">

            {/* Gene parameter tuning */}
            {geneLib && (
              activeGenes.some(n => geneLib.entry[n]) ||
              exitGenes.some(n => geneLib.exit[n])
            ) && (
              <div>
                <p className="text-sm font-medium flex items-center gap-1.5 mb-2">
                  <Zap className="h-3 w-3 text-amber-400" />
                  參數調整
                  <span className="text-muted-foreground font-normal">（勾選要掃的值）</span>
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {[
                    { label: "做多信號", icon: "📈", color: "text-emerald-400", filter: (t: string) => t === "long" },
                    { label: "做空信號", icon: "📉", color: "text-red-400", filter: (t: string) => t === "short" },
                    { label: "濾網", icon: "🔍", color: "text-violet-400", filter: (t: string) => t === "filter" },
                  ].map(({ label, icon, color, filter: typeFilter }) => {
                    const genesInGroup = activeGenes.filter(n => {
                      const gene = geneLib.entry[n];
                      return gene && typeFilter(gene.type);
                    });
                    if (!genesInGroup.length) return null;
                    return genesInGroup.map((geneName, gIdx) => {
                      const gene = geneLib.entry[geneName];
                      const hasParams = Object.keys(gene.params).length > 0;
                      return (
                        <div key={`${label}-${geneName}-${gIdx}`} className="p-3 rounded-lg border border-border/50 bg-muted/30">
                          <p className={`text-[10px] font-medium uppercase tracking-wider mb-1 ${color}`}>{icon} {label}</p>
                          <p className="text-sm font-medium text-foreground mb-2">{gene.desc || geneName}</p>
                          {!hasParams ? (
                            <p className="text-xs text-muted-foreground/50 mt-4 italic">此基因使用固定規則，無需調整參數。</p>
                          ) : (
                            Object.entries(gene.params).map(([paramName, values]) => {
                              const arr = Array.isArray(values) ? values : [values];
                              const selected = paramOverrides[geneName]?.[paramName] ?? arr;
                              return (
                                <div key={paramName} className="mb-2 last:mb-0">
                                  <span className="text-sm text-muted-foreground font-mono">{paramName}:</span>
                                  <div className="flex flex-wrap gap-1.5 mt-1">
                                    {arr.map(v => {
                                      const isOn = selected.includes(v);
                                      return (
                                        <button
                                          key={v}
                                          onClick={() => {
                                            const cur = paramOverrides[geneName]?.[paramName] ?? [...arr];
                                            const next = isOn ? cur.filter(x => x !== v) : [...cur, v];
                                            setParamOverrides({ ...paramOverrides, [geneName]: { ...(paramOverrides[geneName] || {}), [paramName]: next } });
                                          }}
                                          className={`text-sm px-3 py-1 rounded-md border font-mono transition-colors ${isOn ? "bg-amber-500/20 border-amber-500/50 text-amber-400" : "border-border/30 text-muted-foreground/50 line-through"}`}
                                        >
                                          {v}
                                        </button>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })
                          )}
                        </div>
                      );
                    });
                  })}
                  {/* Exit gene params */}
                  {exitGenes.map(geneName => {
                    const gene = geneLib.exit[geneName];
                    if (!gene) return null;
                    const hasParams = Object.keys(gene.params).length > 0;
                    return (
                      <div key={`exit_${geneName}`} className="p-3 rounded-lg border border-red-500/20 bg-red-500/5">
                        <p className="text-[10px] text-red-400 font-medium uppercase tracking-wider mb-1">🚪 出場基因</p>
                        <p className="text-sm font-medium text-red-400 mb-2 flex items-center gap-1">
                          <LogOut className="h-3.5 w-3.5" />
                          {(gene as { desc?: string }).desc || geneName}
                        </p>
                        {!hasParams ? (
                          <p className="text-xs text-red-400/50 mt-4 italic">此出場策略為固定規則，無需調整參數。</p>
                        ) : (
                          Object.entries(gene.params).map(([paramName, values]) => {
                            const arr = Array.isArray(values) ? values : [values];
                            const key = `exit_${geneName}`;
                            const selected = paramOverrides[key]?.[paramName] ?? arr;
                            return (
                              <div key={paramName} className="mb-2 last:mb-0">
                                <span className="text-sm text-muted-foreground font-mono">{paramName}:</span>
                                <div className="flex flex-wrap gap-1.5 mt-1">
                                  {arr.map(v => {
                                    const isOn = selected.includes(v);
                                    return (
                                      <button
                                        key={v}
                                        onClick={() => {
                                          const cur = paramOverrides[key]?.[paramName] ?? [...arr];
                                          const next = isOn ? cur.filter(x => x !== v) : [...cur, v];
                                          setParamOverrides({ ...paramOverrides, [key]: { ...(paramOverrides[key] || {}), [paramName]: next } });
                                        }}
                                        className={`text-sm px-3 py-1 rounded-md border font-mono transition-colors ${isOn ? "bg-amber-500/20 border-amber-500/50 text-amber-400" : "border-border/30 text-muted-foreground/50 line-through"}`}
                                      >
                                        {v}
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            );
                          })
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <Separator />

            {/* SL/TP ranges */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm text-muted-foreground">止損範圍 %</label>
                <input value={slRange} onChange={(e) => setSlRange(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm font-mono" placeholder="1,1.5,2,3" />
              </div>
              <div>
                <label className="text-sm text-muted-foreground">止盈範圍 %</label>
                <input value={tpRange} onChange={(e) => setTpRange(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm font-mono" placeholder="2,4,6,8" />
              </div>
            </div>

            <Separator />

            {/* Optimization method */}
            <div>
              <label className="text-sm text-muted-foreground mb-1.5 block">優化引擎</label>
              <div className="grid grid-cols-3 gap-2">
                {([
                  { value: "grid", label: "網格搜索", desc: "暴力掃描" },
                  { value: "bayesian", label: "貝葉斯", desc: "智能搜索" },
                  { value: "nsga2", label: "NSGA-II", desc: "多目標" },
                ] as const).map(({ value, label, desc }) => (
                  <button
                    key={value}
                    onClick={() => setMethod(value)}
                    className={`text-sm px-3 py-3 rounded-lg border transition-colors text-center ${
                      method === value
                        ? value === "nsga2" ? "bg-purple-500/20 border-purple-500/50 text-purple-400"
                          : value === "bayesian" ? "bg-cyan-500/20 border-cyan-500/50 text-cyan-400"
                            : "bg-blue-500/20 border-blue-500/50 text-blue-400"
                        : "border-border/50 text-muted-foreground hover:border-border"
                    }`}
                  >
                    <div className="font-medium">{label}</div>
                    <div className="text-xs opacity-70">{desc}</div>
                  </button>
                ))}
              </div>
              {method === "bayesian" && (
                <div className="mt-3">
                  <label className="text-sm text-muted-foreground">搜索次數</label>
                  <input type="number" value={bayesTrials} onChange={(e) => setBayesTrials(Number(e.target.value))} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm font-mono" min={20} max={500} step={10} />
                  <p className="text-xs text-muted-foreground mt-1">TPE 自動學習最佳參數區域</p>
                </div>
              )}
              {method === "nsga2" && (
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm text-muted-foreground">族群大小</label>
                    <input type="number" value={nsgaPopSize} onChange={(e) => setNsgaPopSize(Number(e.target.value))} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm font-mono" min={10} max={100} step={10} />
                  </div>
                  <div>
                    <label className="text-sm text-muted-foreground">進化代數</label>
                    <input type="number" value={nsgaGens} onChange={(e) => setNsgaGens(Number(e.target.value))} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm font-mono" min={5} max={50} step={5} />
                  </div>
                  <p className="col-span-2 text-xs text-muted-foreground">同時優化 ROI + Sharpe + 回撤</p>
                </div>
              )}
            </div>

            <Separator />

            {/* Data config */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm text-muted-foreground">交易對</label>
                <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm">
                  {["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"].map(s => (<option key={s} value={s}>{s}</option>))}
                </select>
              </div>
              <div>
                <label className="text-sm text-muted-foreground">K 線週期</label>
                <select value={kInterval} onChange={(e) => setKInterval(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm">
                  {["15m", "1h", "4h", "1d"].map(v => (<option key={v} value={v}>{v}</option>))}
                </select>
              </div>
            </div>

            {/* Date range */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm text-muted-foreground">開始日期</label>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm" />
              </div>
              <div>
                <label className="text-sm text-muted-foreground">結束日期</label>
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm" />
              </div>
              {!(startDate || endDate) && (
                <p className="col-span-2 text-xs text-muted-foreground">不填 = 最近 {kCandles} 根 K 線</p>
              )}
              {(startDate || endDate) && (
                <p className="col-span-2 text-xs text-muted-foreground">
                  指定日期後拉取該區間數據
                  <button className="text-red-400 ml-2 hover:text-red-300" onClick={() => { setStartDate(""); setEndDate(""); }}>清除</button>
                </p>
              )}
            </div>

            {/* Estimated combinations */}
            {method === "grid" && geneLib && (() => {
              const slVals = slRange.split(",").map(Number).filter(n => !isNaN(n)).length || 1;
              const tpVals = tpRange.split(",").map(Number).filter(n => !isNaN(n)).length || 1;
              const exitCount = exitGenes.length || 1;
              let paramCombos = 1;
              for (const geneName of activeGenes) {
                const gene = geneLib.entry[geneName];
                if (!gene) continue;
                for (const [paramName, values] of Object.entries(gene.params)) {
                  const arr = Array.isArray(values) ? values : [values];
                  const sel = paramOverrides[geneName]?.[paramName] ?? arr;
                  paramCombos *= Math.max(sel.length, 1);
                }
              }
              const total = paramCombos * slVals * tpVals * exitCount;
              return (
                <p className="text-xs text-muted-foreground text-center">
                  預估 {total.toLocaleString()} 種組合
                  {total > 500 && <span className="text-amber-400">（超過 500 自動切隨機搜索）</span>}
                </p>
              );
            })()}
            {method === "bayesian" && (
              <p className="text-xs text-muted-foreground text-center">🧠 貝葉斯優化 · {bayesTrials} 次智能搜索</p>
            )}
            {method === "nsga2" && (
              <p className="text-xs text-muted-foreground text-center">🎯 NSGA-II · {nsgaPopSize} 族群 × {nsgaGens} 代</p>
            )}

            <Button
              onClick={startOptimize}
              disabled={loading}
              className={`w-full btn-glow ${
                method === "nsga2" ? "bg-purple-600 hover:bg-purple-500"
                  : method === "bayesian" ? "bg-cyan-600 hover:bg-cyan-500"
                    : "bg-blue-600 hover:bg-blue-500"
              }`}
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {jobProgress ? `${jobProgress.current}/${jobProgress.total}` : "優化中..."}
                </>
              ) : (
                <>
                  <Wrench className="mr-2 h-4 w-4" />
                  {method === "nsga2" ? "啟動 NSGA-II" : method === "bayesian" ? "啟動貝葉斯優化" : "開始優化"}
                </>
              )}
            </Button>
            {loading && (
              <Button
                variant="outline"
                className="w-full border-red-500/30 text-red-400 hover:bg-red-500/10"
                onClick={() => {
                  if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                  setLoading(false);
                  setJobProgress(null);
                }}
              >
                停止優化
              </Button>
            )}
            {loading && jobProgress && (
              <div className="space-y-1">
                <div className="w-full bg-muted rounded-full h-2">
                  <div className="bg-blue-500 h-2 rounded-full transition-all duration-500" style={{ width: `${(jobProgress.current / jobProgress.total) * 100}%` }} />
                </div>
                <p className="text-xs text-muted-foreground text-center">
                  {jobProgress.current}/{jobProgress.total} 組合
                  {optStartTime && jobProgress.current > 0 && (() => {
                    const elapsed = (Date.now() - optStartTime) / 1000;
                    const perItem = elapsed / jobProgress.current;
                    const remaining = Math.round(perItem * (jobProgress.total - jobProgress.current));
                    return remaining > 0 ? ` · 預估剩餘 ${remaining < 60 ? `${remaining}s` : `${Math.floor(remaining / 60)}m${remaining % 60}s`}` : "";
                  })()}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
