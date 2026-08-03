"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SECTIONS = [
  {
    label: "Intraday",
    links: [
      { href: "/", label: "Today" },
      { href: "/history", label: "Historical Scans" },
      { href: "/trades", label: "Trades" },
    ],
  },
  {
    label: "Daily Momentum",
    links: [
      { href: "/momentum", label: "Daily Scans" },
      { href: "/momentum/history", label: "Historical Scans" },
    ],
  },
  {
    label: "Machine Learning",
    links: [
      { href: "/ml", label: "Model Weights" },
      { href: "/ml/data", label: "Training Data" },
    ],
  },
  {
    label: "On-Demand",
    links: [{ href: "/analyze", label: "Analyze Ticker" }],
  },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href === "/momentum") return pathname === "/momentum";
  if (href === "/momentum/history") {
    return pathname === "/momentum/history" || pathname.startsWith("/momentum/history/");
  }
  if (href === "/ml") return pathname === "/ml";
  return pathname.startsWith(href);
}

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="sidebar-nav">
      {SECTIONS.map((section) => (
        <div key={section.label} className="nav-section">
          <div className="nav-section-label">{section.label}</div>
          {section.links.map((l) => {
            const active = isActive(pathname, l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`nav-item${active ? " active" : ""}`}
              >
                {l.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
