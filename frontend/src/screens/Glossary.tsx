import { useEffect, useState } from "react";
import { api, isApiError } from "../api";
import { Button, Field, Notice } from "../components/ui";
import type { Glossary, Term } from "../types";

export function GlossaryScreen() {
  const [items, setItems] = useState<Glossary[]>([]);
  const [current, setCurrent] = useState("");
  const [terms, setTerms] = useState<Term[]>([]);
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [context, setContext] = useState("");
  const [keep, setKeep] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function loadGlossaries(selectId = current) {
    const rows = await api<Glossary[]>("/glossaries");
    setItems(rows);
    const id = selectId || rows[0]?.id || "";
    setCurrent(id);
    if (id) setTerms(await api<Term[]>(`/glossaries/${id}/terms`));
  }

  useEffect(() => {
    loadGlossaries().catch((cause) => setError(isApiError(cause) ? cause.message : "Glossário indisponível."));
  }, []);

  async function createGlossary() {
    const created = await api<Glossary>("/glossaries", { method: "POST", body: JSON.stringify({ name }) });
    setName("");
    await loadGlossaries(created.id);
  }

  async function addTerm() {
    if (!current) return;
    await api(`/glossaries/${current}/terms`, {
      method: "POST",
      body: JSON.stringify({ source, target, context, do_not_translate: keep }),
    });
    setSource("");
    setTarget("");
    setContext("");
    setKeep(false);
    setTerms(await api<Term[]>(`/glossaries/${current}/terms`));
  }

  async function importCsv(file: File) {
    if (!current) return;
    const body = new FormData();
    body.append("file", file);
    const result = await api<{ imported: number }>(`/glossaries/${current}/import`, { method: "POST", body });
    setInfo(`${result.imported} termos importados.`);
    setTerms(await api<Term[]>(`/glossaries/${current}/terms`));
  }

  async function exportCsv() {
    if (!current) return;
    const csv = await api<string>(`/glossaries/${current}/export`);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "glossario.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Glossário técnico</h1>
          <p>Termos preferenciais e expressões que não devem ser traduzidas. O glossário inicial é uma amostra editável, não um dicionário médico.</p>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {info && <Notice>{info}</Notice>}
      <div className="layout">
        <section className="panel">
          <div className="row" style={{ marginBottom: 10 }}>
            <select className="select grow" value={current} onChange={(event) => {
              setCurrent(event.target.value);
              api<Term[]>(`/glossaries/${event.target.value}/terms`).then(setTerms).catch(() => setTerms([]));
            }}>
              {items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            <Button kind="secondary" onClick={() => void exportCsv()}>Exportar CSV</Button>
            <label className="btn secondary">
              Importar CSV
              <input hidden type="file" accept=".csv,text/csv" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importCsv(file).catch((cause) => setError(isApiError(cause) ? cause.message : "CSV recusado."));
              }} />
            </label>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Origem</th><th>Tradução</th><th>Contexto</th><th>Não traduzir</th><th></th></tr></thead>
              <tbody>
                {terms.map((term) => (
                  <tr key={term.id}>
                    <td>{term.source}</td>
                    <td>{term.target || "—"}</td>
                    <td>{term.context || "—"}</td>
                    <td>{term.do_not_translate ? "sim" : "não"}</td>
                    <td><Button kind="ghost" onClick={() => api(`/terms/${term.id}`, { method: "DELETE" }).then(() => loadGlossaries(current))}>Remover</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!terms.length && <div className="empty">Nenhum termo neste glossário.</div>}
          </div>
        </section>
        <div className="stack">
          <form className="panel stack" onSubmit={(event) => { event.preventDefault(); void createGlossary(); }}>
            <h2>Novo glossário</h2>
            <Field label="Nome"><input className="field" value={name} onChange={(event) => setName(event.target.value)} required /></Field>
            <Button type="submit" kind="secondary">Criar</Button>
          </form>
          <form className="panel stack" onSubmit={(event) => { event.preventDefault(); void addTerm(); }}>
            <h2>Novo termo</h2>
            <Field label="Termo"><input className="field" value={source} onChange={(event) => setSource(event.target.value)} required /></Field>
            <Field label="Tradução preferencial"><input className="field" value={target} onChange={(event) => setTarget(event.target.value)} /></Field>
            <Field label="Contexto"><input className="field" value={context} onChange={(event) => setContext(event.target.value)} /></Field>
            <label className="check"><input type="checkbox" checked={keep} onChange={(event) => setKeep(event.target.checked)} /> Não traduzir</label>
            <Button type="submit">Cadastrar</Button>
          </form>
        </div>
      </div>
    </section>
  );
}
