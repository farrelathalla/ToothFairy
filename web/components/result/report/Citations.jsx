"use client";
import { createContext, Fragment, useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Streamdown } from "streamdown";
import { BookOpen, ExternalLink, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Citations inside an advisory document.
 *
 * `lib/report.js` rewrites each `[^n]` into a `#cite-n` link; here those become small chips that
 * open the source — title, link, and the verbatim quote `citations.py` verified — in a sheet,
 * so a claim can be audited without leaving the paragraph it supports.
 */

const CitationContext = createContext({ sources: [], open: () => {} });

export function CitationProvider({ sources, children }) {
  const [openId, setOpenId] = useState(null);
  const source = sources.find((s) => s.id === openId) || null;
  return (
    <CitationContext.Provider value={{ sources, open: setOpenId }}>
      {children}
      <SourceSheet source={source} onClose={() => setOpenId(null)} />
    </CitationContext.Provider>
  );
}

export function CitationChip({ id }) {
  const { sources, open } = useContext(CitationContext);
  const known = sources.some((s) => s.id === id);
  return (
    <button
      type="button"
      onClick={() => known && open(id)}
      aria-label={`Rujukan ${id}`}
      className={cn(
        "mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full px-1 align-middle text-[10px] font-semibold leading-none not-italic transition-colors",
        known ? "bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground" : "bg-muted text-muted-foreground"
      )}
    >
      {id}
    </button>
  );
}

/** Markdown link → citation chip for `#cite-n`, otherwise an external link that wraps. */
export function MdLink({ href = "", children }) {
  const cite = /^#cite-(.+)$/.exec(href);
  if (cite) return <CitationChip id={cite[1]} />;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="wrap-anywhere font-medium text-primary underline underline-offset-2">
      {children}
    </a>
  );
}

const MD_COMPONENTS = { a: MdLink };

/** Full markdown (Streamdown) with citation-aware links, in the report's typography. */
export function Md({ children, className }) {
  if (!children) return null;
  return (
    <div
      className={cn(
        "report-prose prose prose-sm max-w-none break-words text-[14px] leading-relaxed text-foreground/90 dark:prose-invert [&_table]:block [&_table]:overflow-x-auto",
        className
      )}
    >
      <Streamdown components={MD_COMPONENTS}>{children}</Streamdown>
    </div>
  );
}

/**
 * Light inline markdown for table cells and short notes, where a full Streamdown per cell
 * would be heavy: **bold**, *italic*, `code`, links/citations, and <br> line breaks.
 */
const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|<br\s*\/?>)/g;

export function Inline({ text }) {
  const parts = String(text || "").split(INLINE);
  return (
    <>
      {parts.map((p, i) => {
        if (!p) return null;
        if (/^<br/i.test(p)) return <br key={i} />;
        if (p.startsWith("**")) return <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>;
        if (p.startsWith("*") && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>;
        if (p.startsWith("`")) return <code key={i} className="rounded bg-muted px-1 text-[0.9em]">{p.slice(1, -1)}</code>;
        const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(p);
        if (link) return <MdLink key={i} href={link[2]}>{link[1]}</MdLink>;
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}

/** One source: number, title, link, verified quotes. */
export function SourceCard({ source, className, style }) {
  return (
    <article className={cn("rounded-2xl border bg-card p-4", className)} style={style}>
      <div className="flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
          {source.id}
        </span>
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold leading-snug">{source.title}</h4>
          {source.url ? (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="wrap-anywhere mt-1 inline-flex items-start gap-1 text-xs text-primary underline-offset-2 hover:underline"
            >
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
              {source.meta || source.url}
            </a>
          ) : source.meta ? (
            <p className="wrap-anywhere mt-1 text-xs text-muted-foreground">{source.meta}</p>
          ) : null}
        </div>
      </div>
      {source.quotes.length > 0 && (
        <div className="mt-3 space-y-2">
          {source.quotes.map((q, i) => (
            <blockquote key={i} className="rounded-xl border-l-[3px] border-primary/40 bg-muted/50 px-3 py-2 text-[13px] italic leading-relaxed text-foreground/80">
              “{q}”
            </blockquote>
          ))}
        </div>
      )}
    </article>
  );
}

/** Bottom sheet (portal, so no transformed ancestor can trap its `fixed`). */
function SourceSheet({ source, onClose }) {
  const [shown, setShown] = useState(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (source) {
      setShown(source);
      const r = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(r);
    }
    setVisible(false);
    const t = setTimeout(() => setShown(null), 250);
    return () => clearTimeout(t);
  }, [source]);

  useEffect(() => {
    if (!source) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [source, onClose]);

  if (!shown || typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={`Rujukan ${shown.id}`}>
      <div
        className={cn("absolute inset-0 bg-black/40 transition-opacity duration-200", visible ? "opacity-100" : "opacity-0")}
        onClick={onClose}
      />
      <div
        className={cn(
          "relative max-h-[80dvh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-background p-5 pb-8 shadow-2xl transition-transform duration-300 ease-out sm:rounded-3xl sm:pb-5",
          visible ? "translate-y-0" : "translate-y-full sm:translate-y-8"
        )}
      >
        <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-muted sm:hidden" />
        <div className="mb-3 flex items-center justify-between">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <BookOpen className="h-4 w-4 text-primary" />
            Rujukan
          </p>
          <button type="button" onClick={onClose} aria-label="Tutup" className="flex h-8 w-8 items-center justify-center rounded-full hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>
        <SourceCard source={shown} className="border-0 bg-muted/30" />
        <p className="mt-3 text-[11px] text-muted-foreground">Kutipan diverifikasi kata demi kata terhadap dokumen sumber.</p>
      </div>
    </div>,
    document.body
  );
}
