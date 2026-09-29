import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

import { linkCitations, parseReport, sectionForTooth } from "@/lib/report";

const advisory = JSON.parse(
  readFileSync(path.resolve(__dirname, "../public/standalone/advisory.json"), "utf8")
);

describe("parseReport", () => {
  it("splits the bundled diagnosis into its sections and shapes", () => {
    const r = parseReport(advisory.diagnosis_md);
    expect(r.title).toBe("Diagnosis");
    const kinds = Object.fromEntries(r.sections.map((s) => [s.title, s.kind]));
    expect(kinds["Diagnosis per Gigi"]).toBe("teeth-table");
    expect(kinds["Analisis Mendalam Gigi Prioritas"]).toBe("tooth-notes");
    expect(kinds["Rujukan"]).toBe("sources");
    expect(r.sources.length).toBeGreaterThan(0);
    expect(r.sources.every((s) => s.title && s.quotes.length)).toBe(true);
  });

  it("recognises the visit sequence and the red flags in the treatment plan", () => {
    const r = parseReport(advisory.recommendation_md);
    const visits = r.sections.find((s) => s.kind === "visits");
    expect(visits.data.items.length).toBeGreaterThanOrEqual(2);
    expect(visits.data.items[0].title).toMatch(/^Kunjungan 1/);
    expect(r.sections.some((s) => s.kind === "alert")).toBe(true);
  });

  it("drops no content: every table cell and tooth paragraph survives", () => {
    for (const md of [advisory.diagnosis_md, advisory.recommendation_md]) {
      const r = parseReport(md);
      const table = r.sections.find((s) => s.kind === "teeth-table");
      const tableLines = md.split("\n").filter((l) => l.startsWith("|"));
      expect(table.data.rows).toHaveLength(tableLines.length - 2);
      for (const row of table.data.rows) expect(row).toHaveLength(table.data.header.length);
    }
    const notes = parseReport(advisory.diagnosis_md).sections.find((s) => s.kind === "tooth-notes");
    const paras = advisory.diagnosis_md.split("\n").filter((l) => /^\*\*Gigi \d{2}/.test(l));
    expect(notes.data.notes).toHaveLength(paras.length);
  });

  it("finds the section that holds a tooth", () => {
    const r = parseReport(advisory.diagnosis_md);
    const idx = sectionForTooth(r, 21);
    expect(r.sections[idx].kind).toBe("teeth-table");
    expect(sectionForTooth(r, 99)).toBe(-1);
  });

  it("parses a source's link from a URL or a DOI", () => {
    const r = parseReport("## A\n\nx[^1] y[^2]\n\n## Rujukan\n\n[^1]: **One** — https://a.example/p.pdf\n    > quote one\n[^2]: **Two** — DOI: 10.1/abc\n    > q2a\n    > q2b\n");
    expect(r.sources[0]).toMatchObject({ id: "1", title: "One", url: "https://a.example/p.pdf", quotes: ["quote one"] });
    expect(r.sources[1]).toMatchObject({ id: "2", url: "https://doi.org/10.1/abc", quotes: ["q2a", "q2b"] });
    expect(r.sections[0].body).toBe("x[1](#cite-1) y[2](#cite-2)");
  });

  it("links citations but leaves footnote definitions alone", () => {
    expect(linkCitations("a[^3] b")).toBe("a[3](#cite-3) b");
    expect(linkCitations("[^3]: def")).toBe("[^3]: def");
  });
});
