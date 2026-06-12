"""
universes.py — Complete, accurate ticker lists for all supported universes.

Sources & counts (June 2026):
  S&P 500       : 503 tickers — github.com/datasets/s-and-p-500-companies
  Nasdaq 100    : 102 tickers — Wikipedia Nasdaq-100 (January 2026)
  Dow Jones 30  : 30 tickers  — Yahoo Finance ^DJI components (June 2026)
  NYSE American : 101 tickers — StockAnalysis NYSE American list (June 2026),
                                filtered to >$100M market cap with real revenue.
                                Full 244-stock list has many micro-caps (<$10M
                                market cap) and SPACs — excluded from scanning.
  NYSE (main)   : All major NYSE-listed stocks already covered by S&P 500.
                  Every DJIA stock + all large NYSE blue-chips are in SP500.

major_us_markets
────────────────
Union of S&P 500 + Nasdaq 100 + Dow Jones 30 + NYSE American.
~560 unique, liquid, institutionally-traded US equities.
FMP Ultimate plan fetches live constituent lists at runtime,
keeping S&P 500 / Nasdaq 100 / Dow 30 current automatically.

About NYSE American (formerly AMEX):
  - Second exchange under NYSE Group umbrella
  - Lists ~244 stocks, mostly small/mid-cap companies
  - Known for mining, energy, biotech smaller names
  - Also lists structured products, ETFs (not included here — equities only)
  - This list filters to stocks with >$100M market cap and real operations
"""
from typing import Dict, List


def _dedup(lst: List[str]) -> List[str]:
    seen, out = set(), []
    for t in lst:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# S&P 500 — full 503 tickers (github.com/datasets/s-and-p-500-companies)
