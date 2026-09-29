import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

vi.mock("@/lib/api", () => {
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }
  return { ApiError, api: { get: vi.fn(), post: vi.fn() } };
});

import { api, ApiError } from "@/lib/api";
import { AuthProvider, RequireAuth, RequireRole } from "@/lib/auth";

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  replace.mockReset();
  api.get.mockReset();
});

describe("RequireRole / RequireAuth", () => {
  it("renders children when the user has the required role", async () => {
    api.get.mockResolvedValue({ id: 1, email: "a@x.io", role: "admin", name: "A", is_active: true });
    wrap(
      <RequireRole role="admin">
        <div>Panel Admin</div>
      </RequireRole>
    );
    expect(await screen.findByText("Panel Admin")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects unauthenticated users to /login", async () => {
    api.get.mockRejectedValue(new ApiError("Not authenticated", 401));
    wrap(
      <RequireAuth>
        <div>rahasia</div>
      </RequireAuth>
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("rahasia")).not.toBeInTheDocument();
  });

  it("bounces a doctor away from an admin-only area to their home", async () => {
    api.get.mockResolvedValue({ id: 2, email: "d@x.io", role: "doctor", name: "D", is_active: true });
    wrap(
      <RequireRole role="admin">
        <div>Panel Admin</div>
      </RequireRole>
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("Panel Admin")).not.toBeInTheDocument();
  });
});
