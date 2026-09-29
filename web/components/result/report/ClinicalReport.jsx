"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Rows3, ShieldCheck, SquareStack } from "lucide-react";

import { parseReport, sectionForTooth } from "@/lib/report";
import { cn } from "@/lib/utils";
import { CitationProvider, Md } from "./Citations";
import { AlertSection, SourceList, ToothNotes, ToothTable, VisitTimeline } from "./Sections";

function SectionBody({ section, sources, kind, openFdi, setOpenFdi, onShowTooth, grades }) {
  switch (section.kind) {
    case "teeth-table":
      return (
        <div className="space-y-4">
          <Md>{section.data.before}</Md>
          <ToothTable kind={kind} data={section.data} openFdi={openFdi} setOpenFdi={setOpenFdi} onShowTooth={onShowTooth} />
          <Md>{section.data.after}</Md>
        </div>
      );
    case "tooth-notes":
      return <ToothNotes kind={kind} data={section.data} openFdi={openFdi} onShowTooth={onShowTooth} grades={grades} />;
    case "visits":
      return <VisitTimeline data={section.data} />;
    case "alert":
      return <AlertSection body={section.body} />;
    case "sources":
      return (
        <div className="space-y-4">
          <Md>{section.body}</Md>
          <SourceList sources={sources} />
        </div>
      );
    default:
      return <Md>{section.body}</Md>;
  }
}

/**
 * An advisory document (diagnosis or treatment plan) split into its sections.
 *
 * Paged by default — a chip rail of every section, one section at a time, previous/next at the
 * foot — so a 20k-character document reads as a sequence of short screens instead of one wall.
 * "Semua" lays every section out in order for reading straight through. Nothing is condensed.
 *
 * `focus` ({ doc, fdi, nonce }) lets the page jump here from a tooth picked on the 3D model:
 * the section holding that tooth opens, its card expands, and it scrolls into view.
 */
