"use client";
import { Streamdown } from "streamdown";
import { ClipboardList } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Recommendation card — renders the case's stubbed markdown via streamdown. */
export default function LlmRecommendation({ markdown }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0">
        <ClipboardList className="h-5 w-5 text-primary" />
        <CardTitle className="text-base">Rekomendasi Penanganan</CardTitle>
      </CardHeader>
      <CardContent>
        {markdown ? (
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Streamdown>{markdown}</Streamdown>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Rekomendasi belum tersedia.</p>
        )}
      </CardContent>
    </Card>
  );
}
