"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import {
  getExecutionStatus,
  getExecutions,
  runPipeline,
  type ExecutionHistoryItem,
  type ExecutionStatus,
  type ExecutionStatusResponse,
  type PipelineResult,
} from "@/lib/api-client";

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ERRORS = 3;
const ACCOUNT_STORAGE_KEY = "engageai.dashboard.account_id";
const DEFAULT_ACCOUNT_ID = "test";
const SURFACE_CARD_CLASSES =
  "rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm shadow-slate-200/60 transition-shadow duration-200";
const MUTED_CARD_CLASSES =
  "rounded-3xl border border-slate-200/80 bg-slate-50/80 p-6 shadow-sm shadow-slate-200/40 transition-colors duration-200";
const INFO_CARD_CLASSES =
  "rounded-2xl border border-slate-200/80 bg-slate-50 p-5 shadow-sm shadow-slate-200/40 transition-all duration-200";

export default function DashboardPage() {
  const [accountId, setAccountId] = useState("");
  const [nicheText, setNicheText] = useState("AI automation");
  const [mockMode, setMockMode] = useState(true);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [status, setStatus] = useState<ExecutionStatus | null>(null);
  const [data, setData] = useState<ExecutionStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const [history, setHistory] = useState<ExecutionHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historySelectionLoading, setHistorySelectionLoading] = useState(false);
  const pollFailureCountRef = useRef(0);
  const [accountIdHydrated, setAccountIdHydrated] = useState(false);

  const isProcessing = status === "pending" || status === "running";
  const isSubmitting = submitting || isProcessing || historySelectionLoading;
  const totalExecutions = history.length;
  const completedExecutions = history.filter((item) => item.status === "completed").length;
  const failedExecutions = history.filter((item) => item.status === "failed").length;
  const totalResults = history.reduce((sum, item) => sum + item.result_count, 0);
  const successRate = totalExecutions > 0 ? (completedExecutions / totalExecutions) * 100 : 0;
  const avgResultsPerExecution = totalExecutions > 0 ? totalResults / totalExecutions : 0;
  const lastExecutionTimestamp = history.reduce<string | null>((latest, item) => {
    const candidate = item.started_at ?? item.completed_at ?? null;
    if (!candidate) {
      return latest;
    }

    const candidateTime = parseTimestamp(candidate);
    if (candidateTime === null) {
      return latest;
    }

    if (!latest) {
      return candidate;
    }

    const latestTime = parseTimestamp(latest);
    if (latestTime === null || candidateTime > latestTime) {
      return candidate;
    }

    return latest;
  }, null);
  const completedDurations = history
    .filter((item) => item.status === "completed")
    .map((item) => {
      const startedAt = parseTimestamp(item.started_at);
      const completedAt = parseTimestamp(item.completed_at);
      if (startedAt === null || completedAt === null || completedAt < startedAt) {
        return null;
      }

      return (completedAt - startedAt) / 1000;
    })
    .filter((value): value is number => value !== null);
  const avgDurationSeconds =
    completedDurations.length > 0
      ? completedDurations.reduce((sum, value) => sum + value, 0) / completedDurations.length
      : null;

  useEffect(() => {
    const savedAccountId = window.localStorage.getItem(ACCOUNT_STORAGE_KEY)?.trim() ?? "";
    setAccountId(savedAccountId || DEFAULT_ACCOUNT_ID);
    setAccountIdHydrated(true);
  }, []);

  useEffect(() => {
    if (!accountIdHydrated) {
      return;
    }

    const normalizedAccountId = accountId.trim();
    if (!normalizedAccountId) {
      window.localStorage.removeItem(ACCOUNT_STORAGE_KEY);
      return;
    }

    window.localStorage.setItem(ACCOUNT_STORAGE_KEY, normalizedAccountId);
  }, [accountId, accountIdHydrated]);

  async function loadExecutionHistory(targetAccountId: string) {
    const normalizedAccountId = targetAccountId.trim();
    if (!normalizedAccountId) {
      setHistory([]);
      setHistoryError(null);
      setHistoryLoading(false);
      return;
    }

    setHistoryLoading(true);
    setHistoryError(null);

    try {
      const response = await getExecutions(normalizedAccountId);
      setHistory(response);
    } catch (historyFetchError) {
      setHistory([]);
      setHistoryError(
        historyFetchError instanceof Error
          ? historyFetchError.message
          : "Failed to load execution history.",
      );
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadExecutionDetails(targetExecutionId: string) {
    setHistorySelectionLoading(true);
    setError(null);
    setHasRun(true);

    try {
      const response = await getExecutionStatus(targetExecutionId);
      setExecutionId(response.execution_id);
      setStatus(response.status);
      setData(response);
      setError(response.status === "failed" ? response.error ?? "Pipeline execution failed." : null);
    } catch (executionFetchError) {
      setError(
        executionFetchError instanceof Error
          ? executionFetchError.message
          : "Failed to load execution details.",
      );
    } finally {
      setHistorySelectionLoading(false);
    }
  }

  useEffect(() => {
    if (!accountIdHydrated) {
      return undefined;
    }

    const normalizedAccountId = accountId.trim();
    if (!normalizedAccountId) {
      setHistory([]);
      setHistoryError(null);
      setHistoryLoading(false);
      return undefined;
    }

    const timeoutId = setTimeout(() => {
      void loadExecutionHistory(normalizedAccountId);
    }, 300);

    return () => {
      clearTimeout(timeoutId);
    };
  }, [accountId, accountIdHydrated]);

  useEffect(() => {
    if (!executionId || !status || status === "completed" || status === "failed") {
      return undefined;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const pollExecution = async () => {
      try {
        const response = await getExecutionStatus(executionId);
        if (cancelled) {
          return;
        }

        pollFailureCountRef.current = 0;
        setData(response);
        setStatus(response.status);

        if (response.status === "failed") {
          setError(response.error ?? "Pipeline execution failed.");
          void loadExecutionHistory(response.account_id);
          return;
        }

        if (response.status === "completed") {
          setError(null);
          void loadExecutionHistory(response.account_id);
          return;
        }

        timeoutId = setTimeout(pollExecution, POLL_INTERVAL_MS);
      } catch (pollError) {
        if (cancelled) {
          return;
        }

        pollFailureCountRef.current += 1;
        if (pollFailureCountRef.current >= MAX_POLL_ERRORS) {
          setError(
            pollError instanceof Error
              ? pollError.message
              : "Failed to retrieve execution status.",
          );
          return;
        }

        timeoutId = setTimeout(pollExecution, POLL_INTERVAL_MS);
      }
    };

    void pollExecution();

    return () => {
      cancelled = true;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [executionId, status]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextAccountId = accountId.trim();
    const nextNicheText = nicheText.trim();

    if (!nextAccountId || !nextNicheText) {
      setError("Account ID and niche text are required.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setData(null);
    setExecutionId(null);
    setStatus(null);
    pollFailureCountRef.current = 0;
    setHasRun(true);

    try {
      const response = await runPipeline({
        accountId: nextAccountId,
        nicheText: nextNicheText,
        mock: mockMode,
      });
      setExecutionId(response.execution_id);
      setStatus("pending");
    } catch (fetchError) {
      setData(null);
      setExecutionId(null);
      setStatus("failed");
      setError(
        fetchError instanceof Error ? fetchError.message : "Failed to run the pipeline.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  function renderStatusMessage() {
    if (status === "pending") {
      return "Queued...";
    }
    if (status === "running") {
      return "Processing...";
    }
    if (status === "failed") {
      return "Execution failed";
    }
    if (status === "completed") {
      return "Completed";
    }
    return "Ready";
  }

  function getStatusBadgeClasses(currentStatus: ExecutionStatus | null) {
    if (currentStatus === "completed") {
      return "border border-emerald-200 bg-emerald-50 text-emerald-700";
    }
    if (currentStatus === "failed") {
      return "border border-red-200 bg-red-50 text-red-700";
    }
    if (currentStatus === "running") {
      return "border border-sky-200 bg-sky-50 text-sky-700";
    }
    if (currentStatus === "pending") {
      return "border border-slate-200 bg-slate-100 text-slate-700";
    }
    return "border border-slate-200 bg-slate-100 text-slate-600";
  }

  function renderLoadingIndicator(label: string) {
    return (
      <span className="inline-flex items-center gap-2.5 text-sm font-medium text-slate-500">
        <span className="inline-flex h-4 w-4 items-center justify-center">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
        </span>
        {label}
      </span>
    );
  }

  function renderStatusDetail() {
    if (historySelectionLoading) {
      return "Loading the selected execution details.";
    }
    if (status === "pending") {
      return "This execution is queued and will start shortly.";
    }
    if (status === "running") {
      return "The pipeline is actively processing posts and generating suggestions.";
    }
    if (status === "completed") {
      return "Execution completed. Review the results below or load a prior run from history.";
    }
    if (status === "failed") {
      return error ?? "This execution failed before results were returned.";
    }
    return "Start a run to generate suggestions and populate this view.";
  }

  function parseTimestamp(value?: string | null) {
    if (!value) {
      return null;
    }

    const parsedValue = new Date(value);
    if (Number.isNaN(parsedValue.getTime())) {
      return null;
    }

    return parsedValue.getTime();
  }

  function formatTimestamp(value?: string | null) {
    if (!value) {
      return "Not available";
    }

    const parsedValue = parseTimestamp(value);
    if (parsedValue === null) {
      return value;
    }

    return new Date(parsedValue).toLocaleString();
  }

  function formatPercentage(value: number) {
    return `${Math.round(value)}%`;
  }

  function formatAverage(value: number) {
    return value.toFixed(2);
  }

  function formatDuration(value: number | null) {
    if (value === null) {
      return "N/A";
    }

    return `${value.toFixed(1)}s`;
  }

  return (
    <section className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-10">
      <div className={`${SURFACE_CARD_CLASSES} bg-gradient-to-br from-white to-slate-50`}>
        <PageHeader
          title="Dashboard"
          description="Run the engagement pipeline and review suggested comments."
        />
      </div>

      <form
        onSubmit={handleSubmit}
        className={`${SURFACE_CARD_CLASSES} flex flex-col gap-6`}
      >
        <div className="flex flex-col gap-2">
          <h2 className="text-xl font-semibold tracking-tight text-slate-950">Run Pipeline</h2>
          <p className="text-sm leading-6 text-slate-500">
            Configure the account context and start a new asynchronous pipeline execution.
          </p>
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          <label className="flex flex-col gap-2.5 text-sm font-medium text-slate-700">
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Account ID
            </span>
            <input
              type="text"
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              placeholder="Enter account ID"
              className="rounded-2xl border border-slate-300 bg-white px-4 py-3.5 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-500 focus:ring-4 focus:ring-slate-200"
            />
          </label>

          <label className="flex flex-col gap-2.5 text-sm font-medium text-slate-700">
            <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Niche Text
            </span>
            <input
              type="text"
              value={nicheText}
              onChange={(event) => setNicheText(event.target.value)}
              placeholder="Enter niche text"
              className="rounded-2xl border border-slate-300 bg-white px-4 py-3.5 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-slate-500 focus:ring-4 focus:ring-slate-200"
            />
          </label>
        </div>

        <div className="flex flex-col gap-4 border-t border-slate-200 pt-1 md:flex-row md:items-center md:justify-between">
          <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3.5 text-sm text-slate-700 shadow-sm shadow-slate-200/40">
            <span className="font-medium text-slate-900">Mock Mode</span>
            <button
              type="button"
              role="switch"
              aria-checked={mockMode}
              onClick={() => setMockMode((currentValue) => !currentValue)}
              className={`relative inline-flex h-7 w-12 items-center rounded-full shadow-sm transition duration-200 active:scale-[0.98] ${
                mockMode ? "bg-slate-900" : "bg-slate-300"
              }`}
            >
              <span
                className={`inline-block h-5 w-5 transform rounded-full bg-white transition ${
                  mockMode ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
            <span className="text-slate-500">{mockMode ? "Mock data" : "Real scraper"}</span>
          </label>

          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-900 px-6 py-3.5 text-sm font-semibold text-white shadow-sm shadow-slate-300 transition-all duration-200 hover:-translate-y-0.5 hover:bg-slate-800 hover:shadow-md hover:shadow-slate-300/80 active:translate-y-0 active:scale-[0.99] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-slate-200 disabled:translate-y-0 disabled:cursor-not-allowed disabled:bg-slate-400 disabled:text-white/90 disabled:shadow-none"
          >
            {isSubmitting ? (
              <>
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                {historySelectionLoading
                  ? "Loading..."
                  : status === "pending"
                    ? "Queued..."
                    : "Running..."}
              </>
            ) : (
              "Run Pipeline"
            )}
          </button>
        </div>
      </form>

      {executionId ? (
        <div className={SURFACE_CARD_CLASSES}>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Execution
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-700">
            <span className="font-medium text-slate-900">ID: {executionId}</span>
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide transition-colors duration-200 ${getStatusBadgeClasses(status)}`}
            >
              {renderStatusMessage()}
            </span>
          </div>
          <p
            className={`mt-3 text-sm leading-6 transition-colors duration-200 ${
              status === "failed"
                ? "text-red-600"
                : status === "completed"
                  ? "text-emerald-700"
                  : "text-slate-500"
            }`}
          >
            {renderStatusDetail()}
          </p>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-3xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 shadow-sm shadow-red-100/70 transition-all duration-200">
          {error}
        </div>
      ) : null}

      {!hasRun ? (
        <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center text-sm leading-6 text-slate-500 transition-all duration-200">
          Run the pipeline to queue an execution and suggested comments will appear here.
        </div>
      ) : null}

      {hasRun && data ? (
        <div className="flex flex-col gap-5 transition-all duration-200">
          <div className={SURFACE_CARD_CLASSES}>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Results
            </p>
            <div className="mt-3 flex items-end justify-between gap-4">
              <p className="text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                {data.result_count}
              </p>
              <p className="text-sm text-slate-500">Suggested opportunities in this execution</p>
            </div>
          </div>

          {status === "pending" ? (
            <div className={`${MUTED_CARD_CLASSES} px-6 py-12 text-center`}>
              <div className="flex flex-col items-center gap-3">
                {renderLoadingIndicator("Queued and waiting to start")}
                <p className="text-sm leading-6 text-slate-500">
                  The execution is in line and will begin automatically.
                </p>
              </div>
            </div>
          ) : null}

          {status === "running" ? (
            <div className={`${MUTED_CARD_CLASSES} px-6 py-12 text-center`}>
              <div className="flex flex-col items-center gap-3">
                {renderLoadingIndicator("Processing the current execution")}
                <p className="text-sm leading-6 text-slate-500">
                  EngageAI is analyzing posts, drafting comments, and ranking suggestions.
                </p>
              </div>
            </div>
          ) : null}

          {status === "failed" ? (
            <div className="rounded-3xl border border-red-200 bg-red-50 px-6 py-12 text-center text-sm text-red-700 shadow-sm shadow-red-100/70 transition-all duration-200">
              {error ?? "Pipeline execution failed."}
            </div>
          ) : null}

          {status === "completed" && data.results.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center text-sm leading-6 text-slate-500 transition-all duration-200">
              The execution completed, but no matching opportunities were found for this run.
            </div>
          ) : null}

          {status === "completed" && data.results.length > 0 ? (
            <div className="grid gap-5 transition-all duration-200">
              {data.results.map((result: PipelineResult, index: number) => (
                <article
                  key={`${result.post?.author ?? "post"}-${index}`}
                  className={`${SURFACE_CARD_CLASSES} p-6 transition-all duration-200`}
                >
                  <div className="flex flex-col gap-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex flex-col gap-1">
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                          Post
                        </p>
                        <h2 className="text-xl font-semibold tracking-tight text-slate-950">
                          {result.post?.author ?? "Unknown author"}
                        </h2>
                      </div>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-600">
                        Viral score: {result.analytics?.viral_score ?? 0}
                      </span>
                    </div>

                    <p className="text-sm leading-7 text-slate-700">
                      {result.post?.content ?? "No post content available."}
                    </p>

                    <div className="flex flex-wrap gap-3">
                      <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">
                        Likes: {result.post?.likes ?? 0}
                      </span>
                      <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">
                        Comments: {result.post?.comments ?? 0}
                      </span>
                    </div>

                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                        Best Comment
                      </p>
                      <p className="mt-3 text-sm leading-7 text-slate-800">
                        {result.best_comment?.text ?? "No best comment generated."}
                      </p>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-5">
        <div className={SURFACE_CARD_CLASSES}>
          <div className="flex flex-col gap-5">
            <div>
              <h2 className="text-xl font-semibold tracking-tight text-slate-950">
                Analytics Summary
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-500">
                Aggregate metrics from the current execution history.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Total Executions
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {totalExecutions}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Success Rate
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {formatPercentage(successRate)}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Completed
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {completedExecutions}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Failed
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {failedExecutions}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Total Results
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {totalResults}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Avg Results
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {formatAverage(avgResultsPerExecution)}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Last Execution
                </p>
                <p className="mt-3 text-sm font-semibold text-slate-900">
                  {lastExecutionTimestamp ? formatTimestamp(lastExecutionTimestamp) : "No data"}
                </p>
              </div>

              <div className={INFO_CARD_CLASSES}>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Avg Duration
                </p>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 tabular-nums">
                  {formatDuration(avgDurationSeconds)}
                </p>
              </div>
            </div>

            {totalExecutions === 0 ? (
              <p className="text-sm text-slate-500">No data yet</p>
            ) : null}
          </div>
        </div>

        <div className={SURFACE_CARD_CLASSES}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight text-slate-950">
                Execution History
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-500">
                Recent executions for the current account.
              </p>
            </div>
            {historyLoading ? (
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500 transition-all duration-200">
                <span className="inline-flex items-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
                  Loading history
                </span>
              </span>
            ) : null}
          </div>
        </div>

        {historyError ? (
          <div className="rounded-3xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 shadow-sm shadow-red-100/70 transition-all duration-200">
            {historyError}
          </div>
        ) : null}

        {!accountId.trim() ? (
          <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center text-sm leading-6 text-slate-500 transition-all duration-200">
            Enter an account ID to view recent executions and reload prior results.
          </div>
        ) : null}

        {accountId.trim() && !historyLoading && !historyError && history.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center text-sm leading-6 text-slate-500 transition-all duration-200">
            No executions found for this account yet. Start a run to build recent history.
          </div>
        ) : null}

        {accountId.trim() && history.length > 0 ? (
          <div className="grid gap-3.5 transition-all duration-200">
            {history.map((execution) => (
              <button
                key={execution.execution_id}
                type="button"
                onClick={() => void loadExecutionDetails(execution.execution_id)}
                className={`rounded-3xl border p-5 text-left shadow-sm transition-all duration-200 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-slate-200 ${
                  execution.execution_id === executionId
                    ? "border-slate-900 bg-slate-50 shadow-md shadow-slate-200/70 ring-1 ring-slate-900/10"
                    : "border-slate-200 bg-white shadow-slate-200/50 hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50/70 hover:shadow-md hover:shadow-slate-200/70 active:translate-y-0 active:scale-[0.995]"
                }`}
              >
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex flex-col gap-1">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                        Execution ID
                      </p>
                      <p className="text-sm font-semibold text-slate-900">
                        {execution.execution_id}
                      </p>
                    </div>
                    <span
                      className={`rounded-full px-3 py-1.5 text-xs font-semibold uppercase tracking-wide ${getStatusBadgeClasses(
                        execution.status,
                      )}`}
                    >
                      {execution.status}
                    </span>
                  </div>

                  <div className="grid gap-3 text-sm text-slate-600 md:grid-cols-3">
                    <div className="rounded-2xl bg-slate-50 px-3 py-2.5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Results
                      </p>
                      <p className="mt-1 font-semibold text-slate-900 tabular-nums">
                        {execution.result_count}
                      </p>
                    </div>

                    <div className="rounded-2xl bg-slate-50 px-3 py-2.5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Started
                      </p>
                      <p className="mt-1 text-slate-700">{formatTimestamp(execution.started_at)}</p>
                    </div>

                    <div className="rounded-2xl bg-slate-50 px-3 py-2.5">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Completed
                      </p>
                      <p className="mt-1 text-slate-700">
                        {formatTimestamp(execution.completed_at)}
                      </p>
                    </div>
                  </div>

                  {execution.error ? (
                    <p className="text-sm text-red-600">{execution.error}</p>
                  ) : null}
                </div>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
