"use client";
import { Streamdown } from "streamdown";
import { Stethoscope } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** Diagnosis card — renders the case's stubbed markdown via streamdown. */
export default function LlmDiagnosis({ markdown }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0">
        <Stethoscope className="h-5 w-5 text-primary" />
        <CardTitle className="text-base">Diagnosis</CardTitle>
      </CardHeader>
      <CardContent>
        {markdown ? (
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <Streamdown>{markdown}</Streamdown>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Diagnosis belum tersedia.</p>
        )}
      </CardContent>
    </Card>
  );
}
