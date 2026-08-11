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

/** Recent picks that have a predicted favourable price band. */
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

/** Recent picks with an adverse / risk band. */
export async function getRecentRiskPicks(limit = 40): Promise<PickRow[]> {
  const { data, error } = await supabase
    .from("v_scan_picks")
    .select("*")
    .not("adv_mid", "is", null)
    .order("run_ts", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as PickRow[];
}

/** Recent picks with ensemble P(hit). */
export async function getRecentEnsemblePicks(limit = 40): Promise<PickRow[]> {
  const { data, error } = await supabase
    .from("v_scan_picks")
    .select("*")
    .not("ens_phit", "is", null)
    .order("run_ts", { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as PickRow[];
}
