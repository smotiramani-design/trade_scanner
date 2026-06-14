import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "Trade Scanner",
  description: "Intraday conviction picks dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="layout">
          <aside className="sidebar">
            <div className="sidebar-logo">
              TRADE<span>·</span>SCANNER
            </div>
            <Nav />
            <div className="sidebar-footer">paper · read-only</div>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
