"use client";
import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Loader2, Microscope } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import { ICDAS_COLORS, ICDAS_LABEL } from "@/lib/damage";
import ArchTabs from "@/components/result/ArchTabs";
import CariesSummary from "@/components/result/CariesSummary";
import PatientPhotos from "@/components/result/PatientPhotos";
import ModelGallery from "@/components/result/ModelGallery";
import AnamnesaSummary from "@/components/result/AnamnesaSummary";
import LlmDiagnosis from "@/components/result/LlmDiagnosis";
import LlmRecommendation from "@/components/result/LlmRecommendation";
import CaseProgress from "@/components/case/CaseProgress";
import AnalysisLoader from "@/components/case/AnalysisLoader";
import { MODEL_STEP, OPEN_STEPS, PIPELINE_SHARE, PIPELINE_STEPS } from "@/lib/pipeline";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

// 3D + examiner are client-only (three.js has no SSR).
const Teeth3D = dynamic(() => import("@/components/three/Teeth3D"), { ssr: false });
const ToothExaminer = dynamic(() => import("@/components/ToothExaminer"), { ssr: false });

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
  const [archMode, setArchMode] = useState("upper");
  const [selected, setSelected] = useState(null);
  const [examine, setExamine] = useState(null);
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

  const sel = selected && detections ? detections.teeth[String(selected)] : null;

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
    <main className="mx-auto max-w-3xl px-4 py-6 animate-fade-in">
      <Header id={id} title={caseData.patient_name || "Hasil Analisis"} />

      <div className="sticky top-0 z-10 -mx-4 mb-4 bg-background/90 px-4 py-2 backdrop-blur">
        <ArchTabs value={archMode} onChange={setArchMode} />
      </div>

      <div className="mb-4 overflow-hidden rounded-2xl border bg-[#0e1116] shadow-sm">
        <div className="h-[52vh] min-h-[320px] w-full">
          <Teeth3D
            detections={detections}
            archMode={archMode}
            selected={selected}
            onSelectTooth={setSelected}
            onReady={gate.onModelReady}
            onProgress={gate.onModelProgress}
          />
        </div>
      </div>

      {sel && (
        <Card className="mb-4">
          <CardContent className="flex flex-wrap items-center gap-3 pt-6">
            <span
              className="flex h-11 w-11 items-center justify-center rounded-full border-2 text-sm font-bold"
              style={{ borderColor: ICDAS_COLORS[sel.severity] }}
            >
              {sel.fdi}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-semibold">
                Gigi {sel.fdi} —{" "}
                <span style={{ color: ICDAS_COLORS[sel.severity] }}>
                  {sel.severity ? `D${sel.severity}` : "Sehat"}
                </span>
              </p>
              <p className="truncate text-xs text-muted-foreground">{ICDAS_LABEL[sel.severity]}</p>
              {sel.hidden && (
                <p className="mt-1 text-xs text-amber-700">
                  🩻 Lesi internal (X-ray) — permukaan tampak sehat.
                </p>
              )}
            </div>
            <Button variant="outline" size="sm" onClick={() => setExamine(sel)}>
              <Microscope className="h-4 w-4" />
              Belah gigi
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-6">
        <CariesSummary detections={detections} onSelect={setSelected} selected={selected} />
        <PatientPhotos images={caseData.images} base={base} />
        <ModelGallery base={base} key={datasetId} />
        <AnamnesaSummary anamnesa={caseData.anamnesa} />
        <LlmDiagnosis markdown={caseData.diagnosis_md} />
        <LlmRecommendation markdown={caseData.recommendation_md} />
      </div>

      {examine ? <ToothExaminer tooth={examine} onClose={() => setExamine(null)} /> : null}
    </main>
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
