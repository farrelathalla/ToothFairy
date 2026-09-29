"use client";
import { useEffect, useState } from "react";
import { ImagePlus, X } from "lucide-react";

import { cn } from "@/lib/utils";

export const VIEW_SLOTS = [
  { key: "up", label: "Rahang Atas (oklusal)", group: "intraoral" },
  { key: "bottom", label: "Rahang Bawah (oklusal)", group: "intraoral" },
  { key: "front", label: "Depan", group: "intraoral" },
  { key: "side_left", label: "Samping Kiri", group: "intraoral" },
  { key: "side_right", label: "Samping Kanan", group: "intraoral" },
  { key: "panoramic", label: "Panoramik", group: "panoramic" },
];

function Slot({ slot, file, onSelect }) {
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

  return (
    <div className="relative">
      <label
        className={cn(
          "flex aspect-[4/3] cursor-pointer flex-col items-center justify-center gap-1 overflow-hidden rounded-xl border-2 border-dashed bg-muted/30 p-2 text-center transition-colors hover:border-primary/60",
          file && "border-solid border-primary"
        )}
      >
        <input
          type="file"
          accept="image/*"
          aria-label={slot.label}
          className="sr-only"
          onChange={(e) => onSelect(slot.key, e.target.files?.[0] ?? null)}
        />
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt={slot.label} className="absolute inset-0 h-full w-full object-cover opacity-70" />
        ) : (
          <ImagePlus className="h-6 w-6 text-muted-foreground" />
        )}
        <span className="relative z-10 text-xs font-medium drop-shadow-sm">{slot.label}</span>
        {file && (
          <span className="relative z-10 max-w-full truncate text-[10px] text-foreground/80">
            {file.name}
          </span>
        )}
      </label>
      {file && (
        <button
          type="button"
          aria-label={`Hapus ${slot.label}`}
          onClick={() => onSelect(slot.key, null)}
          className="absolute right-1 top-1 z-20 flex h-6 w-6 items-center justify-center rounded-full bg-background/90 shadow"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

/**
 * Six independent upload slots (5 intraoral views + panoramic).
 * @param {{[key:string]: File}} files
 * @param {(viewKey:string, file:File|null)=>void} onSelect
 */
export default function PhotoUpload({ files, onSelect }) {
  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-sm font-medium">Foto Intraoral (5 arah)</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {VIEW_SLOTS.filter((s) => s.group === "intraoral").map((slot) => (
            <Slot key={slot.key} slot={slot} file={files[slot.key]} onSelect={onSelect} />
          ))}
        </div>
      </div>
      <div>
        <p className="mb-2 text-sm font-medium">Panoramik</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {VIEW_SLOTS.filter((s) => s.group === "panoramic").map((slot) => (
            <Slot key={slot.key} slot={slot} file={files[slot.key]} onSelect={onSelect} />
          ))}
        </div>
      </div>
    </div>
  );
}
