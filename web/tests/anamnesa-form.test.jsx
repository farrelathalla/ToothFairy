import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import AnamnesaForm from "@/components/case/AnamnesaForm";

describe("AnamnesaForm wizard", () => {
  it("moves to the next section without validating it", async () => {
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={vi.fn()} />);

    expect(screen.getByText("Anamnesa — Sacred Seven")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Lanjut$/ }));

    // on Riwayat, and nothing turned red on the way
    expect(await screen.findByText("Alasan kuat datang kali ini")).toBeInTheDocument();
    expect(screen.queryByText(/wajib diisi/)).not.toBeInTheDocument();
  });

  it("jumps between sections from the section tabs", async () => {
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={vi.fn()} />);

    await user.click(screen.getByRole("tab", { name: /Riwayat/ }));
    expect(await screen.findByText("Alasan kuat datang kali ini")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Sacred Seven/ }));
    expect(await screen.findByText("Anamnesa — Sacred Seven")).toBeInTheDocument();
    expect(screen.queryByText(/wajib diisi/)).not.toBeInTheDocument();
  });

  it("on submit, returns to the section with a missing required field", async () => {
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={onComplete} />);

    await user.click(screen.getByRole("button", { name: /^Lanjut$/ }));
    await user.type(await screen.findByLabelText(/Alasan kuat/), "Sulit tidur");
    await user.click(screen.getByRole("button", { name: /Lanjut ke Foto/ }));

    expect(await screen.findByText("Lokasi keluhan wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Kualitas nyeri wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Anamnesa — Sacred Seven")).toBeInTheDocument();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("collects all 13 anamnesa fields on submit", async () => {
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={onComplete} />);

    await user.type(screen.getByLabelText(/Lokasi keluhan/), "Geraham kiri");
    await user.type(screen.getByLabelText(/Kualitas nyeri/), "Cenut-cenut");
    await user.click(screen.getByRole("button", { name: /^Lanjut$/ }));

    await user.type(await screen.findByLabelText(/Alasan kuat/), "Sulit tidur");
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

  it("does not submit when Lanjut swaps in the submit button", async () => {
    // Every required field is valid, so a stray submit would reach onComplete.
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(
      <AnamnesaForm
        onComplete={onComplete}
        defaultValues={{ lokasi: "Depan", quality: "Ngilu", alasan_kuat: "Nyeri" }}
      />
    );

    await user.click(screen.getByRole("button", { name: /^Lanjut$/ }));
    await screen.findByText("Alasan kuat datang kali ini");
    expect(onComplete).not.toHaveBeenCalled();
    expect(screen.queryByText(/wajib diisi/)).not.toBeInTheDocument();
  });

  it("can navigate back to step 1", async () => {
    const user = userEvent.setup();
    render(<AnamnesaForm onComplete={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^Lanjut$/ }));
    expect(await screen.findByText("Alasan kuat datang kali ini")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Kembali/ }));
    expect(await screen.findByText("Anamnesa — Sacred Seven")).toBeInTheDocument();
  });

  it("starts from pre-filled answers and submits them untouched", async () => {
    const onComplete = vi.fn();
    const user = userEvent.setup();
    render(
      <AnamnesaForm
        onComplete={onComplete}
        defaultValues={{ patient_name: "Dinda", lokasi: "Depan atas", quality: "Berdenyut", alasan_kuat: "Nyeri" }}
      />
    );

    expect(screen.getByLabelText(/Lokasi keluhan/)).toHaveValue("Depan atas");
    await user.click(screen.getByRole("button", { name: /^Lanjut$/ }));
    await user.click(await screen.findByRole("button", { name: /Lanjut ke Foto/ }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(onComplete.mock.calls[0][0]).toMatchObject({
      patient_name: "Dinda",
      anamnesa: { lokasi: "Depan atas", quality: "Berdenyut", alasan_kuat: "Nyeri" },
    });
  });
});
