"use client";

import React from "react";
import CyberSpinner from "./CyberSpinner";
import { TaskProgress } from "../hooks/useTaskPolling";

interface TaskProgressStepperProps {
  progress: TaskProgress | null;
  filename?: string | null;
  error?: string | null;
  isComplete?: boolean;
  onDismiss?: () => void;
  className?: string;
}

const STAGES = [
  { key: "PARSING", label: "Parse", minPct: 10 },
  { key: "CHUNKING", label: "Chunk", minPct: 30 },
  { key: "SUMMARIZING", label: "Summary", minPct: 50 },
  { key: "EMBEDDING", label: "Embed", minPct: 70 },
  { key: "INDEXING", label: "Index", minPct: 85 },
];

export function TaskProgressStepper({
  progress,
  filename,
  error,
  isComplete,
  onDismiss,
  className = "",
}: TaskProgressStepperProps) {
  if (!progress && !error && !isComplete) {
    return null;
  }

  const currentStage = progress?.stage?.toUpperCase() || (isComplete ? "COMPLETED" : error ? "FAILED" : "PARSING");
  const currentPct = isComplete ? 100 : error ? 100 : progress?.pct ?? 10;
  const currentMsg = error || progress?.msg || (isComplete ? "Document indexed successfully and ready for queries" : "Processing document...");

  // Auto-dismiss completed stepper after 8 seconds
  React.useEffect(() => {
    if (isComplete && onDismiss) {
      const timer = setTimeout(() => {
        onDismiss();
      }, 8000);
      return () => clearTimeout(timer);
    }
  }, [isComplete, onDismiss]);

  const getStageStatus = (stageKey: string, stageMinPct: number) => {
    if (error) return "error";
    if (isComplete) return "complete";

    const stageOrder = ["PARSING", "CHUNKING", "SUMMARIZING", "EMBEDDING", "INDEXING", "COMPLETED"];
    const currentIndex = stageOrder.indexOf(currentStage);
    const thisIndex = stageOrder.indexOf(stageKey);

    if (thisIndex < currentIndex || currentPct > stageMinPct + 15) {
      return "complete";
    }
    if (stageKey === currentStage || (thisIndex === currentIndex)) {
      return "active";
    }
    return "pending";
  };

  return (
    <div
      className={`p-3.5 rounded-card border transition-all duration-300 ${
        error
          ? "bg-ruby-subtle border-ruby/40 text-ruby"
          : isComplete
          ? "bg-emerald-subtle border-emerald/40 text-emerald"
          : "bg-paper-2 border-accent/40 shadow-sm"
      } ${className}`}
    >
      {/* Top Header: File info & Stage Badge */}
      <div className="flex items-center justify-between gap-3 mb-2.5">
        <div className="flex items-center gap-2 overflow-hidden">
          {error ? (
            <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-ruby/20 border border-ruby/30 font-bold shrink-0">
              ✕ FAILED
            </span>
          ) : isComplete ? (
            <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-emerald/20 border border-emerald/30 font-bold shrink-0">
              ✓ READY
            </span>
          ) : (
            <CyberSpinner size="xs" variant="accent" />
          )}

          <div className="truncate">
            <span className="text-xs font-medium text-ink truncate block" title={filename || "Document"}>
              {filename || "Document Processing"}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[10px] px-2 py-0.5 rounded border border-rule bg-paper text-ink font-semibold uppercase">
            {error ? "ERR" : isComplete ? "100%" : `${currentPct}%`}
          </span>

          {onDismiss && (isComplete || error) && (
            <button
              onClick={onDismiss}
              className="text-muted hover:text-ink text-xs font-mono p-0.5 transition-colors cursor-pointer"
              title="Dismiss notification"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* 5-Step Visual Stepper Track */}
      <div className="grid grid-cols-5 gap-1.5 mb-2">
        {STAGES.map((s) => {
          const status = getStageStatus(s.key, s.minPct);
          return (
            <div
              key={s.key}
              className={`flex flex-col items-center gap-1 py-1 px-1 rounded text-center transition-colors ${
                status === "complete"
                  ? "bg-emerald/10 text-emerald border border-emerald/30"
                  : status === "active"
                  ? "bg-accent-subtle text-accent border border-accent/50 animate-pulse font-semibold"
                  : status === "error"
                  ? "bg-ruby/10 text-ruby border border-ruby/30"
                  : "bg-paper text-muted border border-rule opacity-60"
              }`}
            >
              <span className="font-mono text-[9px] uppercase tracking-tight">
                {status === "complete" ? "✓" : s.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Real-Time Progress Bar */}
      <div className="w-full bg-paper rounded-full h-1.5 overflow-hidden border border-rule mb-2">
        <div
          className={`h-full transition-all duration-300 ease-out ${
            error
              ? "bg-ruby"
              : isComplete
              ? "bg-emerald"
              : "bg-gradient-to-r from-accent/80 via-accent to-emerald"
          }`}
          style={{ width: `${Math.min(100, Math.max(5, currentPct))}%` }}
        />
      </div>

      {/* Live Stage Message */}
      <div className="flex items-center justify-between text-[11px] font-mono">
        <span className={`truncate ${error ? "text-ruby font-medium" : isComplete ? "text-emerald" : "text-ink-secondary"}`}>
          {currentMsg}
        </span>
        <span className="text-[10px] text-muted shrink-0 ml-2 uppercase">
          {error ? "Worker Error" : isComplete ? "Ready" : currentStage}
        </span>
      </div>
    </div>
  );
}

export default TaskProgressStepper;