export default function ClinicalReport({
  kind,
  title,
  icon: Icon,
  markdown,
  emptyText,
  sanity,
  focus,
  onShowTooth,
  grades,
}) {
  const report = useMemo(() => parseReport(markdown), [markdown]);
  const [active, setActive] = useState(0);
  const [mode, setMode] = useState("paged");
  const [openFdi, setOpenFdi] = useState(null);
  const rootRef = useRef(null);
  const railRef = useRef(null);

  const sections = report.sections;
  const total = sections.length;
  const current = sections[Math.min(active, Math.max(total - 1, 0))];
  const verified = useMemo(() => /(\d+)\s+dari\s+(\d+)\s+kutipan\s+terverifikasi/i.exec(sanity || ""), [sanity]);

  // Keep the active chip centred in its rail.
  useEffect(() => {
    const rail = railRef.current;
    const chip = rail?.querySelector(`[data-index="${active}"]`);
    if (!rail || !chip) return;
    rail.scrollTo?.({ left: chip.offsetLeft - rail.clientWidth / 2 + chip.clientWidth / 2, behavior: "smooth" });
  }, [active, mode]);

  // Jump to a tooth picked elsewhere on the page.
  useEffect(() => {
    if (!focus || focus.doc !== kind) return;
    const idx = sectionForTooth(report, focus.fdi);
    if (idx >= 0) {
      setMode("paged");
      setActive(idx);
      setOpenFdi(focus.fdi);
    }
    const t = setTimeout(() => {
      const target = document.getElementById(`${kind}-tooth-${focus.fdi}`) || rootRef.current;
      target?.scrollIntoView?.({ behavior: "smooth", block: idx >= 0 ? "center" : "start" });
    }, 80);
    return () => clearTimeout(t);
  }, [focus, kind, report]);

  function go(i) {
    setActive(Math.max(0, Math.min(total - 1, i)));
    // bring the start of the new section into view if the reader had scrolled past it
    const top = rootRef.current?.getBoundingClientRect().top ?? 0;
    if (top < 0) rootRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
      <div className="flex shrink-0 items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          {Icon ? <Icon className="h-5 w-5" /> : null}
        </span>
        <div>
          <h2 className="text-lg font-semibold leading-tight tracking-tight">{title}</h2>
          {total > 0 && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {total} bagian{report.sources.length ? ` · ${report.sources.length} rujukan` : ""}
            </p>
          )}
        </div>
      </div>
      {verified && (
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">
          <ShieldCheck className="h-3.5 w-3.5" />
          {verified[1]}/{verified[2]} kutipan terverifikasi
        </span>
      )}
    </div>
  );

  if (!markdown) {
    return (
      <div ref={rootRef} className="rounded-3xl border bg-card p-5">
        {header}
        <p className="mt-4 text-sm text-muted-foreground">{emptyText}</p>
      </div>
    );
  }

  const bodyProps = { sources: report.sources, kind, openFdi, setOpenFdi, onShowTooth, grades };

  return (
    <CitationProvider sources={report.sources}>
      <div ref={rootRef} className="scroll-mt-32 rounded-3xl border bg-card p-4 shadow-sm sm:p-5">
        {header}

        {report.intro && <Md className="mt-4">{report.intro}</Md>}

        {total === 0 ? null : (
          <>
            {/* section rail + reading mode */}
            <div className="mt-4 flex items-center gap-2">
              <div
                ref={railRef}
                className="no-scrollbar -mx-1 flex min-w-0 flex-1 snap-x gap-1.5 overflow-x-auto px-1 py-0.5 [mask-image:linear-gradient(to_right,black_calc(100%-28px),transparent)]"
                role="tablist"
                aria-label={`Bagian ${title}`}
              >
                {sections.map((s, i) => {
                  const on = mode === "paged" && i === active;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      role="tab"
                      data-index={i}
                      aria-selected={on}
                      onClick={() => {
                        if (mode === "all") {
                          document.getElementById(`${kind}-${s.id}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
                        } else go(i);
                      }}
                      className={cn(
                        "flex shrink-0 snap-start items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200",
                        on
                          ? "border-primary bg-primary text-primary-foreground shadow-[0_4px_14px_-6px_rgba(37,99,235,0.7)]"
                          : "bg-background text-muted-foreground hover:border-primary/30 hover:text-foreground"
                      )}
                    >
                      {s.kind === "sources" ? (
                        <BookOpen className="h-3.5 w-3.5" />
                      ) : (
                        <span className={cn("tabular-nums", on ? "text-primary-foreground/70" : "text-muted-foreground/60")}>{i + 1}</span>
                      )}
                      {s.title}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => setMode((m) => (m === "paged" ? "all" : "paged"))}
                className="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                aria-pressed={mode === "all"}
                title={mode === "paged" ? "Tampilkan semua bagian" : "Satu bagian per halaman"}
              >
                {mode === "paged" ? <Rows3 className="h-3.5 w-3.5" /> : <SquareStack className="h-3.5 w-3.5" />}
                {mode === "paged" ? "Semua" : "Per bagian"}
              </button>
            </div>

            {mode === "paged" ? (
              <>
                {/* progress through the document */}
                <div className="mt-3 flex gap-1" aria-hidden>
                  {sections.map((s, i) => (
                    <span
                      key={s.id}
                      className={cn("h-1 flex-1 rounded-full transition-colors duration-300", i <= active ? "bg-primary" : "bg-muted")}
                    />
                  ))}
                </div>

                <section key={current.id} className="mt-5 animate-fade-in" aria-label={current.title}>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">
                    Bagian {active + 1} dari {total}
                  </p>
                  <h3 className="mb-3 mt-0.5 text-base font-semibold tracking-tight">{current.title}</h3>
                  <SectionBody section={current} {...bodyProps} />
                </section>

                <nav className="mt-6 grid grid-cols-2 gap-2 border-t pt-4" aria-label="Navigasi bagian">
                  <button
                    type="button"
                    onClick={() => go(active - 1)}
                    disabled={active === 0}
                    className="group flex min-w-0 flex-col items-start rounded-2xl px-3 py-2 text-left transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-0"
                  >
                    <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <ArrowLeft className="h-3 w-3 transition-transform group-hover:-translate-x-0.5" />
                      Sebelumnya
                    </span>
                    <span className="w-full truncate text-sm font-medium">{sections[active - 1]?.title}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => go(active + 1)}
                    disabled={active >= total - 1}
                    className="group flex min-w-0 flex-col items-end rounded-2xl px-3 py-2 text-right transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-0"
                  >
                    <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      Berikutnya
                      <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
                    </span>
                    <span className="w-full truncate text-sm font-medium text-primary">{sections[active + 1]?.title}</span>
                  </button>
                </nav>
              </>
            ) : (
              <div className="mt-5 space-y-8">
                {sections.map((s, i) => (
                  <section key={s.id} id={`${kind}-${s.id}`} className="scroll-mt-36" aria-label={s.title}>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">Bagian {i + 1}</p>
                    <h3 className="mb-3 mt-0.5 text-base font-semibold tracking-tight">{s.title}</h3>
                    <SectionBody section={s} {...bodyProps} />
                  </section>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </CitationProvider>
  );
}
