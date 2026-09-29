"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  ArrowLeft,
  Box,
  ChartColumn,
  ClipboardList,
  Images,
  MessageSquareText,
  Microscope,
  MousePointerClick,
  Stethoscope,
  X,
} from "lucide-react";

import { ICDAS_COLORS } from "@/lib/damage";
import { ICDAS_LABEL_ID, summarize } from "@/lib/caries";
import { cn } from "@/lib/utils";
import ArchTabs from "@/components/result/ArchTabs";
import CariesSummary from "@/components/result/CariesSummary";
import PatientPhotos from "@/components/result/PatientPhotos";
import ModelGallery from "@/components/result/ModelGallery";
import AnamnesaSummary from "@/components/result/AnamnesaSummary";
import LlmDiagnosis from "@/components/result/LlmDiagnosis";
import LlmRecommendation from "@/components/result/LlmRecommendation";

// 3D + examiner are client-only (three.js has no SSR).
const Teeth3D = dynamic(() => import("@/components/three/Teeth3D"), { ssr: false });
const ToothExaminer = dynamic(() => import("@/components/ToothExaminer"), { ssr: false });

const NAV = [
  { id: "model", label: "Model 3D", icon: Box },
  { id: "ringkasan", label: "Ringkasan", icon: ChartColumn },
  { id: "diagnosis", label: "Diagnosis", icon: Stethoscope },
  { id: "perawatan", label: "Perawatan", icon: ClipboardList },
  { id: "foto", label: "Foto & AI", icon: Images },
  { id: "anamnesa", label: "Anamnesa", icon: MessageSquareText },
];

/** Height of the sticky header (title row + section nav), for scroll offsets. */
const HEADER_OFFSET = 116;

const isWide = () => typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches;

/** Which section the reader is in: the last one whose top has passed under the header. */
function useScrollSpy(ids) {
  const [active, setActive] = useState(ids[0]);
  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      let current = ids[0];
      for (const id of ids.slice(1)) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top - HEADER_OFFSET - 24 <= 0) current = id;
      }
      // at the very bottom, the last section wins even if it is short
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) current = ids.at(-1);
      setActive(current);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [ids]);
  return active;
}

/**
 * Fades + lifts its children in the first time they scroll into view. The settled state has
 * no `transform` at all (not even an identity one): a transformed ancestor would trap the
 * `position: fixed` lightbox and cross-section modal that live inside these sections.
 */
function Reveal({ children, className }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      className={cn(
        "transition-[opacity,transform] duration-700 ease-out",
        shown ? "opacity-100" : "translate-y-6 opacity-0",
        className
      )}
    >
      {children}
    </div>
  );
}

function SectionTitle({ icon: Icon, title, hint }) {
  return (
    <div className="mb-4 flex items-center gap-3">
      <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <Icon className="h-5 w-5" />
      </span>
      <div>
        <h2 className="text-lg font-semibold leading-tight tracking-tight">{title}</h2>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </div>
    </div>
  );
}

function formatDate(iso) {
  try {
    const d = new Date(iso);
    return `${d.toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" })} · ${d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}`;
  } catch {
    return "";
  }
}

