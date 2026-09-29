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
        {/* break-words: citation URLs are long unbroken strings that would otherwise push the
            page sideways. Tables scroll in their own box rather than widening the card. */}
        {markdown ? (
          <div className="prose prose-sm max-w-none break-words dark:prose-invert [&_table]:block [&_table]:overflow-x-auto">
            <Streamdown>{markdown}</Streamdown>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Rekomendasi belum tersedia.</p>
        )}
      </CardContent>
    </Card>
  );
}
