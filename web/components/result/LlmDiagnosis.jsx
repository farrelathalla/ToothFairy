"use client";
import { Stethoscope } from "lucide-react";

import ClinicalReport from "@/components/result/report/ClinicalReport";

/** Diagnosis document, split into navigable sections (see ClinicalReport). */
export default function LlmDiagnosis({ markdown, sanity, focus, onShowTooth, grades }) {
  return (
    <ClinicalReport
      kind="diagnosis"
      title="Diagnosis"
      icon={Stethoscope}
      markdown={markdown}
      emptyText="Diagnosis belum tersedia."
      sanity={sanity}
      focus={focus}
      onShowTooth={onShowTooth}
      grades={grades}
    />
  );
}
