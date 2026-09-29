"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowRight, Eye, EyeOff, Loader2, RotateCcw } from "lucide-react";

import { useAuth, homePathForRole } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { DEMO_CREDENTIALS, DEMO_MODE } from "@/lib/demo";
import { reset as clearLocalData } from "@/lib/standalone";
import { LogoMark } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";

/**
 * Clears the data standalone mode keeps in this browser (local session + case history).
 *
 * It lives on the sign-in screen because that is the only place reachable without a session,
 * which is exactly when a stale local state needs clearing, and at the foot of the page so it
 * reads as a maintenance escape hatch rather than part of signing in. Nothing here touches
 * the server.
 */
function ClearLocalData() {
  function onClick() {
    clearLocalData();
    toast.success("Data lokal di perangkat ini dihapus");
    // Reload so cached queries (history, session) are dropped along with the storage.
    window.location.reload();
  }

  return (
    <button
      type="button"
      onClick={onClick}
      title="Hapus sesi & riwayat yang tersimpan di perangkat ini"
      className="mx-auto flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px]
                 text-muted-foreground/70 transition-colors hover:bg-muted
                 hover:text-foreground focus-visible:outline-none focus-visible:ring-1
                 focus-visible:ring-ring"
    >
      <RotateCcw className="h-3 w-3" />
      Atur ulang data lokal
    </button>
  );
}

const schema = z.object({
  email: z.string().min(1, "Email wajib diisi").email("Format email tidak valid"),
  password: z.string().min(1, "Kata sandi wajib diisi"),
});

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: DEMO_MODE ? DEMO_CREDENTIALS : { email: "", password: "" },
  });

  async function onSubmit(values) {
    try {
      const user = await login(values.email, values.password);
      toast.success(`Selamat datang, ${user.name}`);
      router.replace(homePathForRole(user.role));
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "Tidak dapat terhubung ke server";
      toast.error(msg);
      form.setError("password", { type: "server", message: msg });
    }
  }

  const busy = form.formState.isSubmitting;

  return (
    // flex-col + my-auto on the panel keeps the form optically centred while the reset control
    // stays pinned to the bottom edge of the screen.
    <main className="relative flex min-h-dvh flex-col items-center overflow-hidden bg-background px-4 py-6">
      {/* backdrop: dotted field fading out from a soft blue glow behind the mark */}
      <div className="bg-dots pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_top,black_10%,transparent_65%)]" />
      <div className="pointer-events-none absolute -top-40 left-1/2 h-80 w-[36rem] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />

      <div className="relative my-auto w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="tf-float">
            <LogoMark animated className="h-16 w-16 drop-shadow-[0_10px_24px_rgba(37,99,235,0.28)]" />
          </div>
          <h1 className="mt-5 text-2xl font-semibold tracking-tight animate-rise" style={{ "--i": 3 }}>
            Masuk ke Tooth<span className="text-primary">Fairy</span>
          </h1>
          <p className="mt-1.5 max-w-[17rem] text-sm text-muted-foreground animate-rise" style={{ "--i": 4 }}>
            Deteksi karies &amp; rekonstruksi gigi 3D untuk dokter gigi
          </p>
        </div>

        <div className="rounded-3xl border bg-card/90 p-6 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_12px_32px_-12px_rgba(15,23,42,0.12)] backdrop-blur animate-rise" style={{ "--i": 5 }}>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input
                        type="email"
                        inputMode="email"
                        autoComplete="email"
                        placeholder="nama@klinik.com"
                        className="h-11 rounded-xl bg-background"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Kata Sandi</FormLabel>
                    <div className="relative">
                      <FormControl>
                        <Input
                          type={showPassword ? "text" : "password"}
                          autoComplete="current-password"
                          placeholder="••••••••"
                          className="h-11 rounded-xl bg-background pr-11"
                          {...field}
                        />
                      </FormControl>
                      <button
                        type="button"
                        onClick={() => setShowPassword((v) => !v)}
                        aria-label={showPassword ? "Sembunyikan kata sandi" : "Tampilkan kata sandi"}
                        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-xl text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" size="lg" className="group h-11 w-full rounded-xl text-[15px]" disabled={busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Masuk
                {!busy && <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />}
              </Button>
            </form>
          </Form>
        </div>
      </div>

      <footer className="relative pt-6">
        <ClearLocalData />
      </footer>
    </main>
  );
}
