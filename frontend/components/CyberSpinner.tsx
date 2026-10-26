"use client";

import React from "react";

interface CyberSpinnerProps {
  size?: "xs" | "sm" | "md" | "lg";
  variant?: "accent" | "emerald" | "brass" | "ink" | "muted";
  className?: string;
  label?: string;
}

export function CyberSpinner({
  size = "sm",
  variant = "accent",
  className = "",
  label,
}: CyberSpinnerProps) {
  const sizeMap = {
    xs: { dim: 12, stroke: 1.5, box: "w-3 h-3" },
    sm: { dim: 16, stroke: 1.75, box: "w-4 h-4" },
    md: { dim: 20, stroke: 2, box: "w-5 h-5" },
    lg: { dim: 28, stroke: 2.25, box: "w-7 h-7" },
  };

  const colorMap = {
    accent: "text-accent",
    emerald: "text-emerald",
    brass: "text-amber-400",
    ink: "text-ink",
    muted: "text-muted",
  };

  const { box } = sizeMap[size];
  const colorClass = colorMap[variant];

  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className={`relative inline-block ${box} shrink-0 ${colorClass}`}>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full animate-spin origin-center"
          style={{ animationDuration: "1.2s" }}
        >
          {/* Outer Segmented Reticle */}
          <circle
            cx="12"
            cy="12"
            r="9.5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeDasharray="16 10 8 10"
            strokeLinecap="round"
            className="opacity-90"
          />
        </svg>

        {/* Counter-rotating Inner Notch */}
        <svg
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="absolute inset-0 w-full h-full animate-spin-reverse origin-center"
          style={{ animationDuration: "1.8s" }}
        >
          <circle
            cx="12"
            cy="12"
            r="5.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeDasharray="8 6"
            strokeLinecap="round"
            className="opacity-60"
          />
        </svg>

        {/* Center Glowing Core */}
        <span className="absolute inset-0 m-auto w-1 h-1 rounded-full bg-current animate-pulse shadow-sm" />
      </span>

      {label && (
        <span className="font-mono text-xs tracking-wider uppercase">{label}</span>
      )}
    </span>
  );
}

export default CyberSpinner;
