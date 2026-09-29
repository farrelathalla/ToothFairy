"use client";
import { useState } from "react";
import { ChevronDown, Crosshair, LayoutList, Table2, TriangleAlert } from "lucide-react";

import { ICDAS_COLORS } from "@/lib/damage";
import { cn } from "@/lib/utils";
import { Inline, Md, SourceCard } from "./Citations";

const fdiOf = (v) => Number(String(v).replace(/\D/g, "")) || null;
const gradeOf = (v) => {
  const m = /D\s*([1-6])/i.exec(String(v || ""));
  return m ? Number(m[1]) : 0;
};

/** Tone for short categorical values (urgency / confidence) so they scan at a glance. */
function toneFor(value) {
  const v = String(value).toLowerCase();
  if (/segera|darurat|tinggi|urgent/.test(v)) return "bg-rose-50 text-rose-700 ring-rose-200";
  if (/prioritas|sedang|terjadwal/.test(v)) return "bg-amber-50 text-amber-800 ring-amber-200";
  if (/rendah|rutin|kontrol/.test(v)) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  return "bg-muted text-foreground/80 ring-border";
}

function ToothBadge({ fdi, grade, size = "md" }) {
  const color = ICDAS_COLORS[grade] || "hsl(var(--border))";
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full border-2 bg-background font-semibold tabular-nums",
        size === "md" ? "h-10 w-10 text-sm" : "h-8 w-8 text-xs"
      )}
      style={{ borderColor: color }}
    >
      {fdi}
    </span>
  );
}

function ShowIn3D({ fdi, onShowTooth }) {
  if (!onShowTooth || !fdi) return null;
  return (
    <button
      type="button"
      onClick={() => onShowTooth(fdi)}
      className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium text-foreground/80 transition-colors hover:border-primary/40 hover:text-primary"
    >
      <Crosshair className="h-3.5 w-3.5" />
      Lihat di model 3D
    </button>
  );
}

/**
 * The per-tooth table as expandable cards: tooth, name, grade and the short categorical
 * columns (ICD-10 code, confidence, urgency) stay visible; the long columns open underneath.
 * Every column of every row is shown — "Tabel" switches back to the original grid.
 */
