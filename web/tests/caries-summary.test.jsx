import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import CariesSummary from "@/components/result/CariesSummary";

const DET = {
  teeth: {
    "11": { fdi: 11, severity: 6, sources: ["seg"], lesions: [{}, {}] },
    "16": { fdi: 16, severity: 3, sources: ["seg"], lesions: [{}] },
    "47": { fdi: 47, severity: 4, hidden: true, lesions: [{}] },
    "21": { fdi: 21, severity: 0 },
  },
};

describe("CariesSummary", () => {
  it("renders totals and the per-class chips", () => {
    render(<CariesSummary detections={DET} />);
    expect(screen.getByText("Gigi berkaries")).toBeInTheDocument();
    // 3 affected teeth
    expect(screen.getByText("3")).toBeInTheDocument();
    // all six ICDAS chips present (some also appear as card badges → getAllByText)
    for (const c of ["D1", "D2", "D3", "D4", "D5", "D6"]) {
      expect(screen.getAllByText(c).length).toBeGreaterThan(0);
    }
  });

  it("lists every affected tooth as a card and selection bubbles up", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<CariesSummary detections={DET} onSelect={onSelect} />);
    const cards = screen.getAllByTestId("affected-card");
    expect(cards).toHaveLength(3);
    await user.click(cards[0]); // worst-first → tooth 11
    expect(onSelect).toHaveBeenCalledWith(11);
  });

  it("marks hidden lesions", () => {
    render(<CariesSummary detections={DET} />);
    expect(screen.getByText(/tersembunyi/)).toBeInTheDocument();
  });
});
