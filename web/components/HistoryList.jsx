"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, ImageOff } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LogoMark } from "@/components/brand/Logo";

const STATUS = {
  draft: { label: "Draf", tone: "bg-muted text-muted-foreground", dot: "bg-muted-foreground/60" },
  uploaded: { label: "Foto terunggah", tone: "bg-amber-50 text-amber-700", dot: "bg-amber-500" },
  queued: { label: "Menunggu", tone: "bg-sky-50 text-sky-700", dot: "bg-sky-500" },
  running: { label: "Diproses", tone: "bg-primary/10 text-primary", dot: "bg-primary animate-pulse" },
  done: { label: "Selesai", tone: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  failed: { label: "Gagal", tone: "bg-destructive/10 text-destructive", dot: "bg-destructive" },
};

function formatDate(iso) {
  try {
    const d = new Date(iso);
    const date = d.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
    const time = d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
    return `${date} · ${time}`;
  } catch {
    return "";
  }
}

function HistoryCard({ c, index }) {
  const thumb = c.dataset_id ? `/results/${c.dataset_id}/thumb.jpg` : null;
  const [imgOk, setImgOk] = useState(true);
  const status = STATUS[c.status] || { label: c.status, tone: "bg-muted text-muted-foreground", dot: "bg-muted-foreground" };

  return (
    <Link
      href={`/case/${c.id}`}
      className="group flex items-center gap-3.5 rounded-2xl border bg-card p-3 transition-all duration-200 hover:-translate-y-px hover:border-primary/30 hover:shadow-[0_8px_24px_-12px_rgba(15,23,42,0.18)] animate-rise"
      style={{ "--i": index }}
    >
      <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-muted">
        {thumb && imgOk ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumb}
            alt=""
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
            onError={() => setImgOk(false)}
          />
        ) : (
          <ImageOff className="h-5 w-5 text-muted-foreground" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{c.patient_name || "Tanpa nama"}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{formatDate(c.created_at)}</p>
        <span className={cn("mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium", status.tone)}>
          <span className={cn("h-1.5 w-1.5 rounded-full", status.dot)} />
          {status.label}
        </span>
      </div>
      <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
    </Link>
  );
}

function SkeletonCard() {
  return (
    <div className="flex items-center gap-3.5 rounded-2xl border p-3">
      <div className="tf-shimmer h-16 w-16 shrink-0 rounded-xl bg-muted" />
      <div className="flex-1 space-y-2">
        <div className="tf-shimmer h-3.5 w-2/5 rounded bg-muted" />
        <div className="tf-shimmer h-3 w-1/3 rounded bg-muted" />
        <div className="tf-shimmer h-4 w-16 rounded-full bg-muted" />
      </div>
    </div>
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
      <div className="space-y-2.5" role="status" aria-label="Memuat riwayat">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (cases.length === 0) {
    return (
      <div className="flex flex-col items-center rounded-2xl border border-dashed px-6 py-10 text-center animate-fade-in">
        <LogoMark className="h-10 w-10 opacity-25 grayscale" title="" />
        <p className="mt-3 text-sm font-medium">Belum ada riwayat kasus.</p>
        <p className="mt-1 text-xs text-muted-foreground">Mulai dengan menekan “Kasus Baru”.</p>
      </div>
    );
  }
  return (
    <div className="space-y-2.5">
      {cases.map((c, i) => (
        <HistoryCard key={c.id} c={c} index={i} />
      ))}
    </div>
  );
}
