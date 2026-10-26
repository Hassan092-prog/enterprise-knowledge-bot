"use client";

import React from "react";

interface TerminalSkeletonProps {
  variant: "chat" | "table" | "stats" | "docs";
  count?: number;
  className?: string;
}

export function TerminalSkeleton({
  variant,
  count = 4,
  className = "",
}: TerminalSkeletonProps) {
  if (variant === "chat") {
    return (
      <div className={`space-y-6 ${className}`}>
        {/* User Query Skeleton */}
        <div className="flex justify-end">
          <div className="w-full max-w-lg rounded-card p-4 bg-paper-3/60 border border-rule-focus/40 space-y-2">
            <div className="h-3.5 w-3/4 rounded bg-paper-2/80 animate-pulse ml-auto" />
            <div className="h-3.5 w-1/2 rounded bg-paper-2/60 animate-pulse ml-auto" />
          </div>
        </div>

        {/* Assistant Response Skeleton */}
        <div className="flex justify-start">
          <div className="w-full max-w-4xl rounded-card p-5 bg-paper-2 border border-rule space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-rule">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-accent/60 animate-pulse" />
                <span className="h-3 w-32 rounded bg-paper-3/80 font-mono text-[10px]" />
              </div>
              <span className="h-3 w-28 rounded bg-paper-3/60 font-mono text-[10px]" />
            </div>

            <div className="space-y-2.5">
              <div className="h-3.5 w-11/12 rounded bg-paper-3/80 animate-pulse" />
              <div className="h-3.5 w-4/5 rounded bg-paper-3/60 animate-pulse" />
              <div className="h-3.5 w-2/3 rounded bg-paper-3/70 animate-pulse" />
              <div className="h-3.5 w-3/4 rounded bg-paper-3/50 animate-pulse" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (variant === "table") {
    return (
      <div className={`divide-y divide-rule font-mono ${className}`}>
        {Array.from({ length: count }).map((_, idx) => (
          <div
            key={idx}
            className="flex items-center justify-between p-3 bg-paper hover:bg-paper-2/40 transition-colors gap-3"
            style={{ animationDelay: `${idx * 80}ms` }}
          >
            {/* Timestamp */}
            <div className="w-32 shrink-0">
              <div className="h-3 w-28 bg-paper-3/80 rounded animate-pulse" />
            </div>

            {/* Username */}
            <div className="w-20 shrink-0">
              <div className="h-3 w-16 bg-paper-3/70 rounded animate-pulse" />
            </div>

            {/* Category Badge */}
            <div className="w-24 shrink-0">
              <div className="h-4 w-18 bg-paper-3/60 rounded border border-rule/50 animate-pulse" />
            </div>

            {/* Action */}
            <div className="w-32 shrink-0">
              <div className="h-3 w-24 bg-paper-3/70 rounded animate-pulse" />
            </div>

            {/* Description */}
            <div className="flex-1 min-w-[140px]">
              <div className="h-3 w-4/5 bg-paper-3/60 rounded animate-pulse" />
            </div>

            {/* Inspect Button */}
            <div className="w-16 shrink-0 text-right">
              <div className="h-5 w-14 bg-paper-3/50 rounded border border-rule/50 ml-auto animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (variant === "stats") {
    return (
      <div className={`grid grid-cols-1 sm:grid-cols-3 gap-4 ${className}`}>
        {Array.from({ length: 3 }).map((_, idx) => (
          <div key={idx} className="bg-paper-2 p-5 rounded-card border border-rule space-y-2">
            <div className="h-3 w-28 bg-paper-3/60 rounded animate-pulse" />
            <div className="h-8 w-20 bg-paper-3/80 rounded animate-pulse" />
            <div className="h-2.5 w-36 bg-paper-3/40 rounded animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  if (variant === "docs") {
    return (
      <div className={`space-y-1.5 ${className}`}>
        {Array.from({ length: count }).map((_, idx) => (
          <div
            key={idx}
            className="flex items-center justify-between p-2 rounded-base bg-paper-2 border border-rule animate-pulse"
            style={{ animationDelay: `${idx * 100}ms` }}
          >
            <div className="flex items-center gap-1.5 overflow-hidden flex-1">
              <div className="w-6 h-4 rounded bg-paper border border-rule" />
              <div className="h-3 w-3/4 bg-paper-3/70 rounded" />
            </div>
            <div className="w-8 h-3 rounded bg-paper-3/40" />
          </div>
        ))}
      </div>
    );
  }

  return null;
}

export default TerminalSkeleton;
