// Chart tokens. Categorical slots validated for CVD separation (dataviz palette, light mode).
export const C = {
  s1: "#257de0", // blue
  s2: "#f47230", // orange
  s3: "#00b894", // aqua
  ink: "#191919",
  ink2: "#666666",
  grid: "#e7e7e7",
  band: "#b6d5f8",
  good: "#0aac23",
  warning: "#fbb315",
  serious: "#f18a59",
  critical: "#dc3c3d",
};

export const axis = { tick: { fontSize: 11, fill: C.ink2 }, stroke: C.grid, tickLine: false } as const;
export const grid = { stroke: C.grid, vertical: false } as const;
export const tooltipStyle = {
  contentStyle: { borderRadius: 8, border: "1px solid #e3e6ea", fontSize: 12, boxShadow: "0 4px 16px rgba(15,39,66,.08)" },
  cursor: { stroke: C.ink2, strokeDasharray: "3 3" },
} as const;
