import { useEffect, useState } from "react";
import { api, isApiError } from "../api";
import { Button, Notice } from "../components/ui";
import { formatBytes, formatWhen } from "../labels";

type Report = Record<string, unknown> & {
  version?: string;
  platform?: string;
  python?: string;
  data_dir?: string;
  database_path?: string;
  database?: { ok?: boolean; message?: string } | string;
  disk_free_bytes?: number;
  disk_total_bytes?: number;
  tesseract?: { installed?: boolean; version?: string; missing?: string[] };
  browser?: { playwright?: boolean; chrome?: boolean; chrome_path?: string };
  translation?: { argos_en_pt?: boolean; argos_zh_pt?: boolean };
  windows_installer_tested?: boolean;
  recent_errors?: { id: string; message: string; category: string; created_at: string }[];
};

export function DiagnosticsScreen() {
  const [report, setReport] = useState<Report | null>(null);
  const [logs, setLogs] = useState<{ id: string; level: string; category: string; message: string; created_at: string }[]>([]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function load() {
    const [diagnostics, entries] = await Promise.all([
      api<Report>("/diagnostics"),
      api<typeof logs>("/logs"),
    ]);
    setReport(diagnostics);
    setLogs(entries);
  }

  useEffect(() => {
    load().catch((cause) => setError(isApiError(cause) ? cause.message : "Diagnóstico indisponível."));
  }, []);

  async function repair() {
    const result = await api<Record<string, unknown>>("/diagnostics/repair", { method: "POST" });
    setInfo(`Reparo executado. ${JSON.stringify(result)}`);
    await load();
  }

  async function backup() {
    const result = await api<{ path: string }>("/diagnostics/backup", { method: "POST" });
    setInfo(`Backup criado em ${result.path}`);
  }

  async function downloadReport() {
    const payload = await api<Report>("/logs/report?redact_document_text=true", { method: "POST" });
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "cpmh-relatorio-tecnico.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  const database = report?.database;
  const databaseOk = typeof database === "object" && database ? database.ok : database === "ok";

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Diagnóstico</h1>
          <p>Estado real dos componentes neste computador. O relatório técnico não inclui o texto dos documentos.</p>
        </div>
        <div className="row">
          <Button kind="secondary" onClick={() => void repair()}>Reparar pastas</Button>
          <Button kind="secondary" onClick={() => void backup()}>Backup do banco</Button>
          <Button onClick={() => void downloadReport()}>Exportar relatório</Button>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {info && <Notice>{info}</Notice>}
      {report && (
        <section className="panel">
          <div className="kv">
            <span>Aplicativo</span><strong>{String(report.version || "—")}</strong>
            <span>Plataforma</span><strong>{String(report.platform || "—")}</strong>
            <span>Python</span><strong>{String(report.python || "—")}</strong>
            <span>Banco</span><strong>{databaseOk ? "íntegro" : "verificar"}</strong>
            <span>Dados</span><strong className="mono">{report.data_dir}</strong>
            <span>Disco livre</span><strong>{formatBytes(report.disk_free_bytes)} de {formatBytes(report.disk_total_bytes)}</strong>
            <span>Tesseract</span><strong>{report.tesseract?.installed ? report.tesseract.version : "ausente"}</strong>
            <span>Idiomas faltantes</span><strong>{report.tesseract?.missing?.length ? report.tesseract.missing.join(", ") : "nenhum dos quatro prioritários"}</strong>
            <span>Playwright</span><strong>{report.browser?.playwright ? "importável" : "ausente"}</strong>
            <span>Chrome</span><strong>{report.browser?.chrome ? report.browser.chrome_path : "não encontrado"}</strong>
            <span>Argos en→pt</span><strong>{report.translation?.argos_en_pt ? "sim" : "não instalado"}</strong>
            <span>Argos zh→pt</span><strong>{report.translation?.argos_zh_pt ? "sim" : "não instalado"}</strong>
            <span>Instalador Windows testado</span><strong>{report.windows_installer_tested ? "sim" : "não"}</strong>
          </div>
        </section>
      )}
      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Últimos registros</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Quando</th><th>Nível</th><th>Categoria</th><th>Mensagem</th></tr></thead>
            <tbody>
              {logs.map((item) => (
                <tr key={item.id}>
                  <td>{formatWhen(item.created_at)}</td>
                  <td>{item.level}</td>
                  <td>{item.category}</td>
                  <td>{item.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!logs.length && <div className="empty">Sem registros.</div>}
        </div>
      </section>
    </section>
  );
}
