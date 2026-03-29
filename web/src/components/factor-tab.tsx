"use client";

import { useState, useMemo } from "react";
import { api, FactorAnalysis, FactorAnalysisResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, FlaskConical, ArrowUp, ArrowDown, Check, BarChart3, TrendingUp, Link2 } from "lucide-react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
const INTERVALS = [
  { value: "1h", label: "1h" },
  { value: "4h", label: "4h" },
];

const GRADE_COLORS: Record<string, string> = {
  A: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  B: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  C: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  D: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  F: "bg-red-500/20 text-red-400 border-red-500/30",
};

type SortKey = "rank" | "grade" | "name" | "ic_mean" | "ic_ir" | "t_stat" | "p_value" | "monotonicity" | "verdict";
type SortDir = "asc" | "desc";

function corrColor(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 0.8) return "bg-red-500/40 text-red-300";
  if (abs >= 0.6) return "bg-orange-500/30 text-orange-300";
  return "bg-yellow-500/20 text-yellow-300";
}

export function FactorTab() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("4h");
  const [candles, setCandles] = useState(1000);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FactorAnalysisResult | null>(null);
  const [selectedFactor, setSelectedFactor] = useState<FactorAnalysis | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedFactor(null);
    try {
      const params: Record<string, unknown> = { symbol, interval, candles };
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;
      const res = await api.factorAnalysis(params as Parameters<typeof api.factorAnalysis>[0]);
      setResult(res);
      if (res.factors.length > 0) setSelectedFactor(res.factors[0]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "分析失敗");
    } finally {
      setLoading(false);
    }
  };

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "rank" ? "asc" : "desc");
    }
  };

  const sortedFactors = useMemo(() => {
    if (!result) return [];
    const gradeOrder: Record<string, number> = { A: 0, B: 1, C: 2, D: 3, F: 4 };
    const arr = result.factors.map((f, i) => ({ ...f, rank: i + 1 }));
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "rank": cmp = a.rank - b.rank; break;
        case "grade": cmp = (gradeOrder[a.grade] ?? 5) - (gradeOrder[b.grade] ?? 5); break;
        case "name": cmp = a.name.localeCompare(b.name); break;
        case "ic_mean": cmp = a.ic_mean - b.ic_mean; break;
        case "ic_ir": cmp = a.ic_ir - b.ic_ir; break;
        case "t_stat": cmp = a.t_stat - b.t_stat; break;
        case "p_value": cmp = a.p_value - b.p_value; break;
        case "monotonicity": cmp = a.monotonicity - b.monotonicity; break;
        case "verdict": cmp = a.verdict.localeCompare(b.verdict); break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [result, sortKey, sortDir]);

  const decayData = useMemo(() => {
    if (!selectedFactor) return [];
    return Object.entries(selectedFactor.decay_curve)
      .map(([k, v]) => ({ horizon: Number(k), ic: v }))
      .sort((a, b) => a.horizon - b.horizon);
  }, [selectedFactor]);

  const quintileData = useMemo(() => {
    if (!selectedFactor) return [];
    return selectedFactor.quintile_returns.map((v, i) => ({
      group: `Q${i + 1}`,
      ret: v,
    }));
  }, [selectedFactor]);

  const SortHeader = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      className="px-3 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:text-emerald-400 transition-colors select-none whitespace-nowrap"
      onClick={() => handleSort(k)}
    >
      {label}
      {sortKey === k && <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>}
    </th>
  );

  return (
    <div className="space-y-6">
      {/* Controls */}
      <Card className="border-border/50 bg-card/50 backdrop-blur">
        <CardHeader className="pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <FlaskConical className="h-4 w-4 text-emerald-400" />
            因子研究
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="text-[11px] font-mono text-muted-foreground mb-1 block">幣種</label>
              <select
                value={symbol}
                onChange={e => setSymbol(e.target.value)}
                className="h-9 rounded-md border border-border/50 bg-background px-3 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
              >
                {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-mono text-muted-foreground mb-1 block">時間框架</label>
              <select
                value={interval}
                onChange={e => setInterval(e.target.value)}
                className="h-9 rounded-md border border-border/50 bg-background px-3 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
              >
                {INTERVALS.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[11px] font-mono text-muted-foreground mb-1 block">K 線數量</label>
              <input
                type="number"
                min={500}
                max={3000}
                step={100}
                value={candles}
                onChange={e => setCandles(Number(e.target.value))}
                className="h-9 w-24 rounded-md border border-border/50 bg-background px-3 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="text-[11px] font-mono text-muted-foreground mb-1 block">開始日期</label>
              <input
                type="date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                className="h-9 rounded-md border border-border/50 bg-background px-3 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="text-[11px] font-mono text-muted-foreground mb-1 block">結束日期</label>
              <input
                type="date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="h-9 rounded-md border border-border/50 bg-background px-3 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
              />
            </div>
            <Button
              onClick={handleAnalyze}
              disabled={loading}
              className="bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <FlaskConical className="h-4 w-4 mr-2" />}
              分析
            </Button>
          </div>
          {error && (
            <div className="mt-3 text-sm text-red-400 font-mono">{error}</div>
          )}
        </CardContent>
      </Card>

      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-emerald-400" />
          <span className="ml-3 text-muted-foreground font-mono text-sm">分析因子中...</span>
        </div>
      )}

      {result && !loading && (
        <>
          {/* D. Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="border-border/50 bg-card/50">
              <CardContent className="pt-4 pb-3 text-center">
                <div className="text-2xl font-mono font-bold text-emerald-400">{result.total_factors}</div>
                <div className="text-[11px] text-muted-foreground mt-1">總因子數</div>
              </CardContent>
            </Card>
            <Card className="border-border/50 bg-card/50">
              <CardContent className="pt-4 pb-3 text-center">
                <div className="text-2xl font-mono font-bold text-cyan-400">{result.recommended.length}</div>
                <div className="text-[11px] text-muted-foreground mt-1">推薦因子</div>
              </CardContent>
            </Card>
            <Card className="border-border/50 bg-card/50">
              <CardContent className="pt-4 pb-3">
                <div className="flex flex-wrap justify-center gap-2">
                  {Object.entries(result.grade_distribution).map(([g, n]) => (
                    <Badge key={g} variant="outline" className={`${GRADE_COLORS[g] || ""} font-mono text-xs`}>
                      {g}: {n}
                    </Badge>
                  ))}
                </div>
                <div className="text-[11px] text-muted-foreground mt-2 text-center">評級分佈</div>
              </CardContent>
            </Card>
            <Card className="border-border/50 bg-card/50">
              <CardContent className="pt-4 pb-3 text-center">
                <div className="text-2xl font-mono font-bold text-emerald-400">
                  {result.high_correlations.length}
                </div>
                <div className="text-[11px] text-muted-foreground mt-1">高相關對</div>
              </CardContent>
            </Card>
          </div>

          {/* A. Factor Ranking Table */}
          <Card className="border-border/50 bg-card/50 backdrop-blur">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <TrendingUp className="h-4 w-4 text-emerald-400" />
                因子排名
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border/30">
                      <SortHeader label="#" k="rank" />
                      <SortHeader label="評級" k="grade" />
                      <SortHeader label="因子" k="name" />
                      <SortHeader label="IC 均值" k="ic_mean" />
                      <SortHeader label="IC IR" k="ic_ir" />
                      <SortHeader label="t-stat" k="t_stat" />
                      <SortHeader label="p-value" k="p_value" />
                      <SortHeader label="單調性" k="monotonicity" />
                      <SortHeader label="判定" k="verdict" />
                      <th className="px-3 py-2.5 text-left text-[11px] font-medium text-muted-foreground uppercase tracking-wider">推薦</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedFactors.map((f) => {
                      const isSelected = selectedFactor?.name === f.name;
                      const isRecommended = result.recommended.includes(f.name);
                      return (
                        <tr
                          key={f.name}
                          onClick={() => setSelectedFactor(f)}
                          className={`border-b border-border/20 cursor-pointer transition-colors ${
                            isSelected ? "bg-emerald-500/10" : "hover:bg-muted/30"
                          }`}
                        >
                          <td className="px-3 py-2 text-sm font-mono text-muted-foreground">{f.rank}</td>
                          <td className="px-3 py-2">
                            <Badge variant="outline" className={`${GRADE_COLORS[f.grade] || ""} font-mono text-xs`}>
                              {f.grade}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 text-sm font-medium">{f.name}</td>
                          <td className="px-3 py-2 text-sm font-mono">
                            <span className={f.ic_mean > 0 ? "text-emerald-400" : f.ic_mean < 0 ? "text-red-400" : "text-muted-foreground"}>
                              {f.ic_mean > 0 ? <ArrowUp className="inline h-3 w-3" /> : f.ic_mean < 0 ? <ArrowDown className="inline h-3 w-3" /> : null}
                              {f.ic_mean.toFixed(4)}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-sm font-mono">{f.ic_ir.toFixed(3)}</td>
                          <td className="px-3 py-2 text-sm font-mono">{f.t_stat.toFixed(2)}</td>
                          <td className={`px-3 py-2 text-sm font-mono ${f.p_value < 0.05 ? "text-emerald-400" : "text-muted-foreground"}`}>
                            {f.p_value.toFixed(4)}
                          </td>
                          <td className="px-3 py-2 text-sm font-mono">{f.monotonicity.toFixed(2)}</td>
                          <td className="px-3 py-2 text-sm">{f.verdict}</td>
                          <td className="px-3 py-2 text-center">
                            {isRecommended && <Check className="inline h-4 w-4 text-emerald-400" />}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* B. Decay Curve & Quintile Chart */}
          {selectedFactor && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Card className="border-border/50 bg-card/50 backdrop-blur">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <BarChart3 className="h-4 w-4 text-cyan-400" />
                    IC 衰減曲線 — {selectedFactor.name}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {decayData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={240}>
                      <LineChart data={decayData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border)/0.3)" />
                        <XAxis dataKey="horizon" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} label={{ value: "Horizon", position: "insideBottom", offset: -2, fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                        <Tooltip contentStyle={{ backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                        <Line type="monotone" dataKey="ic" stroke="#10b981" strokeWidth={2} dot={{ r: 3, fill: "#10b981" }} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="text-sm text-muted-foreground text-center py-10">無衰減數據</div>
                  )}
                </CardContent>
              </Card>

              <Card className="border-border/50 bg-card/50 backdrop-blur">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <BarChart3 className="h-4 w-4 text-emerald-400" />
                    分組回測收益 — {selectedFactor.name}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {quintileData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={quintileData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border)/0.3)" />
                        <XAxis dataKey="group" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${(v * 100).toFixed(1)}%`} />
                        <Tooltip contentStyle={{ backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} formatter={(v) => `${(Number(v) * 100).toFixed(2)}%`} />
                        <Bar dataKey="ret" radius={[4, 4, 0, 0]}>
                          {quintileData.map((d, i) => (
                            <Cell key={i} fill={d.ret >= 0 ? "#10b981" : "#ef4444"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="text-sm text-muted-foreground text-center py-10">無分組數據</div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {/* C. Correlation List */}
          {result.high_correlations.length > 0 && (
            <Card className="border-border/50 bg-card/50 backdrop-blur">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Link2 className="h-4 w-4 text-orange-400" />
                  高相關因子對（|r| ≥ 0.5）
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                  {result.high_correlations.map((c, i) => (
                    <div
                      key={i}
                      className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm font-mono ${corrColor(c.corr)}`}
                    >
                      <span className="truncate mr-2">{c.a} ↔ {c.b}</span>
                      <span className="font-bold whitespace-nowrap">{c.corr.toFixed(3)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
