import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import AccountForm from "@/components/admin/AccountForm";

describe("AccountForm (create)", () => {
  it("validates required fields and password length", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AccountForm mode="create" onSubmit={onSubmit} />);

    await user.click(screen.getByRole("button", { name: "Buat Akun" }));
    expect(await screen.findByText("Email wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Nama wajib diisi")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Email"), "new@x.io");
    await user.type(screen.getByLabelText("Nama"), "Dr Baru");
    await user.type(screen.getByLabelText("Kata Sandi"), "123");
    await user.click(screen.getByRole("button", { name: "Buat Akun" }));
    expect(await screen.findByText("Minimal 6 karakter")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits valid values (role defaults to doctor)", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AccountForm mode="create" onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Email"), "new@x.io");
    await user.type(screen.getByLabelText("Nama"), "Dr Baru");
    await user.type(screen.getByLabelText("Kata Sandi"), "secret1");
    await user.click(screen.getByRole("button", { name: "Buat Akun" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        email: "new@x.io",
        name: "Dr Baru",
        role: "doctor",
        password: "secret1",
      })
    );
  });
});

describe("AccountForm (edit)", () => {
  it("omits an empty password and submits edited fields", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <AccountForm
        mode="edit"
        defaultValues={{ name: "Lama", role: "doctor", is_active: true }}
        onSubmit={onSubmit}
      />
    );

    const name = screen.getByLabelText("Nama");
    await user.clear(name);
    await user.type(name, "Baru");
    await user.click(screen.getByRole("button", { name: "Simpan" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const arg = onSubmit.mock.calls[0][0];
    expect(arg.name).toBe("Baru");
    expect(arg).not.toHaveProperty("password"); // empty password dropped on edit
    // no email field in edit mode
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });
});
