"""
signals/fibonacci.py — Fibonacci price projection with entry/exit targets.

Anchor selection:
  Computes both session range and premarket range; picks the TIGHTER one.
  If FMP real-time price is unavailable (returns 0/None), falls back to
  the last bar's close price so Fib always runs.

Entry / Exit / Stop framework (momentum-synced)
────────────────────────────────────────────────
BULLISH setup (net_score > 0):
  Entry       → 38.2% retracement (ideal pullback entry)
  Stop loss   → 61.8% retracement (invalidation level)
  Target 1    → 100% extension  (measured move)
  Target 2    → 127.2% extension
  Target 3    → 161.8% extension (full measured move)

BEARISH setup (net_score < 0):
  Entry       → 38.2% retracement bounce (ideal short entry)
  Stop loss   → 61.8% retracement (invalidation level)
  Target 1    → 100% extension below swing low
  Target 2    → 127.2% extension
  Target 3    → 161.8% extension

NEUTRAL (net_score == 0):
  Entry       → 50% retracement
  Stop loss   → 78.6% retracement
  Target 1    → 23.6% retracement (mean reversion)
  Target 2    → 100% extension
  Target 3    → 127.2% extension

Risk/reward is pre-calculated for each setup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from data.yahoo_client import Bar

# ── Fibonacci ratios ──────────────────────────────────────────────────────────
RETRACEMENT_RATIOS: List[Tuple[str, float]] = [
    ("23.6%", 0.236),
    ("38.2%", 0.382),
    ("50.0%", 0.500),
    ("61.8%", 0.618),
    ("78.6%", 0.786),
]

EXTENSION_RATIOS: List[Tuple[str, float]] = [
    ("100.0%", 1.000),
    ("127.2%", 1.272),
    ("138.2%", 1.382),
    ("161.8%", 1.618),
    ("200.0%", 2.000),
    ("261.8%", 2.618),
]


@dataclass
class FibLevel:
    label:     str
    ratio:     float
    price:     float
    kind:      str       # "retracement" | "extension"
    is_target: bool = False


@dataclass
class FibLevels:
    ticker:           str
    anchor_type:      str
    swing_high:       float
    swing_low:        float
    swing_range:      float
    current_price:    float
    direction:        str          # "bullish" | "bearish" | "neutral"
    retracements:     List[FibLevel] = field(default_factory=list)
    extensions:       List[FibLevel] = field(default_factory=list)

    # ── Next-hour target (original) ───────────────────────────────────────────
    next_hour_target: Optional[float] = None
    next_hour_label:  str = ""

    # ── Entry / Exit / Stop (new) ─────────────────────────────────────────────
    entry_price:      Optional[float] = None
    entry_label:      str = ""
    stop_loss:        Optional[float] = None
    stop_label:       str = ""
    target_1:         Optional[float] = None
    target_1_label:   str = ""
    target_2:         Optional[float] = None
    target_2_label:   str = ""
    target_3:         Optional[float] = None
    target_3_label:   str = ""
    risk_reward_t1:   Optional[float] = None
    risk_reward_t2:   Optional[float] = None
    risk_reward_t3:   Optional[float] = None

    # ── Nearest S/R ───────────────────────────────────────────────────────────
    support_1:        Optional[float] = None
    resistance_1:     Optional[float] = None

    def all_levels(self) -> List[FibLevel]:
        return sorted(self.retracements + self.extensions, key=lambda l: l.price)

    def _rr(self, entry: float, stop: float, target: float) -> Optional[float]:
        risk = abs(entry - stop)
        if risk < 0.0001:
            return None
        reward = abs(target - entry)
        return round(reward / risk, 2)

    def to_dict(self) -> Dict:
        d = {
            "fib_anchor":       self.anchor_type,
            "fib_swing_high":   round(self.swing_high, 2),
            "fib_swing_low":    round(self.swing_low, 2),
            "fib_direction":    self.direction,
            "fib_entry":        round(self.entry_price, 2) if self.entry_price else "",
            "fib_entry_label":  self.entry_label,
            "fib_stop":         round(self.stop_loss, 2) if self.stop_loss else "",
            "fib_stop_label":   self.stop_label,
            "fib_t1":           round(self.target_1, 2) if self.target_1 else "",
            "fib_t1_label":     self.target_1_label,
            "fib_t2":           round(self.target_2, 2) if self.target_2 else "",
            "fib_t2_label":     self.target_2_label,
            "fib_t3":           round(self.target_3, 2) if self.target_3 else "",
            "fib_t3_label":     self.target_3_label,
            "fib_rr_t1":        self.risk_reward_t1 if self.risk_reward_t1 else "",
            "fib_rr_t2":        self.risk_reward_t2 if self.risk_reward_t2 else "",
            "fib_rr_t3":        self.risk_reward_t3 if self.risk_reward_t3 else "",
            "fib_next_target":  round(self.next_hour_target, 2) if self.next_hour_target else "",
            "fib_next_label":   self.next_hour_label,
            "fib_support_1":    round(self.support_1, 2) if self.support_1 else "",
            "fib_resistance_1": round(self.resistance_1, 2) if self.resistance_1 else "",
        }
        for lvl in self.retracements:
            key = f"fib_r_{lvl.label.replace('%','').replace('.','p')}"
            d[key] = round(lvl.price, 2)
        for lvl in self.extensions:
            key = f"fib_e_{lvl.label.replace('%','').replace('.','p')}"
            d[key] = round(lvl.price, 2)
        return d


# ── Anchor selection ──────────────────────────────────────────────────────────

def _session_range(bars: List[Bar]) -> Tuple[float, float]:
    """Tight 8-bar session range — used as a tiebreaker for pre/after-hours."""
    lookback = min(8, len(bars))
    recent   = bars[-lookback:]
    return max(b.high for b in recent), min(b.low for b in recent)


def _swing_range(bars: List[Bar], lookback: int) -> Tuple[float, float, int]:
    """
    Find the dominant swing high and swing low over the last N bars using
    a fractal-pivot approach:
      Swing high: bar[i].high is higher than the 3 bars on each side
      Swing low:  bar[i].low  is lower  than the 3 bars on each side

    Falls back to the simple max/min over the full lookback if no fractal
    pivots are found (e.g. strong trending move with no retracements).

    Returns (swing_high, swing_low, bars_used).
    """
    window = bars[-lookback:]
    n = len(window)

    # Fractal pivot detection (3-bar each side)
    swing_highs: List[Tuple[float, int]] = []  # (price, index)
    swing_lows:  List[Tuple[float, int]] = []

    for i in range(3, n - 3):
        is_sh = all(window[i].high >= window[i-j].high and
                    window[i].high >= window[i+j].high for j in range(1, 4))
        is_sl = all(window[i].low  <= window[i-j].low  and
                    window[i].low  <= window[i+j].low  for j in range(1, 4))
        if is_sh:
            swing_highs.append((window[i].high, i))
        if is_sl:
            swing_lows.append((window[i].low, i))

    if swing_highs and swing_lows:
        sh = max(swing_highs, key=lambda x: x[0])[0]
        sl = min(swing_lows,  key=lambda x: x[0])[0]
        return sh, sl, lookback

    # Fallback: simple max/min
    sh = max(b.high for b in window)
    sl = min(b.low  for b in window)
    return sh, sl, lookback


def _select_anchor(
    bars: List[Bar],
    pm_high: Optional[float],
    pm_low:  Optional[float],
) -> Tuple[float, float, str]:
    """
    Choose the most relevant Fibonacci anchor by comparing four candidates
    and selecting the one that best captures the meaningful swing:

    Candidate A — Multi-day swing (20 bars): captures the broader structure.
                  Preferred for daily/swing setups and trending stocks.
    Candidate B — Short swing (8 bars):      captures recent intraday moves.
                  Preferred for tight, choppy sessions.
    Candidate C — Pre/after-market range:    tightest anchor when extended-
                  hours trading defines a clear range.
    Candidate D — Session range (8 bars):    same as B, used as reference.

    Selection rule:
      1. If pre/after-market range is tightest AND price is near it → use C
      2. If multi-day swing range is > 3× the session range →
         the stock is trending; use A (big swing is the meaningful context)
      3. Otherwise use B (short swing — avoids noise from distant pivots)
    """
    # Candidate A: multi-day swing high/low (20-bar fractal)
    n_bars = min(20, len(bars))
    md_high, md_low, _ = _swing_range(bars, n_bars)
    md_range = md_high - md_low

    # Candidate B/D: short session swing (8 bars)
    s_high, s_low = _session_range(bars)
    s_range = s_high - s_low

    if s_range <= 0:
        return md_high, md_low, "multi-day swing"

    # Candidate C: pre/after-market range
    if pm_high and pm_low and pm_high > pm_low:
        pm_range = pm_high - pm_low
        # Use pre/after-market only if it's tighter than session
        if pm_range < s_range * 0.8:
            return pm_high, pm_low, "premarket"

    # If multi-day range is much bigger → trending stock → use full swing
    ratio = md_range / s_range
    if ratio > 2.5 and md_range > 0:
        return md_high, md_low, f"multi-day swing ({n_bars}b)"

    # Default: short swing (recent structure)
    return s_high, s_low, "session"


# ── Level computation ─────────────────────────────────────────────────────────

def _compute_levels(
    swing_high: float,
    swing_low:  float,
    direction:  str,
) -> Tuple[List[FibLevel], List[FibLevel]]:
    rng = swing_high - swing_low
    if rng <= 0:
        return [], []

    retracements, extensions = [], []

    for label, ratio in RETRACEMENT_RATIOS:
        price = (swing_high - rng * ratio) if direction != "bearish" else (swing_low + rng * ratio)
        retracements.append(FibLevel(f"R {label}", ratio, round(price, 2), "retracement"))

    for label, ratio in EXTENSION_RATIOS:
        price = (swing_low + rng * ratio) if direction != "bearish" else (swing_high - rng * ratio)
        extensions.append(FibLevel(f"E {label}", ratio, round(price, 2), "extension"))

    return retracements, extensions


def _get_level(levels: List[FibLevel], label_contains: str) -> Optional[FibLevel]:
    return next((l for l in levels if label_contains in l.label), None)


def _nearest_sr(all_levels: List[FibLevel], current: float) -> Tuple[Optional[float], Optional[float]]:
    below = [l.price for l in all_levels if l.price < current]
    above = [l.price for l in all_levels if l.price > current]
    return (max(below) if below else None), (min(above) if above else None)


def _nearest_above(levels: List[FibLevel], current: float) -> Optional[FibLevel]:
    candidates = [l for l in levels if l.price > current]
    return min(candidates, key=lambda l: l.price) if candidates else None


def _nearest_below(levels: List[FibLevel], current: float) -> Optional[FibLevel]:
    candidates = [l for l in levels if l.price < current]
    return max(candidates, key=lambda l: l.price) if candidates else None


# ── Entry / Exit / Stop assignment ───────────────────────────────────────────

def _assign_trade_levels(
    fib: FibLevels,
    retracements: List[FibLevel],
    extensions: List[FibLevel],
) -> None:
    """
    Assign entry, stop, and three targets based on momentum direction.
    Uses well-established Fibonacci trade management rules.
    """
    cur   = fib.current_price
    r236  = _get_level(retracements, "23.6")
    r382  = _get_level(retracements, "38.2")
    r500  = _get_level(retracements, "50.0")
    r618  = _get_level(retracements, "61.8")
    r786  = _get_level(retracements, "78.6")
    e100  = _get_level(extensions,   "100.0")
    e1272 = _get_level(extensions,   "127.2")
    e1382 = _get_level(extensions,   "138.2")
    e1618 = _get_level(extensions,   "161.8")

    if fib.direction == "bullish":
        # Entry: 38.2% pullback level — ideal re-entry on dip
        # Stop:  61.8% — golden ratio invalidation
        # T1/T2/T3: extensions above swing high
        entry = r382 or r500
        stop  = r618 or r786
        t1, t1_lbl = (e100.price,  e100.label)  if e100  else (None, "")
        t2, t2_lbl = (e1272.price, e1272.label) if e1272 else (None, "")
        t3, t3_lbl = (e1618.price, e1618.label) if e1618 else (None, "")

    elif fib.direction == "bearish":
        # Entry: 38.2% bounce level — short on bounce
        # Stop:  61.8% — invalidation above
        # T1/T2/T3: extensions below swing low
        entry = r382 or r500
        stop  = r618 or r786
        t1, t1_lbl = (e100.price,  e100.label)  if e100  else (None, "")
        t2, t2_lbl = (e1272.price, e1272.label) if e1272 else (None, "")
        t3, t3_lbl = (e1618.price, e1618.label) if e1618 else (None, "")

    else:  # neutral
        entry = r500
        stop  = r786
        t1, t1_lbl = (r236.price, r236.label) if r236 else (None, "")
        t2, t2_lbl = (e100.price, e100.label) if e100  else (None, "")
        t3, t3_lbl = (e1272.price, e1272.label) if e1272 else (None, "")

    fib.entry_price   = entry.price if entry else None
    fib.entry_label   = entry.label if entry else ""
    fib.stop_loss     = stop.price  if stop  else None
    fib.stop_label    = stop.label  if stop  else ""
    fib.target_1      = t1
    fib.target_1_label = t1_lbl
    fib.target_2      = t2
    fib.target_2_label = t2_lbl
    fib.target_3      = t3
    fib.target_3_label = t3_lbl

    # Risk/reward ratios
    if fib.entry_price and fib.stop_loss:
        fib.risk_reward_t1 = fib._rr(fib.entry_price, fib.stop_loss, t1) if t1 else None
        fib.risk_reward_t2 = fib._rr(fib.entry_price, fib.stop_loss, t2) if t2 else None
        fib.risk_reward_t3 = fib._rr(fib.entry_price, fib.stop_loss, t3) if t3 else None

    # Next-hour target: nearest extension in momentum direction
    if fib.direction == "bullish":
        tgt = _nearest_above(extensions, cur)
    elif fib.direction == "bearish":
        tgt = _nearest_below(extensions, cur)
    else:
        tgt = r500

    if tgt:
        tgt.is_target        = True
        fib.next_hour_target = tgt.price
        fib.next_hour_label  = tgt.label


# ── Public entry point ────────────────────────────────────────────────────────

def compute_fibonacci(
    ticker:         str,
    bars:           List[Bar],
    current_price:  float,
    net_score:      int,
    premarket_high: Optional[float] = None,
    premarket_low:  Optional[float] = None,
) -> Optional[FibLevels]:
    """
    Compute full Fibonacci level set with entry/exit/stop targets.
    Falls back to last bar close if current_price is 0/None.
    Returns None only if bars are completely insufficient.
    """
    if not bars or len(bars) < 5:
        return None

    # ── Price fallback — use last bar close if FMP price missing ─────────────
    price = current_price if current_price and current_price > 0 else bars[-1].close
    if not price or price <= 0:
        return None

    direction  = "bullish" if net_score > 0 else "bearish" if net_score < 0 else "neutral"
    swing_high, swing_low, anchor_type = _select_anchor(bars, premarket_high, premarket_low)
    swing_range = swing_high - swing_low
    if swing_range <= 0:
        return None

    retracements, extensions = _compute_levels(swing_high, swing_low, direction)
    all_lvls = retracements + extensions
    support_1, resistance_1 = _nearest_sr(all_lvls, price)

    fib = FibLevels(
        ticker=ticker,
        anchor_type=anchor_type,
        swing_high=round(swing_high, 2),
        swing_low=round(swing_low, 2),
        swing_range=round(swing_range, 2),
        current_price=round(price, 2),
        direction=direction,
        retracements=retracements,
        extensions=extensions,
        support_1=support_1,
        resistance_1=resistance_1,
    )

    _assign_trade_levels(fib, retracements, extensions)
    return fib
