# Patch: data/fmp_client.py — get_sector_map fix

## What's wrong

The current `get_sector_map` batches tickers with a comma-separated `?symbol=NVDA,AAPL,XOM`
parameter. FMP's `/stable/profile` endpoint accepts only **one symbol at a time** — when
given a comma-separated list, it treats the whole string as a single bogus ticker and
silently returns `[]`. That's why every sector comes back blank and the heatmap collapses
to an empty "Unknown" bucket.

The misleading warning `"FMP profile may not return sector field on this plan"` is just
wrong — your FMP Ultimate plan returns sector fine. The request shape is the bug.

## What to do

Open `data/fmp_client.py` and replace the existing `get_sector_map` function (around
line 455, between the `# ── Sector data (ENH-17) ─` header and the `# ── Constituent
list helpers ─` header) with the version below.

The `_SECTOR_CACHE: Dict[str, str] = {}` module-level cache declaration **stays where
it is** — only the function body changes.

## Replacement function

```python
def get_sector_map(tickers: List[str]) -> Dict[str, str]:
    """
    Return {symbol: sector} for a list of tickers using FMP /stable/profile.
    Sectors are GICS-standard: Technology, Healthcare, Financials, etc.
    Results cached in _SECTOR_CACHE for the process lifetime.
    Silent fallback — returns "" for any ticker where sector is unavailable.

    NOTE: FMP /stable/profile accepts ONE symbol per call. Comma-separated lists
    are treated as a single bogus ticker and return []. We loop one at a time;
    FMP Ultimate's 3000 req/min budget handles 500+ tickers comfortably.
    """
    global _SECTOR_CACHE
    missing = [t for t in tickers if t not in _SECTOR_CACHE]

    for sym in missing:
        try:
            resp = _SESSION.get(
                f"{BASE}/profile",
                params={"symbol": sym, "apikey": config.FMP_API_KEY},
                timeout=10,
            )
            if resp.status_code in _PLAN_RESTRICTED:
                log.debug("sector/profile: plan restriction — sectors unavailable")
                break
            resp.raise_for_status()
            data = resp.json()
            profiles = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            if profiles:
                p = profiles[0]
                _SECTOR_CACHE[sym] = (p.get("sector") or "").strip()
            else:
                _SECTOR_CACHE[sym] = ""   # cache the miss so we don't retry
        except Exception as e:
            log.debug("sector fetch failed %s: %s", sym, e)
            _SECTOR_CACHE[sym] = ""

    filled = sum(1 for t in tickers if _SECTOR_CACHE.get(t))
    if filled:
        log.info("Sector map: %d/%d tickers resolved", filled, len(tickers))
    else:
        log.warning("Sector map: 0/%d — check FMP /stable/profile response shape",
                    len(tickers))
    return {t: _SECTOR_CACHE.get(t, "") for t in tickers}
```

## Verify

After saving, run:

```bash
python -c "
import sys; sys.path.insert(0, '.')
from data.fmp_client import get_sector_map
print(get_sector_map(['NVDA', 'AAPL', 'XOM', 'JPM']))
"
```

Expected output (sectors may vary slightly by FMP's GICS labeling):

```
Sector map: 4/4 tickers resolved
{'NVDA': 'Technology', 'AAPL': 'Technology', 'XOM': 'Energy', 'JPM': 'Financial Services'}
```

If you see `4/4` and real sector strings, the heatmap will render on the next email run.
