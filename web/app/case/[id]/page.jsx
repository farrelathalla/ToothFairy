"use client";
import { useEffect, useState } from "react";
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
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

// 3D + examiner are client-only (three.js has no SSR).
const Teeth3D = dynamic(() => import("@/components/three/Teeth3D"), { ssr: false });
const ToothExaminer = dynamic(() => import("@/components/ToothExaminer"), { ssr: false });

function ResultsInner() {
  const { id } = useParams();
  const [caseData, setCaseData] = useState(null);
  const [detections, setDetections] = useState(null);
  const [archMode, setArchMode] = useState("upper");
  const [selected, setSelected] = useState(null);
  const [examine, setExamine] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    api
      .get(`/cases/${id}`)
      .then((c) => alive && setCaseData(c))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Gagal memuat kasus"));
    return () => { alive = false; };
  }, [id]);

  const datasetId = caseData?.dataset_id;
  const base = datasetId ? `/results/${datasetId}/` : null;

  useEffect(() => {
    if (!base) return;
    let alive = true;
    fetch(base + "detections.json")
      .then((r) => r.json())
      .then((d) => alive && setDetections(d))
      .catch(() => {});
    return () => { alive = false; };
  }, [base]);

  const sel = selected && detections ? detections.teeth[String(selected)] : null;

  if (error) {
    return <p className="p-6 text-sm text-destructive">{error}</p>;
  }
  if (!caseData) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center" role="status" aria-label="Memuat">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
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
              <CaseProgress caseId={id} onDone={() => window.location.reload()} />
            )}
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
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
