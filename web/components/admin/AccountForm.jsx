"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const nameField = z.string().min(1, "Nama wajib diisi").max(255);
const roleField = z.enum(["admin", "doctor"]);
const optionalPassword = z
  .string()
  .min(6, "Minimal 6 karakter")
  .optional()
  .or(z.literal(""));

function schemaFor(mode) {
  if (mode === "create") {
    return z.object({
      email: z.string().min(1, "Email wajib diisi").email("Format email tidak valid"),
      name: nameField,
      role: roleField,
      password: z.string().min(6, "Minimal 6 karakter"),
    });
  }
  return z.object({
    name: nameField,
    role: roleField,
    is_active: z.boolean(),
    password: optionalPassword,
  });
}

/**
 * Reusable account form.
 * @param {"create"|"edit"} mode
 * @param {object}  defaultValues
 * @param {(values:object)=>Promise<void>|void} onSubmit  parent performs the API call
 */
export default function AccountForm({ mode = "create", defaultValues, onSubmit, onCancel, submitting }) {
  const isCreate = mode === "create";
  const form = useForm({
    resolver: zodResolver(schemaFor(mode)),
    defaultValues: {
      email: "",
      name: "",
      role: "doctor",
      is_active: true,
      password: "",
      ...defaultValues,
    },
  });

  async function handle(values) {
    // Drop an empty password on edit (means "leave unchanged").
    if (!isCreate && !values.password) delete values.password;
    await onSubmit(values);
  }

  const busy = submitting || form.formState.isSubmitting;

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(handle)} className="space-y-4" noValidate>
        {isCreate && (
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input type="email" placeholder="dokter@klinik.com" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Nama</FormLabel>
              <FormControl>
                <Input placeholder="Nama lengkap" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="role"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Peran</FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue placeholder="Pilih peran" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value="doctor">Dokter</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />

        {!isCreate && (
          <FormField
            control={form.control}
            name="is_active"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Status</FormLabel>
                <Select
                  onValueChange={(v) => field.onChange(v === "true")}
                  value={String(field.value)}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="true">Aktif</SelectItem>
                    <SelectItem value="false">Nonaktif</SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>{isCreate ? "Kata Sandi" : "Kata Sandi Baru"}</FormLabel>
              <FormControl>
                <Input type="password" placeholder="••••••••" {...field} />
              </FormControl>
              {!isCreate && (
                <FormDescription>Kosongkan jika tidak ingin mengubah.</FormDescription>
              )}
              <FormMessage />
            </FormItem>
          )}
        />

        <div className="flex justify-end gap-2 pt-2">
          {onCancel && (
            <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
              Batal
            </Button>
          )}
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {isCreate ? "Buat Akun" : "Simpan"}
          </Button>
        </div>
      </form>
    </Form>
  );
}
