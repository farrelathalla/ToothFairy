import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import LlmDiagnosis from "@/components/result/LlmDiagnosis";
import LlmRecommendation from "@/components/result/LlmRecommendation";

const MD = "# Diagnosis\n\nRingkasan awal:\n\n- Gigi 11 D6\n- Gigi 16 D3\n";

// What the diagnosis agent emits: a cited claim plus a `Rujukan` footnote definition
// carrying the verbatim quote. See ml/app/llm/citations.py.
const CITED_MD = [
  "# Diagnosis",
  "",
  "## Diagnosis per Gigi",
  "",
  "| Gigi | ICDAS | Kode ICD-10 |",
  "| --- | --- | --- |",
  "| 11 | D6 | K02.1 |",
  "",
  "Anak diperkirakan sulit makan.[^1]",
  "",
  "## Rujukan",
  "",
  "[^1]: **Impact of untreated caries** — DOI: 10.1111/jphd.12259",
  "    > difficulty eating and disturbed sleep",
  "",
].join("\n");

describe("LLM cards", () => {
  it("renders diagnosis markdown headings and list items", () => {
    render(<LlmDiagnosis markdown={MD} />);
    expect(screen.getByRole("heading", { name: "Diagnosis" })).toBeInTheDocument();
    expect(screen.getByText("Gigi 11 D6")).toBeInTheDocument();
  });

  it("renders the agent's GFM footnotes, not literal [^1] text", () => {
    const { container } = render(<LlmDiagnosis markdown={CITED_MD} />);
    // A literal "[^1]" anywhere means remark-gfm footnotes didn't parse.
    expect(container.textContent).not.toContain("[^1]");
    // Streamdown renders the ref as a <sup> and collects definitions into <section.footnotes>.
    expect(container.querySelector("sup")).toBeTruthy();
    expect(container.querySelector("section.footnotes")).toBeTruthy();
    // The verbatim cited_text — what a dentist audits the claim against — survives as a quote.
    expect(container.querySelector("section.footnotes blockquote")?.textContent).toContain(
      "difficulty eating and disturbed sleep",
    );
  });

  it("renders the per-tooth ICD-10 table", () => {
    const { container } = render(<LlmDiagnosis markdown={CITED_MD} />);
    expect(container.querySelector("table")).toBeTruthy();
    expect(screen.getByText("K02.1")).toBeInTheDocument();
  });

  it("shows a placeholder when recommendation markdown is empty", () => {
    render(<LlmRecommendation markdown="" />);
    expect(screen.getByText(/belum tersedia/)).toBeInTheDocument();
  });
});
