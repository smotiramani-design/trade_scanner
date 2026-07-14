// Row shapes returned by the Supabase views/tables.

export interface PickRow {
  trade_date: string;        // "2026-06-13"
  et_time: string;           // "10:00"
  et_hour: number;
  session: string | null;
  direction: "bull" | "bear";
  rank: number;
  ticker: string;
  company: string | null;
  conviction: number | null;
  grade: string | null;
  net_score: number | null;
  price: number | null;
  chg_pct: number | null;
  fib_target: number | null;
  fib_label: string | null;
  fib_hit: boolean | null;
  fib_window_high: number | null;
  fib_window_low: number | null;
  mtf_aligned: boolean | null;
  earnings_soon: boolean | null;
  verdict: string | null;
  analysis: string | null;
  key_signals: string[] | null;
  conflicting: string[] | null;
  signals: Record<string, { bias: string; label: string }> | null;
  universe: string | null;
  trade_run: boolean | null;
  run_ts: string;
  scan_id: number;
}

export interface TradeRow {
  id: number;
  scan_id: number;
  trade_date: string | null;
  et_time: string | null;
  ticker: string;
  action: string | null;
  reason: string | null;
  qty: number | null;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  size_usd: number | null;
  order_id: string | null;
  status: string | null;
  dry_run: boolean | null;
  ts: string;
}

export interface DaySummary {
  trade_date: string;
  scan_count: number;
  last_et_time: string;
}

export interface FibHitStats {
  hits: number;
  misses: number;
  unknown: number;
  validated: number;
  with_target: number;
  hit_pct: number;
}

// Picks for one scan (one hour), split by direction.
export interface ScanGroup {
  scan_id: number;
  et_time: string;
  et_hour: number;
  session: string | null;
  trade_run: boolean | null;
  bulls: PickRow[];
  bears: PickRow[];
}

// ── Pre-Market Momentum Screener ─────────────────────────────────────────────

export interface MomentumPickRow {
  trade_date: string;
  et_time: string;
  et_hour: number;
  session: string | null;
  universe: string | null;
  run_ts: string;
  scan_id: number;
  ticker: string;
  company: string | null;
  sector: string | null;
  tier: "TRADE" | "WATCH" | "SKIP" | string;
  rank: number | null;
  score: number | null;
  conviction: number | null;
  pm_change_pct: number | null;
  pm_volume: number | null;
  pm_price: number | null;
  prev_close: number | null;
  gap_pct: number | null;
  l1_catalyst: string | null;
  l2_volume: string | null;
  l3_price: string | null;
  l4_rs: string | null;
  l5_options: string | null;
  data_sources: string | null;
}

export interface MomentumDaySummary {
  trade_date: string;
  n_trade: number;
  n_watch: number;
  et_time: string;
}

export interface MomentumScanGroup {
  scan_id: number;
  et_time: string;
  et_hour: number;
  session: string | null;
  universe: string | null;
  trade: MomentumPickRow[];
  watch: MomentumPickRow[];
}

// ── Machine Learning ─────────────────────────────────────────────────────────

// One learned signal weight: hand-tuned baseline vs model-learned value.
export interface MlWeightItem {
  signal: string;
  old: number | null;
  new: number | null;
  coef: number | null;
}

// A context/regime coefficient (insight only, not written to weights).
export interface MlContextCoef {
  name: string;
  coef: number;
}

// Selection-bias comparison (picks vs rejected universe).
export interface MlSelectionBias {
  n_pick: number;
  n_nonpick: number;
  pick_hit_rate: number | null;
  nonpick_hit_rate: number | null;
}

// One row of ml_weight_runs — a single weight-tuning run.
export interface MlRunRow {
  id: number;
  run_ts: string;
  trade_date: string | null;
  et_time: string | null;
  source: string | null;             // "features" | "picks"
  lookback_days: number | null;
  n_samples: number | null;
  n_hits: number | null;
  n_misses: number | null;
  base_rate: number | null;
  train_acc: number | null;
  test_acc: number | null;
  test_auc: number | null;
  n_train: number | null;
  n_test: number | null;
  use_regime: boolean | null;
  use_context: boolean | null;
  c_param: number | null;
  applied: boolean | null;
  weights: MlWeightItem[] | null;
  context_coefs: MlContextCoef[] | null;
  selection_bias: MlSelectionBias | null;
}

// Aggregate stats over the scan_features training set.
export interface FeatureDatasetStats {
  total: number;
  labeled: number;
  hits: number;
  misses: number;
  hit_pct: number | null;
  picks: number;
  nonpicks: number;
  pick_hit_pct: number | null;
  nonpick_hit_pct: number | null;
  days: number;
  first_date: string | null;
  last_date: string | null;
}

// Per-day labeled-row coverage for the training-data timeline.
export interface FeatureDayCoverage {
  trade_date: string;
  labeled: number;
  hits: number;
}
