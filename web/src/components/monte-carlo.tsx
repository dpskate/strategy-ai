"use client";

import { useState } from "react";
import { api, MonteCarloResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, ChevronDown, ChevronUp, Dice5 } from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
} from "recharts";

interface MonteCarloProps {
  code: string;
  symbol?: string;
  interval?: string;
  candles?: number;
  stopLoss?: number;
  takeProfit?: number;
  startDate?: string;
  endDate?: string;
}

export function MonteCarloButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      size="sm"
      variant="outline"
      className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
      onClick={onClick}
    >
      <Dice5 className="h-3 w-3 mr-1" />
      蒙地卡羅
    </Button>
  );
}

function buildHistogram(data: number[], bins: number) {
  if (!data.length) return [];
  const min = data[0];
  const max = data[data.length - 1];
  const range = max - min || 1;
  const step = range / bins;
  const hist: { label: string; count: number; from: number; to: number }[] = [];
  for (let i = 0; i < bins; i++) {
    const from = min + step * i;
    const to = min + step * (i + 1);
    hist.push({
      label: `${from.toFixed(1)}`,
      count: 0,
      from,
      to,
    });
  }
  for (const v of data) {
    let idx = Math.floor((v - min) / step);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    hist[idx].count++;
  }
  return hist;
}

