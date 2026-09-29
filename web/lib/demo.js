/**
 * Demo (mock-up) presets.
 *
 * When the app runs in standalone mode (see `lib/standalone.js`) it is a walkthrough of the
 * product, not a clinic deployment: every form arrives pre-filled with the bundled reference
 * patient (`set3`) so a reviewer can click straight through sign-in → anamnesa → photos →
 * analysis → results. With `NEXT_PUBLIC_STANDALONE=0` (a real gateway) nothing here applies
 * and every form starts empty.
 */

/** Standalone mode is on unless explicitly disabled. */
export const STANDALONE =
  typeof process === "undefined" || process.env.NEXT_PUBLIC_STANDALONE !== "0";

/** Pre-fill forms with the reference patient. Same switch as standalone mode. */
export const DEMO_MODE = STANDALONE;

/** The seeded doctor account (valid against the real gateway's seed too). */
export const DEMO_CREDENTIALS = { email: "dokter@toothfairy.id", password: "doctor123" };

/** The bundled dataset the demo patient's photos and results come from. */
export const DEMO_DATASET = "set3";

/** Anamnesa of the reference patient (mirrors `assets/seed/demo_cases.json` → demo-set3). */
export const DEMO_PATIENT = {
  patient_name: "Dinda A. (7 th)",
  anamnesa: {
    lokasi: "Hampir seluruh kuadran, terparah gigi depan atas",
    quality: "Nyeri spontan, berdenyut",
    severity: "Skala 7, sering mengganggu tidur malam",
    chronology: "±3 bulan, hampir tiap hari",
    setting: "Spontan saat diam maupun saat mengunyah",
    aggravating_alleviating: "Diperparah manis & dingin; obat hanya meredakan sebentar",
    associated: "Gusi bengkak ringan, sesekali sakit kepala",
    pernah_ke_drg_lain: "Belum pernah",
    obat_digunakan: "Paracetamol, ibuprofen anak",
    tindakan_sebelumnya: "Belum ada",
    penyakit_sistemik: "Tidak ada",
    pernah_menunda: "Ya, beberapa bulan karena takut ke dokter gigi",
    alasan_kuat: "Karies sudah rampant dan anak kesakitan hebat",
  },
};

/** The reference patient's source photos, keyed by upload slot. */
const DEMO_PHOTOS = {
  up: "up.png",
  bottom: "bottom.png",
  front: "front.png",
  side_left: "side_left.png",
  side_right: "side_right.png",
  panoramic: "panoramic.jpg",
};

/**
 * Fetches the reference photos as `File`s so they can sit in the upload slots exactly as if
 * the doctor had picked them. Slots whose photo fails to load are simply left empty.
 * @returns {Promise<{[viewKey: string]: File}>}
 */
export async function loadDemoPhotos() {
  const entries = await Promise.all(
    Object.entries(DEMO_PHOTOS).map(async ([key, name]) => {
      try {
        const res = await fetch(`/results/${DEMO_DATASET}/inputs/${name}`);
        if (!res.ok) return null;
        const blob = await res.blob();
        return [key, new File([blob], name, { type: blob.type || "image/png" })];
      } catch {
        return null;
      }
    })
  );
  return Object.fromEntries(entries.filter(Boolean));
}
