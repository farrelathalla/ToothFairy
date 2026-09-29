"use client";
import Link from "next/link";
import { ArrowRight, ClipboardList, LogOut, Plus } from "lucide-react";

import { RequireRole, useAuth } from "@/lib/auth";
import HistoryList from "@/components/HistoryList";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";

function greeting(date = new Date()) {
  const h = date.getHours();
  if (h < 11) return "Selamat pagi";
  if (h < 15) return "Selamat siang";
  if (h < 19) return "Selamat sore";
  return "Selamat malam";
}

function initials(name = "") {
  const parts = name.replace(/^drg\.?\s*/i, "").split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] || "D").toUpperCase() + (parts[1]?.[0] || "").toUpperCase();
}

function DoctorHome() {
  const { user, logout } = useAuth();
  const today = new Date().toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long" });

  return (
    <main className="mx-auto min-h-dvh max-w-2xl px-4 pb-10 pt-4">
      <header className="mb-7 flex items-center justify-between animate-fade-in">
        <Logo />
        <div className="flex items-center gap-1.5">
          <span
            className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
            aria-hidden
          >
            {initials(user?.name)}
          </span>
          <Button variant="ghost" size="icon" className="rounded-full" aria-label="Keluar" onClick={logout}>
            <LogOut className="h-[18px] w-[18px]" />
          </Button>
        </div>
      </header>

      <section className="mb-6 animate-rise" style={{ "--i": 1 }}>
        <p className="text-sm capitalize text-muted-foreground">{today}</p>
        <h1 className="mt-0.5 text-2xl font-semibold tracking-tight">
          {greeting()}, {user?.name || "Dokter"}
        </h1>
      </section>

      <Link
        href="/case/new"
        className="group relative mb-9 flex items-center gap-4 overflow-hidden rounded-3xl bg-primary p-5 text-primary-foreground shadow-[0_12px_32px_-12px_rgba(37,99,235,0.6)] transition-transform duration-200 hover:-translate-y-0.5 active:translate-y-0 animate-rise"
        style={{ "--i": 2 }}
      >
        {/* quiet depth: two offset rings in the corner */}
        <span className="pointer-events-none absolute -right-10 -top-12 h-40 w-40 rounded-full border-[18px] border-white/[0.07]" />
        <span className="pointer-events-none absolute -bottom-16 right-12 h-32 w-32 rounded-full border-[14px] border-white/[0.05]" />
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-white/15 transition-transform duration-300 group-hover:rotate-90">
          <Plus className="h-6 w-6" />
        </span>
        <span className="relative min-w-0 flex-1">
          <span className="block text-base font-semibold">Kasus Baru</span>
          <span className="block text-xs text-primary-foreground/75">Anamnesa → foto → analisis &amp; model 3D</span>
        </span>
        <ArrowRight className="relative h-5 w-5 shrink-0 transition-transform duration-200 group-hover:translate-x-1" />
      </Link>

      <section className="animate-rise" style={{ "--i": 3 }}>
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <ClipboardList className="h-4 w-4 text-muted-foreground" />
          Riwayat Pemeriksaan
        </h2>
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
