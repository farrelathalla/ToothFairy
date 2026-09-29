"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, ImageOff, Loader2 } from "lucide-react";

import { api, ApiError } from "@/lib/api";

const STATUS_LABEL = {
  draft: "Draf", uploaded: "Foto terunggah", queued: "Menunggu",
  running: "Diproses", done: "Selesai", failed: "Gagal",
};

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return "";
  }
}

function HistoryCard({ c }) {
  const thumb = c.dataset_id ? `/results/${c.dataset_id}/thumb.jpg` : null;
  const [imgOk, setImgOk] = useState(true);
  return (
    <Link
      href={`/case/${c.id}`}
      className="flex items-center gap-3 rounded-xl border p-3 transition-colors hover:border-primary/50 hover:bg-muted/40"
    >
      <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted">
        {thumb && imgOk ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="h-full w-full object-cover" onError={() => setImgOk(false)} />
        ) : (
          <ImageOff className="h-5 w-5 text-muted-foreground" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{c.patient_name || "Tanpa nama"}</p>
        <p className="text-xs text-muted-foreground">{formatDate(c.created_at)}</p>
        <span className="mt-1 inline-block rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
          {STATUS_LABEL[c.status] || c.status}
        </span>
      </div>
      <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" />
    </Link>
  );
}

/** Doctor case history from GET /cases (own cases, newest first). */
export default function HistoryList() {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    api
      .get("/cases")
      .then((list) => alive && setCases(list))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : "Gagal memuat riwayat"));
    return () => { alive = false; };
  }, []);

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (cases === null) {
    return (
      <div className="flex justify-center py-8" role="status" aria-label="Memuat riwayat">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (cases.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-8 text-center">
        <p className="text-sm text-muted-foreground">Belum ada riwayat kasus.</p>
        <p className="mt-1 text-xs text-muted-foreground">Mulai dengan menekan “Kasus Baru”.</p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {cases.map((c) => (
        <HistoryCard key={c.id} c={c} />
      ))}
    </div>
  );
}
