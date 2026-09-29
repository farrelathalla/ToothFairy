"use client";
import { ClipboardList } from "lucide-react";

import ClinicalReport from "@/components/result/report/ClinicalReport";

/** Treatment-plan document, split into navigable sections (see ClinicalReport). */
export default function LlmRecommendation({ markdown, focus, onShowTooth, grades }) {
  return (
    <ClinicalReport
      kind="recommendation"
      title="Rencana Perawatan"
      icon={ClipboardList}
      markdown={markdown}
      emptyText="Rekomendasi belum tersedia."
      focus={focus}
      onShowTooth={onShowTooth}
      grades={grades}
    />
  );
}
