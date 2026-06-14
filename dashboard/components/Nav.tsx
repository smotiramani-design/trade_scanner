"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Today" },
  { href: "/history", label: "History" },
  { href: "/trades", label: "Trades" },
  { href: "/momentum", label: "Momentum" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  if (href === "/momentum") return pathname === "/momentum" || pathname.startsWith("/momentum/");
  return pathname.startsWith(href);
}

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="sidebar-nav">
      {LINKS.map((l) => {
        const active = isActive(pathname, l.href);
        return (
          <Link key={l.href} href={l.href} className={`nav-item${active ? " active" : ""}`}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
