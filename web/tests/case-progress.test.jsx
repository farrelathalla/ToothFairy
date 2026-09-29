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
  it("places the run on the pipeline step its progress falls in, with the live stage", async () => {
    getMock.mockResolvedValue({ status: "running", progress: 42, stage: "Menjalankan model deteksi" });
    renderWithClient(<CaseProgress caseId="case-1" />);

    // 42% is inside the ICDAS grading step (30–50)
    await waitFor(() =>
      expect(screen.getByText("Grading karies ICDAS", { selector: "li span" }).closest("li"))
        .toHaveAttribute("aria-current", "step")
    );
    expect(screen.getByText(/Menjalankan model deteksi/)).toBeInTheDocument();
    // earlier steps are done, and the last (3D) step is still ahead
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText("Memuat model 3D pasien")).toBeInTheDocument();
  });

  it("hands over to the results page when the case is done", async () => {
    getMock.mockResolvedValue({ status: "done", progress: 100, stage: "Selesai" });
    renderWithClient(<CaseProgress caseId="case-9" />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/case/case-9?from=analysis"));
    // the screen stays up on the 3D step while the results page loads
    expect(screen.getByText("Memuat model 3D pasien", { selector: "li span" }).closest("li")).toHaveAttribute("aria-current", "step");
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
