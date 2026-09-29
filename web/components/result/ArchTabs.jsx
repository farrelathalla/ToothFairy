"use client";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "upper", label: "Bagian Atas" },
  { key: "lower", label: "Bagian Bawah" },
  { key: "both", label: "Keduanya" },
];

/** Sticky arch selector controlling the 3D `archMode`. */
export default function ArchTabs({ value, onChange }) {
  return (
    <div
      role="tablist"
      aria-label="Pilih bagian rahang"
      className="inline-flex w-full gap-1 rounded-full bg-muted p-1"
    >
      {TABS.map((t) => {
        const active = value === t.key;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.key)}
            className={cn(
              "flex-1 rounded-full px-3 py-2 text-sm font-medium transition-colors",
              active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
