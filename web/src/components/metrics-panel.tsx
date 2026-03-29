"use client";

import { Metrics, RollingWfResult, DeflatedSharpeResult } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import {
  TrendingUp,
  TrendingDown,
  BarChart3,
  Target,
  Shield,
  Zap,
  Clock,
  Trophy,
} from "lucide-react";

// ── Rating thresholds ──
type Level = "good" | "ok" | "bad";

function rateMetric(key: string, value: number): Level {
  switch (key) {
    case "roi_pct":
      return value >= 10 ? "good" : value >= 0 ? "ok" : "bad";
    case "win_rate":
      return value >= 50 ? "good" : value >= 35 ? "ok" : "bad";
    case "profit_factor":
      return value >= 1.5 ? "good" : value >= 1.0 ? "ok" : "bad";
    case "sharpe_ratio":
      return value >= 1.0 ? "good" : value >= 0.3 ? "ok" : "bad";
    case "max_drawdown_pct":
      return value <= 10 ? "good" : value <= 25 ? "ok" : "bad";
    case "avg_rr":
      return value >= 1.5 ? "good" : value >= 1.0 ? "ok" : "bad";
    case "total_trades":
      return value >= 30 ? "good" : value >= 10 ? "ok" : "bad";
    default:
      return "ok";
  }
}

const levelColor: Record<Level, string> = {
  good: "text-emerald-400",
  ok: "text-amber-400",
  bad: "text-red-400",
};

const levelGlow: Record<Level, string> = {
  good: "shadow-emerald-500/20",
  ok: "shadow-amber-500/20",
  bad: "shadow-red-500/20",
};

const levelBorder: Record<Level, string> = {
  good: "border-emerald-500/30",
  ok: "border-amber-500/30",
  bad: "border-red-500/30",
};

const levelIconBg: Record<Level, string> = {
  good: "bg-emerald-500/20 text-emerald-400",
  ok: "bg-amber-500/20 text-amber-400",
  bad: "bg-red-500/20 text-red-400",
};

function StatCard({
  label,
  value,
  icon: Icon,
  level,
  hint,
  large,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  level: Level;
  hint: string;
  large?: boolean;
}) {
  return (
    <div className={`relative group p-4 rounded-xl border ${levelBorder[level]} bg-card shadow-lg ${levelGlow[level]} transition-all duration-200 hover:scale-[1.02]`}>
      <div className="flex items-start justify-between mb-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
        <div className={`p-1.5 rounded-lg ${levelIconBg[level]}`}>
          <Icon className="h-3.5 w-3.5" />
        </div>
      </div>
      <p className={`${large ? "text-3xl" : "text-2xl"} font-bold tracking-tight ${levelColor[level]}`}>
        {value}
      </p>
      {/* Tooltip */}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-1.5 rounded-lg bg-popover border text-xs text-popover-foreground whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 shadow-xl">
        {hint}
      </div>
    </div>
  );
}

// ── Overall grade ──
type Grade = "A" | "B" | "C" | "D" | "F";

interface GradeResult {
  grade: Grade;
  score: number;
  summary: string;
  details: string[];
}

