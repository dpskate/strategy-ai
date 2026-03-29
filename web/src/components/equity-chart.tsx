"use client";

import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function EquityChart({ data }: { data: number[] }) {
  const chartData = data.map((v, i) => ({ bar: i, equity: Math.round(v * 100) / 100 }));
  const min = Math.min(...data) * 0.998;
  const max = Math.max(...data) * 1.002;
  const isProfit = data[data.length - 1] >= data[0];
  const initial = data[0];

  // Calculate max drawdown point
  let peak = data[0];
  let maxDd = 0;
  let maxDdIdx = 0;
  for (let i = 1; i < data.length; i++) {
    if (data[i] > peak) peak = data[i];
    const dd = (peak - data[i]) / peak;
    if (dd > maxDd) { maxDd = dd; maxDdIdx = i; }
  }

  return (
    <Card className="card-glow">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center justify-between">
          資金曲線
          <span className="text-xs font-normal text-muted-foreground">
            最大回撤 {(maxDd * 100).toFixed(1)}%
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[250px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={isProfit ? "#22c55e" : "#ef4444"} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={isProfit ? "#22c55e" : "#ef4444"} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="bar" hide />
              <YAxis domain={[min, max]} hide />
              <Tooltip
                contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8 }}
                labelStyle={{ color: "#888" }}
                formatter={(v: number | undefined) => [`$${(v ?? 0).toLocaleString()}`, "資金"]}
              />
              <ReferenceLine y={initial} stroke="#555" strokeDasharray="4 4" strokeWidth={1} />
              <Area
                type="monotone"
                dataKey="equity"
                stroke={isProfit ? "#22c55e" : "#ef4444"}
                fill="url(#eqGrad)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
