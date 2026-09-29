"use client";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle, RotateCcw } from "lucide-react";

import { api } from "@/lib/api";
import { STANDALONE } from "@/lib/demo";
import { MODEL_STEP, PIPELINE_SHARE, PIPELINE_STEPS, stepIndexFor } from "@/lib/pipeline";
import AnalysisLoader from "@/components/case/AnalysisLoader";
import { Button } from "@/components/ui/button";

const TERMINAL = new Set(["done", "failed"]);
const STEPS = [...PIPELINE_STEPS, MODEL_STEP];

// The standalone replay lives in localStorage, so it can be polled often enough for the bar to
// move smoothly; the real gateway is polled at a gentler rate.
const POLL_MS = STANDALONE ? 400 : 2000;

/**
 * Polls GET /cases/{id}/status and covers the screen with the step-by-step progress view.
 * On `done` it hands over to the results page (or calls `onDone`) — which keeps the same
 * screen up, on its final "Memuat model 3D" step, until the 3D dentition has actually loaded.
 * On `failed` it shows the error with a "Coba lagi" button wired to `onRetry`.
 */
export default function CaseProgress({ caseId, onDone, onRetry }) {
  const router = useRouter();

  const { data } = useQuery({
    queryKey: ["case-status", caseId],
    queryFn: () => api.get(`/cases/${caseId}/status`),
    refetchInterval: (query) =>
      TERMINAL.has(query.state.data?.status) ? false : POLL_MS,
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
  const error = data?.error;

  useEffect(() => {
    if (status === "done") {
      if (onDone) onDone();
      else router.push(`/case/${caseId}?from=analysis`);
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

  const done = status === "done";
  const active = done ? STEPS.length - 1 : stepIndexFor(progress);
  const scale = PIPELINE_SHARE / 100;

  return (
    <AnalysisLoader
      title="Menganalisis citra pasien"
      steps={STEPS}
      active={active}
      percent={done ? PIPELINE_SHARE : progress * scale}
      ceiling={done ? 97 : PIPELINE_STEPS[active].until * scale - 1}
      detail={done ? null : data?.stage}
    />
  );
}
