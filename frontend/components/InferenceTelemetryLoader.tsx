"use client";

import React, { useState, useEffect } from "react";
import CyberSpinner from "./CyberSpinner";

interface InferenceTelemetryLoaderProps {
  queryContext?: string;
}

export function InferenceTelemetryLoader({ queryContext }: InferenceTelemetryLoaderProps) {
  const [elapsed, setElapsed] = useState<number>(0);
  const [phaseIndex, setPhaseIndex] = useState<number>(0);

  // High-frequency telemetry tick (updates every 100ms)
  useEffect(() => {
    const startTime = Date.now();
    const interval = setInterval(() => {
      const delta = (Date.now() - startTime) / 1000;
      setElapsed(delta);

      if (delta < 1.2) {
        setPhaseIndex(0);
      } else if (delta < 2.5) {
        setPhaseIndex(1);
      } else {
        setPhaseIndex(2);
      }
    }, 100);

    return () => clearInterval(interval);
  }, []);

  const phases = [
    {
      code: "PHASE 01: INTENT_DISPATCH",
      desc: "Parsing query syntax, targeting documents & checking SQL schema...",
      badge: "ROUTER",
      color: "border-accent/40 text-accent bg-accent-subtle",
    },
    {
      code: "PHASE 02: VECTOR_FUSION",
      desc: "Executing hybrid ChromaDB + BM25 reciprocal rank fusion (RRF k=60)...",
      badge: "RETRIEVAL",
      color: "border-emerald/40 text-emerald bg-emerald-subtle",
    },
    {
      code: "PHASE 03: EVIDENCE_SYNTHESIS",
      desc: "Synthesizing answer with GPT-OSS-120B & assembling citation links...",
      badge: "LLM INFERENCE",
      color: "border-amber-500/40 text-amber-400 bg-amber-500/10",
    },
  ];

  const currentPhase = phases[phaseIndex] || phases[2];

  return (
    <div className="space-y-4 pt-1 pb-2">
      {/* Laser Scanning Track */}
      <div className="relative w-full h-[2px] bg-paper-3 overflow-hidden rounded-full">
        <div className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-accent to-transparent animate-cyber-scan" />
      </div>

      {/* Telemetry Stage Readout */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-base bg-paper border border-rule">
        <div className="flex items-center gap-2.5 overflow-hidden">
          <CyberSpinner size="sm" variant={phaseIndex === 1 ? "emerald" : phaseIndex === 2 ? "brass" : "accent"} />
          <div className="overflow-hidden">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold text-ink uppercase tracking-wide">
                {currentPhase.code}
              </span>
              <span className={`px-1.5 py-0.2 rounded font-mono text-[9px] uppercase font-bold border ${currentPhase.color}`}>
                {currentPhase.badge}
              </span>
            </div>
            <p className="font-mono text-[11px] text-muted truncate mt-0.5">
              {currentPhase.desc}
            </p>
          </div>
        </div>

        {/* Live Elapsed Telemetry Timer */}
        <div className="flex items-center gap-2 font-mono text-[11px] text-muted shrink-0 self-end sm:self-center">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-ping" />
          <span>T + {elapsed.toFixed(1)}s</span>
        </div>
      </div>

      {/* Holographic Wireframe Ghost Lines */}
      <div className="space-y-2.5 pt-1 px-1">
        <div className="h-3 w-11/12 rounded bg-paper-3/80 animate-pulse relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-accent/10 to-transparent animate-shimmer-sweep" />
        </div>
        <div className="h-3 w-4/5 rounded bg-paper-3/60 animate-pulse relative overflow-hidden" style={{ animationDelay: "150ms" }}>
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-accent/10 to-transparent animate-shimmer-sweep" />
        </div>
        <div className="h-3 w-2/3 rounded bg-paper-3/40 animate-pulse relative overflow-hidden" style={{ animationDelay: "300ms" }}>
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-accent/10 to-transparent animate-shimmer-sweep" />
        </div>
      </div>
    </div>
  );
}

export default InferenceTelemetryLoader;
