"use client";
import { ICDAS_CLASSES, ICDAS_LABEL_ID, summarize } from "@/lib/caries";
import { ICDAS_COLORS } from "@/lib/damage";
import { cn } from "@/lib/utils";

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-2xl border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums tracking-tight">{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * Caries overview: totals, the ICDAS distribution (a stacked bar plus per-class chips), and
 * the affected teeth worst-first as a horizontal scroller. Selecting a tooth bubbles its FDI up
 * via `onSelect` (the page highlights it on the 3D model).
 */
export default function CariesSummary({ detections, onSelect, selected }) {
  const s = summarize(detections);
  const missing = detections?.meta?.missing_fdi || [];
  const worst = s.affected[0]?.grade;

  return (
    <section className="space-y-5" aria-label="Ringkasan karies">
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Gigi berkaries" value={s.total} hint={worst ? `terparah D${worst}` : undefined} />
        <Stat label="Total lesi terdeteksi" value={s.totalLesions} hint={s.hidden.length ? `${s.hidden.length} hanya terlihat di X-ray` : undefined} />
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Sebaran derajat ICDAS</p>
        {s.total > 0 && (
          <div className="mb-3 flex h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden>
            {ICDAS_CLASSES.map((cls, i) =>
              s.perClass[cls] ? (
                <span
                  key={cls}
                  className="h-full transition-[width] duration-700 ease-out first:rounded-l-full last:rounded-r-full"
                  style={{ width: `${(s.perClass[cls] / s.total) * 100}%`, background: ICDAS_COLORS[i + 1] }}
                />
              ) : null
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5">
          {ICDAS_CLASSES.map((cls, i) => (
            <span
              key={cls}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-xs",
                !s.perClass[cls] && "opacity-50"
              )}
              title={ICDAS_LABEL_ID[i + 1]}
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: ICDAS_COLORS[i + 1] }} />
              <b>{cls}</b>
              <span className="tabular-nums text-muted-foreground">{s.perClass[cls]}</span>
            </span>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <p className="text-sm font-medium">Gigi terdampak ({s.total})</p>
          {s.total > 0 && <p className="text-[11px] text-muted-foreground">Ketuk untuk menyorot di model</p>}
        </div>
        {s.total === 0 ? (
          <p className="text-sm text-muted-foreground">Tidak ada karies terdeteksi.</p>
        ) : (
          <div className="no-scrollbar -mx-4 flex snap-x gap-2.5 overflow-x-auto px-4 pb-2">
            {s.affected.map((a, i) => (
              <button
                key={a.fdi}
                onClick={() => onSelect?.(a.fdi)}
                data-testid="affected-card"
                className={cn(
                  "w-32 shrink-0 snap-start rounded-2xl border bg-card p-3 text-left transition-all duration-200 animate-rise",
                  selected === a.fdi
                    ? "border-primary ring-2 ring-primary/30 -translate-y-0.5"
                    : "hover:-translate-y-0.5 hover:border-primary/40"
                )}
                style={{ "--i": Math.min(i, 8) }}
              >
                <div className="flex items-center justify-between">
                  <span className="text-lg font-semibold tabular-nums">{a.fdi}</span>
                  <span
                    className="rounded-full px-2 py-0.5 text-[11px] font-semibold text-white"
                    style={{ background: ICDAS_COLORS[a.grade] }}
                  >
                    D{a.grade}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
                  {ICDAS_LABEL_ID[a.grade]}
                </p>
                {a.hidden && (
                  <span className="mt-1.5 inline-block rounded-md bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                    🩻 tersembunyi
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {missing.length > 0 && (
        <div className="rounded-2xl border border-dashed bg-muted/40 p-3.5">
          <p className="text-sm font-medium">Gigi ompong (hilang)</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Tidak terdeteksi pada intraoral maupun panoramik, sehingga tidak ditampilkan pada model 3D:{" "}
            <b className="text-foreground">{missing.join(", ")}</b>
          </p>
        </div>
      )}
    </section>
  );
}
