import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import AnamnesaForm from "@/components/case/AnamnesaForm";

describe("AnamnesaForm wizard", () => {
  it("blocks advancing past step 1 until required fields are filled", async () => {
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={onComplete} />);

    // step 1 visible
    expect(screen.getByText("Anamnesa — Sacred Seven")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Lanjut/ }));

    expect(await screen.findByText("Lokasi keluhan wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Kualitas nyeri wajib diisi")).toBeInTheDocument();
    // still on step 1 (Riwayat's required field not rendered)
    expect(screen.queryByText("Alasan kuat datang kali ini")).not.toBeInTheDocument();
  });

  it("advances to Riwayat and collects all 13 anamnesa fields on submit", async () => {
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={onComplete} />);

    await user.type(screen.getByLabelText(/Lokasi keluhan/), "Geraham kiri");
    await user.type(screen.getByLabelText(/Kualitas nyeri/), "Cenut-cenut");
    await user.click(screen.getByRole("button", { name: /Lanjut/ }));

    // step 2
    expect(await screen.findByText("Riwayat")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Alasan kuat/), "Sulit tidur");
    await user.click(screen.getByRole("button", { name: /Lanjut ke Foto/ }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    const arg = onComplete.mock.calls[0][0];
    expect(arg.anamnesa.lokasi).toBe("Geraham kiri");
    expect(arg.anamnesa.quality).toBe("Cenut-cenut");
    expect(arg.anamnesa.alasan_kuat).toBe("Sulit tidur");
    // all 13 anamnesa keys present (optional ones default to "")
    expect(Object.keys(arg.anamnesa)).toHaveLength(13);
    expect(arg).toHaveProperty("patient_name");
  });

  it("can navigate back to step 1", async () => {
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={vi.fn()} />);

    await user.type(screen.getByLabelText(/Lokasi keluhan/), "X");
    await user.type(screen.getByLabelText(/Kualitas nyeri/), "Y");
    await user.click(screen.getByRole("button", { name: /Lanjut/ }));
    expect(await screen.findByText("Riwayat")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Kembali/ }));
    expect(await screen.findByText("Anamnesa — Sacred Seven")).toBeInTheDocument();
  });
});
