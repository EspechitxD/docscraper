import { useState } from "react";
import { api, isApiError } from "../api";
import { Button, Notice } from "./ui";

type WebReport = {
  url?: string;
  primary_state: string;
  states: string[];
  viewer_type?: string;
  restrictions?: string[];
  evidence?: string[];
  conclusive?: boolean;
  error?: string;
  summary?: string;
  strategy?: { code: string; name: string; action: string };
  pages?: { reported_by_site: number | null; accessible: number | null; processed: number; with_text: number; without_text: number };
  text?: { document_chars: number; interface_chars_discarded: number };
  resources?: {
    pdf_accessible: string[];
    pdf_linked_not_verified: string[];
    iframes: string[];
    canvas_page_like: number;
    page_images: number;
    export_control_seen: boolean;
  };
  errors?: { network: string[]; console: string[] };
};

const STATE_LABELS: Record<string, string> = {
  html_document: "Documento em HTML",
  pdf_document: "PDF acessível",
  pdf_viewer_detected: "Visualizador PDF.js detectado",
  image_document: "Páginas em imagem",
  canvas_document: "Páginas em canvas",
  ocr_required: "Exige OCR",
  authentication_required: "Exige login",
  captcha_required: "Exige CAPTCHA",
  access_restricted: "Acesso restrito (pagamento ou permissão)",
  interface_only: "Só interface, nenhuma fonte documental",
  partial_document: "Documento parcial",
  document_recovered: "Documento recuperado",
  processing_failed: "Análise não executada",
};

const RESTRICTION_LABELS: Record<string, string> = {
  captcha: "CAPTCHA",
  authentication: "Autenticação",
  access_denied: "Acesso negado",
  payment: "Pagamento",
};

function show(value: number | null | undefined): string {
  return value === null || value === undefined ? "não informado" : String(value);
}

export function WebDocumentDiagnosis() {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<WebReport | null>(null);

  async function run() {
    setBusy(true);
    setError("");
    setReport(null);
    try {
      setReport(await api<WebReport>("/diagnostics/web-document", { method: "POST", body: JSON.stringify({ url }) }));
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Não foi possível analisar a página.");
    } finally {
      setBusy(false);
    }
  }

  function save() {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "diagnostico-documento-web.json";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <section className="panel" style={{ marginTop: 14 }}>
      <h2>Diagnóstico de documentos web</h2>
      <p>
        Abre a página no Chrome, só observa e diz de onde viria o documento. Não resolve CAPTCHA, login nem pagamento.
        Páginas informadas pelo site são metadado e nunca contam como processadas.
      </p>
      <div className="row">
        <input
          style={{ flex: 1 }}
          placeholder="https://…"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          aria-label="Endereço da página a analisar"
        />
        <Button disabled={busy || !url.trim()} onClick={() => void run()}>
          {busy ? "Analisando…" : "Analisar página"}
        </Button>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {report?.error && <Notice kind="error">{report.error}</Notice>}
      {report && !report.error && (
        <div style={{ marginTop: 12 }}>
          <div className="kv">
            <span>Estado</span>
            <strong>{STATE_LABELS[report.primary_state] || report.primary_state}</strong>
            <span>Outros sinais</span>
            <strong>{report.states.slice(1).map((state) => STATE_LABELS[state] || state).join(", ") || "nenhum"}</strong>
            <span>Visualizador</span>
            <strong>{report.viewer_type || "—"}</strong>
            <span>Restrições</span>
            <strong>{report.restrictions?.length ? report.restrictions.map((item) => RESTRICTION_LABELS[item] || item).join(", ") : "nenhuma vista"}</strong>
            <span>Páginas informadas pelo site</span>
            <strong>{show(report.pages?.reported_by_site)}</strong>
            <span>Páginas acessíveis</span>
            <strong>{show(report.pages?.accessible)}</strong>
            <span>Páginas processadas</span>
            <strong>{report.pages?.processed ?? 0}</strong>
            <span>Caracteres documentais</span>
            <strong>{report.text?.document_chars ?? 0}</strong>
            <span>Caracteres de interface descartados</span>
            <strong>{report.text?.interface_chars_discarded ?? 0}</strong>
            <span>PDF acessível</span>
            <strong className="mono">{report.resources?.pdf_accessible.join(", ") || "nenhum"}</strong>
            <span>PDF citado, não verificado</span>
            <strong className="mono">{report.resources?.pdf_linked_not_verified.join(", ") || "nenhum"}</strong>
            <span>Imagens de página / canvas</span>
            <strong>{report.resources?.page_images ?? 0} / {report.resources?.canvas_page_like ?? 0}</strong>
          </div>
          {report.strategy && (
            <Notice>
              Estratégia {report.strategy.code} — {report.strategy.name}. {report.strategy.action}
            </Notice>
          )}
          {!report.conclusive && <Notice kind="error">Diagnóstico não conclusivo: nenhuma fonte documental foi encontrada.</Notice>}
          {!!report.errors?.network.length && (
            <details>
              <summary>Erros de rede ({report.errors.network.length})</summary>
              <pre className="mono">{report.errors.network.join("\n")}</pre>
            </details>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <Button kind="secondary" onClick={save}>Salvar relatório (JSON)</Button>
          </div>
        </div>
      )}
    </section>
  );
}
