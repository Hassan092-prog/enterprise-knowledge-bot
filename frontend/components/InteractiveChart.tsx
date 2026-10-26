"use client";

import React, { useState } from "react";

interface SeriesItem {
  name: string;
  data: number[];
  color?: string;
}

interface ChartSpec {
  type?: "bar" | "donut" | "line" | "pie";
  title?: string;
  xAxisLabel?: string;
  yAxisLabel?: string;
  labels: string[];
  series: SeriesItem[];
}

const PALETTE = [
  "#38bdf8", // Sky
  "#818cf8", // Indigo
  "#34d399", // Emerald
  "#fbbf24", // Amber
  "#f472b6", // Pink
  "#a78bfa", // Violet
  "#2dd4bf", // Teal
  "#fb7185", // Rose
];

function formatValue(val: number, isCurrency: boolean = false): string {
  const prefix = isCurrency ? "$" : "";
  if (Math.abs(val) >= 1_000_000) {
    return `${prefix}${(val / 1_000_000).toFixed(2)}M`;
  }
  if (Math.abs(val) >= 1_000) {
    return `${prefix}${val.toLocaleString()}`;
  }
  return `${prefix}${val.toLocaleString()}`;
}

export default function InteractiveChart({ content }: { content: string }) {
  const [viewMode, setViewMode] = useState<"chart" | "table">("chart");
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [copied, setCopied] = useState<boolean>(false);

  let spec: ChartSpec | null = null;
  try {
    const cleaned = content.trim().replace(/^```(?:json|chart)?\s*/i, "").replace(/```$/, "").trim();
    spec = JSON.parse(cleaned);
  } catch {
    // If not valid JSON, return raw preformatted text
    return (
      <pre className="p-3 bg-paper-3 border border-rule rounded-base font-mono text-xs text-ink overflow-x-auto">
        {content}
      </pre>
    );
  }

  if (!spec || !spec.labels || !spec.series || spec.series.length === 0) {
    return (
      <pre className="p-3 bg-paper-3 border border-rule rounded-base font-mono text-xs text-ink overflow-x-auto">
        {content}
      </pre>
    );
  }

  const primarySeries = spec.series[0];
  const chartType = spec.type || "bar";
  const title = spec.title || "Tabular BI Visualization";
  const labels = spec.labels || [];
  const data = primarySeries.data || [];

  const isCurrency = /salary|compensation|revenue|cost|spend|budget|usd|\$|bonus|earnings|payroll/i.test(
    `${title} ${primarySeries.name || ""}`
  );

  const total = data.reduce((sum, v) => sum + (Number(v) || 0), 0);
  const maxVal = Math.max(...data.map(Number), 1);

  const handleCopyData = () => {
    try {
      const exportRows = labels.map((lbl, idx) => ({
        category: lbl,
        value: data[idx],
      }));
      navigator.clipboard.writeText(JSON.stringify(exportRows, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error("Copy failed:", e);
    }
  };

  return (
    <div className="my-4 rounded-card border border-rule bg-paper-2 shadow-sm overflow-hidden font-body animate-backdrop-fade">
      {/* CHART HEADER TOOLBAR */}
      <div className="px-4 py-2.5 bg-paper-3/80 border-b border-rule flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />
          <h4 className="text-xs font-mono font-semibold uppercase tracking-wider text-ink">
            {title}
          </h4>
          <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase bg-accent-subtle text-accent border border-accent/30 font-bold">
            {chartType.toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="flex rounded border border-rule bg-paper p-0.5 text-[10px] font-mono">
            <button
              type="button"
              onClick={() => setViewMode("chart")}
              className={`px-2 py-0.5 rounded cursor-pointer transition-colors ${
                viewMode === "chart" ? "bg-accent text-black font-semibold" : "text-muted hover:text-ink"
              }`}
            >
              Chart
            </button>
            <button
              type="button"
              onClick={() => setViewMode("table")}
              className={`px-2 py-0.5 rounded cursor-pointer transition-colors ${
                viewMode === "table" ? "bg-accent text-black font-semibold" : "text-muted hover:text-ink"
              }`}
            >
              Table
            </button>
          </div>

          <button
            type="button"
            onClick={handleCopyData}
            className="px-2 py-1 rounded bg-paper hover:bg-paper-2 border border-rule text-[10px] font-mono text-ink transition-colors cursor-pointer"
            title="Copy structured series as JSON"
          >
            {copied ? "✓ Copied" : "Copy Data"}
          </button>
        </div>
      </div>

      {/* CHART BODY */}
      <div className="p-4 sm:p-5">
        {viewMode === "table" ? (
          /* TABULAR FALLBACK VIEW */
          <div className="overflow-x-auto rounded-base border border-rule bg-paper custom-scrollbar">
            <table className="w-full text-xs text-left border-collapse font-mono">
              <thead>
                <tr className="bg-paper-3 border-b border-rule text-muted uppercase text-[10px] tracking-wider">
                  <th className="p-2.5">Category</th>
                  <th className="p-2.5 text-right">{primarySeries.name || "Value"}</th>
                  <th className="p-2.5 text-right">Share (%)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule font-body">
                {labels.map((lbl, idx) => {
                  const val = Number(data[idx]) || 0;
                  const pct = total > 0 ? ((val / total) * 100).toFixed(1) : "0.0";
                  return (
                    <tr key={idx} className="hover:bg-paper-2/60 transition-colors">
                      <td className="p-2.5 text-ink font-medium">{lbl}</td>
                      <td className="p-2.5 text-right font-mono text-ink-secondary">
                        {isCurrency ? formatValue(val, true) : val.toLocaleString()}
                      </td>
                      <td className="p-2.5 text-right font-mono text-muted">{pct}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : chartType === "donut" || chartType === "pie" ? (
          /* NATIVE SVG DONUT / BREAKDOWN CHART */
          <div className="flex flex-col sm:flex-row items-center justify-center gap-6 py-2">
            <div className="relative w-44 h-44 shrink-0">
              <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                {(() => {
                  let accumulatedPercent = 0;
                  return data.map((val, idx) => {
                    const num = Number(val) || 0;
                    const percent = total > 0 ? (num / total) * 100 : 0;
                    const dashArray = `${percent} ${100 - percent}`;
                    const dashOffset = -accumulatedPercent;
                    accumulatedPercent += percent;
                    const color = PALETTE[idx % PALETTE.length];
                    const isHovered = hoveredIndex === idx;

                    return (
                      <circle
                        key={idx}
                        cx="50"
                        cy="50"
                        r="38"
                        fill="transparent"
                        stroke={color}
                        strokeWidth={isHovered ? "14" : "11"}
                        strokeDasharray={dashArray}
                        strokeDashoffset={dashOffset}
                        pathLength="100"
                        onMouseEnter={() => setHoveredIndex(idx)}
                        onMouseLeave={() => setHoveredIndex(null)}
                        className="transition-all duration-200 cursor-pointer"
                        style={{ opacity: hoveredIndex === null || isHovered ? 1 : 0.4 }}
                      />
                    );
                  });
                })()}
              </svg>

              {/* CENTER DONUT TOTAL READOUT */}
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-[10px] font-mono uppercase tracking-wider text-muted">Total</span>
                <span className="text-sm font-mono font-bold text-ink">
                  {hoveredIndex !== null ? formatValue(data[hoveredIndex], isCurrency) : formatValue(total, isCurrency)}
                </span>
                {hoveredIndex !== null && (
                  <span className="text-[10px] font-mono text-accent truncate max-w-[90px]">
                    {labels[hoveredIndex]}
                  </span>
                )}
              </div>
            </div>

            {/* DONUT LEGEND */}
            <div className="flex-1 w-full max-w-xs space-y-1.5 font-mono text-xs">
              {labels.map((lbl, idx) => {
                const val = Number(data[idx]) || 0;
                const pct = total > 0 ? ((val / total) * 100).toFixed(1) : "0";
                const color = PALETTE[idx % PALETTE.length];
                const isHovered = hoveredIndex === idx;

                return (
                  <div
                    key={idx}
                    onMouseEnter={() => setHoveredIndex(idx)}
                    onMouseLeave={() => setHoveredIndex(null)}
                    className={`flex items-center justify-between p-1.5 rounded transition-colors cursor-pointer ${
                      isHovered ? "bg-paper-3 text-ink" : "text-muted hover:text-ink"
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span className="w-2.5 h-2.5 rounded-xs shrink-0" style={{ backgroundColor: color }} />
                      <span className="truncate">{lbl}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="font-semibold text-ink">
                        {isCurrency ? formatValue(val, true) : val.toLocaleString()}
                      </span>
                      <span className="text-[10px] text-muted w-10 text-right">({pct}%)</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          /* NATIVE SVG RESPONSIVE HORIZONTAL BAR CHART */
          <div className="space-y-3">
            {labels.map((lbl, idx) => {
              const val = Number(data[idx]) || 0;
              const ratio = Math.max(0, Math.min(1, val / maxVal));
              const percentWidth = (ratio * 100).toFixed(1);
              const color = PALETTE[idx % PALETTE.length];
              const isHovered = hoveredIndex === idx;

              return (
                <div
                  key={idx}
                  onMouseEnter={() => setHoveredIndex(idx)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  className="space-y-1 group cursor-pointer"
                >
                  <div className="flex justify-between items-center text-xs font-mono">
                    <span className={`transition-colors truncate max-w-[65%] ${isHovered ? "text-ink font-semibold" : "text-ink-secondary"}`}>
                      {lbl}
                    </span>
                    <span className="text-ink font-mono font-bold">
                      {formatValue(val, isCurrency)}
                    </span>
                  </div>

                  <div className="h-5 w-full bg-paper rounded-xs overflow-hidden border border-rule relative">
                    <div
                      className="h-full rounded-xs transition-all duration-300 relative group-hover:brightness-110"
                      style={{
                        width: `${percentWidth}%`,
                        backgroundColor: color,
                        opacity: hoveredIndex === null || isHovered ? 0.9 : 0.45,
                      }}
                    >
                      {isHovered && (
                        <div className="absolute inset-0 bg-white/10 animate-pulse pointer-events-none" />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* BASELINE AXIS FOOTER */}
            <div className="pt-2 border-t border-rule/60 flex justify-between text-[10px] font-mono text-muted">
              <span>0</span>
              <span>Mid: {formatValue(maxVal / 2, isCurrency)}</span>
              <span>Max: {formatValue(maxVal, isCurrency)}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
