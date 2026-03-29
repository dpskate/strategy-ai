const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100";

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.message || "API Error");
  }
  return res.json();
}

export interface Metrics {
  total_trades: number;
  win_rate: number;
  roi_pct: number;
  profit_factor: number;
  sharpe_ratio: number;
  sortino_ratio?: number;
  max_drawdown_pct: number;
  avg_rr: number;
  initial_capital: number;
  final_capital: number;
  total_profit: number;
  avg_win: number;
  avg_loss: number;
  best_trade: number;
  worst_trade: number;
  total_fees?: number;
  long_trades?: number;
  short_trades?: number;
  long_win_rate?: number;
  short_win_rate?: number;
  max_consec_wins?: number;
  max_consec_losses?: number;
  avg_hold_hours?: number;
  error?: string;
}

export interface TradeDetail {
  id: number;
  side: string;
  entry_time: number;
  entry_price: number;
  exit_time: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
}

export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface RollingWfSplit {
  split: number;
  train_start: number;
  train_end: number;
  test_start: number;
  test_end: number;
  train_roi: number;
  test_roi: number;
  train_sharpe: number;
  test_sharpe: number;
  train_trades: number;
  test_trades: number;
  overfit_ratio: number;
}

export interface RollingWfResult {
  splits: RollingWfSplit[];
  avg_test_roi: number;
  avg_overfit_ratio: number;
  consistency: number;
  worst_test_roi: number;
  best_test_roi: number;
  robust: boolean;
}

export interface DeflatedSharpeResult {
  deflated_sharpe: number;
  p_value: number;
  significant: boolean;
  haircut_pct: number;
}

export interface BacktestResult {
  metrics: Metrics;
  walk_forward: { train_roi: number; test_roi: number; overfit_ratio: number };
  rolling_wf?: RollingWfResult;
  deflated_sharpe?: DeflatedSharpeResult;
  trades: number;
  trade_list: TradeDetail[];
  candle_data: CandleData[];
  equity_curve: number[];
  report: string;
}

export interface ResearchResult {
  rank: number;
  score: number;
  description: string;
  metrics: Metrics;
  code: string;
  walk_forward?: { train_roi: number; test_roi: number; overfit_ratio: number };
  rolling_wf?: RollingWfResult;
  deflated_sharpe?: DeflatedSharpeResult;
  dna?: {
    entry_genes: [string, Record<string, number>][];
    exit_gene: string;
    sl: number;
    tp: number;
  };
  pareto_front?: boolean;
  convergence?: { trial: number; best_score: number }[];
}

export interface ResearchJob {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  results?: ResearchResult[];
  error?: string;
  params?: Record<string, unknown>;
  progress?: { current: number; total: number; valid: number; population: number };
  pareto_data?: { roi: number; sharpe: number; drawdown: number; pareto: boolean }[];
  method?: string;
}

export interface CrossValidateEntry {
  symbol: string;
  interval: string;
  metrics: Metrics | null;
  walk_forward: { train_roi: number; test_roi: number; overfit_ratio: number } | null;
  trades: number;
  error: string | null;
}

export interface CrossValidateSummary {
  total_combinations: number;
  profitable: number;
  avg_roi: number;
  avg_win_rate: number;
  avg_sharpe: number;
  worst_drawdown: number;
  consistency_score: number;
}

export interface CrossValidateResult {
  results: CrossValidateEntry[];
  summary: CrossValidateSummary;
}

export interface MonteCarloResult {
  median_roi: number;
  mean_roi: number;
  worst_roi: number;
  best_roi: number;
  p_profit: number;
  median_drawdown: number;
  worst_drawdown: number;
  ruin_probability: number;
  distribution: number[];
  drawdown_distribution: number[];
}

// Factor Research
export interface FactorAnalysis {
  name: string;
  ic_mean: number;
  ic_std: number;
  ic_ir: number;
  t_stat: number;
  p_value: number;
  decay_curve: Record<number, number>;
  quintile_returns: number[];
  monotonicity: number;
  spread: number;
  grade: string;
  verdict: string;
  n_valid: number;
}

export interface FactorAnalysisResult {
  factors: FactorAnalysis[];
  recommended: string[];
  high_correlations: { a: string; b: string; corr: number }[];
  total_factors: number;
  grade_distribution: Record<string, number>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  backtest: (params: {
    code: string;
    symbol?: string;
    interval?: string;
    candles?: number;
    stop_loss_pct?: number;
    take_profit_pct?: number;
    commission_pct?: number;
    slippage_pct?: number;
    initial_capital?: number;
    position_size_pct?: number;
    start_date?: string;
    end_date?: string;
  }) => request<BacktestResult>("/api/backtest", { method: "POST", body: JSON.stringify(params) }),

  presets: () => request<Record<string, { code: string }>>("/api/presets"),

  startResearch: (params: {
    symbol?: string;
    interval?: string;
    candles?: number;
    generations?: number;
    population_size?: number;
    top_k?: number;
    direction?: "both" | "long" | "short";
    allowed_entry?: string[];
    allowed_exit?: string[];
    custom_genes?: Record<string, unknown>[];
    start_date?: string;
    end_date?: string;
  }) => request<{ job_id: string; status: string }>("/api/research", { method: "POST", body: JSON.stringify(params) }),

