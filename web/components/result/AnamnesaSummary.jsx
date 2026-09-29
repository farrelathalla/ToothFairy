"use client";
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
    <section aria-label="Anamnesa pasien" className="grid gap-3 sm:grid-cols-2">
      {GROUPS.map((g) => (
        <div key={g.title} className="rounded-2xl border bg-card p-4">
          <h3 className="mb-1 text-sm font-semibold">{g.title}</h3>
          <dl className="divide-y">
            {g.fields.map(([key, label]) => {
              const value = (anamnesa[key] || "").trim();
              return (
                <div key={key} className="py-2.5">
                  <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
                  <dd className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed">
                    {value || <span className="text-muted-foreground/50">—</span>}
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>
      ))}
    </section>
  );
}
