"use client";
import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";

import { TOOTH_PATH } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";

/**
 * Eases a displayed percentage toward `target` every frame, and while the real work sits on a
 * milestone lets it creep (asymptotically) toward `ceiling` so the bar never looks frozen —
 * without ever passing the next real milestone. Only ever moves forward.
 */
function useSmoothPercent(target, ceiling = target) {
  const [shown, setShown] = useState(target);
  const ref = useRef({ value: target, target, ceiling });
  ref.current.target = target;
  ref.current.ceiling = Math.max(target, ceiling);

  useEffect(() => {
    let raf;
    const tick = () => {
      const s = ref.current;
      let v = s.value;
      if (v < s.target) v += Math.max(0.15, (s.target - v) * 0.08);
      else if (v < s.ceiling) v += (s.ceiling - v) * 0.004;
      v = Math.min(v, Math.max(s.target, s.ceiling));
      if (Math.floor(v) !== Math.floor(s.value)) setShown(v);
      s.value = v;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return Math.min(100, Math.floor(Math.max(shown, 0)));
}

/** Tooth outline with a scan band sweeping through it, inside a slow orbit ring. */
function ScanMark() {
  return (
    <div className="relative h-28 w-28">
      <svg viewBox="0 0 120 120" className="tf-orbit absolute inset-0 h-full w-full" aria-hidden>
        <circle cx="60" cy="60" r="56" fill="none" stroke="hsl(var(--primary) / 0.12)" strokeWidth="2" />
        <circle
          cx="60" cy="60" r="56" fill="none" stroke="hsl(var(--primary))" strokeWidth="2.5"
          strokeLinecap="round" strokeDasharray="44 308"
        />
        <circle cx="60" cy="4" r="3.5" fill="hsl(var(--primary))" />
      </svg>
      <svg viewBox="0 0 64 64" className="absolute inset-[22%] h-[56%] w-[56%]" aria-hidden>
        <defs>
          <clipPath id="tf-scan-clip">
            <path d={TOOTH_PATH} />
          </clipPath>
          <linearGradient id="tf-scan-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="hsl(var(--primary))" stopOpacity="0" />
            <stop offset="0.8" stopColor="hsl(var(--primary))" stopOpacity="0.55" />
            <stop offset="1" stopColor="hsl(var(--primary))" stopOpacity="0.9" />
          </linearGradient>
        </defs>
        <path d={TOOTH_PATH} fill="hsl(var(--primary) / 0.08)" />
        <g clipPath="url(#tf-scan-clip)">
          <rect className="tf-scan-band" x="0" y="0" width="64" height="12" fill="url(#tf-scan-grad)" />
        </g>
        <path
          d={TOOTH_PATH} fill="none" stroke="hsl(var(--primary))" strokeWidth="2.6"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

function StepRow({ label, state, index }) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors duration-300 animate-rise",
        state === "active" && "bg-primary/[0.07]"
      )}
      style={{ "--i": index }}
      aria-current={state === "active" ? "step" : undefined}
    >
      <span
        className={cn(
          "relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full border transition-all duration-300",
          state === "done" && "border-primary bg-primary text-primary-foreground",
          state === "active" && "border-primary bg-background",
          state === "pending" && "border-border bg-background"
        )}
      >
        {state === "done" ? (
          <Check className="h-3.5 w-3.5" strokeWidth={3} />
        ) : state === "active" ? (
          <>
            <span className="absolute inset-0 animate-ping rounded-full bg-primary/25" />
            <span className="h-2 w-2 rounded-full bg-primary" />
          </>
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-border" />
        )}
      </span>
      <span
        className={cn(
          "transition-colors duration-300",
          state === "done" && "text-muted-foreground",
          state === "active" && "font-medium text-foreground",
          state === "pending" && "text-muted-foreground/60"
        )}
      >
        {label}
      </span>
    </li>
  );
}

/**
 * Full-screen progress screen for an analysis (and for building the 3D result after it).
 *
 * @param {object}   props
 * @param {string}   props.title
 * @param {{key:string,label:string}[]} props.steps
 * @param {number}   props.active     index of the running step (steps before it are done)
 * @param {number}   props.percent    real overall progress, 0–100
 * @param {number}  [props.ceiling]   how far the bar may creep while waiting on `percent`
 * @param {string}  [props.detail]    live detail line under the current step
 * @param {boolean} [props.leaving]   fade out (the caller unmounts afterwards)
 */
export default function AnalysisLoader({ title, steps, active, percent, ceiling, detail, leaving = false }) {
  const shown = useSmoothPercent(percent, ceiling);
  const current = steps[Math.min(active, steps.length - 1)];

  // The page underneath keeps mounting (that is the point: the 3D scene loads behind this), so
  // stop it from scrolling while covered.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-background px-4 py-8 transition-opacity duration-500",
        leaving ? "pointer-events-none opacity-0" : "opacity-100"
      )}
      role="status"
      aria-live="polite"
      aria-label={title}
    >
      <div className="bg-dots pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]" />
      <div className="relative w-full max-w-sm animate-fade-in">
        <div className="flex flex-col items-center text-center">
          <ScanMark />
          <p className="mt-6 text-5xl font-semibold tabular-nums tracking-tight">
            {shown}
            <span className="ml-0.5 text-2xl font-medium text-muted-foreground">%</span>
          </p>
          <h2 className="mt-2 text-base font-semibold">{title}</h2>
          <p key={current?.key} className="mt-1 min-h-[1.25rem] text-sm text-primary animate-fade-in">
            {current?.label}
            {detail && detail !== current?.label ? (
              <span className="text-muted-foreground"> · {detail}</span>
            ) : null}
          </p>
        </div>

        <div
          className="mt-5 h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={shown}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Kemajuan analisis"
        >
          <div
            className="tf-shimmer h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
            style={{ width: `${shown}%` }}
          />
        </div>

        <ol className="mt-6 space-y-1">
          {steps.map((s, i) => (
            <StepRow
              key={s.key}
              index={i}
              label={s.label}
              state={i < active ? "done" : i === active ? "active" : "pending"}
            />
          ))}
        </ol>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Mohon tetap di halaman ini hingga selesai.
        </p>
      </div>
    </div>
  );
}
