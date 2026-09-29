"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertCircle, ArrowLeft, ArrowRight, Check, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";

const req = (msg) => z.string().trim().min(1, msg);
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
    short: "Sacred Seven",
    blurb: "Tujuh pertanyaan inti tentang keluhan utama pasien.",
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
    short: "Riwayat",
    blurb: "Riwayat perawatan, obat, dan kondisi umum pasien.",
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

const ALL_FIELDS = STEPS.flatMap((s) => s.fields);
const STEP_OF = Object.fromEntries(
  STEPS.flatMap((s, i) => s.fields.map((f) => [f.name, i]))
);

/**
 * Two-section anamnesa wizard.
 *
 * Moving between sections never validates — the section tabs and "Lanjut" are navigation, so a
 * doctor can look ahead (or back) without the form turning red. Required fields are checked
 * once, on "Simpan"; if any is missing the form jumps to the first section that has one and
 * focuses it, and the section tab carries an error dot.
 *
 * @param {object}   props
 * @param {(v:{patient_name:string|null, anamnesa:object})=>void} props.onComplete
 * @param {boolean} [props.submitting]
 * @param {object}  [props.defaultValues]  pre-filled answers (demo mode)
 */
export default function AnamnesaForm({ onComplete, submitting, defaultValues }) {
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      ...Object.fromEntries(ALL_FIELDS.map((f) => [f.name, ""])),
      ...defaultValues,
    },
    mode: "onSubmit",
    reValidateMode: "onChange",
    shouldFocusError: false, // the field may be on another section; focused manually below
  });

  const [step, setStep] = useState(0);
  const isLast = step === STEPS.length - 1;
  const current = STEPS[step];

  const values = form.watch();
  const errors = form.formState.errors;
  const stepHasError = (i) => STEPS[i].fields.some((f) => errors[f.name]);
  const filled = (i) => STEPS[i].fields.filter((f) => String(values[f.name] ?? "").trim()).length;

  function goTo(i) {
    setStep(Math.max(0, Math.min(STEPS.length - 1, i)));
    // new section starts at its top on a phone
    if (typeof window !== "undefined") window.scrollTo?.({ top: 0, behavior: "smooth" });
  }

  function submit(v) {
    const { patient_name, ...anamnesa } = v;
    onComplete({ patient_name: patient_name?.trim() || null, anamnesa });
  }

  function invalid(errs) {
    const first = ALL_FIELDS.find((f) => errs[f.name]);
    if (!first) return;
    setStep(STEP_OF[first.name]);
    // focus once the section holding it has rendered
    requestAnimationFrame(() => form.setFocus(first.name));
  }

  function onFormSubmit(e) {
    // Enter in a field on an earlier section moves on instead of submitting the whole form.
    if (!isLast) {
      e.preventDefault();
      goTo(step + 1);
      return;
    }
    return form.handleSubmit(submit, invalid)(e);
  }

  const errorCount = Object.keys(errors).length;

  return (
    <Form {...form}>
      <form onSubmit={onFormSubmit} className="space-y-6" noValidate>
        {/* section switcher — plain navigation, never validates */}
        <div role="tablist" aria-label="Bagian anamnesa" className="grid grid-cols-2 gap-1 rounded-2xl bg-muted p-1">
          {STEPS.map((s, i) => {
            const active = i === step;
            const total = s.fields.length;
            const n = filled(i);
            const hasError = stepHasError(i);
            return (
              <button
                key={s.short}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => goTo(i)}
                className={cn(
                  "relative flex items-center gap-2 rounded-xl px-2.5 py-2.5 text-left transition-all duration-200",
                  active ? "bg-background shadow-sm" : "text-muted-foreground hover:bg-background/60"
                )}
              >
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                    hasError
                      ? "bg-destructive text-destructive-foreground"
                      : n === total
                        ? "bg-primary text-primary-foreground"
                        : active
                          ? "bg-primary/10 text-primary"
                          : "bg-background text-muted-foreground"
                  )}
                >
                  {hasError ? "!" : n === total ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className={cn("block whitespace-nowrap text-[13px] font-medium leading-tight", active && "text-foreground")}>
                    {s.short}
                  </span>
                  <span className="block text-[11px] text-muted-foreground">
                    {n}/{total} terisi
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <div key={step} className="animate-fade-in space-y-5">
          <div>
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-base font-semibold">{current.title}</h2>
              <span className="shrink-0 text-xs text-muted-foreground">
                Langkah {step + 1} / {STEPS.length}
              </span>
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">{current.blurb}</p>
          </div>

          <div className="space-y-4">
            {current.fields.map((f) => (
              <FormField
                key={f.name}
                control={form.control}
                name={f.name}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-[13px]">
                      {f.label}
                      {f.required && <span className="text-destructive"> *</span>}
                    </FormLabel>
                    <FormControl>
                      {f.input ? (
                        <Input className="h-10 rounded-lg bg-background" placeholder={f.placeholder} {...field} />
                      ) : (
                        <Textarea
                          rows={2}
                          className="min-h-[64px] resize-y rounded-lg bg-background"
                          placeholder={f.placeholder}
                          {...field}
                        />
                      )}
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
          </div>
        </div>

        {errorCount > 0 && (
          <p className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive animate-fade-in">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Lengkapi {errorCount} kolom wajib yang ditandai.
          </p>
        )}

        {/* Distinct keys: without them React reuses one <button> element and flips its type to
            "submit" mid-click, so pressing "Lanjut" also submitted the form. */}
        <div className="flex items-center justify-between gap-3 border-t pt-4">
          <Button
            key="back"
            type="button"
            variant="ghost"
            onClick={() => goTo(step - 1)}
            disabled={step === 0}
            className={cn(step === 0 && "invisible")}
          >
            <ArrowLeft className="h-4 w-4" />
            Kembali
          </Button>

          {isLast ? (
            <Button key="submit" type="submit" size="lg" disabled={submitting} className="rounded-xl">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Simpan &amp; Lanjut ke Foto
              {!submitting && <ArrowRight className="h-4 w-4" />}
            </Button>
          ) : (
            <Button key="next" type="button" size="lg" onClick={() => goTo(step + 1)} className="rounded-xl">
              Lanjut
              <ArrowRight className="h-4 w-4" />
            </Button>
          )}
        </div>
      </form>
    </Form>
  );
}
