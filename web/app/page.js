"use client";
import Link from "next/link";
import { LogOut, Plus } from "lucide-react";

import { RequireRole, useAuth } from "@/lib/auth";
import HistoryList from "@/components/HistoryList";
import { Button } from "@/components/ui/button";

function DoctorHome() {
  const { user, logout } = useAuth();
  return (
    <main className="mx-auto min-h-dvh max-w-2xl px-4 py-6 animate-fade-in">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground">Halo,</p>
          <h1 className="text-xl font-semibold">{user?.name || "Dokter"}</h1>
        </div>
        <Button variant="ghost" size="icon" aria-label="Keluar" onClick={logout}>
          <LogOut className="h-5 w-5" />
        </Button>
      </header>

      <Button asChild size="lg" className="mb-8 h-16 w-full rounded-2xl text-base shadow-sm">
        <Link href="/case/new">
          <Plus className="h-5 w-5" />
          Kasus Baru
        </Link>
      </Button>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Riwayat</h2>
        <HistoryList />
      </section>
    </main>
  );
}

export default function HomePage() {
  return (
    <RequireRole role="doctor">
      <DoctorHome />
    </RequireRole>
  );
}
