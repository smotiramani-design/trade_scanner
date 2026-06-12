import { useState, useEffect, useCallback } from "react"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from "recharts"

const API = ""   // same origin in production; proxied in dev via vite

// ── API helpers ───────────────────────────────────────────────────────────────
const get = (url) => fetch(API + url).then(r => r.json())
const post = (url, params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return fetch(`${API}${url}${qs ? "?" + qs : ""}`, { method: "POST" }).then(r => r.json())
}

// ── Small components ──────────────────────────────────────────────────────────
const Spinner = () => <div className="spinner" />

const SignalChips = ({ signals = [] }) => (
  <div className="signal-chips">
    {signals.map((s, i) => (
      <span key={i} className={`chip ${s.bias}`} title={s.detail}>{s.name}</span>
    ))}
  </div>
)

const ConvictionBar = ({ pct = 0, dir = "bull" }) => (
  <div className="conviction-row">
    <span className="conviction-label">Conviction</span>
    <div className="conviction-bar-bg">
      <div className={`conviction-fill ${dir}`} style={{ width: `${pct}%` }} />
    </div>
    <span className="conviction-pct">{pct.toFixed(0)}%</span>
  </div>
)

const FibRow = ({ fib }) => {
  if (!fib) return null
  return (
    <div className="fib-row">
      {fib.entry_price && <div className="fib-item"><label>Entry </label><span>${fib.entry_price?.toFixed(2)}</span></div>}
      {fib.stop_loss   && <div className="fib-item"><label>Stop  </label><span style={{color:"var(--bear)"}}>${fib.stop_loss?.toFixed(2)}</span></div>}
      {fib.target_1    && <div className="fib-item"><label>T1    </label><span style={{color:"var(--bull)"}}>${fib.target_1?.toFixed(2)}</span></div>}
      {fib.rr_t1       && <div className="fib-item"><label>R/R   </label><span>{fib.rr_t1?.toFixed(1)}x</span></div>}
    </div>
  )
}

