import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (...a) => getMock(...a) } }));

import HistoryList from "@/components/HistoryList";

beforeEach(() => getMock.mockReset());

describe("HistoryList", () => {
  it("renders a card per case with a link to its results", async () => {
    getMock.mockResolvedValue([
      { id: "case-1", patient_name: "Ananda R.", status: "done", dataset_id: "set1",
        created_at: "2026-07-01T10:00:00Z", updated_at: "2026-07-01T10:00:00Z" },
      { id: "case-2", patient_name: "Bima S.", status: "done", dataset_id: "set2",
        created_at: "2026-07-02T10:00:00Z", updated_at: "2026-07-02T10:00:00Z" },
    ]);
    render(<HistoryList />);
    expect(await screen.findByText("Ananda R.")).toBeInTheDocument();
    expect(screen.getByText("Bima S.")).toBeInTheDocument();
    const links = screen.getAllByRole("link");
    expect(links.some((a) => a.getAttribute("href") === "/case/case-1")).toBe(true);
  });

  it("shows an empty state when there are no cases", async () => {
    getMock.mockResolvedValue([]);
    render(<HistoryList />);
    await waitFor(() => expect(screen.getByText(/belum ada riwayat/i)).toBeInTheDocument());
  });
});
