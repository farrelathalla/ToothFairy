"use client";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "upper", label: "Atas" },
  { key: "lower", label: "Bawah" },
  { key: "both", label: "Keduanya" },
];

/**
 * Arch selector controlling the 3D `archMode`. `overlay` is the frosted variant that floats on
 * the dark viewer; the active pill slides between options.
 */
export default function ArchTabs({ value, onChange, overlay = false, className }) {
  const index = Math.max(0, TABS.findIndex((t) => t.key === value));
  return (
    <div
      role="tablist"
      aria-label="Pilih bagian rahang"
      className={cn(
        "relative grid grid-cols-3 rounded-full p-1",
        overlay ? "bg-black/45 ring-1 ring-white/10 backdrop-blur-md" : "bg-muted",
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-1 left-1 rounded-full shadow-sm transition-transform duration-300 ease-out",
          overlay ? "bg-white" : "bg-background"
        )}
        style={{ width: "calc((100% - 0.5rem) / 3)", transform: `translateX(${index * 100}%)` }}
      />
      {TABS.map((t) => {
        const active = value === t.key;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.key)}
            className={cn(
              "relative z-10 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors duration-200 sm:text-sm",
              overlay
                ? active ? "text-slate-900" : "text-white/75 hover:text-white"
                : active ? "text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
