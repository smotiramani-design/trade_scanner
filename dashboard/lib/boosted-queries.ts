import { supabase } from "./supabase";
import type { BoostedRunRow, PickRow } from "./types";

export async function getLatestBoostedRun(): Promise<BoostedRunRow | null> {
  const { data, error } = await supabase
    .from("ml_boosted_runs")
    .select("*")
    .order("run_ts", { ascending: false })
    .limit(1);
  if (error) throw error;
  return ((data ?? []) as BoostedRunRow[])[0] ?? null;
}

export async function getBoostedRuns(limit = 50): Promise<BoostedRunRow[]> {
  const { data, error } = await supabase
    .from("ml_boosted_runs")
    .select("*")
    .order("run_ts", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as BoostedRunRow[];
}

/** Recent picks that have a predicted price band (for the Ranges page). */
export async function getRecentRangePicks(limit = 40): Promise<PickRow[]> {
  const { data, error } = await supabase
    .from("v_scan_picks")
    .select("*")
    .not("pred_mid", "is", null)
    .order("run_ts", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as PickRow[];
}
