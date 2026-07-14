"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface Point {
  label: string;
  auc: number | null; // 0–100 (AUC × 100)
  acc: number | null; // 0–100 (test accuracy %)
}

export default function MlMetricHistoryChart({ data }: { data: Point[] }) {
  if (data.length < 2) {
    return (
      <div style={{ color: "var(--muted)", fontSize: 13, padding: "20px 0" }}>
        Need at least two saved runs to chart progress over time. Re-run the tuner
        weekly with <code>--save-db</code> and this will fill in.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
        <CartesianGrid stroke="#2a2a2a" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="label"
          stroke="#8a8a8a"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
        />
        <YAxis
          domain={[0, 100]}
          stroke="#8a8a8a"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
          width={40}
        />
        <Tooltip
          contentStyle={{
            background: "#0a0a0a",
            border: "1px solid #2a2a2a",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: "#f0f0f0" }}
          formatter={(v: number, name: string) => [
            v == null ? "—" : `${v.toFixed(1)}${name === "AUC ×100" ? "" : "%"}`,
            name,
          ]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          type="monotone"
          dataKey="auc"
          name="AUC ×100"
          stroke="#3FB950"
          strokeWidth={2}
          dot={{ r: 3, fill: "#3FB950" }}
          activeDot={{ r: 5 }}
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="acc"
          name="Test acc"
          stroke="#D29922"
          strokeWidth={2}
          dot={{ r: 3, fill: "#D29922" }}
          activeDot={{ r: 5 }}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
