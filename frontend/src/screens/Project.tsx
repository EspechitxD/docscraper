import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, isApiError } from "../api";
import { Button, Field, Modal, Notice, Progress } from "../components/ui";
import { isActiveState, nextStep, stateLabel } from "../labels";
import type { DocumentItem, Project } from "../types";

type GlossaryRow = { id: string; name: string };

export function ProjectScreen() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [bulk, setBulk] = useState("");
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [editing, setEditing] = useState<DocumentItem | null>(null);
  const [glossaries, setGlossaries] = useState<GlossaryRow[]>([]);

  async function load() {
    const [current, rows] = await Promise.all([
      api<Project>(`/projects/${projectId}`),
      api<DocumentItem[]>(`/projects/${projectId}/documents?q=${encodeURIComponent(query)}&state=${encodeURIComponent(state)}`),
    ]);
    setProject(current);
    setName(current.name);
    setDocuments(rows);
    const lists = await api<GlossaryRow[]>("/glossaries");
    setGlossaries(lists);
  }

  useEffect(() => {
    load().catch((cause) => setError(isApiError(cause) ? cause.message : "Projeto indisponível."));
  }, [projectId]);

  useEffect(() => {
    if (!documents.some((item) => isActiveState(item.state))) return undefined;
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [documents, projectId]);

  async function extract(documentId: string) {
    await api(`/documents/${documentId}/jobs`, {
      method: "POST",
      body: JSON.stringify({ translate_mode: "none", export_formats: [] }),
    });
  }

  async function addUrl() {
    setError("");
    setInfo("");
    try {
      const result = await api<{ result: string; document: DocumentItem }>(`/projects/${projectId}/documents`, {
        method: "POST",
        body: JSON.stringify({ url, priority: 0 }),
      });
      if (result.result === "duplicate") {
        setInfo("Esse endereço já está no projeto. Use Extrair na linha dele se ainda for rascunho.");
      } else {
        await extract(result.document.id);
        setInfo("Extração iniciada. Quando o estado mudar para aguardando revisão, abra Knowledge AI e pergunte sobre o documento.");
      }
      setUrl("");
      await load();
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "URL recusada.");
    }
  }

  async function importText() {
    setError("");
    setInfo("");
    try {
      const result = await api<{ added: unknown[]; duplicates: unknown[]; rejected: { message: string }[] }>(
        `/projects/${projectId}/documents/import`,
        { method: "POST", body: JSON.stringify({ text: bulk }) },
      );
      for (const item of result.added) {
        const id = (item as { id?: string }).id;
        if (id) await extract(id);
      }
      setInfo(`${result.added.length} em extração, ${result.duplicates.length} duplicados, ${result.rejected.length} recusados.`);
      setBulk("");
      await load();
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Falha na importação.");
    }
  }

  async function importFile(file: File) {
    setError("");
    const body = new FormData();
    body.append("file", file);
    try {
      const saved = await api<{ id?: string; added?: { id: string }[] }>(`/projects/${projectId}/documents/file`, { method: "POST", body });
      if (saved.id) await extract(saved.id);
      for (const item of saved.added || []) await extract(item.id);
      setInfo(`Arquivo “${file.name}” em extração.`);
      await load();
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Arquivo recusado.");
    }
  }

  async function saveProject() {
    await api(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ name }) });
    await load();
  }

  async function archive() {
    if (!project) return;
    await api(`/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: project.status === "archived" ? "active" : "archived" }),
    });
    await load();
  }

  async function removeProject() {
    await api(`/projects/${projectId}?confirm=true`, { method: "DELETE" });
    navigate("/projects");
  }

  async function saveDocument() {
    if (!editing) return;
    try {
      await api(`/documents/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: editing.title, url: editing.url, priority: editing.priority, confirm_reset: true }),
      });
      setEditing(null);
      await load();
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Não foi possível editar o documento.");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{project?.name || "Projeto"}</h1>
          <p>{project ? `${stateLabel(project.status)} · ${project.document_count} documentos` : "Carregando"}</p>
        </div>
        <div className="row">
          <Button kind="secondary" onClick={() => void archive()}>{project?.status === "archived" ? "Reabrir" : "Arquivar"}</Button>
          <Button kind="danger" onClick={() => setConfirmDelete(true)}>Excluir</Button>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {info && <Notice>{info}</Notice>}
      <div className="layout">
        <section className="panel stack">
          <h2>Enviar link</h2>
          <p className="lede">Cole o endereço do PDF ou do documento. A extração começa sozinha. Para perguntar o que foi aprendido, use Knowledge AI no menu à esquerda.</p>
          <div className="row">
            <input className="field grow" value={url} placeholder="https://…" onChange={(event) => setUrl(event.target.value)} />
            <Button onClick={() => void addUrl()}>Extrair</Button>
          </div>
          <Field label="Várias URLs, TXT ou CSV colado">
            <textarea className="area" value={bulk} onChange={(event) => setBulk(event.target.value)} placeholder={"https://exemplo/a.pdf\nhttps://exemplo/b.pdf"} />
          </Field>
          <div className="row">
            <Button kind="secondary" onClick={() => void importText()}>Importar lista</Button>
            <label className="btn secondary">
              Importar arquivo
              <input hidden type="file" accept=".txt,.csv,.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importFile(file);
                event.target.value = "";
              }} />
            </label>
          </div>
          <p className="lede">PDF acessível é processado pelo arquivo. Página HTML entra na captura sequencial. Endereços locais e de metadados são recusados, salvo a preferência explícita de rede local.</p>
        </section>
        <form className="panel stack" onSubmit={(event) => { event.preventDefault(); void saveProject(); }}>
          <h2>Identidade do projeto</h2>
          <Field label="Nome"><input className="field" value={name} onChange={(event) => setName(event.target.value)} /></Field>
          <Field label="Glossário deste projeto">
            <select
              className="select"
              value={project?.glossary_id || ""}
              onChange={(event) => {
                const glossaryId = event.target.value || null;
                void api(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify({ glossary_id: glossaryId }) }).then(load);
              }}
            >
              <option value="">Nenhum glossário associado</option>
              {glossaries.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </Field>
          <p className="lede">A tradução deste projeto usa somente o glossário associado. O glossário de outro projeto não é aplicado.</p>
          <Button type="submit" kind="secondary">Renomear</Button>
        </form>
      </div>
      <section className="panel" style={{ marginTop: 14 }}>
        <div className="row" style={{ marginBottom: 10 }}>
          <input className="field grow" value={query} placeholder="Filtrar documentos" onChange={(event) => setQuery(event.target.value)} />
          <select className="select" value={state} onChange={(event) => setState(event.target.value)}>
            <option value="">Todos os estados</option>
            {["draft", "queued", "awaiting_review", "completed", "failed", "inconclusive", "paused"].map((item) => (
              <option key={item} value={item}>{stateLabel(item)}</option>
            ))}
          </select>
          <Button kind="secondary" onClick={() => load().catch((cause) => setError(isApiError(cause) ? cause.message : "Falha ao filtrar."))}>Aplicar</Button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Documento</th><th>Andamento</th><th></th></tr>
            </thead>
            <tbody>
              {documents.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link to={`/documents/${item.id}`}>{item.title || item.url || "Documento"}</Link>
                    <div className="mono">{item.url || item.domain || item.origin}</div>
                    {item.error_message && <div className="badge bad">{item.error_message}</div>}
                  </td>
                  <td>
                    <div>{nextStep(item.state)}</div>
                    <Progress value={item.state === "awaiting_review" || item.state === "completed" ? 100 : item.progress} waiting={isActiveState(item.state) && item.state !== "paused"} />
                  </td>
                  <td className="row">
                    {(item.state === "draft" || item.state === "failed") && (
                      <Button kind="ghost" onClick={() => void extract(item.id).then(load).catch((cause) => setError(isApiError(cause) ? cause.message : "A extração não começou."))}>Extrair</Button>
                    )}
                    {(item.state === "awaiting_review" || item.state === "completed" || item.state === "inconclusive") && (
                      <Link className="btn secondary" to="/knowledge">Perguntar</Link>
                    )}
                    <Button kind="ghost" onClick={() => setEditing(item)}>Editar</Button>
                    <Button kind="ghost" onClick={() => api(`/documents/${item.id}`, { method: "DELETE" }).then(load)}>Remover</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!documents.length && <div className="empty">Nenhum documento neste filtro.</div>}
        </div>
      </section>
      {confirmDelete && (
        <Modal title="Excluir projeto" onClose={() => setConfirmDelete(false)}>
          <p>A exclusão remove o projeto e os arquivos de trabalho locais. Exportações já gravadas fora da pasta de dados permanecem.</p>
          <div className="row">
            <Button kind="danger" onClick={() => void removeProject()}>Excluir</Button>
            <Button kind="secondary" onClick={() => setConfirmDelete(false)}>Cancelar</Button>
          </div>
        </Modal>
      )}
      {editing && (
        <Modal title="Editar documento" onClose={() => setEditing(null)}>
          <div className="stack">
            <Field label="Título"><input className="field" value={editing.title} onChange={(event) => setEditing({ ...editing, title: event.target.value })} /></Field>
            <Field label="URL"><input className="field" value={editing.url} onChange={(event) => setEditing({ ...editing, url: event.target.value })} /></Field>
            <Field label="Prioridade"><input className="field" type="number" min={0} max={100} value={editing.priority} onChange={(event) => setEditing({ ...editing, priority: Number(event.target.value) })} /></Field>
            <Notice kind="warn">Alterar a URL de um documento já capturado descarta as páginas armazenadas.</Notice>
            <div className="row">
              <Button onClick={() => void saveDocument()}>Salvar</Button>
              <Button kind="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