/** The picked tooth: grade, notes, and shortcuts into its diagnosis / plan / cross-section. */
function ToothPanel({ tooth, onClose, onExamine, onJump }) {
  if (!tooth) {
    return (
      <p className="flex items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-3 text-xs text-muted-foreground">
        <MousePointerClick className="h-4 w-4" />
        Ketuk gigi pada model untuk melihat detail & rencananya
      </p>
    );
  }
  const color = ICDAS_COLORS[tooth.severity];
  return (
    <div key={tooth.fdi} className="rounded-2xl border bg-card p-4 shadow-sm animate-fade-in">
      <div className="flex items-start gap-3">
        <span
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-[3px] text-base font-bold tabular-nums"
          style={{ borderColor: color }}
        >
          {tooth.fdi}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            Gigi {tooth.fdi} —{" "}
            <span style={{ color }}>{tooth.severity ? `D${tooth.severity}` : "Sehat"}</span>
          </p>
          <p className="text-xs text-muted-foreground">{tooth.severity ? ICDAS_LABEL_ID[tooth.severity] : "Tidak ada karies terdeteksi"}</p>
          {tooth.hidden && (
            <p className="mt-1 text-xs text-amber-700">🩻 Lesi internal (X-ray) — permukaan tampak sehat.</p>
          )}
        </div>
        <button type="button" onClick={onClose} aria-label="Tutup detail gigi" className="-mr-1 -mt-1 flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <button type="button" onClick={onExamine} aria-label={`Belah gigi ${tooth.fdi}`} className="flex flex-col items-center gap-1 rounded-xl bg-muted/60 px-2 py-2.5 text-[11px] font-medium transition-colors hover:bg-primary/10 hover:text-primary">
          <Microscope className="h-4 w-4" />
          Belah gigi
        </button>
        <button type="button" onClick={() => onJump("diagnosis")} aria-label={`Diagnosis gigi ${tooth.fdi}`} className="flex flex-col items-center gap-1 rounded-xl bg-muted/60 px-2 py-2.5 text-[11px] font-medium transition-colors hover:bg-primary/10 hover:text-primary">
          <Stethoscope className="h-4 w-4" />
          Diagnosis
        </button>
        <button type="button" onClick={() => onJump("recommendation")} aria-label={`Rencana gigi ${tooth.fdi}`} className="flex flex-col items-center gap-1 rounded-xl bg-muted/60 px-2 py-2.5 text-[11px] font-medium transition-colors hover:bg-primary/10 hover:text-primary">
          <ClipboardList className="h-4 w-4" />
          Rencana
        </button>
      </div>
    </div>
  );
}

/**
 * The finished-case screen: a sticky header with a section menu that tracks the scroll, the
 * 3D dentition (sticky beside the report on wide screens), then summary, diagnosis, treatment
 * plan, photos/XAI and anamnesa — each a section the menu jumps to.
 */
