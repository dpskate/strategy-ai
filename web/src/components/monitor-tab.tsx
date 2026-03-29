"use client";

import { useState, useEffect, useCallback } from "react";
import { api, MonitorStrategy, MonitorCheckResult, MonitorTrendEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Shield, Loader2, Plus, Play, Trash2, Eye, TrendingUp,
  ChevronDown, ChevronUp, AlertTriangle, CheckCircle2, XCircle,
  Activity, Code2,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";

const SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"];
const INTERVALS = [
  { value: "15m", label: "15 分鐘" },
  { value: "1h", label: "1 小時" },
  { value: "4h", label: "4 小時" },
  { value: "1d", label: "1 天" },
];

function statusIcon(status: string) {
  if (status === "active") return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
  if (status === "warning") return <AlertTriangle className="h-4 w-4 text-yellow-400" />;
  return <XCircle className="h-4 w-4 text-red-400" />;
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    warning: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
    stopped: "bg-red-500/15 text-red-400 border-red-500/30",
  };
  return map[status] || map.stopped;
}

export function MonitorTab() {
  const [strategies, setStrategies] = useState<MonitorStrategy[]>([]);
  const [checkResults, setCheckResults] = useState<MonitorCheckResult[] | null>(null);
  const [trendData, setTrendData] = useState<MonitorTrendEntry[]>([]);
  const [trendId, setTrendId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

  // Add form
  const [addName, setAddName] = useState("");
  const [addCode, setAddCode] = useState("");
  const [addSymbol, setAddSymbol] = useState("BTCUSDT");
  const [addInterval, setAddInterval] = useState("4h");
  const [addSl, setAddSl] = useState("2");
  const [addTp, setAddTp] = useState("4");
  const [adding, setAdding] = useState(false);

  const fetchList = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.monitorList();
      setStrategies(res.strategies);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "載入失敗");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchList(); }, [fetchList]);

  const handleCheck = async () => {
    try {
      setChecking(true);
      setError(null);
      const res = await api.monitorCheck();
      setCheckResults(res.results);
      fetchList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "檢查失敗");
    } finally {
      setChecking(false);
    }
  };

  const handleRemove = async (id: string) => {
    try {
      setRemoving(id);
      await api.monitorRemove(id);
      setStrategies((prev) => prev.filter((s) => s.id !== id));
      if (trendId === id) { setTrendId(null); setTrendData([]); }
      if (checkResults) setCheckResults((prev) => prev?.filter((r) => r.id !== id) || null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "移除失敗");
    } finally {
      setRemoving(null);
    }
  };

  const handleViewTrend = async (id: string) => {
    if (trendId === id) { setTrendId(null); setTrendData([]); return; }
    try {
      setTrendId(id);
      const res = await api.monitorTrend(id, 30);
      setTrendData(res.trend);
    } catch {
      setTrendData([]);
    }
  };

  const handleAdd = async () => {
    if (!addName.trim() || !addCode.trim()) return;
    try {
      setAdding(true);
      setError(null);
      await api.monitorAdd({
        name: addName.trim(),
        code: addCode.trim(),
        symbol: addSymbol,
        interval: addInterval,
        stop_loss_pct: parseFloat(addSl) || 2,
        take_profit_pct: parseFloat(addTp) || 4,
      });
      setAddName(""); setAddCode(""); setShowAdd(false);
      fetchList();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加入失敗");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <Shield className="h-5 w-5 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-foreground">策略監控</h2>
            <p className="text-xs text-muted-foreground font-mono">
              {strategies.length} 個策略監控中
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowAdd(!showAdd)}
            className="border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
          >
            {showAdd ? <ChevronUp className="h-4 w-4 mr-1" /> : <Plus className="h-4 w-4 mr-1" />}
            加入策略
          </Button>
          <Button
            size="sm"
            onClick={handleCheck}
            disabled={checking || strategies.length === 0}
            className="bg-emerald-600 hover:bg-emerald-700 text-white"
          >
            {checking ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
            執行檢查
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Add Strategy Form */}
      {showAdd && (
        <Card className="border-emerald-500/20 bg-card/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-emerald-400">加入監控策略</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">策略名稱</label>
              <input
                type="text"
                value={addName}
                onChange={(e) => setAddName(e.target.value)}
                placeholder="例：BTC 動量突破"
                className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">策略代碼</label>
              <textarea
                value={addCode}
                onChange={(e) => setAddCode(e.target.value)}
                placeholder="def strategy(df): ..."
                rows={6}
                className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500/50 resize-y"
              />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">幣種</label>
                <select
                  value={addSymbol}
                  onChange={(e) => setAddSymbol(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
                >
                  {SYMBOLS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">週期</label>
                <select
                  value={addInterval}
                  onChange={(e) => setAddInterval(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
                >
                  {INTERVALS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">止損 %</label>
                <input
                  type="number"
                  value={addSl}
                  onChange={(e) => setAddSl(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">止盈 %</label>
                <input
                  type="number"
                  value={addTp}
                  onChange={(e) => setAddTp(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-500/50"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button size="sm" variant="ghost" onClick={() => setShowAdd(false)}>取消</Button>
              <Button
                size="sm"
                onClick={handleAdd}
                disabled={adding || !addName.trim() || !addCode.trim()}
                className="bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                {adding ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Plus className="h-4 w-4 mr-1" />}
                加入
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mr-2" />
          載入中...
        </div>
      )}

      {/* Empty State */}
      {!loading && strategies.length === 0 && (
        <Card className="border-dashed border-border/50 bg-card/30">
          <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Shield className="h-10 w-10 mb-3 opacity-30" />
            <p className="text-sm">尚無監控策略</p>
            <p className="text-xs mt-1">點擊「加入策略」開始監控</p>
          </CardContent>
        </Card>
      )}

      {/* Strategy Cards */}
      {!loading && strategies.length > 0 && (
        <div className="space-y-3">
          {strategies.map((s) => (
            <Card key={s.id} className="border-border/50 bg-card/50 hover:border-emerald-500/20 transition-colors">
              <CardContent className="p-4">
                {/* Top row */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {statusIcon(s.status)}
                    <span className="font-medium text-sm text-foreground">{s.name}</span>
                    <Badge variant="outline" className={`text-[10px] ${statusBadge(s.status)}`}>
                      {s.status}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-muted-foreground hover:text-foreground"
                      onClick={() => setExpandedCode(expandedCode === s.id ? null : s.id)}
                    >
                      <Code2 className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-muted-foreground hover:text-cyan-400"
                      onClick={() => handleViewTrend(s.id)}
                    >
                      <TrendingUp className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-muted-foreground hover:text-red-400"
                      onClick={() => handleRemove(s.id)}
                      disabled={removing === s.id}
                    >
                      {removing === s.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                </div>

                {/* Info row */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground font-mono mb-3">
                  <span>{s.symbol} · {s.interval}</span>
                  <span>SL {s.sl}% / TP {s.tp}%</span>
                  <span>加入 {new Date(s.added_at).toLocaleDateString("zh-TW")}</span>
                </div>

                {/* Baseline */}
                {s.baseline && (
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                      <div className="text-[10px] text-muted-foreground">Sharpe</div>
                      <div className={`text-sm font-mono font-medium ${s.baseline.sharpe >= 1 ? "text-emerald-400" : s.baseline.sharpe >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                        {s.baseline.sharpe.toFixed(2)}
                      </div>
                    </div>
                    <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                      <div className="text-[10px] text-muted-foreground">ROI</div>
                      <div className={`text-sm font-mono font-medium ${s.baseline.roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {s.baseline.roi.toFixed(1)}%
                      </div>
                    </div>
                    <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                      <div className="text-[10px] text-muted-foreground">勝率</div>
                      <div className="text-sm font-mono font-medium text-foreground">
                        {(s.baseline.win_rate * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                      <div className="text-[10px] text-muted-foreground">回撤</div>
                      <div className={`text-sm font-mono font-medium ${s.baseline.drawdown <= 15 ? "text-emerald-400" : s.baseline.drawdown <= 30 ? "text-yellow-400" : "text-red-400"}`}>
                        {s.baseline.drawdown.toFixed(1)}%
                      </div>
                    </div>
                    <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                      <div className="text-[10px] text-muted-foreground">交易數</div>
                      <div className="text-sm font-mono font-medium text-foreground">
                        {s.baseline.trades}
                      </div>
                    </div>
                  </div>
                )}

                {/* Expanded code */}
                {expandedCode === s.id && (
                  <div className="mt-3">
                    <Separator className="mb-3 opacity-30" />
                    <pre className="text-xs font-mono text-muted-foreground bg-background/50 border border-border/30 rounded-md p-3 overflow-x-auto max-h-48 overflow-y-auto">
                      {s.code}
                    </pre>
                  </div>
                )}

                {/* Trend chart inline */}
                {trendId === s.id && trendData.length > 0 && (
                  <div className="mt-3">
                    <Separator className="mb-3 opacity-30" />
                    <TrendChart data={trendData} />
                  </div>
                )}
                {trendId === s.id && trendData.length === 0 && (
                  <div className="mt-3 text-xs text-muted-foreground text-center py-4">
                    暫無趨勢數據
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Check Results */}
      {checkResults && checkResults.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-cyan-400" />
            <h3 className="text-sm font-medium text-foreground">檢查結果</h3>
            <span className="text-xs text-muted-foreground font-mono">
              {new Date().toLocaleString("zh-TW")}
            </span>
          </div>
          {checkResults.map((r) => (
            <Card key={r.id} className="border-border/50 bg-card/50">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {statusIcon(r.status)}
                    <span className="font-medium text-sm text-foreground">{r.name}</span>
                    <span className="text-xs text-muted-foreground font-mono">{r.symbol} · {r.interval}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {r.wf_robust ? (
                      <Badge variant="outline" className="text-[10px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30">
                        WF 穩健
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-[10px] bg-red-500/15 text-red-400 border-red-500/30">
                        WF 不穩
                      </Badge>
                    )}
                  </div>
                </div>

                {/* Metrics row */}
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-3">
                  <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                    <div className="text-[10px] text-muted-foreground">滾動 Sharpe</div>
                    <div className={`text-sm font-mono font-medium ${r.rolling_sharpe >= 1 ? "text-emerald-400" : r.rolling_sharpe >= 0 ? "text-yellow-400" : "text-red-400"}`}>
                      {r.rolling_sharpe.toFixed(2)}
                    </div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                    <div className="text-[10px] text-muted-foreground">近期勝率</div>
                    <div className="text-sm font-mono font-medium text-foreground">
                      {(r.recent_win_rate * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                    <div className="text-[10px] text-muted-foreground">連虧</div>
                    <div className={`text-sm font-mono font-medium ${r.consec_losses >= 5 ? "text-red-400" : r.consec_losses >= 3 ? "text-yellow-400" : "text-emerald-400"}`}>
                      {r.consec_losses}
                    </div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                    <div className="text-[10px] text-muted-foreground">ROI</div>
                    <div className={`text-sm font-mono font-medium ${r.roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {r.roi.toFixed(1)}%
                    </div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-background/50 border border-border/30">
                    <div className="text-[10px] text-muted-foreground">回撤</div>
                    <div className={`text-sm font-mono font-medium ${r.drawdown <= 15 ? "text-emerald-400" : r.drawdown <= 30 ? "text-yellow-400" : "text-red-400"}`}>
                      {r.drawdown.toFixed(1)}%
                    </div>
                  </div>
                </div>

                {/* Alerts */}
                {r.alerts.length > 0 && (
                  <div className="space-y-1">
                    {r.alerts.map((a, i) => (
                      <div
                        key={i}
                        className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${
                          a.level === "critical"
                            ? "bg-red-500/10 border border-red-500/20 text-red-400"
                            : "bg-yellow-500/10 border border-yellow-500/20 text-yellow-400"
                        }`}
                      >
                        {a.level === "critical" ? "🔴" : "🟡"}
                        <span className="font-mono">[{a.type}]</span>
                        <span>{a.msg}</span>
                      </div>
                    ))}
                  </div>
                )}
                {r.alerts.length === 0 && (
                  <div className="text-xs text-emerald-400/70 flex items-center gap-1">
                    <CheckCircle2 className="h-3 w-3" /> 無警報
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Trend Chart ── */
function TrendChart({ data }: { data: MonitorTrendEntry[] }) {
  const formatted = data.map((d) => ({
    ...d,
    date: new Date(d.timestamp).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" }),
    wr_pct: +(d.recent_wr * 100).toFixed(1),
  }));

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={formatted} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#888" }} />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 10, fill: "#34d399" }}
            label={{ value: "Sharpe", angle: -90, position: "insideLeft", style: { fontSize: 10, fill: "#34d399" } }}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 10, fill: "#22d3ee" }}
            label={{ value: "勝率 %", angle: 90, position: "insideRight", style: { fontSize: 10, fill: "#22d3ee" } }}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "#1a1a2e", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: "#888" }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line yAxisId="left" type="monotone" dataKey="rolling_sharpe" name="Sharpe" stroke="#34d399" strokeWidth={2} dot={false} />
          <Line yAxisId="right" type="monotone" dataKey="wr_pct" name="勝率 %" stroke="#22d3ee" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