const PickCard = ({ item }) => {
  const { analysis: ta, conviction: cs } = item
  if (!ta) return null
  const dir    = cs?.direction || (ta.net_score > 0 ? "bullish" : "bearish")
  const isUp   = ta.chg_pct >= 0
  const grade  = cs?.grade || "—"
  return (
    <div className={`pick-card ${dir === "bullish" ? "bull-card" : "bear-card"}`}>
      <div className="card-head">
        <div>
          <div className="card-ticker">
            {ta.ticker}
            <span className="grade-badge" style={{marginLeft:8}}>{grade}</span>
          </div>
          <div className="card-name">{ta.company_name}</div>
        </div>
        <div>
          <div className="card-price">${ta.price?.toFixed(2)}</div>
          <div className={`card-chg ${isUp ? "up" : "down"}`}>{isUp ? "▲" : "▼"} {Math.abs(ta.chg_pct).toFixed(2)}%</div>
        </div>
      </div>
      <div className="card-body">
        {ta.earnings_soon && <div className="earnings-flag">⚠ Earnings within 2 days</div>}
        <SignalChips signals={ta.signals} />
        <ConvictionBar pct={cs?.conviction_pct || 0} dir={dir === "bullish" ? "bull" : "bear"} />
        {!ta.mtf_aligned && <div className="mtf-badge conflict">⚡ MTF conflict — {ta.mtf_detail}</div>}
        <FibRow fib={ta.fib} />
        {cs?.analysis && (
          <div style={{fontSize:11,color:"var(--muted)",marginTop:8,lineHeight:1.5}}>
            {cs.analysis.slice(0, 120)}{cs.analysis.length > 120 ? "…" : ""}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Pages ─────────────────────────────────────────────────────────────────────

const Dashboard = () => {
  const [data, setData]         = useState(null)
  const [scanning, setScanning] = useState(false)
  const [universe, setUniverse] = useState("watchlist")
  const [toast, setToast]       = useState(null)

  const showToast = (msg, type = "success") => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const fetchLatest = useCallback(() => {
    get("/api/results/latest?top_n=5").then(d => {
      if (!d.error) setData(d)
    })
  }, [])

  useEffect(() => { fetchLatest() }, [fetchLatest])

  // Poll while scan is running
  useEffect(() => {
    if (!scanning) return
    const t = setInterval(() => {
      get("/api/health").then(h => {
        if (!h.scan_running) {
          setScanning(false)
          fetchLatest()
          showToast("Scan complete!")
          clearInterval(t)
        }
      })
    }, 2000)
    return () => clearInterval(t)
  }, [scanning, fetchLatest])

  const triggerScan = () => {
    setScanning(true)
    post("/api/scan", { universe }).then(r => {
      if (r.status === "already_running") {
        showToast("Scan already running", "error")
        setScanning(false)
      }
    })
  }

  const bulls = data?.bulls || []
  const bears = data?.bears || []

  return (
    <div>
      <div className="topbar">
        <div>
          <div className="page-title">Signal Dashboard</div>
          <div className="page-sub">
            {data?.timestamp ? `Last scan: ${new Date(data.timestamp).toLocaleTimeString()}  ·  ${data.total || 0} tickers` : "No scan yet"}
          </div>
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <select value={universe} onChange={e => setUniverse(e.target.value)}
            style={{background:"var(--bg3)",border:"1px solid var(--border)",color:"var(--text)",padding:"7px 10px",borderRadius:6,fontSize:13}}>
            <option value="watchlist">Watchlist (35)</option>
            <option value="watchlist_t1">Tier 1 (9)</option>
            <option value="nasdaq100">Nasdaq 100</option>
            <option value="sp500">S&P 500</option>
          </select>
          <button className="btn btn-primary" onClick={triggerScan} disabled={scanning}>
            {scanning ? <><Spinner /> Scanning…</> : "▶ Run Scan"}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-label">Total Scanned</div>
          <div className="stat-value accent">{data?.total || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Bull Picks</div>
          <div className="stat-value bull">{bulls.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Bear Picks</div>
          <div className="stat-value bear">{bears.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Universe</div>
          <div className="stat-value" style={{fontSize:14,paddingTop:6}}>{data?.universe || "—"}</div>
        </div>
      </div>

      {/* Bullish picks */}
      <div className="section-header">
        <span className="section-title" style={{color:"var(--bull)"}}>▲ Top Bullish Picks</span>
      </div>
      {bulls.length > 0
        ? <div className="picks-grid">{bulls.map((item, i) => <PickCard key={i} item={item} />)}</div>
        : <div className="empty-state"><div className="icon">📊</div><p>No bullish picks yet</p><div className="hint">Run a scan to see signals</div></div>}

      {/* Bearish picks */}
      {bears.length > 0 && <>
        <div className="section-header" style={{marginTop:24}}>
          <span className="section-title" style={{color:"var(--bear)"}}>▼ Top Bearish Picks</span>
        </div>
        <div className="picks-grid">{bears.map((item, i) => <PickCard key={i} item={item} />)}</div>
      </>}

      {toast && <div className={`toast ${toast.type}`}>{toast.msg}</div>}
    </div>
  )
}

const Positions = () => {
  const [data, setData] = useState(null)
  useEffect(() => { get("/api/positions").then(setData) }, [])
  if (!data) return <div style={{padding:40}}><Spinner /></div>
  if (data.error) return <div className="empty-state"><p>{data.error}</p></div>

  const positions = data.positions || []
  const acct      = data.account   || {}

  return (
    <div>
      <div className="topbar">
        <div><div className="page-title">Open Positions</div>
          <div className="page-sub">{acct.paper ? "Paper Trading" : "⚠ Live Trading"}</div>
        </div>
      </div>
      <div className="stats-row">
        <div className="stat-card"><div className="stat-label">Equity</div>
          <div className="stat-value accent">${acct.equity?.toLocaleString("en-US", {maximumFractionDigits:0})}</div></div>
        <div className="stat-card"><div className="stat-label">Cash</div>
          <div className="stat-value">${acct.cash?.toLocaleString("en-US", {maximumFractionDigits:0})}</div></div>
        <div className="stat-card"><div className="stat-label">Buying Power</div>
          <div className="stat-value">${acct.buying_power?.toLocaleString("en-US", {maximumFractionDigits:0})}</div></div>
        <div className="stat-card"><div className="stat-label">Positions</div>
          <div className="stat-value">{positions.length}</div></div>
      </div>
      {positions.length === 0
        ? <div className="empty-state"><div className="icon">📂</div><p>No open positions</p></div>
        : positions.map((p, i) => (
          <div key={i} className="position-row">
            <div>
              <div className="pos-ticker">{p.symbol}</div>
              <div className="pos-detail">{p.qty} shares · {p.side} · avg ${p.avg_entry?.toFixed(2)}</div>
            </div>
            <div style={{textAlign:"right"}}>
              <div className="pos-pnl" style={{color: p.unrealized_pl >= 0 ? "var(--bull)" : "var(--bear)"}}>
                {p.unrealized_pl >= 0 ? "+" : ""}${p.unrealized_pl?.toFixed(2)}
              </div>
              <div className="pos-detail">{p.unrealized_pct >= 0 ? "+" : ""}{p.unrealized_pct?.toFixed(2)}% · ${p.current_price?.toFixed(2)}</div>
            </div>
          </div>
        ))}
    </div>
  )
}

const Performance = () => {
  const [data, setData] = useState(null)
  useEffect(() => { get("/api/performance").then(setData) }, [])
  if (!data) return <div style={{padding:40}}><Spinner /></div>

  if (data.total_trades === 0) return (
    <div className="empty-state"><div className="icon">📈</div>
      <p>No closed trades yet</p><div className="hint">P&L data appears after first paper trade closes</div></div>
  )

  const pnlColor = data.total_pnl_usd >= 0 ? "var(--bull)" : "var(--bear)"
  const wrColor  = data.win_rate >= 50 ? "var(--bull)" : "var(--bear)"

  return (
    <div>
      <div className="topbar"><div><div className="page-title">Paper Trade Performance</div>
        <div className="page-sub">{data.total_trades} closed trades</div></div></div>

      <div className="perf-grid">
        <div className="perf-card"><div className="perf-value" style={{color:wrColor}}>{data.win_rate?.toFixed(1)}%</div>
          <div className="perf-label">Win Rate · {data.wins}W / {data.losses}L</div></div>
        <div className="perf-card"><div className="perf-value" style={{color:"var(--accent)"}}>{data.avg_r?.toFixed(2)}R</div>
          <div className="perf-label">Avg R-Multiple</div></div>
        <div className="perf-card"><div className="perf-value" style={{color:pnlColor}}>${data.total_pnl_usd?.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
          <div className="perf-label">Total P&L</div></div>
        <div className="perf-card"><div className="perf-value" style={{color:"var(--accent)"}}>${data.expectancy?.toFixed(2)}</div>
          <div className="perf-label">Expectancy / Trade</div></div>
        <div className="perf-card"><div className="perf-value" style={{color:"var(--bull)"}}>${data.avg_win_usd?.toFixed(2)}</div>
          <div className="perf-label">Avg Win</div></div>
        <div className="perf-card"><div className="perf-value" style={{color:"var(--bear)"}}>${data.avg_loss_usd?.toFixed(2)}</div>
          <div className="perf-label">Avg Loss</div></div>
      </div>

      {data.best_trade && (
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
          <div className="stat-card">
            <div className="stat-label">Best Trade</div>
            <div style={{fontFamily:"var(--mono)",fontSize:16,color:"var(--bull)",marginTop:4}}>
              {data.best_trade.ticker} +${data.best_trade.pnl?.toFixed(2)}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Worst Trade</div>
            <div style={{fontFamily:"var(--mono)",fontSize:16,color:"var(--bear)",marginTop:4}}>
              {data.worst_trade.ticker} ${data.worst_trade.pnl?.toFixed(2)}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const Watchlist = () => {
  const [data, setData] = useState(null)
  useEffect(() => { get("/api/watchlist").then(setData) }, [])
  if (!data) return <div style={{padding:40}}><Spinner /></div>

  const tiers = [
    { label: "Tier 1 — Core (E ≥ 6)", tickers: data.tier1, color: "var(--bull)" },
    { label: "Tier 2 — Standard (E 2–6)", tickers: data.tier2, color: "var(--accent)" },
    { label: "Tier 3 — Monitor (E < 2)", tickers: data.tier3, color: "var(--muted)" },
  ]

  return (
    <div>
      <div className="topbar">
        <div><div className="page-title">Watchlist</div>
          <div className="page-sub">{data.total} validated tickers · {data.no_fib?.length} use fixed % stop</div>
        </div>
      </div>
      {tiers.map(tier => (
        <div key={tier.label} style={{marginBottom:24}}>
          <div className="section-header">
            <span className="section-title" style={{color:tier.color}}>{tier.label}</span>
          </div>
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {(tier.tickers || []).map(t => (
              <div key={t} style={{
                background:"var(--bg2)", border:"1px solid var(--border)",
                borderLeft:`3px solid ${tier.color}`,
                borderRadius:6, padding:"8px 12px",
                fontFamily:"var(--mono)", fontSize:14, fontWeight:500,
                display:"flex", alignItems:"center", gap:8,
              }}>
                {t}
                {data.no_fib?.includes(t) && (
                  <span style={{fontSize:10,color:"var(--gold)",background:"rgba(210,153,34,.15)",
                    padding:"1px 5px",borderRadius:3,border:"1px solid var(--gold)"}}>fixed%</span>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      <div className="section-header" style={{marginTop:8}}>
        <span className="section-title" style={{color:"var(--bear)"}}>Exclude List</span>
      </div>
      <div style={{display:"flex",flexWrap:"wrap",gap:6}}>
        {(data.exclude || []).map(t => (
          <span key={t} style={{fontFamily:"var(--mono)",fontSize:12,color:"var(--muted)",
            background:"var(--bg2)",border:"1px solid var(--border)",
            padding:"3px 8px",borderRadius:4,textDecoration:"line-through"}}>{t}</span>
        ))}
      </div>
    </div>
  )
}

// ── Sidebar nav items ─────────────────────────────────────────────────────────
const NAV = [
  { id: "dashboard",   label: "Dashboard",    icon: "📊" },
  { id: "positions",   label: "Positions",    icon: "💼" },
  { id: "performance", label: "Performance",  icon: "📈" },
  { id: "watchlist",   label: "Watchlist",    icon: "🎯" },
]

const PAGE = {
  dashboard:   Dashboard,
  positions:   Positions,
  performance: Performance,
  watchlist:   Watchlist,
}

// ── App root ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("dashboard")
  const [health, setHealth] = useState(null)
  useEffect(() => { get("/api/health").then(setHealth) }, [])
  const Page = PAGE[page] || Dashboard

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span>▲</span> SIGNAL SCANNER
        </div>
        <nav className="sidebar-nav">
          {NAV.map(n => (
            <div key={n.id} className={`nav-item ${page === n.id ? "active" : ""}`}
              onClick={() => setPage(n.id)}>
              <span>{n.icon}</span>
              <span>{n.label}</span>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          {health?.trade_enabled
            ? <span style={{color:"var(--bull)"}}>● Trading ON</span>
            : <span style={{color:"var(--muted)"}}>○ Trading OFF</span>}
          <br />
          {health?.alpaca_enabled ? "Alpaca: connected" : "Alpaca: —"}
        </div>
      </aside>
      <main className="main">
        <Page />
      </main>
    </div>
  )
}
