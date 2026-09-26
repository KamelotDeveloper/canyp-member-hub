"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportResource, type ExportFormat } from "@/lib/canyp/api";
import { downloadBlob } from "@/components/import/downloads";

interface ExportButtonProps {
  /** Resource key, e.g. "socios" — must exist in the backend export registry. */
  resource: string;
  /** Human label for the export filename / toast, e.g. "socios". */
  label?: string;
  variant?: "outline" | "ghost";
}

/** Dropdown button that downloads a complete CSV or XLSX export of a resource. */
export function ExportButton({
  resource,
  label = resource,
  variant = "outline",
}: ExportButtonProps) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);

  async function descargar(format: ExportFormat) {
    setBusy(format);
    try {
      const blob = await exportResource(resource, format);
      const today = new Date().toISOString().slice(0, 10);
      downloadBlob(blob, `${resource}_${today}.${format}`);
      toast.success(`Export de ${label} descargado`);
    } catch {
      toast.error(`No se pudo exportar ${label}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={variant} disabled={busy !== null}>
          <Download className="mr-2 size-4" /> {busy ? "Exportando..." : "Exportar"}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Exportar {label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => descargar("csv")} disabled={busy !== null}>
          <FileText className="mr-2 size-4" /> CSV
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => descargar("xlsx")} disabled={busy !== null}>
          <FileSpreadsheet className="mr-2 size-4" /> XLSX
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