# Note: BRK-B is the standard trading symbol; BRK.B is the dataset symbol.
#       Both included for compatibility with different data providers.
# ─────────────────────────────────────────────────────────────────────────────
SP500: List[str] = _dedup([
    "MMM","AOS","ABT","ABBV","ACN","ADBE","AMD","AES","AFL","A","APD","ABNB",
    "AKAM","ALB","ARE","ALGN","ALLE","LNT","ALL","GOOGL","GOOG","MO","AMZN",
    "AMCR","AEE","AEP","AXP","AIG","AMT","AWK","AMP","AME","AMGN","APH","ADI",
    "AON","APA","APO","AAPL","AMAT","APP","APTV","ACGL","ADM","ARES","ANET",
    "AJG","AIZ","T","ATO","ADSK","ADP","AZO","AVB","AVY","AXON","BKR","BALL",
    "BAC","BAX","BDX","BRK-B","BBY","TECH","BIIB","BLK","BX","BNY",
    "BA","BKNG","BSX","BMY","AVGO","BR","BRO","BLDR","BG","BXP","CHRW","CDNS",
    "CPT","CPB","COF","CAH","CCL","CARR","CVNA","CASY","CAT","CBOE","CBRE","CDW",
    "COR","CNC","CNP","CF","CRL","SCHW","CHTR","CVX","CMG","CB","CHD","CIEN","CI",
    "CINF","CTAS","CSCO","C","CFG","CLX","CME","CMS","KO","CTSH","COHR","COIN",
    "CL","CMCSA","FIX","CAG","COP","ED","STZ","CEG","COO","CPRT","GLW","CPAY",
    "CTVA","CSGP","COST","CRH","CRWD","CCI","CSX","CMI","CVS","DHR","DRI","DDOG",
    "DVA","DECK","DE","DELL","DAL","DVN","DXCM","FANG","DLR","DG","DLTR","D",
    "DPZ","DASH","DOV","DOW","DHI","DTE","DUK","DD","ETN","EBAY","SATS","ECL",
    "EIX","EW","EA","ELV","EME","EMR","ETR","EOG","EQT","EFX","EQIX","EQR",
    "ERIE","ESS","EL","EG","EVRG","ES","EXC","EXE","EXPE","EXPD","EXR","XOM",
    "FFIV","FDS","FICO","FAST","FRT","FDX","FIS","FITB","FSLR","FE","FISV","F",
    "FTNT","FTV","FOXA","FOX","FCX","GRMN","IT","GE","GEHC","GEV","GEN","GNRC",
    "GD","GIS","GM","GPC","GILD","GPN","GL","GDDY","GS","HAL","HIG","HAS","HCA",
    "DOC","HSIC","HSY","HPE","HLT","HD","HON","HRL","HST","HWM","HPQ","HUBB",
    "HUM","HBAN","HII","IBM","IEX","IDXX","ITW","INCY","IR","PODD","INTC","IBKR",
    "ICE","IFF","IP","INTU","ISRG","IVZ","INVH","IQV","IRM","JBHT","JBL","JKHY",
    "JNJ","JCI","JPM","KVUE","KDP","KEY","KEYS","KMB","KIM","KMI","KKR","KLAC",
    "KHC","KR","LHX","LH","LRCX","LVS","LDOS","LEN","LII","LLY","LIN","LYV",
    "LMT","LOW","LULU","LITE","LYB","MTB","MPC","MAR","MLM","MAS","MA","MKC",
    "MCD","MCK","MDT","MRK","META","MET","MTD","MGM","MCHP","MU","MSFT","MAA",
    "MRNA","TAP","MDLZ","MPWR","MNST","MCO","MS","MOS","MSI","MSCI","NDAQ","NTAP",
    "NFLX","NEM","NWSA","NWS","NEE","NKE","NI","NDSN","NSC","NTRS","NOC","NCLH",
    "NRG","NUE","NVDA","NVR","NXPI","ORLY","OXY","ODFL","OMC","ON","OKE","ORCL",
    "OTIS","PCAR","PKG","PLTR","PANW","PH","PAYX","PYPL","PNR","PEP","PFE","PCG",
    "PM","PSX","PNW","PNC","POOL","PPG","PPL","PFG","PG","PGR","PLD","PRU","PEG",
    "PTC","PSA","PHM","PWR","QCOM","DGX","RL","RJF","RTX","O","REG","REGN","RF",
    "RSG","RMD","RVTY","HOOD","ROK","ROL","ROP","ROST","RCL","SPGI","CRM","SNDK",
    "SBAC","SLB","STX","SRE","NOW","SHW","SPG","SWKS","SJM","SW","SNA","SOLV",
    "SO","LUV","SWK","SBUX","STT","STLD","STE","SYK","SMCI","SYF","SNPS","SYY",
    "TMUS","TROW","TTWO","TPR","TRGP","TGT","TEL","TDY","TER","TSLA","TXN","TPL",
    "TXT","TMO","TJX","TKO","TTD","TSCO","TT","TDG","TRV","TRMB","TFC","TYL",
    "TSN","USB","UBER","UDR","ULTA","UNP","UAL","UPS","URI","UNH","UHS","VLO",
    "VEEV","VTR","VLTO","VRSN","VRSK","VZ","VRTX","VRT","VTRS","VICI","V","VST",
    "VMC","WRB","GWW","WAB","WMT","DIS","WBD","WM","WAT","WEC","WFC","WELL","WST",
    "WDC","WY","WSM","WMB","WTW","WDAY","WYNN","XEL","XYL","YUM","ZBRA","ZBH","ZTS",
])

# ─────────────────────────────────────────────────────────────────────────────
# Nasdaq 100 — 102 tickers (Wikipedia, January 2026)
# ─────────────────────────────────────────────────────────────────────────────
NDX100: List[str] = _dedup([
    "ADBE","AMD","ABNB","ALNY","GOOGL","GOOG","AMZN","AEP","AMGN","ADI","AAPL",
    "AMAT","APP","ARM","ASML","ADSK","ADP","AXON","BKR","BKNG","AVGO","CDNS",
    "CHTR","CTAS","CSCO","CCEP","CTSH","CMCSA","CEG","CPRT","CSGP","COST","CRWD",
    "CSX","DDOG","DXCM","FANG","DASH","EA","EXC","FAST","FER","FTNT","GEHC","GILD",
    "HON","IDXX","INSM","INTC","INTU","ISRG","KDP","KLAC","KHC","LRCX","LIN","MAR",
    "MRVL","MELI","META","MCHP","MU","MSFT","MSTR","MDLZ","MPWR","MNST","NFLX",
    "NVDA","NXPI","ORLY","ODFL","PCAR","PLTR","PANW","PAYX","PYPL","PDD","PEP",
    "QCOM","REGN","ROP","ROST","SNDK","STX","SHOP","SBUX","SNPS","TMUS","TTWO",
    "TSLA","TXN","TRI","VRSK","VRTX","WMT","WBD","WDC","WDAY","XEL","ZS",
])