  getResearch: (jobId: string) => request<ResearchJob>(`/api/research/${jobId}`),

  validate: (params: { code: string; symbol?: string; interval?: string; candles?: number }) =>
    request<{ train: Metrics; test: Metrics; overfit_ratio: number }>("/api/validate", { method: "POST", body: JSON.stringify(params) }),

  generate: (params: { prompt: string; api_key: string; base_url?: string; model?: string }) =>
    request<{ code: string; error: string | null }>("/api/generate", { method: "POST", body: JSON.stringify(params) }),

  generateGene: (params: { prompt: string; api_key: string; base_url?: string; model?: string }) =>
    request<{ gene: { name: string; desc: string; side: string; setup: string; code: string } | null; error: string | null }>("/api/generate-gene", { method: "POST", body: JSON.stringify(params) }),

  genes: () => request<{
    entry: Record<string, { desc: string; params: Record<string, number[]>; type: string }>;
    exit: Record<string, { desc: string; params: Record<string, number[]> }>;
  }>("/api/genes"),

  startOptimize: (params: {
    code: string;
    dna: Record<string, unknown>;
    symbol?: string;
    interval?: string;
    candles?: number;
    modifications?: Record<string, unknown>;
    start_date?: string;
    end_date?: string;
  }) => request<{ job_id: string; status: string }>("/api/optimize", { method: "POST", body: JSON.stringify(params) }),

  getOptimize: (jobId: string) => request<ResearchJob>(`/api/optimize/${jobId}`),

  startAdvancedOptimize: (params: {
    code: string;
    dna: Record<string, unknown>;
    method: "nsga2" | "bayesian";
    symbol?: string;
    interval?: string;
    candles?: number;
    modifications?: Record<string, unknown>;
    pop_size?: number;
    n_gen?: number;
    n_trials?: number;
    start_date?: string;
    end_date?: string;
  }) => request<{ job_id: string; status: string }>("/api/advanced-optimize", { method: "POST", body: JSON.stringify(params) }),

  getAdvancedOptimize: (jobId: string) => request<ResearchJob>(`/api/advanced-optimize/${jobId}`),

  crossValidate: (params: {
    code: string;
    symbols: string[];
    intervals: string[];
    candles?: number;
    stop_loss_pct?: number;
    take_profit_pct?: number;
    start_date?: string;
    end_date?: string;
  }) => request<CrossValidateResult>("/api/cross-validate", { method: "POST", body: JSON.stringify(params) }),

  monteCarlo: (params: {
    code: string;
    symbol?: string;
    interval?: string;
    candles?: number;
    stop_loss_pct?: number;
    take_profit_pct?: number;
    n_simulations?: number;
    start_date?: string;
    end_date?: string;
  }) => request<MonteCarloResult>("/api/monte-carlo", { method: "POST", body: JSON.stringify(params) }),

  factorAnalysis: (params: {
    symbol?: string;
    interval?: string;
    candles?: number;
    start_date?: string;
    end_date?: string;
  }) => request<FactorAnalysisResult>("/api/factor-analysis", { method: "POST", body: JSON.stringify(params) }),

  // Monitor
  monitorList: () => request<{ strategies: MonitorStrategy[] }>("/api/monitor/list"),

  monitorAdd: (params: {
    name: string;
    code: string;
    symbol?: string;
    interval?: string;
    stop_loss_pct?: number;
    take_profit_pct?: number;
  }) => request<{ ok: boolean; id: string }>("/api/monitor/add", { method: "POST", body: JSON.stringify(params) }),

  monitorCheck: () => request<{ results: MonitorCheckResult[] }>("/api/monitor/check", { method: "POST" }),

  monitorRemove: (id: string) => request<{ ok: boolean }>(`/api/monitor/${id}`, { method: "DELETE" }),

  monitorTrend: (id: string, days?: number) => request<{ trend: MonitorTrendEntry[] }>(`/api/monitor/trend/${id}?days=${days || 30}`),
};

export interface MonitorStrategy {
  id: string;
  name: string;
  symbol: string;
  interval: string;
  status: "active" | "warning" | "stopped";
  baseline?: {
    sharpe: number;
    roi: number;
    win_rate: number;
    drawdown: number;
    trades: number;
    checked_at: string;
  };
  thresholds: Record<string, number>;
  added_at: string;
  code: string;
  sl: number;
  tp: number;
}

export interface MonitorCheckResult {
  id: string;
  name: string;
  symbol: string;
  interval: string;
  status: string;
  rolling_sharpe: number;
  recent_win_rate: number;
  consec_losses: number;
  roi: number;
  drawdown: number;
  wf_robust: boolean;
  alerts: { level: string; type: string; msg: string }[];
  checked_at: string;
}

export interface MonitorTrendEntry {
  timestamp: string;
  rolling_sharpe: number;
  recent_wr: number;
  consec_losses: number;
  roi: number;
  drawdown: number;
  alerts: number;
}
