"use client";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowLeft, CheckCircle2, Loader2, Sparkles, UploadCloud } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { RequireRole } from "@/lib/auth";
import AnamnesaForm from "@/components/case/AnamnesaForm";
import PhotoUpload, { VIEW_SLOTS } from "@/components/case/PhotoUpload";
import CaseProgress from "@/components/case/CaseProgress";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

function NewCaseInner() {
  const [caseId, setCaseId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [files, setFiles] = useState({});
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [running, setRunning] = useState(false);

  const nFiles = Object.values(files).filter(Boolean).length;

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
    <main className="mx-auto min-h-dvh max-w-2xl px-4 py-6">
      <header className="mb-5 flex items-center gap-2">
        <Button asChild variant="ghost" size="icon">
          <Link href="/" aria-label="Kembali">
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>
        <h1 className="text-xl font-semibold">Kasus Baru</h1>
      </header>

      <Card className="animate-fade-in">
        <CardContent className="pt-6">
          {!caseId ? (
            <AnamnesaForm onComplete={handleAnamnesa} submitting={creating} />
          ) : running ? (
            <CaseProgress caseId={caseId} onRetry={run} />
          ) : uploaded ? (
            <div className="space-y-5 text-center">
              <div className="flex flex-col items-center gap-2">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                  <CheckCircle2 className="h-6 w-6 text-primary" />
                </div>
                <h2 className="text-base font-semibold">Foto siap dianalisis</h2>
                <p className="text-sm text-muted-foreground">
                  {nFiles} foto tersimpan. Jalankan deteksi karies & rekonstruksi 3D.
                </p>
              </div>
              <Button className="w-full" size="lg" onClick={run}>
                <Sparkles className="h-4 w-4" />
                Jalankan Analisis
              </Button>
            </div>
          ) : (
            <div className="space-y-5">
              <div>
                <h2 className="text-base font-semibold">Unggah Foto</h2>
                <p className="text-sm text-muted-foreground">
                  Tambahkan 5 foto intraoral (tiap arah terpisah) dan 1 panoramik.
                </p>
              </div>
              <PhotoUpload files={files} onSelect={selectFile} />
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-muted-foreground">{nFiles} foto dipilih</span>
                <Button onClick={upload} disabled={nFiles === 0 || uploading}>
                  {uploading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <UploadCloud className="h-4 w-4" />
                  )}
                  Unggah Foto
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
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
