"use client";

import { useEffect, useState } from "react";

import { getHealth, getRoot } from "@/src/api";


type ApiState = {
  health: unknown;
  root: unknown;
};


export default function HomePage() {
  const [data, setData] = useState<ApiState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function loadApiState() {
      try {
        const [health, root] = await Promise.all([getHealth(), getRoot()]);
        if (cancelled) {
          return;
        }

        setData({ health, root });
        setError(null);
      } catch (fetchError) {
        if (cancelled) {
          return;
        }

        setError(fetchError instanceof Error ? fetchError.message : "Failed to reach backend.");
        setData(null);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadApiState();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-semibold text-slate-950">EngageAI Backend Check</h1>
        <p className="mt-2 text-sm text-slate-500">
          Verifies browser connectivity to the deployed FastAPI backend.
        </p>
      </div>

      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        {loading ? <p className="text-sm text-slate-500">Loading backend health...</p> : null}
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        {data ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                /health
              </p>
              <pre className="mt-3 overflow-x-auto text-sm text-slate-800">
                {JSON.stringify(data.health, null, 2)}
              </pre>
            </div>
            <div className="rounded-2xl bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                /
              </p>
              <pre className="mt-3 overflow-x-auto text-sm text-slate-800">
                {JSON.stringify(data.root, null, 2)}
              </pre>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