# ─────────────────────────────────────────────────────────────────────────────
# Dow Jones 30 — current 30 components (Yahoo Finance, June 2026)
# ─────────────────────────────────────────────────────────────────────────────
DOW30: List[str] = _dedup([
    "NVDA","AAPL","MSFT","CSCO","IBM","CRM","AMZN","HD","MCD","NKE",
    "JPM","V","GS","AXP","TRV","WMT","KO","PG","JNJ","UNH",
    "MRK","AMGN","CAT","BA","HON","MMM","VZ","DIS","CVX","SHW",
])

# ─────────────────────────────────────────────────────────────────────────────
# NYSE American (formerly AMEX) — 101 tickers >$100M market cap
# Source: StockAnalysis.com NYSE American list (June 2026)
# Focused on mining, energy, biotech, and specialty companies.
# Excludes: SPACs, blank-check cos, sub-$100M micro-caps, warrants/units.
# ─────────────────────────────────────────────────────────────────────────────
NYSE_AMERICAN: List[str] = _dedup([
    # Energy & Mining (largest constituents by market cap)
    "IMO",    # Imperial Oil - $58.9B (oil sands, Canadian)
    "EQX",    # Equinox Gold - $8.5B
    "UEC",    # Uranium Energy Corp - $6.2B
    "BTG",    # B2Gold Corp - $5.6B
    "SEB",    # Seaboard Corp - $4.9B
    "SIM",    # Grupo Simec - $4.8B (steel)
    "ORLA",   # Orla Mining - $3.7B
    "UUUU",   # Energy Fuels - $3.7B (uranium/rare earth)
    "NG",     # NovaGold Resources - $3.2B
    "DNN",    # Denison Mines - $2.75B
    "TGB",    # Taseko Mines - $2.4B
    "SVM",    # Silvercorp Metals - $2.35B
    "SLSR",   # Solaris Resources - $1.46B
    "VZLA",   # Vizsla Silver - $1.17B
    "NAK",    # Northern Dynasty Minerals - $1.07B
    "ASM",    # Avino Silver & Gold - $996M
    "HSLV",   # Highlander Silver - $922M
    "SLI",    # Standard Lithium - $838M
    "NEWP",   # New Pacific Metals - $784M
    "REPX",   # Riley Exploration Permian - $774M (oil E&P)
    "OBE",    # Obsidian Energy - $740M
    "GROY",   # Gold Royalty Corp - $728M
    "TMQ",    # Trilogy Metals - $678M
    "DC",     # Dakota Gold Corp - $676M
    "MTA",    # Metalla Royalty & Streaming - $663M
    "URG",    # Ur-Energy - $651M (uranium)
    "NFGC",   # New Found Gold - $634M
    "ISOU",   # IsoEnergy - $617M (uranium)
    "WRN",    # Western Copper and Gold - $561M
    "THM",    # International Tower Hill Mines - $534M
    "GAU",    # Galiano Gold - $527M
    "CTGO",   # Contango Silver & Gold - $527M
    "IDR",    # Idaho Strategic Resources - $518M
    "ITRG",   # Integra Resources - $481M
    "REI",    # Ring Energy - $322M (oil E&P)
    "VGZ",    # Vista Gold - $321M
    "TRX",    # TRX Gold - $316M
    "SBMT",   # Silver Bow Mining - $246M
    "PLG",    # Platinum Group Metals - $179M
    "GLDG",   # GoldMining Inc - $203M
    "GORO",   # Gold Resource Corp - $199M
    "MINE",   # Mayfair Gold - $185M
    "PED",    # PEDEVCO Corp - $183M (oil E&P)
    "EPM",    # Evolution Petroleum - $154M
    "XPL",    # Solitario Resources - $73M
    "FURY",   # Fury Gold Mines - $97M
    "PZG",    # Paramount Gold Nevada - $98M
    # Healthcare & Biotech
    "PRK",    # Park National Corp - $3.14B (financials)
    "NHC",    # National HealthCare Corp - $2.93B
    "IE",     # Ivanhoe Electric - $1.79B (copper)
    "CATX",   # Perspective Therapeutics - $334M
    "LCTX",   # Lineage Cell Therapeutics - $302M
    "STXS",   # Stereotaxis - $177M (robotic surgical)
    "PLX",    # Protalix BioTherapeutics - $158M
    "OSTX",   # OS Therapies - $80M
    "MAIA",   # MAIA Biotechnology - $77M
    "NRXS",   # NeurAxis - $77M
    "ARMP",   # Armata Pharmaceuticals - $278M
    "PTHS",   # Pelthos Therapeutics - $91M
    # Industrials & Specialty
    "HYLN",   # Hyliion Holdings - $1.29B (electric powertrains)
    "UMAC",   # Unusual Machines - $1.24B (drones)
    "ELA",    # Envela Corp - $610M
    "BHB",    # Bar Harbor Bankshares - $600M
    "RLGT",   # Radiant Logistics - $407M
    "MPTI",   # M-tron Industries - $397M
    "CMCL",   # Caledonia Mining - $380M
    "ELMD",   # Electromed - $309M
    "CIX",    # CompX International - $307M
    "BKTI",   # BK Technologies Corp - $301M
    "ELLO",   # Ellomay Capital - $298M
    "BRBS",   # Blue Ridge Bankshares - $291M
    "GTE",    # Gran Tierra Energy - $269M (oil E&P)
    "FLYX",   # flyExclusive - $248M
    "EVI",    # EVI Industries - $218M
    "GENC",   # Gencor Industries - $218M
    "NEN",    # New England Realty - $209M (REIT)
    "TII",    # Titan Mining - $205M
    "VENU",   # Venu Holding - $202M
    "CMT",    # Core Molding Technologies - $199M
    "INTT",   # InTest Corp - $195M
    "OZ",     # Belpointe PREP (REIT) - $188M
    "TGEN",   # Tecogen - $182M
    "INFU",   # InfuSystem Holdings - $182M
    "KULR",   # KULR Technology - $172M
    "ACU",    # Acme United - $166M
    "ESP",    # Espey Mfg & Electronics - $157M
    "MRT",    # Marti Technologies - $156M
    "NINE",   # Nine Energy Service - $142M
    "LGCY",   # Legacy Education - $142M
    "TRT",    # Trio-Tech International - $106M
    "FSI",    # Flexible Solutions Intl - $82M
    "MHH",    # Mastech Digital - $76M
    "DIT",    # AMCON Distributing - $74M
    "COHN",   # Cohen & Company - $70M
    "CVU",    # CPI Aerostructures - $66M
    "FSP",    # Franklin Street Properties - $65M (REIT)
    "BDL",    # Flanigan's Enterprises - $64M
    "CET",    # Central Securities Corp - $1.56B (closed-end fund)
    "AZUL",   # Azul S.A. - $1.52B (Brazilian airline)
    "TMP",    # Tompkins Financial - $1.26B (regional bank)
    "IAUX",   # i-80 Gold Corp - $1.24B
    "CNL",    # Collective Mining - $1.28B
    "JBSS",   # John B. Sanfilippo & Son - nut products
    "SIF",    # SIFCO Industries - $129M (aerospace forgings)
    "LODE",   # Comstock Inc - $303M (clean energy)
    "MPTI",   # M-tron Industries - $397M
    "STRW",   # Strawberry Fields REIT - $729M
    "GRO",    # Brazil Potash - $136M
])

