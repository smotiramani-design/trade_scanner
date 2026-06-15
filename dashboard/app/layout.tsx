import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "Signal Desk",
  description: "Intraday and daily momentum signal dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="layout">
          <aside className="sidebar">
            <div className="sidebar-logo">
              SIGNAL<span>·</span>DESK
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
