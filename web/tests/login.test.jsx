import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

const loginMock = vi.fn();
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ login: loginMock }),
  homePathForRole: (r) => (r === "admin" ? "/admin" : "/"),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import LoginPage from "@/app/login/page";
import { toast } from "sonner";

beforeEach(() => {
  replace.mockReset();
  loginMock.mockReset();
  toast.error.mockReset?.();
  toast.success.mockReset?.();
});

describe("LoginPage", () => {
  it("shows validation errors and does not call login on empty submit", async () => {
    const user = userEvent.setup();
    render(<LoginPage />);
    await user.click(screen.getByRole("button", { name: "Masuk" }));
    expect(await screen.findByText("Email wajib diisi")).toBeInTheDocument();
    expect(screen.getByText("Kata sandi wajib diisi")).toBeInTheDocument();
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("logs in and redirects to the role home on success", async () => {
    loginMock.mockResolvedValue({ name: "Administrator", role: "admin" });
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "admin@toothfairy.com");
    await user.type(screen.getByLabelText("Kata Sandi"), "admin123");
    await user.click(screen.getByRole("button", { name: "Masuk" }));

    await waitFor(() =>
      expect(loginMock).toHaveBeenCalledWith("admin@toothfairy.com", "admin123")
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
  });

  it("surfaces a server error toast on failed login", async () => {
    class ApiErr extends Error {
      constructor(m, s) {
        super(m);
        this.name = "ApiError";
        this.status = s;
      }
    }
    loginMock.mockRejectedValue(new ApiErr("Email atau kata sandi salah", 401));
    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "x@x.io");
    await user.type(screen.getByLabelText("Kata Sandi"), "wrong");
    await user.click(screen.getByRole("button", { name: "Masuk" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(replace).not.toHaveBeenCalled();
  });
});
