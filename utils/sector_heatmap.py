"""
utils/sector_heatmap.py — ENH-17: Sector signal heatmap for email reports.

Groups all scanned tickers by GICS sector and shows:
  - Net signal direction per sector (bull/bear/neutral aggregate)
  - Count of bull/bear picks per sector
  - Strongest ticker per sector (highest conviction)
  - Visual heat blocks — green for bullish sectors, red for bearish

GICS sectors (11 standard):
  Information Technology, Health Care, Financials, Consumer Discretionary,
  Communication Services, Industrials, Consumer Staples, Energy, Utilities,
  Real Estate, Materials

Used in email_sender.py — appended after the summary table.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from signals.base import TickerAnalysis
from signals.conviction import ConvictionScore


# ── GICS sector display order (most tech-heavy first for Nasdaq scans) ─────────
SECTOR_ORDER = [
    "Information Technology",
    "Communication Services",
    "Consumer Discretionary",
    "Health Care",
    "Financials",
    "Industrials",
    "Energy",
    "Materials",
    "Consumer Staples",
    "Real Estate",
    "Utilities",
    "Unknown",
]

# Short labels for compact display
SECTOR_SHORT = {
    "Information Technology":  "Tech",
    "Communication Services":  "Comm",
    "Consumer Discretionary":  "Cons.D",
    "Health Care":             "Health",
    "Financials":              "Finance",
    "Industrials":             "Indust.",
    "Energy":                  "Energy",
    "Materials":               "Materials",
    "Consumer Staples":        "Cons.S",
    "Real Estate":             "Real Est.",
    "Utilities":               "Utilities",
    "Unknown":                 "Other",
}


# ── Data model ─────────────────────────────────────────────────────────────────

class SectorStats:
    def __init__(self, sector: str):
        self.sector   = sector
        self.tickers: List[Tuple[TickerAnalysis, ConvictionScore]] = []

    def add(self, ta: TickerAnalysis, cs: ConvictionScore) -> None:
        self.tickers.append((ta, cs))

    @property
    def count(self) -> int:
        return len(self.tickers)

    @property
    def bull_count(self) -> int:
        return sum(1 for ta, _ in self.tickers if ta.net_score > 0)

    @property
    def bear_count(self) -> int:
        return sum(1 for ta, _ in self.tickers if ta.net_score < 0)

    @property
    def net_score(self) -> float:
        """Average net score across all tickers in this sector."""
        if not self.tickers:
            return 0.0
        return sum(ta.net_score for ta, _ in self.tickers) / len(self.tickers)

    @property
    def avg_conviction(self) -> float:
        if not self.tickers:
            return 0.0
        return sum(cs.conviction_pct for _, cs in self.tickers) / len(self.tickers)

    @property
    def direction(self) -> str:
        """bull | bear | neutral — based on average net score."""
        ns = self.net_score
        if ns >= 1.5:  return "bull"
        if ns <= -1.5: return "bear"
        return "neutral"

    @property
    def strongest(self) -> Optional[Tuple[TickerAnalysis, ConvictionScore]]:
        """Ticker with highest conviction % in this sector."""
        if not self.tickers:
            return None
        return max(self.tickers, key=lambda x: x[1].conviction_pct)

    @property
    def intensity(self) -> float:
        """0.0–1.0 colour intensity based on bull/bear ratio."""
        if self.count == 0:
            return 0.0
        dominant = max(self.bull_count, self.bear_count)
        return dominant / self.count


def build_sector_stats(
    results: List[TickerAnalysis],
    conviction_scores: Optional[Dict[str, ConvictionScore]] = None,
) -> Dict[str, SectorStats]:
    """
    Group TickerAnalysis objects by sector.

    Args:
        results:           all scan results
        conviction_scores: {ticker: ConvictionScore} — if None, a dummy score is used
    """
    stats: Dict[str, SectorStats] = {}

    for ta in results:
        sector = ta.sector.strip() if ta.sector else "Unknown"
        if not sector:
            sector = "Unknown"

        if sector not in stats:
            stats[sector] = SectorStats(sector)

        # Get conviction score — dummy if not provided
        if conviction_scores and ta.ticker in conviction_scores:
            cs = conviction_scores[ta.ticker]
        else:
            from signals.conviction import ConvictionScore as CS
            cs = CS(
                ticker=ta.ticker, raw_score=ta.net_score,
                weighted_score=float(ta.net_score), conviction_pct=50.0,
                direction="bullish" if ta.net_score > 0 else "bearish" if ta.net_score < 0 else "neutral",
                grade="C", analysis="", key_signals=[], conflicting=[],
            )
        stats[sector].add(ta, cs)

    return stats


# ── HTML generation ────────────────────────────────────────────────────────────

def _heat_colour(direction: str, intensity: float) -> Tuple[str, str]:
    """Return (background_hex, text_hex) for a heatmap cell."""
    if direction == "bull":
        # Green scale: light (#E8F5E9) → strong (#1B5E20)
        r = int(232 - intensity * 170)
        g = int(245 - intensity * 150)
        b = int(233 - intensity * 210)
        bg   = f"#{r:02X}{g:02X}{b:02X}"
        text = "#1B5E20" if intensity < 0.5 else "#FFFFFF"
    elif direction == "bear":
        # Red scale: light (#FFEBEE) → strong (#B71C1C)
        r = int(255 - intensity * 70)
        g = int(235 - intensity * 210)
        b = int(238 - intensity * 215)
        bg   = f"#{r:02X}{g:02X}{b:02X}"
        text = "#B71C1C" if intensity < 0.5 else "#FFFFFF"
    else:
        bg, text = "#F5F5F5", "#757575"
    return bg, text


def build_heatmap_html(
    results: List[TickerAnalysis],
    conviction_scores: Optional[Dict[str, ConvictionScore]] = None,
) -> str:
    """
    Build the full sector heatmap HTML section for email insertion.
    Returns empty string if fewer than 3 sectors have data.
    """
    stats = build_sector_stats(results, conviction_scores)
    if len(stats) < 2:
        return ""

    # Sort sectors — highest |net_score| first, then by order list
    def sort_key(kv):
        sector, s = kv
        order = SECTOR_ORDER.index(sector) if sector in SECTOR_ORDER else 99
        return (-abs(s.net_score), order)

    sorted_sectors = sorted(stats.items(), key=sort_key)

    # ── Heatmap grid ───────────────────────────────────────────────────────────
    cells = ""
    for sector, s in sorted_sectors:
        if s.count == 0:
            continue
        bg, text_c = _heat_colour(s.direction, s.intensity)
        short      = SECTOR_SHORT.get(sector, sector[:8])
        arrow      = "▲" if s.direction == "bull" else "▼" if s.direction == "bear" else "—"
        strongest  = s.strongest

        strongest_html = ""
        if strongest:
            ta, cs = strongest
            g_color = "#1D6F42" if cs.direction == "bullish" else "#9C0006"
            strongest_html = (
                f'<div style="font-size:10px;color:{text_c};opacity:0.85;margin-top:3px">'
                f'{ta.ticker} {cs.grade}</div>'
            )

        cells += f"""
