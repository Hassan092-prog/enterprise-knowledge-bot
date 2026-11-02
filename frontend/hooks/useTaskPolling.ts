"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { getApiUrl } from "@/lib/api";

export type IngestionStage =
  | "PARSING"
  | "CHUNKING"
  | "SUMMARIZING"
  | "EMBEDDING"
  | "INDEXING"
  | "COMPLETED"
  | "FAILED";

export interface TaskProgress {
  stage: IngestionStage | string;
  pct: number;
  msg: string;
}

export interface TaskStatusResponse {
  task_id: string;
  status: string;
  ready: boolean;
  successful: boolean;
  result: any;
  progress?: TaskProgress | null;
}

export interface UseTaskPollingOptions {
  onSuccess?: (result: any) => void;
  onError?: (error: string) => void;
  pollIntervalMs?: number;
  maxAttempts?: number;
}

export function useTaskPolling(
  authFetch: (url: string, options?: RequestInit) => Promise<Response>,
  options?: UseTaskPollingOptions
) {
  const [isPolling, setIsPolling] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [progress, setProgress] = useState<TaskProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);

  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const attemptsRef = useRef(0);
  const isCancelledRef = useRef(false);

  const stopPolling = useCallback(() => {
    isCancelledRef.current = true;
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setIsPolling(false);
  }, []);

  const reset = useCallback(() => {
    stopPolling();
    setTaskId(null);
    setFilename(null);
    setProgress(null);
    setError(null);
    setIsComplete(false);
  }, [stopPolling]);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      isCancelledRef.current = true;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  const startPolling = useCallback(
    (
      id: string,
      targetFilename?: string,
      callbacks?: { onSuccess?: (res?: any) => void; onError?: (err: string) => void }
    ) => {
      stopPolling();
      isCancelledRef.current = false;
      setTaskId(id);
      if (targetFilename) setFilename(targetFilename);
      setIsPolling(true);
      setError(null);
      setIsComplete(false);
      setProgress({
        stage: "PARSING",
        pct: 10,
        msg: "Initializing background worker...",
      });

      attemptsRef.current = 0;
      const intervalMs = options?.pollIntervalMs || 1000;
      const maxAttempts = options?.maxAttempts || 90; // 90 seconds timeout for OCR/LLM
      const API_URL = getApiUrl();

      const pollTick = async () => {
        if (isCancelledRef.current) return;

        attemptsRef.current += 1;
        let shouldContinue = true;

        try {
          const res = await authFetch(`${API_URL}/tasks/${id}`);

          if (isCancelledRef.current) return;

          if (!res.ok) {
            // Task not yet registered in Redis/Celery (race condition on fast poll)
            if (res.status === 404 && attemptsRef.current <= 5) {
              // retry on next tick
            } else if (res.status === 403) {
              shouldContinue = false;
              const forbiddenMsg = "Access denied: You do not have permission to inspect this task.";
              setError(forbiddenMsg);
              setProgress({ stage: "FAILED", pct: 0, msg: forbiddenMsg });
              options?.onError?.(forbiddenMsg);
              callbacks?.onError?.(forbiddenMsg);
              stopPolling();
              return;
            } else {
              throw new Error(`Failed to query task status (HTTP ${res.status})`);
            }
          } else {
            const data: TaskStatusResponse = await res.json();

            if (isCancelledRef.current) return;

            if (data.progress && data.progress.stage) {
              setProgress(data.progress);
            }

            if (data.ready) {
              shouldContinue = false;
              stopPolling();
              if (data.successful) {
                setProgress({
                  stage: "COMPLETED",
                  pct: 100,
                  msg: "Document indexed successfully",
                });
                setIsComplete(true);
                options?.onSuccess?.(data.result);
                callbacks?.onSuccess?.(data.result);
              } else {
                const errMsg =
                  typeof data.result === "string"
                    ? data.result
                    : data.progress?.msg || "Worker error during document processing";
                setError(errMsg);
                setProgress({
                  stage: "FAILED",
                  pct: 0,
                  msg: errMsg,
                });
                options?.onError?.(errMsg);
                callbacks?.onError?.(errMsg);
              }
              return;
            }
          }

          if (attemptsRef.current >= maxAttempts) {
            shouldContinue = false;
            stopPolling();
            const timeoutMsg = "Ingestion task timed out after 90 seconds.";
            setError(timeoutMsg);
            setProgress({
              stage: "FAILED",
              pct: 0,
              msg: timeoutMsg,
            });
            options?.onError?.(timeoutMsg);
            callbacks?.onError?.(timeoutMsg);
            return;
          }
        } catch (err: unknown) {
          if (isCancelledRef.current) return;
          const errString = err instanceof Error ? err.message : String(err);
          console.warn("Task poll check error:", errString);
        }

        if (shouldContinue && !isCancelledRef.current) {
          pollTimerRef.current = setTimeout(pollTick, intervalMs);
        }
      };

      // Kick off first poll tick after interval
      pollTimerRef.current = setTimeout(pollTick, intervalMs);
    },
    [authFetch, options, stopPolling]
  );

  return {
    isPolling,
    taskId,
    filename,
    progress,
    error,
    isComplete,
    startPolling,
    stopPolling,
    reset,
  };
}
