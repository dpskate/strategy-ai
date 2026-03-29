"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BacktestTab, BacktestTabRef } from "@/components/backtest-tab";
import { ResearchTab } from "@/components/research-tab";
import { OptimizeTab, OptimizeJobState } from "@/components/optimize-tab";
import { OptimizeResultsTab } from "@/components/optimize-results-tab";
import { ResearchResult, api } from "@/lib/api";
import { FactorTab } from "@/components/factor-tab";
import { MonitorTab } from "@/components/monitor-tab";
import { Zap, Activity, Terminal } from "lucide-react";
import { useAppStore } from "@/lib/store";

const VALID_TABS = ["backtest", "research", "optimize", "opt-results", "factors", "monitor"];

export default function Home() {
  const [activeTab, setActiveTab] = useState("backtest");
  const backtestRef = useRef<BacktestTabRef>(null);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  const {
    optimizeDna, optimizeCode, optimizeDesc,
    optJob, optGeneLib, optSourceGenes, optSymbol, optInterval,
    setOptimizeSource, setOptResults, setOptJob, resetAll,
  } = useAppStore();

  // Health check
  useEffect(() => {
    const check = () => api.health().then(() => setApiOnline(true)).catch(() => setApiOnline(false));
    check();
    const iv = setInterval(check, 30000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const hash = window.location.hash.replace("#", "");
    if (VALID_TABS.includes(hash)) setActiveTab(hash);
  }, []);

  const changeTab = useCallback((tab: string) => {
    setActiveTab(tab);
    window.location.hash = tab;
  }, []);

  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash.replace("#", "");
      if (VALID_TABS.includes(hash)) setActiveTab(hash);
    };
    const onOptReset = () => resetAll();
    window.addEventListener("hashchange", onHash);
    window.addEventListener("optimize-reset", onOptReset);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("optimize-reset", onOptReset);
    };
  }, [resetAll]);

  const handleRunStrategy = (code: string, opts?: { sl?: number; tp?: number }) => {
    if (backtestRef.current) {
      backtestRef.current.loadAndRun(code, opts);
    }
    changeTab("backtest");
  };

  const handleOptimizeStrategy = (result: ResearchResult) => {
    setOptimizeSource(result.dna, result.code, result.description);
    changeTab("optimize");
  };

  const handleJobComplete = (state: OptimizeJobState) => {
    setOptResults(state.job, state.geneLib, state.sourceGenes, state.symbol, state.interval);
    changeTab("opt-results");
  };

  const handleOptimizeReset = () => resetAll();

  const handleClearResults = () => setOptJob(null);

  return (
    <main className="min-h-screen bg-background bg-grid bg-glow">
      {/* Header */}
      <header className="header-gradient header-scan sticky top-0 z-50 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="relative">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-500 btn-glow">
                <Zap className="h-5 w-5 text-white" />
              </div>
              <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-emerald-400 rounded-full pulse-dot" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-emerald-400 via-cyan-300 to-emerald-400 bg-clip-text text-transparent">
                  策略 AI
                </h1>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-emerald-500/20 text-emerald-400/70 bg-emerald-500/5">
                  測試版
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground font-mono tracking-widest uppercase">
                智能策略研發引擎
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-muted-foreground">
              <Terminal className="h-3 w-3" />
              <span>API</span>
              {apiOnline === null ? (
                <span className="text-muted-foreground">檢測中</span>
              ) : apiOnline ? (
                <span className="text-emerald-400">已連線</span>
              ) : (
                <span className="text-red-400">離線</span>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-[11px] font-mono text-muted-foreground">
              <Activity className="h-3 w-3 text-emerald-400" />
              <span>v0.1.0</span>
            </div>
          </div>
        </div>
      </header>

      {/* Content */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 py-8">
        <Tabs value={activeTab} onValueChange={changeTab}>
          <TabsList className="mb-8">
            <TabsTrigger value="backtest">策略回測</TabsTrigger>
            <TabsTrigger value="research">自動研發</TabsTrigger>
            <TabsTrigger value="optimize">優化工作台</TabsTrigger>
            <TabsTrigger value="opt-results">
              優化結果
              {optJob?.results?.length ? (
                <span className="ml-1.5 px-1.5 py-0.5 text-[10px] rounded-full bg-emerald-500/20 text-emerald-400">
                  {optJob.results.length}
                </span>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="factors">因子研究</TabsTrigger>
            <TabsTrigger value="monitor">策略監控</TabsTrigger>
          </TabsList>

          <TabsContent value="backtest" forceMount className="data-[state=inactive]:hidden animate-fade-in">
            <BacktestTab ref={backtestRef} />
          </TabsContent>

          <TabsContent value="research" forceMount className="data-[state=inactive]:hidden animate-fade-in">
            <ResearchTab onRunStrategy={handleRunStrategy} onOptimizeStrategy={handleOptimizeStrategy} />
          </TabsContent>

          <TabsContent value="optimize" forceMount className="data-[state=inactive]:hidden animate-fade-in">
            <OptimizeTab
              onRunStrategy={handleRunStrategy}
              onJobComplete={handleJobComplete}
              onReset={handleOptimizeReset}
              initialDna={optimizeDna}
              initialCode={optimizeCode}
              initialDescription={optimizeDesc}
            />
          </TabsContent>

          <TabsContent value="opt-results" forceMount className="data-[state=inactive]:hidden animate-fade-in">
            <OptimizeResultsTab
              job={optJob}
              geneLib={optGeneLib}
              sourceGenes={optSourceGenes}
              symbol={optSymbol}
              interval={optInterval}
              onRunStrategy={handleRunStrategy}
              onClear={handleClearResults}
            />
          </TabsContent>

          <TabsContent value="factors" forceMount className="data-[state=inactive]:hidden animate-fade-in">
            <FactorTab />
          </TabsContent>

          <TabsContent value="monitor" forceMount className="data-[state=inactive]:hidden animate-fade-in">
            <MonitorTab />
          </TabsContent>
        </Tabs>
      </div>

      {/* Footer */}
      <footer className="relative z-10 border-t border-border/30 px-6 py-4 mt-16">
        <div className="max-w-7xl mx-auto flex items-center justify-between text-[11px] font-mono text-muted-foreground">
          <span>© 2026 策略 AI</span>
          <span className="hidden sm:block">回測結果不代表未來收益 · 投資有風險</span>
          <span className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${apiOnline ? "bg-emerald-400 pulse-dot" : apiOnline === false ? "bg-red-400" : "bg-gray-400"}`} />
            {apiOnline ? "系統正常運行" : apiOnline === false ? "API 離線" : "檢測中"}
          </span>
        </div>
      </footer>
    </main>
  );
}
