"use client";
import { useEffect, useState } from "react";
import { Check, ImagePlus, ScanLine, X } from "lucide-react";

import { cn } from "@/lib/utils";

export const VIEW_SLOTS = [
  { key: "up", label: "Rahang Atas (oklusal)", group: "intraoral" },
  { key: "bottom", label: "Rahang Bawah (oklusal)", group: "intraoral" },
  { key: "front", label: "Depan", group: "intraoral" },
  { key: "side_left", label: "Samping Kiri", group: "intraoral" },
  { key: "side_right", label: "Samping Kanan", group: "intraoral" },
  { key: "panoramic", label: "Panoramik", group: "panoramic" },
];

/** Object-URL preview for a picked file, revoked when it changes. */
export function useFilePreview(file) {
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return preview;
}

function Slot({ slot, file, onSelect, loading, wide, index }) {
  const preview = useFilePreview(file);

  return (
    <div className={cn("relative animate-rise", wide && "col-span-2")} style={{ "--i": index }}>
      <label
        className={cn(
          "group relative flex cursor-pointer flex-col items-center justify-center gap-1.5 overflow-hidden rounded-2xl border-2 border-dashed bg-muted/40 p-2 text-center transition-all duration-200 hover:border-primary/60 hover:bg-primary/[0.03] focus-within:ring-2 focus-within:ring-ring",
          wide ? "aspect-[2.2/1]" : "aspect-[4/3]",
          file && "border-solid border-transparent bg-muted"
        )}
      >
        <input
          type="file"
          accept="image/*"
          aria-label={slot.label}
          className="sr-only"
          onChange={(e) => onSelect(slot.key, e.target.files?.[0] ?? null)}
        />
        {loading && !file ? (
          <span className="tf-shimmer absolute inset-0 bg-muted" aria-hidden />
        ) : null}
        {preview ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={preview}
              alt={slot.label}
              className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03] animate-fade-in"
            />
            <span className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-black/70 to-transparent" />
            <span className="absolute left-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow">
              <Check className="h-3 w-3" strokeWidth={3} />
            </span>
            <span className="absolute inset-x-2 bottom-2 text-left">
              <span className="block truncate text-xs font-medium text-white">{slot.label}</span>
              <span className="block max-w-full truncate text-[10px] text-white/70">{file.name}</span>
            </span>
          </>
        ) : (
          <>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-background text-muted-foreground shadow-sm transition-colors group-hover:text-primary">
              {slot.group === "panoramic" ? <ScanLine className="h-4 w-4" /> : <ImagePlus className="h-4 w-4" />}
            </span>
            <span className="relative text-xs font-medium text-foreground/80">{slot.label}</span>
            {file && <span className="relative max-w-full truncate text-[10px] text-muted-foreground">{file.name}</span>}
          </>
        )}
      </label>
      {file && (
        <button
          type="button"
          aria-label={`Hapus ${slot.label}`}
          onClick={() => onSelect(slot.key, null)}
          className="absolute right-2 top-2 z-20 flex h-7 w-7 items-center justify-center rounded-full bg-background/90 shadow-sm backdrop-blur transition-colors hover:bg-background"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function GroupHeading({ title, hint, count, total }) {
  return (
    <div className="mb-2.5 flex items-baseline justify-between gap-3">
      <p className="text-sm font-medium">
        {title} <span className="font-normal text-muted-foreground">· {hint}</span>
      </p>
      <span className={cn("text-xs tabular-nums", count === total ? "text-primary" : "text-muted-foreground")}>
        {count}/{total}
      </span>
    </div>
  );
}

/**
 * Six independent upload slots (5 intraoral views + panoramic).
 * @param {{[key:string]: File}} files
 * @param {(viewKey:string, file:File|null)=>void} onSelect
 * @param {boolean} [loading]  show placeholders shimmering while preset photos load
 */
export default function PhotoUpload({ files, onSelect, loading = false }) {
  const intraoral = VIEW_SLOTS.filter((s) => s.group === "intraoral");
  const panoramic = VIEW_SLOTS.filter((s) => s.group === "panoramic");
  const count = (slots) => slots.filter((s) => files[s.key]).length;

  return (
    <div className="space-y-5">
      <div>
        <GroupHeading title="Foto Intraoral" hint="5 arah" count={count(intraoral)} total={intraoral.length} />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {intraoral.map((slot, i) => (
            <Slot key={slot.key} index={i} slot={slot} file={files[slot.key]} onSelect={onSelect} loading={loading} />
          ))}
        </div>
      </div>
      <div>
        <GroupHeading title="Panoramik" hint="rontgen" count={count(panoramic)} total={panoramic.length} />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {panoramic.map((slot, i) => (
            <Slot key={slot.key} index={5 + i} slot={slot} file={files[slot.key]} onSelect={onSelect} loading={loading} wide />
          ))}
        </div>
      </div>
    </div>
  );
}