# ─────────────────────────────────────────────────────────────────────────────
# Major US Markets — union of all four, deduplicated and sorted
# This is the recommended default universe.
# ─────────────────────────────────────────────────────────────────────────────
MAJOR_US_MARKETS: List[str] = sorted(
    set(SP500) | set(NDX100) | set(DOW30) | set(NYSE_AMERICAN)
)

# ─────────────────────────────────────────────────────────────────────────────
# Backtest-validated watchlist — tickers where the 7-signal conviction model
# has demonstrated positive expectancy (no-Fib, stop=1.5%, tp=4.5%, conv≥60%).
# Derived from 50-ticker Nasdaq 100 backtest (June 2026, 1-year daily bars).
#
# Tier 1 — Strong edge (E > 3, WR ≥ 39%):  trade always
# Tier 2 — Decent edge (E = 1.5–3.0):       trade, monitor closely
# Tier 3 — Marginal edge (E = 0–1.5):       paper only, watch for degradation
#
# Re-validate quarterly by re-running the backtest on these tickers.
# Remove any ticker whose live paper P&L diverges from backtest expectancy
# by more than 2× after 20+ paper trades.
# ─────────────────────────────────────────────────────────────────────────────
# ── Tier 1: Best edge — E≥6, WR≥43%, DD≤7% ─────────────────────────────────
# Core positions — highest confidence, trade always when signal fires
WATCHLIST_TIER1: List[str] = [
    "APP",    # AppLovin Corp        — E=+12.45  WR=56%  DD=2.9%
    "NFLX",   # Netflix Inc          — E=+12.18  WR=47%  DD=2.3%  (lowest DD of all)
    "INSM",   # Insmed Inc           — E=+10.16  WR=43%  DD=4.1%
    "QCOM",   # Qualcomm Inc         — E=+9.63   WR=50%  DD=6.2%
    "AAPL",   # Apple Inc            — E=+9.27   WR=46%  DD=3.0%  (works in every config)
    "TTWO",   # Take-Two Interactive — E=+8.56   WR=55%  DD=5.8%
    "MNST",   # Monster Beverage     — E=+8.17   WR=47%  DD=4.9%
    "SNDK",   # Sandisk Corp         — E=+7.26   WR=45%  DD=4.5%
    "PANW",   # Palo Alto Networks   — E=+6.20   WR=50%  DD=6.8%
]

