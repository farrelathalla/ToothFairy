import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (...a) => getMock(...a) } }));

import CaseProgress from "@/components/case/CaseProgress";

function renderWithClient(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  push.mockReset();
  getMock.mockReset();
});

describe("CaseProgress", () => {
  it("renders the stage label and progress from polled status", async () => {
    getMock.mockResolvedValue({ status: "running", progress: 42, stage: "Grading karies" });
    renderWithClient(<CaseProgress caseId="case-1" />);

    expect(await screen.findByText("Grading karies")).toBeInTheDocument();
    const bar = await screen.findByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).toBe("42");
  });

  it("navigates to the results page when the case is done", async () => {
    getMock.mockResolvedValue({ status: "done", progress: 100, stage: "Selesai" });
    renderWithClient(<CaseProgress caseId="case-9" />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/case/case-9"));
  });

  it("shows an error with a retry button on failure", async () => {
    getMock.mockResolvedValue({ status: "failed", progress: 0, error: "model meledak" });
    const onRetry = vi.fn();
    const user = userEvent.setup();
    renderWithClient(<CaseProgress caseId="case-2" onRetry={onRetry} />);

    expect(await screen.findByText(/model meledak/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /coba lagi/i }));
    expect(onRetry).toHaveBeenCalled();
  });
});
