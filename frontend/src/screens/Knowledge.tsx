import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isApiError } from "../api";
import { Button, Field, Notice } from "../components/ui";

type Status = {
  documents: number;
  chunks: number;
  runtime: {
    llm_ready: boolean;
    provider: string | null;
    embedding_model: string;
    embedding_kind: string;
    neural_embedding: boolean;
    silent_download: boolean;
    note: string;
    ollama: { reachable: boolean; models: string[] };
  };
  training: { training_executed: boolean; approved_examples: number; note: string };
};

type Indexed = { document_id: string; title: string; project_id: string; chunks: number; pages: number };
type Project = { id: string; name: string };
type Library = { id: string; name: string; project_id: string | null };
type Citation = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  page: number;
  section: string;
  element_type: string;
};
type Answer = { answer: string; citations: Citation[]; mode: string };
type Conversation = { id: string; title: string; scope: string };
type ModelRow = {
  id: string;
  name: string;
  kind: string;
  license: string;
  quantization: string;
  size_bytes: number;
  profile: string;
  active: boolean;
  sha256: string;
};
type Models = { runtime: Status["runtime"]; installed: ModelRow[]; catalog: { name: string; profile: string; license: string; note: string }[] };

const REFUSAL = "Não encontrei informações suficientes na biblioteca documental para responder com segurança.";

