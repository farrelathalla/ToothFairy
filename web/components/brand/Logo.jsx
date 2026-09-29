import { useId } from "react";

import { cn } from "@/lib/utils";

/** Tooth silhouette (crown + two roots) on a 64-unit grid. Shared with the PWA icons. */
export const TOOTH_PATH =
  "M22 11C15.6 11 11.5 15.6 11.5 22.2c0 5.6 2.3 9 3.8 13.4 1.8 5.4 2 15.4 7.4 15.4 4.3 0 4.5-7.6 6-11.5.8-2.1 1.9-2.9 3.3-2.9s2.5.8 3.3 2.9c1.5 3.9 1.7 11.5 6 11.5 5.4 0 5.6-10 7.4-15.4 1.5-4.4 3.8-7.8 3.8-13.4C52.5 15.6 48.4 11 42 11c-4 0-6.3 1.9-10 1.9S26 11 22 11Z";

/** Four-point "fairy" sparkle. */
export const SPARK_PATH = "M50 3.5c.7 4.6 2.4 6.3 7 7-4.6.7-6.3 2.4-7 7-.7-4.6-2.4-6.3-7-7 4.6-.7 6.3-2.4 7-7Z";

/** Enamel highlight on the crown. */
export const SHINE_PATH = "M18.2 22.5c0-3.6 1.8-5.8 5.2-6.3";

/**
 * The ToothFairy mark: a tooth on a clinical-blue tile with a sparkle.
 *
 * `animated` draws the outline in, fills it, then lets the sparkle twinkle on a slow loop —
 * used on the sign-in screen. Everywhere else it is static. Motion is dropped entirely under
 * `prefers-reduced-motion`.
 */
export function LogoMark({ className, animated = false, title = "ToothFairy" }) {
  const gid = useId().replace(/:/g, "");
  return (
    <svg
      viewBox="0 0 64 64"
      role="img"
      aria-label={title}
      className={cn("tf-logo shrink-0", animated && "tf-logo--animated", className)}
    >
      <defs>
        <linearGradient id={`tile-${gid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3b82f6" />
          <stop offset="1" stopColor="#1d4ed8" />
        </linearGradient>
      </defs>
      <rect className="tf-logo-tile" width="64" height="64" rx="17" fill={`url(#tile-${gid})`} />
      <path
        className="tf-logo-tooth"
        d={TOOTH_PATH}
        pathLength="1"
        fill="#fff"
        stroke="#fff"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <path className="tf-logo-shine" d={SHINE_PATH} fill="none" stroke="#93b4f5" strokeWidth="2.4" strokeLinecap="round" />
      {/* the tile-coloured halo separates the sparkle from the crown it overlaps */}
      <path className="tf-logo-spark" d={SPARK_PATH} fill="#fff" stroke="#377bf2" strokeWidth="2.4" paintOrder="stroke" />
    </svg>
  );
}

/** Mark + wordmark, for page headers. */
export function Logo({ className, markClassName, animated = false }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark animated={animated} className={cn("h-8 w-8", markClassName)} />
      <span className="text-[15px] font-semibold tracking-tight">
        Tooth<span className="text-primary">Fairy</span>
      </span>
    </span>
  );
}
