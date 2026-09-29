"use client";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, RotateCcw } from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

const TERMINAL = new Set(["done", "failed"]);

/**
 * Polls GET /cases/{id}/status every 2s and renders a "thinking" progress UI.
 * On `done` it navigates to the results page (or calls `onDone`); on `failed`
 * it shows the error with a "Coba lagi" button wired to `onRetry`.
 */
export default function CaseProgress({ caseId, onDone, onRetry }) {
  const router = useRouter();

  const { data } = useQuery({
    queryKey: ["case-status", caseId],
    queryFn: () => api.get(`/cases/${caseId}/status`),
    refetchInterval: (query) =>
      TERMINAL.has(query.state.data?.status) ? false : 2000,
    enabled: !!caseId,
  });

  // Warm the results view while the analysis is still running. Importing the 3D module pulls
  // its chunk and fires the module-level `useGLTF.preload` calls, so the ~29 MB dentition GLB
  // (10 MB gzipped) and the gingiva are already in cache when we navigate. Without this the
  // whole download happens *after* the run finishes, which reads as a long freeze on the
  // results screen — on a phone that is by far the longest wait in the flow.
  useEffect(() => {
    if (!caseId) return;
    router.prefetch?.(`/case/${caseId}`);
    import("@/components/three/Teeth3D").catch(() => {});
  }, [caseId, router]);

  const status = data?.status;
  const progress = Math.max(0, Math.min(100, data?.progress ?? 0));
  const stage = data?.stage;
  const error = data?.error;

  useEffect(() => {
    if (status === "done") {
      if (onDone) onDone();
      else router.push(`/case/${caseId}`);
    }
  }, [status, caseId, onDone, router]);

  if (status === "failed") {
    return (
      <div className="flex flex-col items-center gap-4 py-8 text-center" role="alert">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle className="h-6 w-6 text-destructive" />
        </div>
        <div>
          <p className="font-semibold">Analisis gagal</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {error || "Terjadi kesalahan saat memproses. Silakan coba lagi."}
          </p>
        </div>
        <Button onClick={onRetry} variant="outline">
          <RotateCcw className="h-4 w-4" />
          Coba lagi
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-5 py-8 text-center">
      <div className="relative flex h-14 w-14 items-center justify-center">
        <Loader2 className="h-14 w-14 animate-spin text-primary/30" />
        <Loader2 className="absolute h-8 w-8 animate-spin text-primary" />
      </div>
      <div>
        <p className="font-semibold">Menganalisis citra…</p>
        <p className="mt-1 text-sm text-muted-foreground">{stage || "Memulai analisis"}</p>
      </div>
      <div className="w-full max-w-sm">
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Kemajuan analisis"
        >
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">{progress}%</p>
      </div>
    </div>
  );
}
