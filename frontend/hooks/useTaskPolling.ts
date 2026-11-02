"use client";

import { useState, useRef, useCallback, useEffect } from "react";

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

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const attemptsRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
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

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
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
      const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

      pollIntervalRef.current = setInterval(async () => {
        attemptsRef.current += 1;
        try {
          const res = await authFetch(`${API_URL}/tasks/${id}`);
          if (!res.ok) {
            // Task not yet registered in Redis/Celery (race condition on fast poll)
            if (res.status === 404 && attemptsRef.current <= 3) {
              return;
            }
            throw new Error(`Failed to query task status (HTTP ${res.status})`);
          }

          const data: TaskStatusResponse = await res.json();

          if (data.progress && data.progress.stage) {
            setProgress(data.progress);
          }

          if (data.ready) {
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
                  : "Worker error during document processing";
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

          if (attemptsRef.current >= maxAttempts) {
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
          }
        } catch (err: unknown) {
          const errString = err instanceof Error ? err.message : String(err);
          console.warn("Task poll check error:", errString);
        }
      }, intervalMs);
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

