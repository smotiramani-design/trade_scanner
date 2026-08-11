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
  fib_entry: number | null;
  fib_stop: number | null;
  fib_t1: number | null;
  fib_t2: number | null;
  atr_entry: number | null;
  atr_stop: number | null;
  atr_t1: number | null;
  atr_t2: number | null;
  fib_hit: boolean | null;
  fib_window_high: number | null;
  fib_window_low: number | null;
  phit: number | null;
  xgb_phit: number | null;
  xgboost_phit: number | null;
  ens_phit: number | null;
  pred_lo: number | null;
  pred_mid: number | null;
  pred_hi: number | null;
  pred_mid_pct: number | null;
  adv_lo: number | null;
  adv_mid: number | null;
  adv_hi: number | null;
  adv_mid_pct: number | null;
  ev_score: number | null;
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

// ── Daily Scanner (conviction + Fibonacci model, top 10 long / 10 short) ──────
// Backed by the momentum_scans / momentum_picks tables (extended in db/schema.sql).

export interface MomentumPickRow {
  trade_date: string;
  et_time: string;
  et_hour: number;
  session: string | null;
  universe: string | null;
  mode: string | null;               // "Daily"
  run_ts: string;
  scan_id: number;
  ticker: string;
  company: string | null;
  sector: string | null;

  // New conviction+Fib model
  direction: "bull" | "bear" | string | null;
  rank: number | null;               // 1-based within direction
  net_score: number | null;          // raw −10…+10
  conviction: number | null;         // conviction % (0–100)
  grade: string | null;              // A+ / A / B / C / D
  price: number | null;              // price at scan (9:15)
  chg_pct: number | null;
  analysis: string | null;
  key_signals: string[] | null;
  signals: Record<string, { bias: string; label: string }> | null;
  phit: number | null;

  // Gradient-boosted predictions (parallel to logistic — not used for ranking)
  xgb_phit: number | null;
  xgboost_phit: number | null;
  ens_phit: number | null;
  pred_lo: number | null;
  pred_mid: number | null;
  pred_hi: number | null;
  pred_mid_pct: number | null;
  adv_lo: number | null;
  adv_mid: number | null;
  adv_hi: number | null;
  adv_mid_pct: number | null;
  ev_score: number | null;

  // ATR R-multiple plan (parallel to Fib)
  atr_entry: number | null;
  atr_stop: number | null;
  atr_t1: number | null;
  atr_t2: number | null;

  // Fibonacci plan + whole-day (9:15 → 4 PM) target and hit result
  fib_direction: string | null;
  fib_entry: number | null;
  fib_stop: number | null;
  fib_t1: number | null;
  fib_t2: number | null;
  fib_t3: number | null;
  day_target: number | null;
  day_target_label: string | null;
  target_hit: boolean | null;
  day_high: number | null;
  day_low: number | null;
  validated_at: string | null;

  // Legacy pre-market fields (kept for historical rows)
  tier: "TRADE" | "WATCH" | "SKIP" | string | null;
  score: number | null;
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
  n_long: number;
  n_short: number;
  et_time: string;
}

// One day's whole-day target hit-rate stats (from v_momentum_hit_stats).
export interface MomentumHitStats {
  trade_date: string;
  n_picks: number;
  n_long: number;
  n_short: number;
  validated: number;
  hits: number;
  misses: number;
  long_validated: number;
  long_hits: number;
  short_validated: number;
  short_hits: number;
}

export interface MomentumScanGroup {
  scan_id: number;
  et_time: string;
  et_hour: number;
  session: string | null;
  universe: string | null;
  mode: string | null;
  longs: MomentumPickRow[];
  shorts: MomentumPickRow[];
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

// Feature importance entry from a LightGBM dump.
export interface BoostedImportanceItem {
  name: string;
  gain: number;
}

// One row of ml_boosted_runs — gradient-boosted P(hit) + range model run.
export interface BoostedRunRow {
  id: number;
  run_ts: string;
  trade_date: string | null;
  et_time: string | null;
  source: string | null;
  lookback_days: number | null;
  phit_n_samples: number | null;
  phit_n_hits: number | null;
  phit_n_misses: number | null;
  phit_base_rate: number | null;
  phit_test_acc: number | null;
  phit_test_auc: number | null;
  phit_n_train: number | null;
  phit_n_test: number | null;
  phit_importance: BoostedImportanceItem[] | null;
  range_n_samples: number | null;
  range_mean_excursion: number | null;
  range_median_excursion: number | null;
  range_test_mae: Record<string, number> | null;
  range_test_coverage: Record<string, number> | null;
  range_importance: BoostedImportanceItem[] | null;
  adv_n_samples: number | null;
  adv_mean_excursion: number | null;
  adv_median_excursion: number | null;
  adv_test_mae: Record<string, number> | null;
  adv_test_coverage: Record<string, number> | null;
  adv_importance: BoostedImportanceItem[] | null;
  xgb_test_acc: number | null;
  xgb_test_auc: number | null;
  xgb_importance: BoostedImportanceItem[] | null;
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

// ── On-demand ticker analyzer (served by the FastAPI engine via /api/analyze) ──
export interface AnalyzeSignal {
  name: string;
  bias: string; // "bull" | "bear" | "neutral"
  label: string;
  detail: string;
}

export interface AnalyzeConviction {
  ticker: string;
  raw_score: number;
  weighted_score: number;
  conviction_pct: number;
  direction: string; // "LONG" | "SHORT" | "NEUTRAL"
  grade: string;
  analysis: string;
  key_signals: string[];
  conflicting: string[];
}

export interface AnalyzeFib {
  direction: string | null;
  anchor_type: string | null;
  current_price: number | null;
  swing_high: number | null;
  swing_low: number | null;
  entry_price: number | null;
  entry_label: string;
  stop_loss: number | null;
  stop_label: string;
  target_1: number | null;
  target_1_label: string;
  target_2: number | null;
  target_3: number | null;
  risk_reward_t1: number | null;
  next_target: number | null; // projected ~1-hour target price
  next_label: string;
  support_1: number | null;
  resistance_1: number | null;
}

export interface AnalyzeAtr {
  entry: number | null;
  stop: number | null;
  target_1: number | null;
  target_2: number | null;
  atr: number | null;
  r_distance: number | null;
  multiplier: number | null;
  direction: string | null;
}

// Raw payload from the FastAPI /api/signals/{ticker} endpoint.
export interface AnalyzePayload {
  ticker: string;
  price: number;
  chg_pct: number;
  mode: string;
  net_score: number;
  verdict: string;
  conviction: AnalyzeConviction;
  signals: AnalyzeSignal[];
  fib: AnalyzeFib | null;
  atr?: AnalyzeAtr | null;
  as_of: string;
}

// One entry per requested ticker from the dashboard's /api/analyze proxy.
export interface AnalyzeResult {
  ticker: string;
  data?: AnalyzePayload;
  error?: string;
}

export interface AnalyzeResponse {
  results: AnalyzeResult[];
  api: string;
}
