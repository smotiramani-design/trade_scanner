/** Matches signals/__init__.py SIG_NAMES — order preserved for chip display. */
export const SIGNAL_ORDER = [
  "Candle",
  "Volume",
  "SMA",
  "Gaps",
  "Stoch",
  "CCI",
  "RR",
  "Rel.Str",
  "VWAP",
  "News",
] as const;

export type SignalBias = "bull" | "bear" | "neutral";

export interface SignalChip {
  name: string;
  bias: SignalBias;
  label: string;
}

function normalizeBias(raw: string | undefined): SignalBias {
  if (raw === "bull" || raw === "bear") return raw;
  return "neutral";
}

/** Parse picks.signals JSONB from Supabase into ordered chips. */
export function parseSignalChips(raw: unknown): SignalChip[] {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  const obj = raw as Record<string, { bias?: string; label?: string }>;
  return SIGNAL_ORDER.filter((name) => name in obj).map((name) => ({
    name,
    bias: normalizeBias(obj[name]?.bias),
    label: obj[name]?.label ?? "",
  }));
}

export function biasIcon(bias: SignalBias): string {
  if (bias === "bull") return "▲";
  if (bias === "bear") return "▼";
  return "—";
}
