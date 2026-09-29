import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  "| Gigi | Nama gigi | ICDAS | Kode ICD-10 | Pola kerusakan |",
  "| --- | --- | --- | --- | --- |",
  "| 11 | Insisivus sentral rahang atas kanan | D6 | K02.1 | Dua kavitasi terbuka dengan rasio 0,289 dan fokus yang luas. |",
  "",
  "## Dampak Harian",
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
  it("renders the document heading and its intro markdown", () => {
    render(<LlmDiagnosis markdown={MD} />);
    expect(screen.getByRole("heading", { name: "Diagnosis" })).toBeInTheDocument();
    expect(screen.getByText("Gigi 11 D6")).toBeInTheDocument();
  });

  it("splits the document into sections and pages through them", async () => {
    const user = userEvent.setup();
    render(<LlmDiagnosis markdown={CITED_MD} />);

    const rail = screen.getByRole("tablist", { name: /Bagian Diagnosis/ });
    expect(within(rail).getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByText("Bagian 1 dari 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Berikutnya/ }));
    expect(await screen.findByText("Bagian 2 dari 3")).toBeInTheDocument();
    expect(screen.getByText(/Anak diperkirakan sulit makan/)).toBeInTheDocument();
  });

  it("shows every column of the per-tooth table as a tooth card", async () => {
    const user = userEvent.setup();
    const { container } = render(<LlmDiagnosis markdown={CITED_MD} />);
    expect(screen.getAllByText("K02.1").length).toBeGreaterThan(0);
    expect(screen.getByText("Insisivus sentral rahang atas kanan")).toBeInTheDocument();
    expect(container.textContent).toContain("Dua kavitasi terbuka");

    // …and the original grid is one tap away
    await user.click(screen.getByRole("tab", { name: /Tabel/ }));
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("turns [^n] into a citation chip that opens the verified quote", async () => {
    const user = userEvent.setup();
    const { container } = render(<LlmDiagnosis markdown={CITED_MD} />);
    await user.click(within(screen.getByRole("tablist", { name: /Bagian/ })).getByRole("tab", { name: /Dampak Harian/ }));

    expect(container.textContent).not.toContain("[^1]");
    await user.click(screen.getByRole("button", { name: "Rujukan 1" }));
    const sheet = await screen.findByRole("dialog", { name: "Rujukan 1" });
    expect(within(sheet).getByText(/difficulty eating and disturbed sleep/)).toBeInTheDocument();
    expect(within(sheet).getByRole("link")).toHaveAttribute("href", "https://doi.org/10.1111/jphd.12259");
  });

  it("lists every source in the Rujukan section", async () => {
    const user = userEvent.setup();
    render(<LlmDiagnosis markdown={CITED_MD} />);
    await user.click(within(screen.getByRole("tablist", { name: /Bagian/ })).getByRole("tab", { name: /Rujukan/ }));
    expect(await screen.findByText("Impact of untreated caries")).toBeInTheDocument();
    expect(screen.getByText(/difficulty eating and disturbed sleep/)).toBeInTheDocument();
  });

  it("shows a placeholder when recommendation markdown is empty", () => {
    render(<LlmRecommendation markdown="" />);
    expect(screen.getByText(/belum tersedia/)).toBeInTheDocument();
  });
});