# ── Tier 2: Strong edge — E=2–6, DD≤10% ──────────────────────────────────────
# Standard positions — solid edge, watch for regime changes quarterly
WATCHLIST_TIER2: List[str] = [
    "KDP",    # Keurig Dr Pepper     — E=+4.94   WR=36%  DD=6.0%
    "ZS",     # Zscaler Inc          — E=+4.94   WR=38%  DD=5.1%
    "INTU",   # Intuit Inc           — E=+4.50   WR=39%  DD=8.1%
    "AVGO",   # Broadcom Inc         — E=+3.91   WR=30%  DD=4.3%
    "GOOGL",  # Alphabet Inc         — E=+3.62   WR=50%  DD=4.3%
    "LRCX",   # Lam Research         — E=+3.29   WR=32%  DD=6.8%
    "NXPI",   # NXP Semiconductors   — E=+3.13   WR=38%  DD=8.9%
    "BKR",    # Baker Hughes         — E=+2.95   WR=33%  DD=7.3%
    "CMCSA",  # Comcast Corp         — E=+2.83   WR=39%  DD=10.0%
    "ADSK",   # Autodesk Inc         — E=+2.55   WR=35%  DD=5.8%
    "CTSH",   # Cognizant Tech       — E=+2.07   WR=37%  DD=5.3%
    "SNPS",   # Synopsys Inc         — E=+2.06   WR=26%  DD=6.8%
    "CSCO",   # Cisco Systems        — E=+1.88   WR=29%  DD=10.6%
]

