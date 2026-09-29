"use client";
import React, { useEffect, useRef, useState } from "react";

// Bottom-right gallery of per-model detection result images, with a zoom/pan lightbox.
// `base` is the selected dataset's public dir (e.g. "/results/set1/"); overlay `src`
// values in the manifest are relative to it.
export default function ResultsGallery({ base }) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(true);
  const [active, setActive] = useState(null); // index of lightbox image

  useEffect(() => {
    const root = base || "/";
    fetch(root + "overlays/overlays.json")
      .then((r) => r.json())
      .then((list) => setItems(list.map((it) => ({
        ...it,
        src: it.src?.startsWith("http") || it.src?.startsWith("/") ? it.src : root + it.src,
      }))))
      .catch(() => setItems([]));
  }, [base]);

  if (!items.length) return null;

  return (
    <>
      <div className={"gallery" + (open ? "" : " collapsed")}>
        <div className="ghead" onClick={() => setOpen((o) => !o)}>
          <span>Detection results</span>
          <span className="gtoggle">{open ? "▾" : "▴"}</span>
        </div>
        {open && (
          <div className="gbody">
            {items.map((it, i) => {
              const isXai = it.id.startsWith("xai_");
              const firstXai = isXai && !items[i - 1]?.id.startsWith("xai_");
              return (
                <React.Fragment key={it.id}>
                  {i === 0 && <div className="gsection">Detections</div>}
                  {firstXai && <div className="gsection">Explainable AI (attention maps)</div>}
                  <button className="gcard" onClick={() => setActive(i)} title="Click to zoom">
                    <img src={it.src} alt={it.title} loading="lazy" />
                    <div className="gcap">
                      <b>{it.title}</b>
                      <span>{it.desc}</span>
                    </div>
                    <div className="gzoom">⤢</div>
                  </button>
                </React.Fragment>
              );
            })}
          </div>
        )}
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
    </>
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
    <div className="lb" onClick={onClose}>
      <div className="lbstage" ref={wrapRef} onClick={(e) => e.stopPropagation()}
        onWheel={(e) => { e.preventDefault(); zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.2 : 1 / 1.2); }}
        onDoubleClick={(e) => zoomAt(e.clientX, e.clientY, t.s > 1 ? 1 / t.s : 2.2)}
        onPointerDown={(e) => { if (t.s > 1) { drag.current = { sx: e.clientX, sy: e.clientY, px: t.x, py: t.y }; e.currentTarget.setPointerCapture(e.pointerId); } }}
        onPointerMove={(e) => { const d = drag.current; if (d) setT((p) => ({ ...p, x: d.px + (e.clientX - d.sx), y: d.py + (e.clientY - d.sy) })); }}
        onPointerUp={() => (drag.current = null)}
        style={{ cursor: t.s > 1 ? "grab" : "default" }}
      >
        <img src={item.src} alt={item.title} draggable={false}
          style={{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.s})` }} />
      </div>

      <div className="lbbar" onClick={(e) => e.stopPropagation()}>
        <div className="lbinfo"><b>{item.title}</b><span>{item.model}</span><span>{item.desc}</span></div>
        <div className="lbctrl">
          <button onClick={() => setT((p) => ({ ...p, s: Math.max(1, p.s / 1.3), x: p.s / 1.3 <= 1 ? 0 : p.x, y: p.s / 1.3 <= 1 ? 0 : p.y }))}>−</button>
          <span>{Math.round(t.s * 100)}%</span>
          <button onClick={() => setT((p) => ({ ...p, s: Math.min(8, p.s * 1.3) }))}>+</button>
          <button onClick={() => setT({ s: 1, x: 0, y: 0 })}>reset</button>
        </div>
      </div>

      {hasPrev && <button className="lbnav prev" onClick={(e) => { e.stopPropagation(); onPrev(); }}>‹</button>}
      {hasNext && <button className="lbnav next" onClick={(e) => { e.stopPropagation(); onNext(); }}>›</button>}
      <button className="lbclose" onClick={onClose}>✕</button>
    </div>
  );
}