export function gradeStrategy(m: Metrics, wf?: { overfit_ratio: number; test_roi: number }): GradeResult {
  let score = 50;
  const details: string[] = [];

  // ROI — 核心指標，權重拉高
  if (m.roi_pct >= 20) { score += 15; details.push("✅ 投報率優秀"); }
  else if (m.roi_pct >= 5) { score += 10; details.push("✅ 投報率正向"); }
  else if (m.roi_pct >= 2) { score += 5; }
  else if (m.roi_pct >= 0) { score -= 5; details.push("⚠️ 投報率偏低"); }
  else { score -= 15; details.push("❌ 策略虧損"); }

  // 勝率 — 太低的要重罰
  if (m.win_rate >= 55) { score += 10; details.push("✅ 勝率高"); }
  else if (m.win_rate >= 40) { score += 3; }
  else if (m.win_rate >= 30) { score -= 5; details.push("⚠️ 勝率偏低"); }
  else { score -= 15; details.push("❌ 勝率過低（< 30%）"); }

  if (m.profit_factor >= 2.0) { score += 15; details.push("✅ 利潤因子優秀"); }
  else if (m.profit_factor >= 1.3) { score += 8; }
  else if (m.profit_factor >= 1.0) { score += 0; details.push("⚠️ 利潤因子勉強"); }
  else { score -= 15; details.push("❌ 利潤因子 < 1（虧多賺少）"); }

  if (m.sharpe_ratio >= 1.5) { score += 10; details.push("✅ 風險調整報酬優秀"); }
  else if (m.sharpe_ratio >= 0.5) { score += 5; }
  else { score -= 5; details.push("⚠️ 夏普比率偏低"); }

  if (m.max_drawdown_pct <= 10) { score += 10; details.push("✅ 回撤控制良好"); }
  else if (m.max_drawdown_pct <= 20) { score += 3; }
  else { score -= 10; details.push("❌ 最大回撤過大"); }

  if (m.total_trades >= 30) { score += 5; }
  else if (m.total_trades >= 10) { score += 0; details.push("⚠️ 交易次數偏少，統計意義有限"); }
  else { score -= 10; details.push("❌ 交易次數太少，結果不可靠"); }

  if (m.avg_rr >= 2.0) { score += 8; details.push("✅ 盈虧比優秀"); }
  else if (m.avg_rr >= 1.0) { score += 3; }
  else { score -= 5; details.push("⚠️ 盈虧比偏低"); }

  // Walk-forward — 看過擬合比 + 測試集實際表現
  if (wf) {
    if (wf.overfit_ratio >= 999) { score -= 20; details.push("❌ 嚴重過擬合（測試集虧損）"); }
    else if (wf.overfit_ratio > 3) { score -= 10; details.push("⚠️ 過擬合風險高"); }
    else if (wf.overfit_ratio <= 2 && wf.test_roi > 0) { score += 10; details.push("✅ 前推驗證通過"); }
    else if (wf.overfit_ratio <= 2 && wf.test_roi <= 0) { score += 0; details.push("⚠️ 過擬合比低但測試集未獲利"); }
  }

  // Long/Short balance — 雙向策略但只做單邊
  const longT = m.long_trades ?? 0;
  const shortT = m.short_trades ?? 0;
  if (longT > 0 && shortT > 0) {
    const ratio = Math.min(longT, shortT) / Math.max(longT, shortT);
    if (ratio < 0.1) { score -= 10; details.push("⚠️ 多空嚴重失衡（一邊 < 10%）"); }
    else if (ratio < 0.25) { score -= 5; details.push("⚠️ 多空比例不均"); }
  } else if (longT + shortT >= 10 && (longT === 0 || shortT === 0)) {
    details.push(`⚠️ 純${longT === 0 ? "做空" : "做多"}策略（無${longT === 0 ? "多" : "空"}單）`);
  }

  score = Math.max(0, Math.min(100, score));

  let grade: Grade;
  let summary: string;
  if (score >= 80) { grade = "A"; summary = "優秀策略，可考慮實盤測試"; }
  else if (score >= 65) { grade = "B"; summary = "不錯，但有改進空間"; }
  else if (score >= 50) { grade = "C"; summary = "一般，建議優化後再用"; }
  else if (score >= 35) { grade = "D"; summary = "偏弱，不建議直接使用"; }
  else { grade = "F"; summary = "不可用，需要重新設計"; }

  return { grade, score, summary, details };
}

