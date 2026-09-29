"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import ResultsView from "@/components/result/ResultsView";
import CaseProgress from "@/components/case/CaseProgress";
import AnalysisLoader from "@/components/case/AnalysisLoader";
import { MODEL_STEP, OPEN_STEPS, PIPELINE_SHARE, PIPELINE_STEPS } from "@/lib/pipeline";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

/** Give up covering the page if the 3D scene never reports ready (e.g. no WebGL). */
const GATE_FAILSAFE_MS = 120_000;

/**
 * Keeps a full-screen progress view over the results until the 3D dentition has actually
 * loaded, been carved and drawn a frame — so the page never appears with an empty viewer.
 * Arriving straight from an analysis (`?from=analysis`) it continues that run's step list on
 * its final "Memuat model 3D" step; opening a finished case shows the load steps instead.
 */
function useResultsGate({ caseData, detections, detectionsFailed, error }) {
  const [fromAnalysis, setFromAnalysis] = useState(false);
  const [modelReady, setModelReady] = useState(false);
  const [assetPct, setAssetPct] = useState(0);
  const [ready, setReady] = useState(false);
  const [phase, setPhase] = useState("covering"); // covering → leaving → gone

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("from") !== "analysis") return;
    setFromAnalysis(true);
    params.delete("from");
    const qs = params.toString();
    window.history.replaceState(window.history.state, "", window.location.pathname + (qs ? `?${qs}` : ""));
  }, []);

  const onModelReady = useCallback(() => setModelReady(true), []);
  const onModelProgress = useCallback((p) => setAssetPct(p), []);

  // Ready = scene set up + detections applied + two frames drawn with them.
  useEffect(() => {
    if (!modelReady || !(detections || detectionsFailed)) return;
    let r2;
    const r1 = requestAnimationFrame(() => {
      r2 = requestAnimationFrame(() => setReady(true));
    });
    return () => {
      cancelAnimationFrame(r1);
      cancelAnimationFrame(r2);
    };
  }, [modelReady, detections, detectionsFailed]);

  useEffect(() => {
    if (ready && phase === "covering") setPhase("leaving");
    if (phase !== "leaving") return;
    const t = setTimeout(() => setPhase("gone"), 500);
    return () => clearTimeout(t);
  }, [ready, phase]);

  const caseDone = caseData?.status === "done";
  useEffect(() => {
    if (!caseDone) return;
    const t = setTimeout(() => setReady(true), GATE_FAILSAFE_MS);
    return () => clearTimeout(t);
  }, [caseDone]);

  // Not covering on error, or while the case is still running (CaseProgress has its own).
  const applies = !error && (!caseData || caseData.status === "done");
  let overlay = null;
  if (applies && phase !== "gone") {
    const leaving = phase === "leaving";
    const haveDetections = !!(detections || detectionsFailed);
    const frac =
      (caseData ? 0.1 : 0) +
      (haveDetections ? 0.1 : 0) +
      0.6 * (Math.min(100, assetPct) / 100) +
      (ready ? 0.2 : 0);

    if (fromAnalysis) {
      overlay = (
        <AnalysisLoader
          title="Menganalisis citra pasien"
          steps={[...PIPELINE_STEPS, MODEL_STEP]}
          active={ready ? PIPELINE_STEPS.length + 1 : PIPELINE_STEPS.length}
          percent={PIPELINE_SHARE + (100 - PIPELINE_SHARE) * frac}
          ceiling={99}
          leaving={leaving}
        />
      );
    } else {
      const active = ready ? 4 : !caseData ? 0 : !haveDetections ? 1 : assetPct < 100 ? 2 : 3;
      const milestones = [10, 20, 80, 100];
      overlay = (
        <AnalysisLoader
          title="Membuka hasil analisis"
          steps={OPEN_STEPS}
          active={active}
          percent={frac * 100}
          ceiling={milestones[Math.min(active, 3)] - 1}
          leaving={leaving}
        />
      );
    }
  }

  return { overlay, onModelReady, onModelProgress, markFromAnalysis: () => setFromAnalysis(true) };
}

function ResultsInner() {
  const { id } = useParams();
  const [caseData, setCaseData] = useState(null);
  const [detections, setDetections] = useState(null);
  const [detectionsFailed, setDetectionsFailed] = useState(false);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    api
      .get(`/cases/${id}`)
      .then((c) => alive && setCaseData(c))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Gagal memuat kasus"));
    return () => { alive = false; };
  }, [id, reloadKey]);

  const gate = useResultsGate({ caseData, detections, detectionsFailed, error });

  const datasetId = caseData?.dataset_id;
  const base = datasetId ? `/results/${datasetId}/` : null;

  useEffect(() => {
    if (!base) return;
    let alive = true;
    fetch(base + "detections.json")
      .then((r) => r.json())
      .then((d) => alive && setDetections(d))
      .catch(() => alive && setDetectionsFailed(true));
    return () => { alive = false; };
  }, [base]);

  if (error) {
    return <p className="p-6 text-sm text-destructive">{error}</p>;
  }
  if (!caseData) {
    return (
      gate.overlay ?? (
        <div className="flex min-h-[50vh] items-center justify-center" role="status" aria-label="Memuat">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )
    );
  }
  if (caseData.status !== "done") {
    return (
      <main className="mx-auto max-w-2xl px-4 py-6">
        <Header id={id} title={caseData.patient_name || "Kasus"} />
        <Card>
          <CardContent className="pt-6">
            {caseData.status === "failed" ? (
              <p className="text-sm text-destructive">
                Analisis gagal: {caseData.error || "kesalahan tidak diketahui"}
              </p>
            ) : (
              <CaseProgress
                caseId={id}
                onDone={() => {
                  gate.markFromAnalysis();
                  setReloadKey((k) => k + 1);
                }}
              />
            )}
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <>
      {gate.overlay}
      <ResultsView
        caseData={caseData}
        detections={detections}
        base={base}
        onModelReady={gate.onModelReady}
        onModelProgress={gate.onModelProgress}
      />
    </>
  );
}

function Header({ id, title }) {
  return (
    <header className="mb-5 flex items-center gap-2">
      <Button asChild variant="ghost" size="icon">
        <Link href="/" aria-label="Kembali">
          <ArrowLeft className="h-5 w-5" />
        </Link>
      </Button>
      <h1 className="truncate text-xl font-semibold">{title}</h1>
    </header>
  );
}

export default function CaseResultsPage() {
  return (
    <RequireRole role="doctor">
      <ResultsInner />
    </RequireRole>
  );
}
