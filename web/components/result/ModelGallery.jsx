"use client";
import React, { useEffect, useRef, useState } from "react";

/**
 * Per-model detection overlays + XAI attention maps as a horizontal slider.
 * `base` is the selected dataset's public dir (e.g. "/results/set1/"); overlay `src`s
 * in overlays.json are relative and get base-prefixed (CLAUDE.md §7). Clicking a card
 * opens a zoom/pan lightbox (wheel/double-click to zoom, drag to pan, ←/→ to page).
 */
export default function ModelGallery({
  base,
  items: itemsProp,
  title = "Hasil Deteksi & Explainable AI",
  ariaLabel = "Hasil deteksi per model",
}) {
  const [items, setItems] = useState(itemsProp || []);
  const [active, setActive] = useState(null);

  useEffect(() => {
    if (itemsProp) { setItems(itemsProp); return; } // allow injected items (tests, photos)
    const root = base || "/";
    fetch(root + "overlays/overlays.json")
      .then((r) => r.json())
      .then((list) =>
        setItems(
          list.map((it) => ({
            ...it,
            src:
              it.src?.startsWith("http") || it.src?.startsWith("/")
                ? it.src
                : root + it.src,
          }))
        )
      )
      .catch(() => setItems([]));
  }, [base, itemsProp]);

  if (!items.length) return null;

  const firstXaiIdx = items.findIndex((it) => it.id?.startsWith("xai_"));

  return (
    <section aria-label={ariaLabel} className="space-y-2">
      <p className="text-sm font-medium">{title}</p>
      <div className="no-scrollbar -mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2">
        {items.map((it, i) => (
          <button
            key={it.id}
            data-testid="gallery-card"
            onClick={() => setActive(i)}
            className="w-56 shrink-0 snap-start overflow-hidden rounded-xl border text-left transition-shadow hover:shadow-md"
          >
            <div className="aspect-video w-full overflow-hidden bg-muted">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={it.src} alt={it.title} loading="lazy" className="h-full w-full object-cover" />
            </div>
            <div className="p-2">
              <p className="truncate text-xs font-semibold">{it.title}</p>
              <p className="truncate text-[11px] text-muted-foreground">{it.desc}</p>
              {i === firstXaiIdx && firstXaiIdx >= 0 && (
                <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                  attention map
                </span>
              )}
            </div>
          </button>
        ))}
      </div>

      {active !== null && (
        <Lightbox
          item={items[active]}
          hasPrev={active > 0}
          hasNext={active < items.length - 1}
          onPrev={() => setActive((a) => Math.max(0, a - 1))}
          onNext={() => setActive((a) => Math.min(items.length - 1, a + 1))}
          onClose={() => setActive(null)}
        />
      )}
    </section>
  );
}

function Lightbox({ item, onClose, onPrev, onNext, hasPrev, hasNext }) {
  const [t, setT] = useState({ s: 1, x: 0, y: 0 });
  const drag = useRef(null);
  const wrapRef = useRef(null);

  useEffect(() => setT({ s: 1, x: 0, y: 0 }), [item.src]);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft" && hasPrev) onPrev();
      if (e.key === "ArrowRight" && hasNext) onNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onPrev, onNext, hasPrev, hasNext]);

  const zoomAt = (clientX, clientY, factor) => {
    const rect = wrapRef.current.getBoundingClientRect();
    const cx = clientX - rect.left - rect.width / 2;
    const cy = clientY - rect.top - rect.height / 2;
    setT((p) => {
      const s = Math.min(8, Math.max(1, p.s * factor));
      const k = s / p.s;
      let x = cx - (cx - p.x) * k;
      let y = cy - (cy - p.y) * k;
      if (s === 1) { x = 0; y = 0; }
      return { s, x, y };
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/80"
      role="dialog"
      aria-label={`Pratinjau ${item.title}`}
      onClick={onClose}
    >
      <div
        ref={wrapRef}
        className="relative flex max-h-[80vh] max-w-[92vw] items-center justify-center overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        onWheel={(e) => { e.preventDefault(); zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.2 : 1 / 1.2); }}
        onDoubleClick={(e) => zoomAt(e.clientX, e.clientY, t.s > 1 ? 1 / t.s : 2.2)}
        onPointerDown={(e) => { if (t.s > 1) { drag.current = { sx: e.clientX, sy: e.clientY, px: t.x, py: t.y }; e.currentTarget.setPointerCapture(e.pointerId); } }}
        onPointerMove={(e) => { const d = drag.current; if (d) setT((p) => ({ ...p, x: d.px + (e.clientX - d.sx), y: d.py + (e.clientY - d.sy) })); }}
        onPointerUp={() => (drag.current = null)}
        style={{ cursor: t.s > 1 ? "grab" : "default" }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={item.src}
          alt={item.title}
          draggable={false}
          style={{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.s})` }}
        />
      </div>
      <div className="mt-3 flex items-center gap-3 text-sm text-white" onClick={(e) => e.stopPropagation()}>
        <b>{item.title}</b>
        <span className="text-white/70">{item.desc}</span>
        <button className="rounded bg-white/10 px-2" onClick={() => setT((p) => ({ ...p, s: Math.max(1, p.s / 1.3) }))}>−</button>
        <span>{Math.round(t.s * 100)}%</span>
        <button className="rounded bg-white/10 px-2" onClick={() => setT((p) => ({ ...p, s: Math.min(8, p.s * 1.3) }))}>+</button>
        <button className="rounded bg-white/10 px-2" onClick={() => setT({ s: 1, x: 0, y: 0 })}>reset</button>
      </div>
      {hasPrev && <button aria-label="Sebelumnya" className="absolute left-4 top-1/2 text-3xl text-white" onClick={(e) => { e.stopPropagation(); onPrev(); }}>‹</button>}
      {hasNext && <button aria-label="Berikutnya" className="absolute right-4 top-1/2 text-3xl text-white" onClick={(e) => { e.stopPropagation(); onNext(); }}>›</button>}
      <button aria-label="Tutup" className="absolute right-4 top-4 text-2xl text-white" onClick={onClose}>✕</button>
    </div>
  );
}
