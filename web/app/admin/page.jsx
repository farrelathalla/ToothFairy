"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { LogOut, Plus } from "lucide-react";

import { api, ApiError } from "@/lib/api";
import { RequireRole, useAuth } from "@/lib/auth";
import AccountTable from "@/components/admin/AccountTable";
import AccountForm from "@/components/admin/AccountForm";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Logo } from "@/components/brand/Logo";

function AdminInner() {
  const qc = useQueryClient();
  const { user, logout } = useAuth();
  const [dialog, setDialog] = useState(null); // { mode, account } | null

  const { data: accounts, isLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get("/accounts"),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["accounts"] });
  const onError = (e) =>
    toast.error(e instanceof ApiError ? e.message : "Terjadi kesalahan");

  const createMut = useMutation({
    mutationFn: (v) => api.post("/accounts", v),
    onSuccess: () => {
      toast.success("Akun dibuat");
      invalidate();
    },
    onError,
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...v }) => api.patch(`/accounts/${id}`, v),
    onSuccess: () => {
      toast.success("Akun diperbarui");
      invalidate();
    },
    onError,
  });

  const toggleMut = useMutation({
    mutationFn: (a) =>
      a.is_active ? api.del(`/accounts/${a.id}`) : api.patch(`/accounts/${a.id}`, { is_active: true }),
    onSuccess: () => invalidate(),
    onError,
  });

  async function handleSubmit(values) {
    if (dialog.mode === "create") await createMut.mutateAsync(values);
    else await updateMut.mutateAsync({ id: dialog.account.id, ...values });
    setDialog(null);
  }

  return (
    <main className="mx-auto min-h-dvh max-w-4xl px-4 py-6">
      <header className="mb-6 flex items-center justify-between gap-3 animate-fade-in">
        <Logo />
        <Button variant="ghost" size="sm" className="rounded-full" onClick={logout}>
          <LogOut className="h-4 w-4" />
          Keluar
        </Button>
      </header>

      <div className="mb-5 animate-rise" style={{ "--i": 1 }}>
        <h1 className="text-2xl font-semibold tracking-tight">Manajemen Akun</h1>
        <p className="text-sm text-muted-foreground">Masuk sebagai {user?.name}</p>
      </div>

      <div className="mb-4 flex justify-end">
        <Button onClick={() => setDialog({ mode: "create" })}>
          <Plus className="h-4 w-4" />
          Akun Baru
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : (
        <AccountTable
          accounts={accounts}
          onEdit={(a) => setDialog({ mode: "edit", account: a })}
          onToggleActive={(a) => toggleMut.mutate(a)}
        />
      )}

      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialog?.mode === "create" ? "Akun Baru" : "Ubah Akun"}</DialogTitle>
            <DialogDescription>
              {dialog?.mode === "create"
                ? "Buat akun dokter atau admin baru."
                : "Perbarui detail akun atau setel ulang kata sandi."}
            </DialogDescription>
          </DialogHeader>
          {dialog && (
            <AccountForm
              mode={dialog.mode}
              defaultValues={
                dialog.mode === "edit"
                  ? {
                      name: dialog.account.name,
                      role: dialog.account.role,
                      is_active: dialog.account.is_active,
                    }
                  : undefined
              }
              onSubmit={handleSubmit}
              onCancel={() => setDialog(null)}
            />
          )}
        </DialogContent>
      </Dialog>
    </main>
  );
}

export default function AdminPage() {
  return (
    <RequireRole role="admin">
      <AdminInner />
    </RequireRole>
  );
}