export default function ResultsView({ caseData, detections, base, onModelReady, onModelProgress }) {
  const [archMode, setArchMode] = useState("upper");
  const [selected, setSelected] = useState(null);
  const [examine, setExamine] = useState(null);
  const [focus, setFocus] = useState(null);
  const navRef = useRef(null);

  const ids = useMemo(() => NAV.map((n) => n.id), []);
  const active = useScrollSpy(ids);
  const summary = useMemo(() => summarize(detections), [detections]);
  const grades = useMemo(
    () => Object.fromEntries(Object.values(detections?.teeth || {}).map((t) => [Number(t.fdi), t.severity || 0])),
    [detections]
  );
  const sel = selected && detections ? detections.teeth[String(selected)] : null;

  // keep the active menu item in view
  useEffect(() => {
    const nav = navRef.current;
    const chip = nav?.querySelector(`[data-id="${active}"]`);
    if (nav && chip) nav.scrollTo?.({ left: chip.offsetLeft - 16, behavior: "smooth" });
  }, [active]);

  const jumpTo = useCallback((id) => {
    if (id === "model") {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, []);

  const showTooth = useCallback((fdi) => {
    setSelected(fdi);
    const upper = [1, 2, 5, 6].includes(Math.floor(fdi / 10)); // permanent + primary upper quadrants
    setArchMode((m) => (m === "both" ? m : upper ? "upper" : "lower"));
    if (!isWide()) window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const jumpToTooth = (doc) => setFocus({ doc, fdi: selected, nonce: Date.now() });

  return (
    <>
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-4 pt-2.5 lg:max-w-6xl">
          <Link href="/" aria-label="Kembali" className="-ml-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-muted">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold leading-tight sm:text-lg">
              {caseData.patient_name || "Hasil Analisis"}
            </h1>
            <p className="truncate text-[11px] text-muted-foreground">
              {formatDate(caseData.created_at)}
              {summary.total ? ` · ${summary.total} gigi berkaries` : ""}
            </p>
          </div>
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Selesai
          </span>
        </div>
        <nav
          ref={navRef}
          aria-label="Bagian hasil"
          className="no-scrollbar mx-auto flex max-w-3xl gap-1 overflow-x-auto px-4 pb-2 pt-2 lg:max-w-6xl"
        >
          {NAV.map((n) => {
            const on = active === n.id;
            return (
              <button
                key={n.id}
                type="button"
                data-id={n.id}
                onClick={() => jumpTo(n.id)}
                aria-current={on ? "true" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-all duration-200",
                  on ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <n.icon className="h-3.5 w-3.5" />
                {n.label}
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-3xl px-4 pb-16 pt-4 lg:grid lg:max-w-6xl lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-start lg:gap-8">
        {/* 3D — sticky beside the report on wide screens */}
        <section id="model" aria-label="Model 3D" className="scroll-mt-32 space-y-3 lg:sticky lg:top-[132px]">
          <div className="relative overflow-hidden rounded-3xl border bg-[#0e1116] shadow-[0_20px_50px_-24px_rgba(15,23,42,0.6)] animate-fade-in">
            <div className="h-[52vh] min-h-[320px] w-full lg:h-[calc(100dvh-330px)] lg:min-h-[380px]">
              <Teeth3D
                detections={detections}
                archMode={archMode}
                selected={selected}
                onSelectTooth={setSelected}
                onReady={onModelReady}
                onProgress={onModelProgress}
              />
            </div>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center p-3">
              <ArchTabs value={archMode} onChange={setArchMode} overlay className="pointer-events-auto w-full max-w-xs" />
            </div>
          </div>
          <ToothPanel
            tooth={sel}
            onClose={() => setSelected(null)}
            onExamine={() => setExamine(sel)}
            onJump={jumpToTooth}
          />
        </section>

        <div className="mt-8 space-y-10 lg:mt-0">
          <section id="ringkasan" className="scroll-mt-32" aria-label="Ringkasan">
            <Reveal>
              <SectionTitle icon={ChartColumn} title="Ringkasan Temuan" hint="Hasil fusi deteksi intraoral & panoramik" />
              <CariesSummary detections={detections} onSelect={showTooth} selected={selected} />
            </Reveal>
          </section>

          <section id="diagnosis" className="scroll-mt-32" aria-label="Diagnosis">
            <Reveal>
              <LlmDiagnosis
                markdown={caseData.diagnosis_md}
                sanity={caseData.sanity_md}
                focus={focus}
                onShowTooth={showTooth}
                grades={grades}
              />
            </Reveal>
          </section>

          <section id="perawatan" className="scroll-mt-32" aria-label="Rencana perawatan">
            <Reveal>
              <LlmRecommendation
                markdown={caseData.recommendation_md}
                focus={focus}
                onShowTooth={showTooth}
                grades={grades}
              />
            </Reveal>
          </section>

          <section id="foto" className="scroll-mt-32 space-y-6" aria-label="Foto dan explainable AI">
            <Reveal>
              <SectionTitle icon={Images} title="Foto & Explainable AI" hint="Foto pasien, deteksi per model, dan peta atensi" />
              <div className="space-y-6">
                <PatientPhotos images={caseData.images} base={base} />
                <ModelGallery base={base} key={base} />
              </div>
            </Reveal>
          </section>

          <section id="anamnesa" className="scroll-mt-32" aria-label="Anamnesa">
            <Reveal>
              <SectionTitle icon={MessageSquareText} title="Anamnesa Pasien" hint="Jawaban yang dicatat saat kasus dibuat" />
              <AnamnesaSummary anamnesa={caseData.anamnesa} />
            </Reveal>
          </section>
        </div>
      </main>

      {examine ? <ToothExaminer tooth={examine} onClose={() => setExamine(null)} /> : null}
    </>
  );
}
