"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Point {
  et_time: string;
  conviction: number;
}

export default function ConvictionChart({ data }: { data: Point[] }) {
  if (!data.length) {
    return (
      <div style={{ color: "var(--muted)", fontSize: 13, padding: "20px 0" }}>
        No conviction data yet for this day.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
        <CartesianGrid stroke="#30363D" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="et_time"
          stroke="#7D8590"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
        />
        <YAxis
          domain={[0, 100]}
          stroke="#7D8590"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
          width={40}
        />
        <Tooltip
          contentStyle={{
            background: "#161B22",
            border: "1px solid #30363D",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: "#E6EDF3" }}
          formatter={(v: number) => [`${v.toFixed(0)}%`, "Top conviction"]}
        />
        <Line
          type="monotone"
          dataKey="conviction"
          stroke="#3FB950"
          strokeWidth={2}
          dot={{ r: 3, fill: "#3FB950" }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
