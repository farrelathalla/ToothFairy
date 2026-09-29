"use client";
import { createContext, useCallback, useContext, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { api, ApiError, setToken } from "@/lib/api";

const AuthContext = createContext(null);

/** Fetches /auth/me once; 401/403 → treated as "not logged in" (user=null). */
export function AuthProvider({ children }) {
  const qc = useQueryClient();

  const { data: user, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.get("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
        throw e;
      }
    },
    staleTime: 5 * 60 * 1000,
  });

  const login = useCallback(
    async (email, password) => {
      const res = await api.post("/auth/login", { email, password });
      setToken(res.token); // Bearer fallback for cross-origin (cookie is SameSite=Lax)
      qc.setQueryData(["me"], res.user);
      return res.user;
    },
    [qc]
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setToken(null);
      qc.setQueryData(["me"], null);
      qc.clear();
    }
  }, [qc]);

  const value = {
    user: user ?? null,
    isLoading,
    login,
    logout,
    refetch: () => qc.invalidateQueries({ queryKey: ["me"] }),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export function homePathForRole(role) {
  return role === "admin" ? "/admin" : "/";
}

function FullPageLoader() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center" role="status" aria-label="Memuat">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}

/** Gate that requires any authenticated user. */
export function RequireAuth({ children }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
  }, [isLoading, user, router]);

  if (isLoading) return <FullPageLoader />;
  if (!user) return null;
  return children;
}

/** Gate that requires a specific role; wrong role is bounced to its own home. */
export function RequireRole({ role, children }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace("/login");
    } else if (user.role !== role) {
      router.replace(homePathForRole(user.role));
    }
  }, [isLoading, user, role, router]);

  if (isLoading) return <FullPageLoader />;
  if (!user || user.role !== role) return null;
  return children;
}
