import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isApiError } from "../api";
import { Button, Field, Notice } from "../components/ui";
import { formatWhen, stateLabel } from "../labels";
import type { Project } from "../types";

export function ProjectsScreen() {
  const [items, setItems] = useState<Project[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  async function load(nextQuery = query, nextStatus = status) {
    const params = new URLSearchParams();
    if (nextQuery) params.set("q", nextQuery);
    if (nextStatus) params.set("status", nextStatus);
    setItems(await api<Project[]>(`/projects?${params.toString()}`));
  }

  useEffect(() => {
    load().catch((cause) => setError(isApiError(cause) ? cause.message : "Falha ao listar projetos."));
  }, []);

  async function createProject() {
    setError("");
    try {
      await api("/projects", { method: "POST", body: JSON.stringify({ name, description }) });
      setName("");
      setDescription("");
      await load();
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Não foi possível criar o projeto.");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Projetos</h1>
          <p>Cada projeto agrupa documentos, glossário e exportações.</p>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      <div className="layout">
        <section className="panel">
          <div className="row" style={{ marginBottom: 10 }}>
            <input className="field grow" value={query} placeholder="Pesquisar" onChange={(event) => setQuery(event.target.value)} />
            <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">Todos</option>
              <option value="active">Ativos</option>
              <option value="archived">Arquivados</option>
            </select>
            <Button kind="secondary" onClick={() => load().catch((cause) => setError(isApiError(cause) ? cause.message : "Falha na pesquisa."))}>Filtrar</Button>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Nome</th><th>Documentos</th><th>Estado</th><th>Atualização</th></tr></thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td><Link to={`/projects/${item.id}`}>{item.name}</Link><div className="mono">{item.description}</div></td>
                    <td>{item.document_count}</td>
                    <td>{stateLabel(item.status)}</td>
                    <td>{formatWhen(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!items.length && <div className="empty">Nenhum projeto encontrado.</div>}
          </div>
        </section>
        <form className="panel stack" onSubmit={(event) => { event.preventDefault(); void createProject(); }}>
          <h2>Novo projeto</h2>
          <Field label="Nome"><input className="field" value={name} onChange={(event) => setName(event.target.value)} required /></Field>
          <Field label="Descrição"><textarea className="area" value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
          <Button type="submit">Criar projeto</Button>
        </form>
      </div>
    </section>
  );
}
