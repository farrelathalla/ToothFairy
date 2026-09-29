"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowLeft, Check, Loader2, Sparkles, UploadCloud } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import { DEMO_MODE, DEMO_PATIENT, loadDemoPhotos } from "@/lib/demo";
import { cn } from "@/lib/utils";
import AnamnesaForm from "@/components/case/AnamnesaForm";
import PhotoUpload, { VIEW_SLOTS, useFilePreview } from "@/components/case/PhotoUpload";
import CaseProgress from "@/components/case/CaseProgress";
import { Button } from "@/components/ui/button";

const FLOW = ["Anamnesa", "Foto", "Analisis"];

/** Anamnesa → Foto → Analisis, as a compact progress rail under the page title. */
function FlowSteps({ current }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Tahapan kasus">
      {FLOW.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li
            key={label}
            className={cn("flex items-center gap-2", i < FLOW.length - 1 && "flex-1")}
            aria-current={active ? "step" : undefined}
          >
            <span
              className={cn(
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition-all duration-300",
                done && "bg-primary text-primary-foreground",
                active && "bg-primary/10 text-primary ring-2 ring-primary",
                !done && !active && "bg-muted text-muted-foreground"
              )}
            >
              {done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
            </span>
            <span className={cn("text-xs font-medium", active ? "text-foreground" : "text-muted-foreground")}>
              {label}
            </span>
            {i < FLOW.length - 1 && (
              <span className="relative mx-1 h-0.5 min-w-4 flex-1 overflow-hidden rounded-full bg-muted">
                <span
                  className="absolute inset-y-0 left-0 bg-primary transition-[width] duration-500 ease-out"
                  style={{ width: done ? "100%" : "0%" }}
                />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Thumb({ file, label }) {
  const src = useFilePreview(file);
  return (
    <div className="relative aspect-square overflow-hidden rounded-xl bg-muted">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {src ? <img src={src} alt={label} className="h-full w-full object-cover" /> : null}
    </div>
  );
}

function NewCaseInner() {
  const [caseId, setCaseId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [files, setFiles] = useState({});
  const [loadingPhotos, setLoadingPhotos] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [running, setRunning] = useState(false);

  const nFiles = Object.values(files).filter(Boolean).length;
  const flowStep = !caseId ? 0 : uploaded ? 2 : 1;

  // Demo: drop the reference patient's photos into the slots once the photo step opens.
  useEffect(() => {
    if (!DEMO_MODE || !caseId) return;
    let alive = true;
    setLoadingPhotos(true);
    loadDemoPhotos()
      .then((preset) => alive && setFiles((prev) => ({ ...preset, ...prev })))
      .finally(() => alive && setLoadingPhotos(false));
    return () => {
      alive = false;
    };
  }, [caseId]);

  async function handleAnamnesa({ patient_name, anamnesa }) {
    setCreating(true);
    try {
      const c = await api.post("/cases", { patient_name, anamnesa });
      setCaseId(c.id);
      toast.success("Data anamnesa tersimpan");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Gagal menyimpan anamnesa");
    } finally {
      setCreating(false);
    }
  }

  function selectFile(key, file) {
    setFiles((prev) => {
      const next = { ...prev };
      if (file) next[key] = file;
      else delete next[key];
      return next;
    });
  }

  async function upload() {
    setUploading(true);
    try {
      const fd = new FormData();
      for (const { key } of VIEW_SLOTS) if (files[key]) fd.append(key, files[key]);
      await api.post(`/cases/${caseId}/images`, fd);
      toast.success("Foto berhasil diunggah");
      setUploaded(true);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Gagal mengunggah foto");
    } finally {
      setUploading(false);
    }
  }

  async function run() {
    try {
      await api.post(`/cases/${caseId}/run`);
      setRunning(true);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Gagal menjalankan analisis");
    }
  }

  return (
    <main className="mx-auto min-h-dvh max-w-2xl px-4 pb-10 pt-4">
      <header className="mb-5 space-y-4">
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="icon" className="-ml-2 rounded-full">
            <Link href="/" aria-label="Kembali">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <h1 className="text-xl font-semibold tracking-tight">Kasus Baru</h1>
        </div>
        <FlowSteps current={flowStep} />
      </header>

      <section className="rounded-3xl border bg-card p-5 shadow-sm sm:p-6 animate-fade-in">
        {!caseId ? (
          <>
            <AnamnesaForm
              onComplete={handleAnamnesa}
              submitting={creating}
              defaultValues={DEMO_MODE ? { patient_name: DEMO_PATIENT.patient_name, ...DEMO_PATIENT.anamnesa } : undefined}
            />
          </>
        ) : running ? (
          <CaseProgress caseId={caseId} onRetry={run} />
        ) : uploaded ? (
          <div className="space-y-6 animate-fade-in">
            <div className="flex flex-col items-center gap-2 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                <Check className="h-6 w-6 text-primary" strokeWidth={2.5} />
              </div>
              <h2 className="text-base font-semibold">Foto siap dianalisis</h2>
              <p className="max-w-xs text-sm text-muted-foreground">
                {nFiles} foto tersimpan. Jalankan deteksi karies, grading ICDAS, dan rekonstruksi 3D.
              </p>
            </div>
            <div className="grid grid-cols-6 gap-1.5">
              {VIEW_SLOTS.filter((s) => files[s.key]).map((s) => (
                <Thumb key={s.key} file={files[s.key]} label={s.label} />
              ))}
            </div>
            <Button className="h-12 w-full rounded-xl text-base" size="lg" onClick={run}>
              <Sparkles className="h-4 w-4" />
              Jalankan Analisis
            </Button>
          </div>
        ) : (
          <div className="space-y-5 animate-fade-in">
            <div>
              <h2 className="text-base font-semibold">Unggah Foto</h2>
              <p className="text-sm text-muted-foreground">
                Tambahkan 5 foto intraoral (tiap arah terpisah) dan 1 panoramik.
              </p>
            </div>
            <PhotoUpload files={files} onSelect={selectFile} loading={loadingPhotos} />
            <div className="flex items-center justify-between gap-3 border-t pt-4">
              <span className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{nFiles}</span> / {VIEW_SLOTS.length} foto dipilih
              </span>
              <Button size="lg" className="rounded-xl" onClick={upload} disabled={nFiles === 0 || uploading}>
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                Unggah Foto
              </Button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

export default function NewCasePage() {
  return (
    <RequireRole role="doctor">
      <NewCaseInner />
    </RequireRole>
  );
}
