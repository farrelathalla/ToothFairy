/**
 * Aggregate a detections.json into a caries summary for the results view.
 *
 * The 3D viewer reads `teeth[fdi].severity` (0 healthy, 1–6 = ICDAS D1–D6). This
 * derives the totals + per-class counts + an affected-tooth list (sorted worst-first)
 * that the CariesSummary UI renders.
 */

export const ICDAS_CLASSES = ["D1", "D2", "D3", "D4", "D5", "D6"];

export const ICDAS_LABEL_ID = {
  1: "Perubahan awal email",
  2: "Lesi email jelas",
  3: "Kerusakan email terlokalisir",
  4: "Bayangan pada dentin",
  5: "Kavitas jelas, dentin terlihat",
  6: "Kavitas luas, dentin ekstensif",
};

/**
 * @param {object|null} detections a parsed detections.json ({ teeth: {fdi: {...}} })
 * @returns {{total:number, totalLesions:number, perClass:Record<string,number>,
 *            affected:Array<{fdi:number,grade:number,source:string,hidden:boolean,notes:string,lesions:number}>,
 *            hidden:number[]}}
 */
export function summarize(detections) {
  const teeth = detections && detections.teeth ? Object.values(detections.teeth) : [];

  const perClass = { D1: 0, D2: 0, D3: 0, D4: 0, D5: 0, D6: 0 };
  const affected = [];
  let totalLesions = 0;

  for (const t of teeth) {
    const grade = t.severity || 0;
    if (grade <= 0) continue;
    const lesions = Array.isArray(t.lesions) ? t.lesions.length : 0;
    totalLesions += lesions;
    if (perClass["D" + grade] !== undefined) perClass["D" + grade] += 1;
    affected.push({
      fdi: Number(t.fdi),
      grade,
      source: t.grade_source || (Array.isArray(t.sources) ? t.sources.join("+") : ""),
      hidden: !!t.hidden,
      notes: t.notes || "",
      lesions,
    });
  }

  affected.sort((a, b) => b.grade - a.grade || a.fdi - b.fdi);
  const hidden = affected.filter((a) => a.hidden).map((a) => a.fdi);

  return { total: affected.length, totalLesions, perClass, affected, hidden };
}