export function ToothTable({ kind, data, openFdi, setOpenFdi, onShowTooth }) {
  const [view, setView] = useState("cards");
  const [allOpen, setAllOpen] = useState(false);
  const { header, rows } = data;

  const nameCol = header.findIndex((h) => /nama/i.test(h));
  const gradeCol = header.findIndex((h) => /icdas/i.test(h));
  const rest = header.map((_, i) => i).filter((i) => i > 0 && i !== nameCol && i !== gradeCol);
  const longest = (i) => Math.max(...rows.map((r) => String(r[i] || "").length));
  const shortCols = rest.filter((i) => longest(i) <= 16);
  const longCols = rest.filter((i) => !shortCols.includes(i));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">{rows.length}</span> gigi
        </p>
        <div className="flex items-center gap-1.5">
          {view === "cards" && (
            <button
              type="button"
              onClick={() => {
                setAllOpen((v) => !v);
                setOpenFdi(null);
              }}
              className="rounded-full px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/5"
            >
              {allOpen ? "Tutup semua" : "Buka semua"}
            </button>
          )}
          <div className="inline-flex rounded-full bg-muted p-0.5" role="tablist" aria-label="Tampilan">
            {[
              ["cards", "Kartu", LayoutList],
              ["table", "Tabel", Table2],
            ].map(([key, label, Icon]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={view === key}
                onClick={() => setView(key)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-all",
                  view === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === "table" ? (
        <div className="overflow-x-auto rounded-2xl border animate-fade-in">
          <table className="w-full min-w-[720px] border-collapse text-left text-[13px]">
            <thead className="bg-muted/60">
              <tr>
                {header.map((h, i) => (
                  <th key={i} className="whitespace-nowrap px-3 py-2 text-xs font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri} className="border-t align-top">
                  {r.map((c, ci) => (
                    <td key={ci} className="px-3 py-2 leading-relaxed"><Inline text={c} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="space-y-2">
          {rows.map((r, ri) => {
            const fdi = fdiOf(r[0]);
            const grade = gradeOf(gradeCol >= 0 ? r[gradeCol] : "");
            const open = allOpen || openFdi === fdi;
            return (
              <li
                key={ri}
                id={`${kind}-tooth-${fdi}`}
                className={cn(
                  "scroll-mt-40 overflow-hidden rounded-2xl border bg-card transition-all duration-300 animate-rise",
                  open ? "border-primary/30 shadow-[0_8px_24px_-14px_rgba(37,99,235,0.45)]" : "hover:border-primary/20",
                  openFdi === fdi && "ring-2 ring-primary/30"
                )}
                style={{ "--i": Math.min(ri, 10) }}
              >
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => {
                    setAllOpen(false);
                    setOpenFdi(open && !allOpen ? null : fdi);
                  }}
                  className="flex w-full items-start gap-3 p-3 text-left"
                >
                  <ToothBadge fdi={r[0]} grade={grade} />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      {gradeCol >= 0 && r[gradeCol] ? (
                        <span
                          className="rounded-full px-2 py-0.5 text-[11px] font-semibold text-white"
                          style={{ background: ICDAS_COLORS[grade] || "#64748b" }}
                        >
                          {r[gradeCol]}
                        </span>
                      ) : null}
                      {shortCols.map((i) =>
                        r[i] ? (
                          <span key={i} title={header[i]} className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", toneFor(r[i]))}>
                            {r[i]}
                          </span>
                        ) : null
                      )}
                    </span>
                    {nameCol >= 0 && <span className="mt-1 block text-sm font-medium leading-snug">{r[nameCol]}</span>}
                    {!open && longCols[0] !== undefined && (
                      <span className="mt-0.5 line-clamp-2 block text-xs leading-relaxed text-muted-foreground">
                        <Inline text={r[longCols[0]]} />
                      </span>
                    )}
                  </span>
                  <ChevronDown className={cn("mt-2.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-300", open && "rotate-180 text-primary")} />
                </button>

                <div className={cn("grid transition-[grid-template-rows] duration-300 ease-out", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                  <div className="overflow-hidden" aria-hidden={!open} inert={open ? undefined : ""}>
                    <dl className="space-y-3 border-t bg-muted/20 px-4 py-3">
                      {longCols.map((i) => (
                        <div key={i}>
                          <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{header[i]}</dt>
                          <dd className="mt-0.5 text-[13.5px] leading-relaxed"><Inline text={r[i] || "—"} /></dd>
                        </div>
                      ))}
                      {shortCols.map((i) => (
                        <div key={i} className="flex items-baseline gap-2 text-xs">
                          <dt className="text-muted-foreground">{header[i]}:</dt>
                          <dd className="font-medium">{r[i] || "—"}</dd>
                        </div>
                      ))}
                      <div className="pt-1">
                        <ShowIn3D fdi={fdi} onShowTooth={onShowTooth} />
                      </div>
                    </dl>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** "**Gigi 21 (…)** — paragraph" blocks as one card per tooth. */
export function ToothNotes({ kind, data, openFdi, onShowTooth, grades }) {
  return (
    <div className="space-y-3">
      <Md>{data.before}</Md>
      <ul className="space-y-2.5">
        {data.notes.map((n, i) => (
          <li
            key={i}
            id={`${kind}-tooth-${n.fdi}`}
            className={cn(
              "scroll-mt-40 rounded-2xl border bg-card p-4 animate-rise",
              openFdi === n.fdi && "ring-2 ring-primary/30"
            )}
            style={{ "--i": i }}
          >
            <div className="flex items-center gap-3">
              <ToothBadge fdi={n.fdi} grade={grades?.[n.fdi] || 0} size="sm" />
              <p className="text-sm font-semibold leading-snug">{n.label}</p>
            </div>
            <p className="mt-2.5 text-[13.5px] leading-relaxed text-foreground/85"><Inline text={n.text} /></p>
            <div className="mt-3">
              <ShowIn3D fdi={n.fdi} onShowTooth={onShowTooth} />
            </div>
          </li>
        ))}
      </ul>
      <Md>{data.after}</Md>
    </div>
  );
}

/** The visit sequence as a vertical timeline. */
export function VisitTimeline({ data }) {
  return (
    <div className="space-y-3">
      <Md>{data.before}</Md>
      <ol className="relative space-y-4 pl-1">
        <span className="absolute bottom-3 left-[15px] top-3 w-px bg-gradient-to-b from-primary/50 via-primary/20 to-transparent" aria-hidden />
        {data.items.map((v, i) => (
          <li key={i} className="relative flex gap-3.5 animate-rise" style={{ "--i": i }}>
            <span className="relative z-10 flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground ring-4 ring-background">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1 rounded-2xl border bg-card p-3.5">
              <p className="text-sm font-semibold leading-snug">{v.title}</p>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-foreground/85"><Inline text={v.text} /></p>
            </div>
          </li>
        ))}
      </ol>
      <Md>{data.after}</Md>
    </div>
  );
}

export function AlertSection({ body }) {
  return (
    <div className="relative rounded-2xl border border-rose-200 bg-rose-50/60 p-4 pr-10">
      <TriangleAlert className="absolute right-3.5 top-3.5 h-4 w-4 text-rose-500" aria-hidden />
      <Md className="[&_li]:marker:text-rose-500">{body}</Md>
    </div>
  );
}

export function SourceList({ sources }) {
  if (!sources.length) return <p className="text-sm text-muted-foreground">Tidak ada rujukan.</p>;
  return (
    <div className="space-y-3">
      {sources.map((s, i) => (
        <SourceCard key={s.id} source={s} className="animate-rise" style={{ "--i": i }} />
      ))}
      <p className="text-[11px] text-muted-foreground">Setiap kutipan telah diverifikasi kata demi kata terhadap dokumen sumbernya.</p>
    </div>
  );
}
