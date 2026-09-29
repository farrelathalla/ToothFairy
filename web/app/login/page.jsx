"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Loader2, RotateCcw } from "lucide-react";

import { useAuth, homePathForRole } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { reset as clearLocalData } from "@/lib/standalone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
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
    // flex-col + my-auto on the card keeps the form optically centred while the reset control
    // stays pinned to the bottom edge of the screen.
    <main className="flex min-h-dvh flex-col items-center bg-muted/30 p-4">
      <Card className="my-auto w-full max-w-sm animate-fade-in shadow-lg">
        <CardHeader className="space-y-2 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-2xl">
            🦷
          </div>
          <CardTitle className="text-xl">Masuk Smile XAI</CardTitle>
          <CardDescription>
            Deteksi karies &amp; rekonstruksi gigi 3D untuk dokter gigi
          </CardDescription>
        </CardHeader>
        <CardContent>
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
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete="current-password"
                        placeholder="••••••••"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" size="lg" className="w-full" disabled={busy}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />}
                Masuk
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>
      <footer className="pt-6">
        <ClearLocalData />
      </footer>
    </main>
  );
}