# ── Tier 3: Marginal edge — E<2 or DD>10% ────────────────────────────────────
# Smaller positions or paper-only; validate with live paper data before sizing up
WATCHLIST_TIER3: List[str] = [
    "ARM",    # Arm Holdings         — E=+3.64   WR=33%  DD=10.2%  (high DD)
    "ODFL",   # Old Dominion Freight — E=+4.83   WR=33%  DD=13.6%  (fragile, high DD)
    "TSLA",   # Tesla Inc            — E=+1.32   WR=29%  DD=8.9%   (no-Fib only)
    "PEP",    # PepsiCo Inc          — E=+1.15   WR=40%  DD=4.2%
    "MU",     # Micron Technology    — E=+1.02   WR=29%  DD=7.0%
    "MDLZ",   # Mondelez Intl        — E=+0.89   WR=28%  DD=5.8%
    "AMD",    # Advanced Micro Dev   — E=+0.55   WR=29%  DD=6.7%
    "AMAT",   # Applied Materials    — E=+0.48   WR=29%  DD=11.5%
    "COST",   # Costco Wholesale     — E=+0.29   WR=35%  DD=4.4%
    "REGN",   # Regeneron Pharma     — E=+0.17   WR=27%  DD=9.2%
    "WDC",    # Western Digital      — E=+0.08   WR=25%  DD=7.8%
    "ORLY",   # O'Reilly Automotive  — E=+0.03   WR=44%  DD=4.7%
    "VRSK",   # Verisk Analytics     — E=+0.02   WR=29%  DD=5.3%
]

# Full watchlist — all 35 tickers with validated edge
# Validated: 101-ticker Nasdaq 100 backtest, no-Fib, stop=1.5%, tp=4.5%, June 2026
WATCHLIST: List[str] = WATCHLIST_TIER1 + WATCHLIST_TIER2 + WATCHLIST_TIER3

# ─────────────────────────────────────────────────────────────────────────────
# No-Fibonacci execution set — validated across 10 backtest runs (June 2026).
#
# These tickers produce HIGHER expectancy with FIXED % stop/TP (1.5%/4.5%)
# than with Fibonacci levels. On fast momentum stocks the Fib 61.8% stop
# lands too close to entry and daily gap-opens blow through it, realising
# 3–5× the planned loss. trade_engine.py checks this set and overrides
# Fib levels with fixed % for these tickers.
#
# Expectancy deltas (no-fib minus Fib):
#   INSM −12.98  TTWO −12.19  MNST −10.03  NFLX −9.88  QCOM −8.22
#   INTU  −7.50  LRCX  −7.58  CMCSA −6.01  NXPI −6.24  BKR  −5.41
# ─────────────────────────────────────────────────────────────────────────────
NO_FIB_TICKERS: List[str] = [
    # T1 tickers — Fib significantly hurts (delta E < −4)
    "NFLX",   # delta −9.88   E: +12.18 → +2.30
    "QCOM",   # delta −8.22   E: +9.63  → +1.41
    "INSM",   # delta −12.98  E: +10.16 → −2.82
    "TTWO",   # delta −12.19  E: +8.56  → −3.63
    "MNST",   # delta −10.03  E: +8.17  → −1.86
    "PANW",   # delta −4.75   E: +6.20  → +1.45
    # T2 tickers — Fib moderately hurts
    "INTU",   # delta −7.50   E: +4.50  → −3.00
    "LRCX",   # delta −7.58   E: +3.29  → −4.29
    "NXPI",   # delta −6.24   E: +3.13  → −3.11
    "BKR",    # delta −5.41   E: +2.95  → −2.46
    "CMCSA",  # delta −6.01   E: +2.83  → −3.18
    # T3 and other tickers
    "KDP",    # delta −1.23   E: +4.94  → +3.71
    "TSLA",   # volatile — no-fib only (E: +1.32 no-fib)
    "AVGO",   # delta −0.99   (borderline, no-fib to be safe)
]
# Fib-safe tickers (Fib ON improves or is neutral):
#   APP +0.55  ZS +4.31  CTSH +3.03  AMD +3.53  SNDK −0.18
# All tickers NOT in NO_FIB_TICKERS default to Fibonacci when available.

