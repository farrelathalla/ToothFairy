"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";

const req = (msg) => z.string().min(1, msg);
const opt = z.string().optional().default("");

const schema = z.object({
  patient_name: z.string().optional().default(""),
  // Sacred Seven
  lokasi: req("Lokasi keluhan wajib diisi"),
  quality: req("Kualitas nyeri wajib diisi"),
  severity: opt,
  chronology: opt,
  setting: opt,
  aggravating_alleviating: opt,
  associated: opt,
  // Riwayat
  pernah_ke_drg_lain: opt,
  obat_digunakan: opt,
  tindakan_sebelumnya: opt,
  penyakit_sistemik: opt,
  pernah_menunda: opt,
  alasan_kuat: req("Alasan utama wajib diisi"),
});

const STEPS = [
  {
    title: "Anamnesa — Sacred Seven",
    fields: [
      { name: "patient_name", label: "Nama Pasien (opsional)", input: true, placeholder: "Nama anak" },
      { name: "lokasi", label: "Lokasi keluhan", required: true, placeholder: "Di mana lokasi keluhan utama? Apakah menjalar ke tempat lain?" },
      { name: "quality", label: "Kualitas nyeri", required: true, placeholder: "Ngilu / nyeri spontan / cenut-cenut / tajam, dll." },
      { name: "severity", label: "Keparahan (Quantity/Severity)", placeholder: "Skala 1–7, atau dampak: mengganggu tidur / tidak bisa mengunyah / nyeri malam hari" },
      { name: "chronology", label: "Kronologi / Waktu", placeholder: "Kapan saja dirasakan? Seberapa sering per hari / minggu?" },
      { name: "setting", label: "Setting", placeholder: "Kondisi saat nyeri: diam tiba-tiba / saat mengunyah / keduanya?" },
      { name: "aggravating_alleviating", label: "Memperparah / Meredakan", placeholder: "Apa yang memperparah? Apa yang meredakan?" },
      { name: "associated", label: "Gejala Penyerta", placeholder: "Bengkak gusi? Sakit kepala? Nyeri sinus?" },
    ],
  },
  {
    title: "Riwayat",
    fields: [
      { name: "pernah_ke_drg_lain", label: "Sudah pernah ke dokter gigi lain?", placeholder: "Sudah / belum, dan detailnya" },
      { name: "obat_digunakan", label: "Obat-obatan yang sudah digunakan", placeholder: "Sebutkan obat yang sudah dipakai" },
      { name: "tindakan_sebelumnya", label: "Tindakan dokter gigi sebelumnya", placeholder: "Pernah diberi tindakan? Berupa apa?" },
      { name: "penyakit_sistemik", label: "Penyakit / kondisi sistemik", placeholder: "Diabetes / hipertensi / gangguan pembekuan darah?" },
      { name: "pernah_menunda", label: "Pernah menunda kunjungan untuk keluhan yang sama?", placeholder: "Ya / tidak, dan berapa lama" },
      { name: "alasan_kuat", label: "Alasan kuat datang kali ini", required: true, placeholder: "Apa alasan/motivasi utama yang membawa Anda ke sini?" },
    ],
  },
];

const STEP_FIELDS = STEPS.map((s) => s.fields.map((f) => f.name));

export default function AnamnesaForm({ onComplete, submitting }) {
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: Object.fromEntries(
      STEPS.flatMap((s) => s.fields).map((f) => [f.name, ""])
    ),
    mode: "onTouched",
  });

  // step is derived from RHF is overkill; keep local
  const [step, setStep] = useState(0);
  const isLast = step === STEPS.length - 1;

  async function next() {
    const ok = await form.trigger(STEP_FIELDS[step]);
    if (ok) setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }

  function submit(values) {
    const { patient_name, ...anamnesa } = values;
    onComplete({ patient_name: patient_name?.trim() || null, anamnesa });
  }

  const current = STEPS[step];

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(submit)} className="space-y-5" noValidate>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">{current.title}</h2>
          <span className="text-xs text-muted-foreground">
            Langkah {step + 1} / {STEPS.length}
          </span>
        </div>

        <div className="space-y-4">
          {current.fields.map((f) => (
            <FormField
              key={f.name}
              control={form.control}
              name={f.name}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    {f.label}
                    {f.required && <span className="text-destructive"> *</span>}
                  </FormLabel>
                  <FormControl>
                    {f.input ? (
                      <Input placeholder={f.placeholder} {...field} />
                    ) : (
                      <Textarea rows={3} placeholder={f.placeholder} {...field} />
                    )}
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </div>

        <div className="flex items-center justify-between pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            <ArrowLeft className="h-4 w-4" />
            Kembali
          </Button>

          {isLast ? (
            <Button type="submit" disabled={submitting}>
              Simpan &amp; Lanjut ke Foto
              <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button type="button" onClick={next}>
              Lanjut
              <ArrowRight className="h-4 w-4" />
            </Button>
          )}
        </div>
      </form>
    </Form>
  );
}