<div style="background:{bg};border-radius:6px;padding:10px 8px;text-align:center;
            min-width:80px;flex:1;border:1px solid rgba(0,0,0,0.08)">
  <div style="font-size:11px;font-weight:700;color:{text_c}">{short}</div>
  <div style="font-size:18px;font-weight:700;color:{text_c};margin:2px 0">{arrow}</div>
  <div style="font-size:10px;color:{text_c};opacity:0.9">
    {s.bull_count}▲ {s.bear_count}▼ / {s.count}
  </div>
  {strongest_html}
</div>"""

    # ── Sector details table ───────────────────────────────────────────────────
    rows = ""
    for sector, s in sorted_sectors:
        if s.count == 0:
            continue
        bg, _ = _heat_colour(s.direction, s.intensity * 0.4)  # lighter for table
        arrow  = "▲" if s.direction == "bull" else "▼" if s.direction == "bear" else "—"
        ac     = "#1D6F42" if s.direction == "bull" else "#9C0006" if s.direction == "bear" else "#888"
        top3   = sorted(s.tickers, key=lambda x: x[1].conviction_pct, reverse=True)[:3]
        top3_str = "  ".join(
            f'<span style="font-weight:600;color:{ac}">{ta.ticker}</span>'
            f'<span style="color:#888;font-size:10px">({cs.grade})</span>'
            for ta, cs in top3
        )
        rows += f"""
<tr style="background:{bg}">
  <td style="padding:6px 10px;font-weight:600">{sector}</td>
  <td style="padding:6px 10px;text-align:center;font-size:16px;color:{ac}">{arrow}</td>
  <td style="padding:6px 10px;text-align:center;font-family:monospace">
    <span style="color:#1D6F42">{s.bull_count}▲</span>
    &nbsp;
    <span style="color:#9C0006">{s.bear_count}▼</span>
    &nbsp;/&nbsp;{s.count}
  </td>
  <td style="padding:6px 10px;text-align:center;font-size:12px">{s.avg_conviction:.0f}%</td>
  <td style="padding:6px 10px;font-size:12px">{top3_str}</td>
</tr>"""

    return f"""
<h2 style="color:#2E75B6;border-bottom:2px solid #C9D8F0;padding-bottom:8px;
           font-size:18px;margin:28px 0 16px">
  🗺 Sector Heatmap — {len([s for s in stats.values() if s.count > 0])} sectors
</h2>

<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px">
  {cells}
</div>

<table width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;font-size:12px;font-family:Arial,sans-serif;
              border:1px solid #ddd;border-radius:6px;overflow:hidden">
  <thead>
    <tr style="background:#2E75B6;color:#fff">
      <th style="padding:8px 10px;text-align:left">Sector</th>
      <th style="padding:8px 10px;text-align:center;width:40px">Dir</th>
      <th style="padding:8px 10px;text-align:center">Bull/Bear</th>
      <th style="padding:8px 10px;text-align:center">Avg Conv</th>
      <th style="padding:8px 10px;text-align:left">Top Picks</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<div style="margin-top:8px;font-size:11px;color:#888">
  Sector data from FMP /stable/profile · GICS classification
</div>"""