const gradeConfig: Record<Grade, { gradient: string; bg: string; ring: string; glow: string }> = {
  A: {
    gradient: "from-emerald-400 to-cyan-300",
    bg: "bg-emerald-500/10",
    ring: "ring-emerald-500/30",
    glow: "shadow-[0_0_60px_oklch(0.72_0.19_165/0.15)]",
  },
  B: {
    gradient: "from-blue-400 to-cyan-400",
    bg: "bg-blue-500/10",
    ring: "ring-blue-500/30",
    glow: "shadow-[0_0_60px_oklch(0.65_0.19_250/0.15)]",
  },
  C: {
    gradient: "from-amber-400 to-yellow-300",
    bg: "bg-amber-500/10",
    ring: "ring-amber-500/30",
    glow: "shadow-[0_0_60px_oklch(0.75_0.15_80/0.15)]",
  },
  D: {
    gradient: "from-orange-400 to-red-400",
    bg: "bg-orange-500/10",
    ring: "ring-orange-500/30",
    glow: "shadow-[0_0_60px_oklch(0.65_0.2_40/0.15)]",
  },
  F: {
    gradient: "from-red-500 to-rose-400",
    bg: "bg-red-500/10",
    ring: "ring-red-500/30",
    glow: "shadow-[0_0_60px_oklch(0.55_0.25_25/0.2)]",
  },
};