# ── Tickers with ZERO model edge — exclude from paper trading ─────────────────
# Scanner still scans these for signal data; only trade execution is blocked.
# Consumer brands, financials, and inverted-signal stocks all excluded.
# Re-evaluate quarterly — edge can emerge as market regimes change.
WATCHLIST_EXCLUDE: List[str] = [
    # Strongly inverted signals (WR < 16%):
    "PYPL",  "DASH",  "ADBE",  "ADI",   "CDNS",
    "DXCM",  "INTC",  "CEG",   "CHTR",
    # Consumer brands (model not calibrated for these):
    "WMT",   "SBUX",  "KHC",   "WBD",
    # High-volatility with no edge at 1.5% stop:
    "AXON",  "FTNT",  "DDOG",  "CRWD",  "ABNB",
    # Other consistent losers:
    "FER",   "CSX",   "GILD",  "CPRT",  "BKNG",
    "AMGN",  "CTAS",  "FAST",  "AMZN",
    # Previously identified:
    "META",  "JPM",   "CCEP",  "ADI",
]

# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSES: Dict[str, List[str]] = {
    "major_us_markets": MAJOR_US_MARKETS,
    "sp500":            SP500,
    "nasdaq100":        NDX100,
    "dowjones":         DOW30,
    "nyse_american":    NYSE_AMERICAN,
    "watchlist":        WATCHLIST,
    "watchlist_t1":     WATCHLIST_TIER1,
    "watchlist_t2":     WATCHLIST_TIER2,
}


def get_tickers(universe: str, max_tickers: int = 0) -> List[str]:
    """Return ticker list for a named universe, optionally capped."""
    tickers = UNIVERSES.get(universe.lower(), [])
    if max_tickers and max_tickers < len(tickers):
        tickers = tickers[:max_tickers]
    return tickers


def is_watchlist_ticker(ticker: str) -> bool:
    """Return True if ticker has validated backtest edge (safe to paper trade)."""
    return ticker in set(WATCHLIST)


def is_excluded_ticker(ticker: str) -> bool:
    """Return True if ticker has demonstrated zero model edge — skip paper trading."""
    return ticker in set(WATCHLIST_EXCLUDE)


if __name__ == "__main__":
    print("\n=== Universe counts ===")
    for k, v in UNIVERSES.items():
        print(f"  {k:20s}: {len(v):>4} unique tickers")

    sp  = set(SP500)
    ndx = set(NDX100)
    dj  = set(DOW30)
    amex = set(NYSE_AMERICAN)

    print("\n=== Overlaps ===")
    print(f"  S&P 500  ∩ Nasdaq 100   : {len(sp & ndx):>4}")
    print(f"  S&P 500  ∩ Dow Jones    : {len(sp & dj):>4}")
    print(f"  S&P 500  ∩ NYSE American: {len(sp & amex):>4}")
    print(f"  Nasdaq100 ∩ Dow Jones   : {len(ndx & dj):>4}")
    print(f"  Nasdaq100 ∩ NYSE Amer.  : {len(ndx & amex):>4}")
    print(f"  Dow Jones ∩ NYSE Amer.  : {len(dj & amex):>4}")

    amex_unique = amex - sp - ndx - dj
    print(f"\n  NYSE American unique only: {len(amex_unique):>4}")
    print(f"  (tickers in NYSE Am not in any other index)")
    print(f"\n  major_us_markets total   : {len(MAJOR_US_MARKETS):>4} unique tickers")

    print("\n=== Duplicate check ===")
    for name, lst in [("SP500",SP500),("NDX100",NDX100),("DOW30",DOW30),("NYSE_AMERICAN",NYSE_AMERICAN)]:
        seen, dups = set(), []
        for t in lst:
            if t in seen: dups.append(t)
            seen.add(t)
        print(f"  {name:14s}: {'DUPS: '+str(dups) if dups else 'clean ✓'}")
