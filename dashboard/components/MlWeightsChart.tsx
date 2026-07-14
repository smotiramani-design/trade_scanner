"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface Item {
  signal: string;
  old: number | null;
  new: number | null;
}

export default function MlWeightsChart({ data }: { data: Item[] }) {
  if (!data.length) {
    return (
      <div style={{ color: "var(--muted)", fontSize: 13, padding: "20px 0" }}>
        No learned weights yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
        <CartesianGrid stroke="#2a2a2a" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="signal"
          stroke="#8a8a8a"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
        />
        <YAxis
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
          cursor={{ fill: "rgba(255,255,255,0.04)" }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="old" name="Hand-tuned" fill="#8a8a8a" radius={[2, 2, 0, 0]} />
        <Bar dataKey="new" name="Learned" fill="#3FB950" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
