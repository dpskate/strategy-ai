"use client";

import { TradeDetail } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { List, Download } from "lucide-react";

function formatTime(ts: number) {
  if (!ts) return "-";
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

function formatTimeFull(ts: number) {
  if (!ts) return "";
  return new Date(ts).toISOString().slice(0, 19).replace("T", " ");
}

const REASON_MAP: Record<string, string> = {
  signal: "信號",
  stop_loss: "止損",
  take_profit: "止盈",
  timeout: "超時",
};

export function TradeTable({ trades }: { trades: TradeDetail[] }) {
  if (!trades.length) return null;

  const longTrades = trades.filter(t => t.side === "long");
  const shortTrades = trades.filter(t => t.side === "short");
  const longWins = longTrades.filter(t => t.pnl >= 0).length;
  const shortWins = shortTrades.filter(t => t.pnl >= 0).length;

  const exportCsv = () => {
    const header = "編號,方向,進場時間,進場價,出場時間,出場價,盈虧,盈虧%,原因\n";
    const rows = trades.map(t =>
      `${t.id},${t.side === "long" ? "做多" : "做空"},${formatTimeFull(t.entry_time)},${t.entry_price},${formatTimeFull(t.exit_time)},${t.exit_price},${t.pnl.toFixed(2)},${t.pnl_pct},${REASON_MAP[t.exit_reason] || t.exit_reason}`
    ).join("\n");
    const bom = "\uFEFF";
    const blob = new Blob([bom + header + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <List className="h-4 w-4" />
          交易明細（{trades.length} 筆）
          <button
            onClick={exportCsv}
            className="ml-auto text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
            title="匯出 CSV"
          >
            <Download className="h-3 w-3" />
            匯出
          </button>
        </CardTitle>
        <div className="flex gap-3 text-xs text-muted-foreground mt-1">
          {longTrades.length > 0 && (
            <span>
              📈 做多 {longTrades.length} 筆
              <span className={longWins / longTrades.length >= 0.5 ? " text-emerald-400" : " text-red-400"}>
                （勝率 {(longWins / longTrades.length * 100).toFixed(0)}%）
              </span>
            </span>
          )}
          {shortTrades.length > 0 && (
            <span>
              📉 做空 {shortTrades.length} 筆
              <span className={shortWins / shortTrades.length >= 0.5 ? " text-emerald-400" : " text-red-400"}>
                （勝率 {(shortWins / shortTrades.length * 100).toFixed(0)}%）
              </span>
            </span>
          )}
          {longTrades.length === 0 && shortTrades.length > 0 && (
            <span className="text-yellow-400">⚠️ 僅做空，做多條件未觸發</span>
          )}
          {shortTrades.length === 0 && longTrades.length > 0 && (
            <span className="text-yellow-400">⚠️ 僅做多，做空條件未觸發</span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="text-muted-foreground text-xs border-b">
                <th className="text-left py-2 px-2">#</th>
                <th className="text-left py-2 px-2">方向</th>
                <th className="text-left py-2 px-2">進場時間</th>
                <th className="text-right py-2 px-2">進場價</th>
                <th className="text-left py-2 px-2">出場時間</th>
                <th className="text-right py-2 px-2">出場價</th>
                <th className="text-right py-2 px-2">盈虧</th>
                <th className="text-right py-2 px-2">盈虧%</th>
                <th className="text-left py-2 px-2">原因</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b border-border/30 hover:bg-muted/30">
                  <td className="py-1.5 px-2 text-muted-foreground">{t.id}</td>
                  <td className="py-1.5 px-2">
                    <Badge variant={t.side === "long" ? "default" : "destructive"} className="text-xs">
                      {t.side === "long" ? "做多" : "做空"}
                    </Badge>
                  </td>
                  <td className="py-1.5 px-2 text-xs">{formatTime(t.entry_time)}</td>
                  <td className="py-1.5 px-2 text-right font-mono">${t.entry_price.toLocaleString()}</td>
                  <td className="py-1.5 px-2 text-xs">{formatTime(t.exit_time)}</td>
                  <td className="py-1.5 px-2 text-right font-mono">${t.exit_price.toLocaleString()}</td>
                  <td className={`py-1.5 px-2 text-right font-mono ${t.pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {t.pnl >= 0 ? "+" : ""}{t.pnl.toFixed(2)}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-mono ${t.pnl_pct >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct}%
                  </td>
                  <td className="py-1.5 px-2 text-xs text-muted-foreground">
                    {REASON_MAP[t.exit_reason] || t.exit_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