export function MetricsPanel({
  metrics,
  walkForward,
  rollingWf,
  deflatedSharpe,
}: {
  metrics: Metrics;
  walkForward?: { overfit_ratio: number; test_roi: number };
  rollingWf?: RollingWfResult;
  deflatedSharpe?: DeflatedSharpeResult;
}) {
  const isProfit = metrics.roi_pct >= 0;
  const { grade, score, summary, details } = gradeStrategy(metrics, walkForward);
  const gc = gradeConfig[grade];

  return (
    <div className="space-y-6">
      {/* ── Grade + ROI hero ── */}
      <div className={`rounded-2xl ${gc.bg} ring-1 ${gc.ring} ${gc.glow} p-6`}>
        <div className="flex items-center gap-6">
          {/* Grade badge */}
          <div className="flex-shrink-0">
            <div className={`w-20 h-20 rounded-2xl bg-gradient-to-br ${gc.gradient} flex items-center justify-center shadow-2xl`}>
              <span className="text-4xl font-black text-black/80">{grade}</span>
            </div>
            <div className="text-center mt-2">
              <span className="text-xs font-mono text-muted-foreground">{score}/100</span>
            </div>
          </div>

          {/* ROI + summary */}
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">投報率</p>
            <p className={`text-5xl font-black tracking-tighter ${isProfit ? "text-emerald-400" : "text-red-400"}`}>
              {isProfit ? "+" : ""}{metrics.roi_pct}%
            </p>
            <p className="text-sm text-muted-foreground mt-2">{summary}</p>
          </div>

          {/* Capital */}
          <div className="hidden md:block text-right flex-shrink-0">
            <p className="text-xs text-muted-foreground mb-1">資金變化</p>
            <p className="text-lg font-mono text-muted-foreground">
              ${metrics.initial_capital?.toLocaleString()}
            </p>
            <p className="text-xs text-muted-foreground my-0.5">→</p>
            <p className={`text-lg font-mono font-bold ${isProfit ? "text-emerald-400" : "text-red-400"}`}>
              ${metrics.final_capital?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>

        {/* Details */}
        {details.length > 0 && (
          <div className="mt-4 pt-4 border-t border-border/30 flex flex-wrap gap-x-4 gap-y-1">
            {details.map((d, i) => (
              <span key={i} className="text-xs text-muted-foreground">{d}</span>
            ))}
          </div>
        )}
      </div>

      {/* ── Metrics grid ── */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard
          label="勝率"
          value={`${metrics.win_rate}%`}
          icon={Target}
          level={rateMetric("win_rate", metrics.win_rate)}
          hint="≥50% 優 | 35-50% 普通 | <35% 差"
          large
        />
        <StatCard
          label="利潤因子"
          value={metrics.profit_factor >= 9999 ? "∞" : `${metrics.profit_factor}`}
          icon={Zap}
          level={rateMetric("profit_factor", metrics.profit_factor)}
          hint="≥1.5 優 | 1.0-1.5 普通 | <1.0 虧損"
          large
        />
        <StatCard
          label="夏普比率"
          value={`${metrics.sharpe_ratio}`}
          icon={TrendingUp}
          level={rateMetric("sharpe_ratio", metrics.sharpe_ratio)}
          hint="≥1.0 優 | 0.3-1.0 普通 | <0.3 差"
          large
        />
        <StatCard
          label="最大回撤"
          value={`${metrics.max_drawdown_pct}%`}
          icon={Shield}
          level={rateMetric("max_drawdown_pct", metrics.max_drawdown_pct)}
          hint="≤10% 優 | 10-25% 普通 | >25% 危險"
        />
        <StatCard
          label="盈虧比"
          value={metrics.avg_rr >= 9999 ? "∞" : `${metrics.avg_rr}`}
          icon={isProfit ? TrendingUp : TrendingDown}
          level={rateMetric("avg_rr", metrics.avg_rr)}
          hint="≥1.5 優 | 1.0-1.5 普通 | <1.0 差"
        />
        <StatCard
          label="交易次數"
          value={`${metrics.total_trades}`}
          icon={BarChart3}
          level={rateMetric("total_trades", metrics.total_trades)}
          hint="≥30 可靠 | 10-30 偏少 | <10 不可靠"
        />
      </div>
      {/* ── Secondary metrics ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {metrics.sortino_ratio !== undefined && (
          <div className="p-3 rounded-lg border border-border/30 bg-card">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Sortino</p>
            <p className={`text-lg font-bold ${metrics.sortino_ratio >= 1.5 ? "text-emerald-400" : metrics.sortino_ratio >= 0.5 ? "text-amber-400" : "text-red-400"}`}>
              {metrics.sortino_ratio >= 9999 ? "∞" : metrics.sortino_ratio.toFixed(2)}
            </p>
          </div>
        )}
        {metrics.max_consec_wins !== undefined && (
          <div className="p-3 rounded-lg border border-border/30 bg-card">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">最大連勝/連虧</p>
            <p className="text-lg font-bold">
              <span className="text-emerald-400">{metrics.max_consec_wins}</span>
              <span className="text-muted-foreground mx-1">/</span>
              <span className="text-red-400">{metrics.max_consec_losses ?? 0}</span>
            </p>
          </div>
        )}
        {metrics.avg_hold_hours !== undefined && (
          <div className="p-3 rounded-lg border border-border/30 bg-card">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">平均持倉</p>
            <p className="text-lg font-bold text-foreground">
              {metrics.avg_hold_hours < 1 ? `${Math.round(metrics.avg_hold_hours * 60)}m` : metrics.avg_hold_hours < 24 ? `${metrics.avg_hold_hours.toFixed(1)}h` : `${(metrics.avg_hold_hours / 24).toFixed(1)}d`}
            </p>
          </div>
        )}
        {metrics.total_fees !== undefined && metrics.total_fees > 0 && (
          <div className="p-3 rounded-lg border border-border/30 bg-card">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">總手續費</p>
            <p className="text-lg font-bold text-amber-400">${metrics.total_fees.toFixed(2)}</p>
          </div>
        )}
      </div>
      {/* Long/Short breakdown */}
      {((metrics.long_trades ?? 0) > 0 || (metrics.short_trades ?? 0) > 0) && (
        <div className="mt-2 px-1">
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span>📈 做多 {metrics.long_trades ?? 0} 筆{(metrics.long_trades ?? 0) > 0 ? `（勝率 ${metrics.long_win_rate}%）` : ""}</span>
            <span>📉 做空 {metrics.short_trades ?? 0} 筆{(metrics.short_trades ?? 0) > 0 ? `（勝率 ${metrics.short_win_rate}%）` : ""}</span>
          </div>
          {(() => {
            const lt = metrics.long_trades ?? 0;
            const st = metrics.short_trades ?? 0;
            const total = lt + st;
            if (total < 2) return null;
            const ratio = Math.min(lt, st) / Math.max(lt, st);
            if (lt === 0 || st === 0) return (
              <p className="text-[10px] text-amber-400 mt-1">⚠ 純{lt === 0 ? "做空" : "做多"}策略，無法驗證雙向表現</p>
            );
            if (ratio < 0.1) return (
              <p className="text-[10px] text-red-400 mt-1">🚨 多空嚴重失衡（{Math.round(Math.min(lt, st) / total * 100)}% vs {Math.round(Math.max(lt, st) / total * 100)}%）</p>
            );
            if (ratio < 0.25) return (
              <p className="text-[10px] text-amber-400 mt-1">⚠ 多空比例不均（{Math.round(Math.min(lt, st) / total * 100)}% vs {Math.round(Math.max(lt, st) / total * 100)}%）</p>
            );
            return null;
          })()}
        </div>
      )}

      {/* ── Rolling Walk-Forward ── */}
      {rollingWf && rollingWf.splits.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">滾動 Walk-Forward 驗證</p>
          <div className="space-y-1.5">
            {rollingWf.splits.map((s) => (
              <div key={s.split} className="flex items-center gap-2 text-xs font-mono">
                <span className="text-muted-foreground w-8">#{s.split}</span>
                <span className={`w-20 text-right ${s.train_roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {s.train_roi >= 0 ? "+" : ""}{s.train_roi.toFixed(1)}%
                </span>
                <span className="text-muted-foreground">→</span>
                <span className={`w-20 text-right font-bold ${s.test_roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {s.test_roi >= 0 ? "+" : ""}{s.test_roi.toFixed(1)}%
                </span>
                <span className="text-muted-foreground text-[10px] ml-1">
                  ({s.test_trades} 筆)
                </span>
                <div className={`ml-auto w-2 h-2 rounded-full ${s.test_roi > 0 ? "bg-emerald-400" : "bg-red-400"}`} />
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 pt-2 border-t border-border/30 text-xs">
            <span className="text-muted-foreground">
              一致性 <span className={`font-bold ${rollingWf.consistency >= 0.6 ? "text-emerald-400" : "text-red-400"}`}>
                {(rollingWf.consistency * 100).toFixed(0)}%
              </span>
            </span>
            <span className="text-muted-foreground">
              平均測試 ROI <span className={`font-bold ${rollingWf.avg_test_roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {rollingWf.avg_test_roi >= 0 ? "+" : ""}{rollingWf.avg_test_roi.toFixed(1)}%
              </span>
            </span>
            <span className="text-muted-foreground">
              最差 <span className="font-bold text-red-400">{rollingWf.worst_test_roi.toFixed(1)}%</span>
            </span>
            <span className={`font-bold ${rollingWf.robust ? "text-emerald-400" : "text-red-400"}`}>
              {rollingWf.robust ? "✅ 穩健" : "⚠️ 不穩健"}
            </span>
          </div>
        </div>
      )}

      {/* ── Deflated Sharpe Ratio ── */}
      {deflatedSharpe && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Deflated Sharpe Ratio</p>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs">
            <div>
              <span className="text-muted-foreground">原始 Sharpe </span>
              <span className="font-bold text-foreground">{metrics.sharpe_ratio}</span>
            </div>
            <div>
              <span className="text-muted-foreground">校正後 </span>
              <span className={`font-bold ${deflatedSharpe.significant ? "text-emerald-400" : "text-red-400"}`}>
                {deflatedSharpe.deflated_sharpe.toFixed(2)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">p-value </span>
              <span className={`font-bold ${deflatedSharpe.p_value < 0.05 ? "text-emerald-400" : "text-red-400"}`}>
                {deflatedSharpe.p_value.toFixed(4)}
              </span>
              {deflatedSharpe.p_value < 0.05
                ? <span className="ml-1 text-emerald-400">✓ 顯著</span>
                : <span className="ml-1 text-red-400">✗ 不顯著</span>
              }
            </div>
            {deflatedSharpe.haircut_pct > 0 && (
              <div>
                <span className="text-muted-foreground">Haircut </span>
                <span className="font-bold text-amber-400">{deflatedSharpe.haircut_pct.toFixed(1)}%</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
