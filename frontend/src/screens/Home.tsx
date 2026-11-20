import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isApiError } from "../api";
import { Notice } from "../components/ui";
import { formatWhen, stateLabel } from "../labels";
import type { Dashboard } from "../types";

type Diagnostics = {
  version?: string;
  tesseract?: { installed?: boolean; languages?: string[]; missing?: string[] };
  browser?: { playwright?: boolean; chrome?: boolean };
  translation?: { argos_en_pt?: boolean; argos_zh_pt?: boolean };
  database?: { ok?: boolean } | string;
};

export function HomeScreen() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [dashboard, diagnostics] = await Promise.all([
          api<Dashboard>("/dashboard"),
          api<Diagnostics>("/diagnostics"),
        ]);
        if (!cancelled) {
          setData(dashboard);
          setDiag(diagnostics);
        }
      } catch (cause) {
        if (!cancelled) setError(isApiError(cause) ? cause.message : "Não foi possível ler o painel.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section>
      <div className="home-hero">
        <img className="home-mark" src="/branding/cpmh-mark-512.png" alt="Marca CPMH" />
        <div>
          <h1>CPMH Document Intelligence</h1>
          <p className="lede">Captura autorizada, reconhecimento e reconstrução de documentos. Os números abaixo vêm do banco local.</p>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {data && (
        <div className="grid-stats">
          <article className="stat"><b>{data.documents_total}</b><span>Documentos</span></article>
          <article className="stat"><b>{data.completed}</b><span>Concluídos</span></article>
          <article className="stat"><b>{data.in_progress}</b><span>Em andamento</span></article>
          <article className="stat"><b>{data.awaiting_review}</b><span>Aguardando revisão</span></article>
          <article className="stat"><b>{data.failed}</b><span>Falhas</span></article>
          <article className="stat"><b>{data.inconclusive}</b><span>Inconclusivos</span></article>
        </div>
      )}
      <div className="layout">
        <section className="panel">
          <h2>Documentos recentes</h2>
          {!data?.recent.length && <div className="empty">Nenhum documento registrado.</div>}
          <div className="table-wrap">
            <table>
              <thead><tr><th>Título</th><th>Estado</th><th>Inclusão</th></tr></thead>
              <tbody>
                {data?.recent.map((item) => (
                  <tr key={item.id}>
                    <td><Link to={`/documents/${item.id}`}>{item.title || item.url || item.id}</Link></td>
                    <td>{stateLabel(item.state)}</td>
                    <td>{formatWhen(item.added_at)} <span className="badge">Brasília</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="panel stack">
          <h2>Atalhos</h2>
          <Link className="btn" to="/projects">Abrir projetos</Link>
          <Link className="btn secondary" to="/queue">Ver fila</Link>
          <h2>Mecanismos</h2>
          <div className="kv">
            <span>Versão</span><strong>{diag?.version || "—"}</strong>
            <span>Tesseract</span><strong>{diag?.tesseract?.installed ? "disponível" : "ausente"}</strong>
            <span>Idiomas OCR</span><strong>{(diag?.tesseract?.languages || []).filter((item) => ["por", "eng", "chi_sim", "chi_tra"].includes(item)).join(", ") || "—"}</strong>
            <span>Navegador</span><strong>{diag?.browser?.chrome && diag?.browser?.playwright ? "Chrome + Playwright" : "incompleto"}</strong>
            <span>Tradução neural</span><strong>{diag?.translation?.argos_en_pt || diag?.translation?.argos_zh_pt ? "Argos disponível" : "Argos não instalado"}</strong>
          </div>
          {!diag?.translation?.argos_en_pt && (
            <Notice kind="warn">Sem Argos, a tradução usa somente o glossário e é marcada como parcial. Nenhum texto é enviado para fora.</Notice>
          )}
        </section>
      </div>
    </section>
  );
}
