import { describe, it, expect } from "vitest";

import { summarize } from "@/lib/caries";

const FIXTURE = {
  teeth: {
    "11": { fdi: 11, severity: 6, grade_source: "rfdetr+seg", hidden: false,
            sources: ["seg", "rfdetr"], lesions: [{}, {}], notes: "" },
    "12": { fdi: 12, severity: 6, grade_source: "seg", hidden: false, lesions: [{}] },
    "16": { fdi: 16, severity: 3, grade_source: "seg", hidden: false, lesions: [{}] },
    "47": { fdi: 47, severity: 4, grade_source: "panoramic", hidden: true, lesions: [{}], notes: "X-ray" },
    "21": { fdi: 21, severity: 0 },              // healthy → excluded
    "22": { fdi: 22, severity: 0, lesions: [] },
  },
};

describe("summarize(detections)", () => {
  it("counts affected teeth and lesions", () => {
    const s = summarize(FIXTURE);
    expect(s.total).toBe(4);
    expect(s.totalLesions).toBe(5);
  });

  it("tallies per ICDAS class", () => {
    const s = summarize(FIXTURE);
    expect(s.perClass).toEqual({ D1: 0, D2: 0, D3: 1, D4: 1, D5: 0, D6: 2 });
  });

  it("sorts affected worst-first and flags hidden lesions", () => {
    const s = summarize(FIXTURE);
    expect(s.affected.map((a) => a.fdi)).toEqual([11, 12, 47, 16]);
    expect(s.affected[0].grade).toBe(6);
    expect(s.hidden).toEqual([47]);
  });

  it("is safe on empty / null input", () => {
    expect(summarize(null).total).toBe(0);
    expect(summarize({}).affected).toEqual([]);
  });
});
