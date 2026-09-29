"use client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export default function AccountTable({ accounts, onEdit, onToggleActive }) {
  if (!accounts?.length) {
    return <p className="py-8 text-center text-sm text-muted-foreground">Belum ada akun.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nama</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Peran</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Aksi</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {accounts.map((a) => (
            <TableRow key={a.id}>
              <TableCell className="font-medium">{a.name}</TableCell>
              <TableCell className="text-muted-foreground">{a.email}</TableCell>
              <TableCell>
                <Badge variant={a.role === "admin" ? "default" : "secondary"}>
                  {a.role === "admin" ? "Admin" : "Dokter"}
                </Badge>
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={a.is_active ? "text-emerald-600" : "text-muted-foreground"}
                >
                  {a.is_active ? "Aktif" : "Nonaktif"}
                </Badge>
              </TableCell>
              <TableCell className="space-x-1 text-right whitespace-nowrap">
                <Button size="sm" variant="ghost" onClick={() => onEdit(a)}>
                  Ubah
                </Button>
                <Button size="sm" variant="ghost" onClick={() => onToggleActive(a)}>
                  {a.is_active ? "Nonaktifkan" : "Aktifkan"}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