export function KnowledgeScreen() {
  const [status, setStatus] = useState<Status | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [documents, setDocuments] = useState<Indexed[]>([]);
  const [models, setModels] = useState<Models | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [scope, setScope] = useState("project");
  const [projectId, setProjectId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [libraryId, setLibraryId] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [graphCount, setGraphCount] = useState<{ entities: number; relations: number } | null>(null);

  async function reload() {
    const [nextStatus, nextProjects, nextLibraries, nextDocuments, nextModels, nextConversations] = await Promise.all([
      api<Status>("/knowledge/status"),
      api<Project[]>("/projects"),
      api<Library[]>("/knowledge/libraries"),
      api<Indexed[]>("/knowledge/documents"),
      api<Models>("/knowledge/models"),
      api<Conversation[]>("/knowledge/conversations"),
    ]);
    setStatus(nextStatus);
    setProjects(nextProjects);
    setLibraries(nextLibraries);
    setDocuments(nextDocuments);
    setModels(nextModels);
    setConversations(nextConversations);
    setProjectId((current) => current || nextProjects[0]?.id || "");
    setDocumentId((current) => current || nextDocuments[0]?.document_id || "");
    setLibraryId((current) => current || nextLibraries[0]?.id || "");
  }

  useEffect(() => {
    reload().catch((cause) => setError(isApiError(cause) ? cause.message : "Knowledge AI indisponível."));
  }, []);

  async function submitQuestion() {
    setBusy(true);
    setError("");
    setAnswer(null);
    try {
      const body: Record<string, string> = { question, scope };
      if (scope === "project") body.project_id = projectId;
      if (scope === "document") body.document_id = documentId;
      if (scope === "library") body.library_id = libraryId;
      if (conversationId) body.conversation_id = conversationId;
      setAnswer(await api<Answer>("/knowledge/ask", { method: "POST", body: JSON.stringify(body) }));
      if (conversationId) setConversations(await api<Conversation[]>("/knowledge/conversations"));
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "A consulta não foi concluída.");
    } finally {
      setBusy(false);
    }
  }

  async function newConversation() {
    const created = await api<Conversation>("/knowledge/conversations", {
      method: "POST",
      body: JSON.stringify({
        title: question.slice(0, 80) || "Conversa",
        scope,
        project_id: projectId || null,
        document_id: documentId || null,
        library_id: libraryId || null,
      }),
    });
    setConversationId(created.id);
    setConversations(await api<Conversation[]>("/knowledge/conversations"));
  }

  async function reindex(id: string) {
    await api(`/knowledge/documents/${id}/index`, { method: "POST" });
    await reload();
  }

  async function removeIndexed(id: string) {
    await api(`/knowledge/documents/${id}`, { method: "DELETE" });
    await reload();
  }

  async function loadGraph(id: string) {
    const payload = await api<{ entities: unknown[]; relations: unknown[] }>(`/knowledge/graph?library_id=${id}`);
    setGraphCount({ entities: payload.entities.length, relations: payload.relations.length });
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Knowledge AI</h1>
          <p>Biblioteca local construída a partir dos documentos já processados. A consulta recupera trechos e cita a origem. Indexar não treina o modelo.</p>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      <div className="grid-stats">
        <article className="stat"><span>Documentos indexados</span><b>{status?.documents ?? "—"}</b></article>
        <article className="stat"><span>Segmentos</span><b>{status?.chunks ?? "—"}</b></article>
        <article className="stat"><span>Modelo de linguagem</span><b>{status?.runtime.llm_ready ? status.runtime.provider : "não instalado"}</b></article>
        <article className="stat"><span>Embedding</span><b>{status?.runtime.embedding_kind ?? "—"}</b></article>
      </div>
      {status && <Notice>{status.runtime.note} {status.training.note}</Notice>}
      <div className="layout">
        <section className="panel stack">
          <h2>Consulta</h2>
          <Field label="Escopo">
            <select className="select" value={scope} onChange={(event) => setScope(event.target.value)}>
              <option value="document">Documento</option>
              <option value="project">Projeto</option>
              <option value="library">Biblioteca</option>
              <option value="global">Biblioteca global desta instalação</option>
            </select>
          </Field>
          {scope === "project" && (
            <Field label="Projeto">
              <select className="select" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
          )}
          {scope === "document" && (
            <Field label="Documento">
              <select className="select" value={documentId} onChange={(event) => setDocumentId(event.target.value)}>
                {documents.map((item) => <option key={item.document_id} value={item.document_id}>{item.title}</option>)}
              </select>
            </Field>
          )}
          {scope === "library" && (
            <Field label="Biblioteca">
              <select className="select" value={libraryId} onChange={(event) => setLibraryId(event.target.value)}>
                {libraries.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
          )}
          <Field label="Conversa">
            <select className="select" value={conversationId} onChange={(event) => setConversationId(event.target.value)}>
              <option value="">Sem histórico</option>
              {conversations.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.scope}</option>)}
            </select>
          </Field>
          <Field label="Pergunta">
            <textarea className="field" rows={4} value={question} onChange={(event) => setQuestion(event.target.value)} />
          </Field>
          <div className="row">
            <Button disabled={busy || !question.trim()} onClick={() => void submitQuestion()}>{busy ? "Consultando…" : "Consultar"}</Button>
            <Button kind="secondary" onClick={() => void newConversation().catch((cause) => setError(isApiError(cause) ? cause.message : "Conversa não criada."))}>Nova conversa</Button>
          </div>
          {answer && (
            <div className="stack">
              <p style={{ whiteSpace: "pre-wrap" }}>{answer.answer.replace(/\s*\[[0-9a-f-]{36}\]/gi, "")}</p>
              <p>Modo: {answer.mode === "extractive" ? "extração dos trechos, sem modelo de linguagem" : answer.mode === "insufficient_evidence" ? "sem evidência suficiente" : answer.mode === "local_llm" ? "modelo local, com citações validadas" : answer.mode}</p>
              {answer.answer === REFUSAL && <Notice kind="warn">A biblioteca não continha evidência suficiente para esta pergunta.</Notice>}
              <h2>Fontes</h2>
              {answer.citations.map((citation) => (
                <p key={citation.chunk_id}>
                  <Link to={`/documents/${citation.document_id}?page=${citation.page}`}>{citation.document_title || "Documento"}</Link>
                  {" — página "}{citation.page || "—"}{" — "}{citation.section || citation.element_type}
                </p>
              ))}
              {!answer.citations.length && <p>Nenhuma fonte validada.</p>}
            </div>
          )}
        </section>
        <div className="stack">
          <section className="panel">
            <h2>Biblioteca</h2>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Documento</th><th>Segmentos</th><th></th></tr></thead>
                <tbody>
                  {documents.map((item) => (
                    <tr key={item.document_id}>
                      <td><Link to={`/documents/${item.document_id}`}>{item.title}</Link></td>
                      <td>{item.chunks}</td>
                      <td>
                        <Button kind="ghost" onClick={() => void reindex(item.document_id)}>Reindexar</Button>
                        <Button kind="ghost" onClick={() => void removeIndexed(item.document_id)}>Remover</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!documents.length && <div className="empty">Nenhum documento indexado. Processe um documento para alimentar a biblioteca.</div>}
            </div>
          </section>
          <section className="panel stack">
            <h2>Modelos</h2>
            <p>Download automático: {models?.runtime.silent_download ? "ligado" : "desligado"}. Embedding neural: {models?.runtime.neural_embedding ? "sim" : "não"}.</p>
            <p>Ollama nesta máquina: {models?.runtime.ollama.reachable ? models.runtime.ollama.models.join(", ") || "sem modelo" : "não encontrado"}.</p>
            {models?.catalog.map((item) => (
              <p key={item.name}><strong>{item.name}</strong> · {item.profile} · {item.license}. {item.note}</p>
            ))}
            {models?.installed.map((item) => (
              <p key={item.id}>{item.name} · {item.size_bytes} bytes · {item.license || "licença não informada"} · {item.active ? "ativo" : "inativo"}</p>
            ))}
            {!models?.installed.length && <div className="empty">Nenhum arquivo de modelo foi baixado.</div>}
          </section>
          <section className="panel stack">
            <h2>Relações</h2>
            <Field label="Biblioteca">
              <select className="select" value={libraryId} onChange={(event) => setLibraryId(event.target.value)}>
                {libraries.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
            <Button kind="secondary" disabled={!libraryId} onClick={() => void loadGraph(libraryId)}>Carregar relações</Button>
            {graphCount && <p>{graphCount.entities} entidades e {graphCount.relations} relações. Coocorrência é inferida, não um fato documentado.</p>}
          </section>
        </div>
      </div>
    </section>
  );
}
