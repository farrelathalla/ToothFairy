"use client";
import { ICDAS_CLASSES, ICDAS_LABEL_ID, summarize } from "@/lib/caries";
import { ICDAS_COLORS } from "@/lib/damage";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Caries overview placed BELOW the 3D box: total karies, per-ICDAS-class counts, and
 * the affected teeth as a horizontal scroller of cards (worst-first). Selecting a card
 * bubbles the FDI up via `onSelect`.
 */
export default function CariesSummary({ detections, onSelect, selected }) {
  const s = summarize(detections);
  const missing = detections?.meta?.missing_fdi || [];

  return (
    <section className="space-y-4" aria-label="Ringkasan karies">
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Gigi berkaries</p>
            <p className="text-2xl font-semibold">{s.total}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Total lesi terdeteksi</p>
            <p className="text-2xl font-semibold">{s.totalLesions}</p>
          </CardContent>
        </Card>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Sebaran derajat ICDAS</p>
        <div className="flex flex-wrap gap-2">
          {ICDAS_CLASSES.map((cls, i) => (
            <span
              key={cls}
              className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
              title={ICDAS_LABEL_ID[i + 1]}
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: ICDAS_COLORS[i + 1] }} />
              <b>{cls}</b>
              <span className="text-muted-foreground">{s.perClass[cls]}</span>
            </span>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Gigi terdampak ({s.total})</p>
        {s.total === 0 ? (
          <p className="text-sm text-muted-foreground">Tidak ada karies terdeteksi.</p>
        ) : (
          <div className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2">
            {s.affected.map((a) => (
              <button
                key={a.fdi}
                onClick={() => onSelect?.(a.fdi)}
                data-testid="affected-card"
                className={
                  "shrink-0 snap-start rounded-xl border p-3 text-left transition-colors w-36 " +
                  (selected === a.fdi ? "border-primary ring-1 ring-primary" : "hover:border-primary/50")
                }
              >
                <div className="flex items-center justify-between">
                  <span className="text-lg font-semibold">{a.fdi}</span>
                  <span
                    className="rounded-full px-2 py-0.5 text-xs font-semibold text-white"
                    style={{ background: ICDAS_COLORS[a.grade] }}
                  >
                    D{a.grade}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                  {ICDAS_LABEL_ID[a.grade]}
                </p>
                {a.hidden && (
                  <span className="mt-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                    🩻 tersembunyi
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {missing.length > 0 && (
        <div className="rounded-xl border border-dashed bg-muted/40 p-3">
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
