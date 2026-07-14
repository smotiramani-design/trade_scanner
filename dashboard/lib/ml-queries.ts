import { supabase } from "./supabase";
import type { MlRunRow, FeatureDatasetStats } from "./types";

// Most recent weight-tuning run (null if none logged yet).
export async function getLatestMlRun(): Promise<MlRunRow | null> {
  const { data, error } = await supabase
    .from("ml_weight_runs")
    .select("*")
    .order("run_ts", { ascending: false })
    .limit(1);
  if (error) throw error;
  return ((data ?? []) as MlRunRow[])[0] ?? null;
}

// Recent runs, newest first (for the "getting better over time" chart + history).
export async function getMlRuns(limit = 50): Promise<MlRunRow[]> {
  const { data, error } = await supabase
    .from("ml_weight_runs")
    .select("*")
    .order("run_ts", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as MlRunRow[];
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

// Cheap COUNT over scan_features (head request — no rows transferred).
async function featureCount(
  build: (q: ReturnType<typeof baseCountQuery>) => ReturnType<typeof baseCountQuery>
): Promise<number> {
  const { count, error } = await build(baseCountQuery());
  if (error) throw error;
  return count ?? 0;
}

function baseCountQuery() {
  return supabase
    .from("scan_features")
    .select("*", { count: "exact", head: true });
}

/**
 * Aggregate stats over the scan_features training set, computed with a handful of
 * cheap COUNT(head) queries so we never download the (large) universe table.
 */
export async function getFeatureDatasetStats(
  days?: number
): Promise<FeatureDatasetStats> {
  const since = days ? isoDaysAgo(days) : null;
  const range = <T extends ReturnType<typeof baseCountQuery>>(q: T): T =>
    (since ? q.gte("trade_date", since) : q) as T;

  const total = await featureCount((q) => range(q));
  const labeled = await featureCount((q) => range(q).not("fib_hit", "is", null));
  const hits = await featureCount((q) => range(q).eq("fib_hit", true));
  const picks = await featureCount((q) =>
    range(q).eq("was_pick", true).not("fib_hit", "is", null)
  );
  const pickHits = await featureCount((q) =>
    range(q).eq("was_pick", true).eq("fib_hit", true)
  );

  const misses = Math.max(0, labeled - hits);
  const nonpicks = Math.max(0, labeled - picks);
  const nonpickHits = Math.max(0, hits - pickHits);

  const pct = (num: number, den: number) =>
    den > 0 ? Math.round((num / den) * 100) : null;

  // Distinct trading days + date range from the small scans table.
  let firstDate: string | null = null;
  let lastDate: string | null = null;
  let dayCount = 0;
  {
    let q = supabase
      .from("scans")
      .select("trade_date")
      .not("trade_date", "is", null)
      .order("trade_date", { ascending: true })
      .limit(5000);
    if (since) q = q.gte("trade_date", since);
    const { data, error } = await q;
    if (error) throw error;
    const dates = new Set<string>();
    for (const row of (data ?? []) as { trade_date: string | null }[]) {
      if (row.trade_date) dates.add(row.trade_date);
    }
    const sorted = Array.from(dates).sort();
    dayCount = sorted.length;
    firstDate = sorted[0] ?? null;
    lastDate = sorted[sorted.length - 1] ?? null;
  }

  return {
    total,
    labeled,
    hits,
    misses,
    hit_pct: pct(hits, labeled),
    picks,
    nonpicks,
    pick_hit_pct: pct(pickHits, picks),
    nonpick_hit_pct: pct(nonpickHits, nonpicks),
    days: dayCount,
    first_date: firstDate,
    last_date: lastDate,
  };
}
