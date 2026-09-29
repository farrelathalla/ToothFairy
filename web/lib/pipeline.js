/**
 * The analysis pipeline as the progress screen presents it.
 *
 * The server reports a percentage plus its own free-text stage label (the real ML service and
 * the standalone replay word them differently), so the screen places the run on this fixed
 * list by percentage — `until` is the exclusive upper bound of each step — and shows the
 * server's label underneath as the live detail.
 */
export const PIPELINE_STEPS = [
  { key: "prepare", label: "Menyiapkan & memvalidasi gambar", until: 10 },
  { key: "detect", label: "Deteksi FDI & segmentasi gigi", until: 30 },
  { key: "grade", label: "Grading karies ICDAS", until: 50 },
  { key: "panoramic", label: "Analisis panoramik — karies tersembunyi", until: 70 },
  { key: "fuse", label: "Fusi temuan & rekonstruksi 3D", until: 88 },
  { key: "advisory", label: "Menyusun diagnosis & rencana perawatan", until: 100 },
];

/** The client-side step after the server finishes: download + build the 3D dentition. */
export const MODEL_STEP = { key: "model", label: "Memuat model 3D pasien" };

/** Steps shown when opening an already-finished case. */
export const OPEN_STEPS = [
  { key: "case", label: "Memuat data kasus" },
  { key: "detections", label: "Memuat hasil deteksi" },
  { key: "download", label: "Mengunduh model 3D" },
  { key: "build", label: "Merekonstruksi gigi pasien" },
];

/** Share of the overall bar the server pipeline occupies; the 3D load fills the rest. */
export const PIPELINE_SHARE = 90;

/** Index of the pipeline step a server percentage falls in. */
export function stepIndexFor(progress) {
  const i = PIPELINE_STEPS.findIndex((s) => progress < s.until);
  return i < 0 ? PIPELINE_STEPS.length - 1 : i;
}
