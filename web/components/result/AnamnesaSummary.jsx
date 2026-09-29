"use client";
import { ClipboardList } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

/**
 * Read-only display of the case's anamnesa answers (Sacred Seven + Riwayat).
 * Labels mirror `case/AnamnesaForm.jsx` so the doctor sees exactly what was entered.
 */
const GROUPS = [
  {
    title: "Anamnesa — Sacred Seven",
    fields: [
      ["lokasi", "Lokasi keluhan"],
      ["quality", "Kualitas nyeri"],
      ["severity", "Keparahan (Quantity/Severity)"],
      ["chronology", "Kronologi / Waktu"],
      ["setting", "Setting"],
      ["aggravating_alleviating", "Memperparah / Meredakan"],
      ["associated", "Gejala Penyerta"],
    ],
  },
  {
    title: "Riwayat",
    fields: [
      ["pernah_ke_drg_lain", "Sudah pernah ke dokter gigi lain?"],
      ["obat_digunakan", "Obat-obatan yang sudah digunakan"],
      ["tindakan_sebelumnya", "Tindakan dokter gigi sebelumnya"],
      ["penyakit_sistemik", "Penyakit / kondisi sistemik"],
      ["pernah_menunda", "Pernah menunda kunjungan untuk keluhan yang sama?"],
      ["alasan_kuat", "Alasan kuat datang kali ini"],
    ],
  },
];

export default function AnamnesaSummary({ anamnesa }) {
  if (!anamnesa) return null;

  return (
    <section aria-label="Anamnesa pasien" className="space-y-2">
      <p className="flex items-center gap-1.5 text-sm font-medium">
        <ClipboardList className="h-4 w-4" />
        Anamnesa Pasien
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {GROUPS.map((g) => (
          <Card key={g.title}>
            <CardContent className="pt-5">
              <h3 className="mb-3 text-sm font-semibold">{g.title}</h3>
              <dl className="space-y-2.5">
                {g.fields.map(([key, label]) => {
                  const value = (anamnesa[key] || "").trim();
                  return (
                    <div key={key}>
                      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
                      <dd className="whitespace-pre-wrap text-sm">
                        {value || <span className="text-muted-foreground/50">—</span>}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