export function MonteCarloPanel({
  code, symbol, interval, candles, stopLoss = 2, takeProfit = 4,
  startDate, endDate, onClose,
}: MonteCarloProps & { onClose: () => void }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MonteCarloResult | null>(null);
  const [error, setError] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [sims, setSims] = useState(1000);

  const run = async () => {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await api.monteCarlo({
        code,
        symbol,
        interval,
        candles,
        stop_loss_pct: stopLoss,
        take_profit_pct: takeProfit,
        n_simulations: sims,
        ...(startDate ? { start_date: startDate } : {}),
        ...(endDate ? { end_date: endDate } : {}),
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "蒙地卡羅模擬失敗");
    } finally {
      setLoading(false);
    }
  };

  const roiHist = result ? buildHistogram(result.distribution, 20) : [];
  const ddHist = result ? buildHistogram(result.drawdown_distribution, 20) : [];

  return (
    <Card className="border-amber-500/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Dice5 className="h-4 w-4 text-amber-400" />
            蒙地卡羅模擬
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
                <label className="text-xs text-muted-foreground">模擬次數</label>
                <select
                  value={sims}
                  onChange={(e) => setSims(+e.target.value)}
                  className="w-full mt-1 px-3 py-2 rounded-md border bg-background text-sm"
                >
                  <option value={500}>500 次（快速）</option>
                  <option value={1000}>1,000 次（標準）</option>
                  <option value={3000}>3,000 次（精確）</option>
                  <option value={5000}>5,000 次（高精度）</option>
                </select>
              </div>
              <Button
                onClick={run}
                disabled={loading}
                className="w-full bg-amber-600 hover:bg-amber-500"
              >
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    模擬中...
                  </>
                ) : (
                  <>
                    <Dice5 className="mr-2 h-4 w-4" />
                    開始模擬（{sims.toLocaleString()} 次）
                  </>
                )}
              </Button>
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          {result && (
            <div className="space-y-4">
              {/* Profit probability circle */}
              <div className="flex items-center gap-6">
                <div className="relative w-24 h-24 flex-shrink-0">
                  <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                    <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="6" className="text-muted/30" />
                    <circle
                      cx="50" cy="50" r="42" fill="none" strokeWidth="6"
                      strokeDasharray={`${2 * Math.PI * 42}`}
                      strokeDashoffset={`${2 * Math.PI * 42 * (1 - result.p_profit)}`}
                      strokeLinecap="round"
                      className={
                        result.p_profit >= 0.7 ? "text-emerald-500"
                          : result.p_profit >= 0.5 ? "text-yellow-500"
                            : "text-red-500"
                      }
                      stroke="currentColor"
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className={`text-xl font-bold ${
                      result.p_profit >= 0.7 ? "text-emerald-400"
                        : result.p_profit >= 0.5 ? "text-yellow-400"
                          : "text-red-400"
                    }`}>
                      {(result.p_profit * 100).toFixed(0)}%
                    </span>
                    <span className="text-[10px] text-muted-foreground">盈利機率</span>
                  </div>
                </div>
                <div className="space-y-1.5 text-sm">
                  <p className="font-medium">
                    蒙地卡羅結果
                    <Badge variant="outline" className={`ml-2 text-xs ${
                      result.p_profit >= 0.7 ? "text-emerald-400 border-emerald-400/30"
                        : result.p_profit >= 0.5 ? "text-yellow-400 border-yellow-400/30"
                          : "text-red-400 border-red-400/30"
                    }`}>
                      {result.p_profit >= 0.8 ? "穩健" : result.p_profit >= 0.6 ? "尚可" : result.p_profit >= 0.4 ? "風險偏高" : "高風險"}
                    </Badge>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    隨機打亂 {result.distribution.length.toLocaleString()} 次交易順序的表現分佈
                  </p>
                </div>
              </div>

              {/* Key stats */}
              <div className="grid grid-cols-4 gap-2 text-center">
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-[10px] text-muted-foreground">中位數 ROI</p>
                  <p className={`text-sm font-bold ${result.median_roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {result.median_roi > 0 ? "+" : ""}{result.median_roi}%
                  </p>
                </div>
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-[10px] text-muted-foreground">最差 5%</p>
                  <p className={`text-sm font-bold ${result.worst_roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {result.worst_roi > 0 ? "+" : ""}{result.worst_roi}%
                  </p>
                </div>
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-[10px] text-muted-foreground">最好 5%</p>
                  <p className="text-sm font-bold text-emerald-400">
                    +{result.best_roi}%
                  </p>
                </div>
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-[10px] text-muted-foreground">破產機率</p>
                  <p className={`text-sm font-bold ${result.ruin_probability > 0.05 ? "text-red-400" : result.ruin_probability > 0 ? "text-yellow-400" : "text-emerald-400"}`}>
                    {(result.ruin_probability * 100).toFixed(1)}%
                  </p>
                </div>
              </div>

              {/* ROI distribution histogram */}
              <div>
                <p className="text-xs text-muted-foreground mb-2 font-medium">ROI 分佈</p>
                <div className="h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={roiHist} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 9, fill: "#888" }}
                        interval="preserveStartEnd"
                        tickCount={5}
                      />
                      <YAxis tick={{ fontSize: 9, fill: "#888" }} />
                      <Tooltip
                        contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 12 }}
                        formatter={(v: any) => [`${v} 次`, "頻率"]}
                        labelFormatter={(_label: any, payload: any) => {
                          if (payload?.[0]?.payload) {
                            const p = payload[0].payload as { from: number; to: number };
                            return `ROI: ${p.from.toFixed(1)}% ~ ${p.to.toFixed(1)}%`;
                          }
                          return "";
                        }}
                      />
                      <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                        {roiHist.map((entry, idx) => (
                          <Cell
                            key={idx}
                            fill={entry.from >= 0 ? "rgba(16, 185, 129, 0.7)" : "rgba(239, 68, 68, 0.7)"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Drawdown stats + histogram */}
              <div className="grid grid-cols-2 gap-3 text-center">
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-[10px] text-muted-foreground">中位數回撤</p>
                  <p className={`text-sm font-bold ${result.median_drawdown < 15 ? "text-emerald-400" : result.median_drawdown < 30 ? "text-yellow-400" : "text-red-400"}`}>
                    {result.median_drawdown}%
                  </p>
                </div>
                <div className="bg-muted/50 rounded-lg p-2">
                  <p className="text-[10px] text-muted-foreground">最差 5% 回撤</p>
                  <p className={`text-sm font-bold ${result.worst_drawdown < 20 ? "text-emerald-400" : result.worst_drawdown < 40 ? "text-yellow-400" : "text-red-400"}`}>
                    {result.worst_drawdown}%
                  </p>
                </div>
              </div>

              <div>
                <p className="text-xs text-muted-foreground mb-2 font-medium">回撤分佈</p>
                <div className="h-32">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={ddHist} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 9, fill: "#888" }}
                        interval="preserveStartEnd"
                        tickCount={5}
                      />
                      <YAxis tick={{ fontSize: 9, fill: "#888" }} />
                      <Tooltip
                        contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 12 }}
                        formatter={(v: any) => [`${v} 次`, "頻率"]}
                        labelFormatter={(_label: any, payload: any) => {
                          if (payload?.[0]?.payload) {
                            const p = payload[0].payload as { from: number; to: number };
                            return `回撤: ${p.from.toFixed(1)}% ~ ${p.to.toFixed(1)}%`;
                          }
                          return "";
                        }}
                      />
                      <Bar dataKey="count" radius={[2, 2, 0, 0]} fill="rgba(251, 146, 60, 0.7)" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                className="w-full border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                onClick={() => setResult(null)}
              >
                重新模擬
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
