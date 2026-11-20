import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiBlob, hasDesktopBridge, isApiError, type ApiError } from "../api";
import { Button, Field, Modal, Notice, Progress } from "../components/ui";
import { CATEGORIES, categoryLabel, formatWhen, isActiveState, stateLabel } from "../labels";
import type { DocumentItem, ElementItem, FormulaItem, ImageItem, Job, PageItem, Region, TableItem } from "../types";

type Tab = "process" | "review" | "structure" | "export" | "browser";

export function DocumentScreen() {
  const { documentId = "" } = useParams();
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [tab, setTab] = useState<Tab>("process");
  const [error, setError] = useState("");
  const [translateMode, setTranslateMode] = useState("none");
  const [consent, setConsent] = useState(false);
  const [disclosure, setDisclosure] = useState("");

  async function load() {
    const [current, allJobs] = await Promise.all([api<DocumentItem>(`/documents/${documentId}`), api<Job[]>("/jobs")]);
    setDoc(current);
    setJobs(allJobs.filter((job) => job.document_id === documentId));
  }

  useEffect(() => {
    load().catch((cause) => setError(isApiError(cause) ? cause.message : "Documento indisponível."));
  }, [documentId]);

  useEffect(() => {
    if (!doc || !isActiveState(doc.state)) return;
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [doc?.state, documentId]);

  const latest = [...jobs].sort((left, right) => (right.created_at || "").localeCompare(left.created_at || ""))[0];

  async function startJob(force = false) {
    setError("");
    try {
      await api(`/documents/${documentId}/jobs`, {
        method: "POST",
        body: JSON.stringify({
          translate_mode: translateMode,
          external_translation: translateMode !== "none" && consent,
          external_consent: consent,
          force_recapture: force,
          export_formats: [],
        }),
      });
      await load();
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Não foi possível enfileirar.");
    }
  }

  async function showDisclosure() {
    const payload = await api<{ purpose: string; data: string; service: string; cost: string; consent: string }>("/translation/disclosure");
    setDisclosure(`${payload.purpose} ${payload.data} ${payload.service} ${payload.cost} ${payload.consent}`);
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>{doc?.title || "Documento"}</h1>
          <p>
            {doc ? (
              <>
                {stateLabel(doc.state)} · {doc.language || "idioma não detectado"} · {doc.page_count || 0} páginas
                {doc.project_id && <> · <Link to={`/projects/${doc.project_id}`}>projeto</Link></>}
              </>
            ) : "Carregando"}
          </p>
        </div>
        {doc && <Progress value={doc.progress} />}
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {doc?.error_message && <Notice kind="error">{doc.error_message}</Notice>}
      {doc?.capture_status === "inconclusive" && (
        <Notice kind="warn">A captura não tem evidência suficiente de que o documento terminou. Revise as páginas antes de tratar o resultado como completo.</Notice>
      )}
      <div className="tabs">
        {([
          ["process", "Processamento"],
          ["review", "Revisão"],
          ["structure", "Estrutura"],
          ["export", "Exportação"],
          ["browser", "Navegador"],
        ] as [Tab, string][]).map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {tab === "process" && doc && (
        <section className="panel stack">
          <div className="kv">
            <span>Origem</span><strong className="mono">{doc.url || doc.origin}</strong>
            <span>Domínio</span><strong>{doc.domain || "—"}</strong>
            <span>Tipo</span><strong>{doc.source_kind || "desconhecido"}</strong>
            <span>Inclusão</span><strong>{formatWhen(doc.added_at)} (Brasília)</strong>
            <span>Conclusão</span><strong>{formatWhen(doc.completed_at)}</strong>
            <span>Exportado</span><strong>{doc.exported_formats.join(", ") || "ainda não"}</strong>
          </div>
          <Field label="Tradução nesta tarefa">
            <select className="select" value={translateMode} onChange={(event) => setTranslateMode(event.target.value)}>
              <option value="none">Sem tradução</option>
              <option value="full">Documento completo</option>
              <option value="side_by_side">Original e tradução</option>
              <option value="portuguese">Somente português</option>
            </select>
          </Field>
          {translateMode !== "none" && (
            <div className="stack">
              <Button kind="secondary" onClick={() => void showDisclosure()}>Ver o que seria enviado a um serviço externo</Button>
              {disclosure && <Notice>{disclosure}</Notice>}
              <label className="check">
                <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
                Autorizo o envio do texto ao endereço configurado, se houver. Sem URL configurada, só o glossário local é usado.
              </label>
            </div>
          )}
          <div className="row">
            <Button onClick={() => void startJob(false)}>Processar</Button>
            <Button kind="secondary" onClick={() => void startJob(true)}>Recapturar</Button>
            {latest && isActiveState(latest.state) && latest.state !== "paused" && (
              <Button kind="secondary" onClick={() => api(`/jobs/${latest.id}/pause`, { method: "POST" }).then(load)}>Pausar</Button>
            )}
            {latest?.state === "paused" && <Button onClick={() => api(`/jobs/${latest.id}/resume`, { method: "POST" }).then(load)}>Retomar</Button>}
            {latest && latest.state !== "completed" && latest.state !== "cancelled" && (
              <Button kind="danger" onClick={() => api(`/jobs/${latest.id}/cancel`, { method: "POST" }).then(load)}>Cancelar</Button>
            )}
          </div>
          {latest && (
            <div>
              <h2>Etapa atual: {stateLabel(latest.stage)}</h2>
              <Progress value={latest.progress} />
              <p>{latest.attempts} tentativas. Início {formatWhen(latest.started_at)}. Fim {formatWhen(latest.finished_at)}.</p>
              {!latest.started_at && <p>Ainda não há tempo decorrido. A estimativa só aparece quando houver páginas já medidas.</p>}
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Quando</th><th>Etapa</th><th>Estado</th><th>Mensagem</th></tr></thead>
                  <tbody>
                    {latest.steps.map((step, index) => (
                      <tr key={`${step.created_at}-${index}`}>
                        <td>{formatWhen(step.created_at)}</td>
                        <td>{stateLabel(step.name)}</td>
                        <td>{stateLabel(step.state)}</td>
                        <td>{step.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}
      {tab === "review" && <ReviewPane documentId={documentId} />}
      {tab === "structure" && <StructurePane documentId={documentId} />}
      {tab === "export" && doc && <ExportPane document={doc} onDone={load} />}
      {tab === "browser" && <BrowserPane initialUrl={doc?.url || ""} />}
    </section>
  );
}

function ReviewPane({ documentId }: { documentId: string }) {
  const [pages, setPages] = useState<PageItem[]>([]);
  const [pageId, setPageId] = useState("");
  const [regions, setRegions] = useState<Region[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [imageUrl, setImageUrl] = useState("");
  const [draft, setDraft] = useState<Region | null>(null);
  const [mode, setMode] = useState<"select" | "draw">("select");
  const [error, setError] = useState("");
  const [thresholds, setThresholds] = useState({ high: 85, medium: 60 });
  const drawing = useRef<{ x: number; y: number } | null>(null);
  const liveBox = useRef<[number, number, number, number] | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  async function loadPages() {
    const rows = await api<PageItem[]>(`/documents/${documentId}/pages`);
    setPages(rows);
    setPageId((current) => current || rows[0]?.id || "");
  }

  useEffect(() => {
    loadPages().catch((cause) => setError(isApiError(cause) ? cause.message : "Páginas indisponíveis."));
    api<{ values: { confidence_high: number; confidence_medium: number } }>("/preferences")
      .then((payload) => setThresholds({ high: Number(payload.values.confidence_high), medium: Number(payload.values.confidence_medium) }))
      .catch(() => undefined);
  }, [documentId]);

  useEffect(() => {
    if (!pageId) return;
    let cancelled = false;
    let url = "";
    api<Region[]>(`/pages/${pageId}/regions`).then((rows) => {
      if (!cancelled) {
        setRegions(rows);
        setSelected(rows[0]?.id || "");
      }
    }).catch((cause) => setError(isApiError(cause) ? cause.message : "Regiões indisponíveis."));
    apiBlob(`/pages/${pageId}/image`).then((blob) => {
      url = URL.createObjectURL(blob);
      if (!cancelled) setImageUrl(url);
    }).catch((cause) => setError(isApiError(cause) ? cause.message : "Imagem indisponível."));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [pageId]);

  const current = regions.find((item) => item.id === selected) || null;
  useEffect(() => setDraft(current), [current?.id, current?.text, current?.category, current?.review_state]);

  function point(event: React.PointerEvent): { x: number; y: number } | null {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    };
  }

  async function commitBox(box: [number, number, number, number], id?: string) {
    if (id) {
      const updated = await api<Region>(`/regions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ x: box[0], y: box[1], w: box[2], h: box[3] }),
      });
      setRegions((rows) => rows.map((item) => (item.id === id ? updated : item)));
      return;
    }
    const created = await api<Region>(`/pages/${pageId}/regions`, {
      method: "POST",
      body: JSON.stringify({ category: "unknown", text: "", x: box[0], y: box[1], w: box[2], h: box[3] }),
    });
    setRegions((rows) => [...rows, created]);
    setSelected(created.id);
    setMode("select");
  }

  function onPointerDown(event: React.PointerEvent) {
    if (mode !== "draw") return;
    drawing.current = point(event);
  }

  function onPointerUp(event: React.PointerEvent) {
    if (mode !== "draw" || !drawing.current) return;
    const end = point(event);
    const start = drawing.current;
    drawing.current = null;
    if (!end) return;
    const x = Math.min(start.x, end.x);
    const y = Math.min(start.y, end.y);
    const w = Math.abs(end.x - start.x);
    const h = Math.abs(end.y - start.y);
    if (w < 0.01 || h < 0.01) return;
    void commitBox([x, y, w, h]).catch((cause) => setError(isApiError(cause) ? cause.message : "Não foi possível criar a região."));
  }

  function moveRegion(event: React.PointerEvent, region: Region, handle: "move" | "se") {
    event.stopPropagation();
    const start = point(event);
    if (!start) return;
    const origin = [...region.bbox] as [number, number, number, number];
    liveBox.current = origin;
    const move = (ev: PointerEvent) => {
      const rect = stageRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = (ev.clientX - rect.left) / rect.width;
      const y = (ev.clientY - rect.top) / rect.height;
      const dx = x - start.x;
      const dy = y - start.y;
      const next: [number, number, number, number] = handle === "move"
        ? [origin[0] + dx, origin[1] + dy, origin[2], origin[3]]
        : [origin[0], origin[1], Math.max(0.01, origin[2] + dx), Math.max(0.01, origin[3] + dy)];
      liveBox.current = next;
      setRegions((rows) => rows.map((item) => (item.id === region.id ? { ...item, bbox: next } : item)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const box = liveBox.current;
      if (box) {
        void commitBox(box, region.id).catch((cause) => setError(isApiError(cause) ? cause.message : "Não foi possível ajustar a região."));
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  async function saveText() {
    if (!draft) return;
    const updated = await api<Region>(`/regions/${draft.id}`, {
      method: "PATCH",
      body: JSON.stringify({ text: draft.text, category: draft.category, review_state: "reviewed" }),
    });
    setRegions((rows) => rows.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function restore(id: string) {
    const updated = await api<Region>(`/regions/${id}/restore`, { method: "POST" });
    setRegions((rows) => rows.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function reprocess(id: string) {
    try {
      const updated = await api<Region>(`/regions/${id}/reprocess`, { method: "POST" });
      setRegions((rows) => rows.map((item) => (item.id === updated.id ? updated : item)));
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "OCR da região falhou.");
    }
  }

  const band = (score: number) => (score >= thresholds.high ? "alta" : score >= thresholds.medium ? "intermediária" : "baixa");

  return (
    <div className="stack">
      {error && <Notice kind="error">{error}</Notice>}
      <div className="row">
        <Field label="Página">
          <select className="select" value={pageId} onChange={(event) => setPageId(event.target.value)}>
            {pages.map((page) => (
              <option key={page.id} value={page.id}>
                {page.sequence}{page.reported_number ? ` (nº ${page.reported_number})` : ""} · {page.width}×{page.height} · {page.state}
              </option>
            ))}
          </select>
        </Field>
        <Button kind={mode === "draw" ? "primary" : "secondary"} onClick={() => setMode(mode === "draw" ? "select" : "draw")}>
          {mode === "draw" ? "Desenhar região" : "Adicionar região"}
        </Button>
      </div>
      {!pages.length && <div className="empty">Este documento ainda não tem páginas capturadas.</div>}
      <div className="legend">
        {CATEGORIES.slice(0, 8).map((item) => (
          <span key={item.id}><i className={`swatch cat-${item.id}`} />{item.label}</span>
        ))}
      </div>
      <div className="split">
        <div className="stage" ref={stageRef} onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
          {imageUrl && <img src={imageUrl} alt={`Página ${pages.find((page) => page.id === pageId)?.sequence || ""}`} />}
          <svg className="overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
            {regions.map((region) => (
              <g key={region.id}>
                <rect
                  className={`region cat-${region.category} ${region.id === selected ? "selected" : ""}`}
                  x={region.bbox[0]}
                  y={region.bbox[1]}
                  width={region.bbox[2]}
                  height={region.bbox[3]}
                  onPointerDown={(event) => {
                    if (mode === "draw") return;
                    event.stopPropagation();
                    setSelected(region.id);
                    moveRegion(event, region, "move");
                  }}
                />
                {region.id === selected && (
                  <rect
                    className="handle"
                    x={region.bbox[0] + region.bbox[2] - 0.012}
                    y={region.bbox[1] + region.bbox[3] - 0.012}
                    width={0.018}
                    height={0.018}
                    onPointerDown={(event) => moveRegion(event, region, "se")}
                  />
                )}
              </g>
            ))}
          </svg>
        </div>
        <aside className="panel stack">
          <h2>Inspeção</h2>
          {draft ? (
            <>
              <div className="kv">
                <span>Confiança</span><strong>{draft.confidence.toFixed(1)} · {band(draft.confidence)}</strong>
                <span>Idioma</span><strong>{draft.language || "—"}</strong>
                <span>Revisão</span><strong>{draft.review_state}</strong>
                <span>Origem</span><strong>{draft.source}</strong>
                <span>Caixa</span><strong className="mono">{draft.bbox.map((value) => value.toFixed(3)).join(", ")}</strong>
              </div>
              <Field label="Classificação">
                <select className="select" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>
                  {CATEGORIES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
              </Field>
              <Field label="Texto"><textarea className="area" value={draft.text} onChange={(event) => setDraft({ ...draft, text: event.target.value })} /></Field>
              <div className="row">
                <Button onClick={() => void saveText()}>Marcar revisada</Button>
                <Button kind="secondary" onClick={() => void restore(draft.id)}>Restaurar</Button>
                <Button kind="secondary" onClick={() => void reprocess(draft.id)}>Reprocessar</Button>
                <Button kind="danger" onClick={() => api(`/regions/${draft.id}`, { method: "DELETE" }).then(() => {
                  setRegions((rows) => rows.filter((item) => item.id !== draft.id));
                  setSelected("");
                })}>Excluir</Button>
              </div>
            </>
          ) : <div className="empty">Selecione uma região.</div>}
          <div className="table-wrap">
            <table>
              <tbody>
                {regions.map((region) => (
                  <tr key={region.id} className="clickable" onClick={() => setSelected(region.id)}>
                    <td>{categoryLabel(region.category)}</td>
                    <td>{region.confidence.toFixed(0)}</td>
                    <td>{region.text.slice(0, 48)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
    </div>
  );
}

function StructurePane({ documentId }: { documentId: string }) {
  const [elements, setElements] = useState<ElementItem[]>([]);
  const [tables, setTables] = useState<TableItem[]>([]);
  const [formulas, setFormulas] = useState<FormulaItem[]>([]);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<ElementItem[]>(`/documents/${documentId}/elements`),
      api<TableItem[]>(`/documents/${documentId}/tables`),
      api<FormulaItem[]>(`/documents/${documentId}/formulas`),
      api<ImageItem[]>(`/documents/${documentId}/images`),
    ]).then(([nextElements, nextTables, nextFormulas, nextImages]) => {
      setElements(nextElements);
      setTables(nextTables);
      setFormulas(nextFormulas);
      setImages(nextImages);
    }).catch((cause) => setError(isApiError(cause) ? cause.message : "Estrutura indisponível."));
  }, [documentId]);

  return (
    <div className="stack">
      {error && <Notice kind="error">{error}</Notice>}
      <section className="panel">
        <h2>Ordem de leitura</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Tipo</th><th>Confiança</th><th>Texto</th><th>Continuidade</th></tr></thead>
            <tbody>
              {elements.map((item) => (
                <tr key={item.id}>
                  <td>{item.order + 1}</td>
                  <td>{categoryLabel(item.kind)}</td>
                  <td>{item.confidence.toFixed(0)}</td>
                  <td>{item.text}</td>
                  <td>{item.continued_from ? "continua da página anterior" : item.continued_in ? "continua na página seguinte" : item.skip_export ? "unido ao anterior" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!elements.length && <div className="empty">Sem elementos estruturados.</div>}
        </div>
      </section>
      <section className="panel">
        <h2>Tabelas</h2>
        {tables.map((table) => (
          <div key={table.id} className="stack" style={{ marginBottom: 12 }}>
            <div className="row">
              <span className={`badge ${table.reliable ? "ok" : "warn"}`}>{table.reliable ? "confiável" : "revisão necessária"}</span>
              <span>página {table.page_sequence} · confiança {table.confidence.toFixed(0)}</span>
              <Button kind="secondary" onClick={() => api(`/tables/${table.id}/review`, { method: "POST" }).then(() => {
                setTables((rows) => rows.map((item) => item.id === table.id ? { ...item, review_state: "reviewed", reliable: item.rows.length > 0 } : item));
              })}>Marcar revisada</Button>
            </div>
            {table.notes && <p>{table.notes}</p>}
            {table.rows.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <tbody>
                    {table.rows.map((row, index) => (
                      <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Notice kind="warn">A grade não foi reconstruída. A imagem da tabela é preservada na exportação. Nenhuma célula foi inventada.</Notice>}
          </div>
        ))}
        {!tables.length && <div className="empty">Nenhuma tabela identificada.</div>}
      </section>
      <section className="panel">
        <h2>Fórmulas e imagens</h2>
        {formulas.map((item) => (
          <p key={item.id}>{item.reliable ? item.text : `Preservada para revisão: ${item.notes || item.text}`}</p>
        ))}
        {images.map((item) => (
          <p key={item.id}>{item.name} · {categoryLabel(item.category)} · {item.width}×{item.height} · confiança {item.confidence.toFixed(0)}{item.caption ? ` · ${item.caption}` : ""}</p>
        ))}
        {!formulas.length && !images.length && <div className="empty">Nenhuma fórmula ou imagem extraída.</div>}
      </section>
    </div>
  );
}

function ExportPane({ document, onDone }: { document: DocumentItem; onDone: () => Promise<void> }) {
  const [formats, setFormats] = useState<string[]>(["docx"]);
  const [mode, setMode] = useState("editable");
  const [translateMode, setTranslateMode] = useState("none");
  const [name, setName] = useState(document.title.replace(/\s+/g, "_") || "documento");
  const [directory, setDirectory] = useState("");
  const [error, setError] = useState("");
  const [files, setFiles] = useState<{ name: string; path: string; format: string; size: number }[]>([]);
  const [collision, setCollision] = useState<ApiError | null>(null);

  useEffect(() => {
    api<{ values: { default_output_dir?: string; default_export_mode?: string; default_format?: string } }>("/preferences").then((payload) => {
      if (payload.values.default_output_dir) setDirectory(payload.values.default_output_dir);
      if (payload.values.default_export_mode) setMode(payload.values.default_export_mode);
      if (payload.values.default_format) setFormats([payload.values.default_format]);
    }).catch(() => undefined);
    api<typeof files>(`/documents/${document.id}/exports`).then(setFiles).catch(() => undefined);
  }, [document.id]);

  const summary = useMemo(() => `${formats.join(" + ") || "nenhum"} · ${mode} · ${translateMode}`, [formats, mode, translateMode]);

  function toggle(format: string) {
    setFormats((current) => current.includes(format) ? current.filter((item) => item !== format) : [...current, format]);
  }

  async function chooseDir() {
    if (!window.cpmh) return;
    const picked = await window.cpmh.pickDirectory();
    if (picked) setDirectory(picked);
  }

  async function exportNow(choice: string | null) {
    setError("");
    try {
      const produced = await api<typeof files>(`/documents/${document.id}/export`, {
        method: "POST",
        body: JSON.stringify({
          formats,
          mode,
          output_name: name,
          output_dir: directory,
          collision: choice,
          translate_mode: translateMode,
        }),
      });
      setFiles(produced);
      setCollision(null);
      const prefs = await api<{ values: { open_folder_after_export?: boolean } }>("/preferences");
      if (prefs.values.open_folder_after_export && window.cpmh && produced[0]) {
        await window.cpmh.openPath(directory);
      }
      await onDone();
    } catch (cause) {
      if (isApiError(cause) && cause.code === "name_collision") {
        setCollision(cause);
        return;
      }
      setError(isApiError(cause) ? cause.message : "Exportação falhou.");
    }
  }

  return (
    <section className="panel stack">
      {error && <Notice kind="error">{error}</Notice>}
      <div className="row">
        {["docx", "pdf", "txt", "json", "package"].map((format) => (
          <label key={format} className="check">
            <input type="checkbox" checked={formats.includes(format)} onChange={() => toggle(format)} /> {format.toUpperCase()}
          </label>
        ))}
      </div>
      <div className="row">
        <Field label="Modo">
          <select className="select" value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="visual">A — Fidelidade visual</option>
            <option value="editable">B — Documento editável</option>
            <option value="translated">C — Documento traduzido</option>
          </select>
        </Field>
        <Field label="Tradução já armazenada">
          <select className="select" value={translateMode} onChange={(event) => setTranslateMode(event.target.value)}>
            <option value="none">Sem tradução</option>
            <option value="side_by_side">Lado a lado</option>
            <option value="portuguese">Somente português</option>
          </select>
        </Field>
      </div>
      <Field label="Nome do arquivo"><input className="field" value={name} onChange={(event) => setName(event.target.value)} /></Field>
      <div className="row">
        <input className="field grow" value={directory} placeholder="Pasta de destino" onChange={(event) => setDirectory(event.target.value)} />
        {hasDesktopBridge() && <Button kind="secondary" onClick={() => void chooseDir()}>Escolher pasta</Button>}
      </div>
      {!hasDesktopBridge() && <p className="lede">No aplicativo desktop, a pasta é escolhida pelo seletor do sistema. Aqui informe o caminho absoluto.</p>}
      <p>Revisão: {summary}. A exportação reutiliza OCR e capturas já gravados.</p>
      <Button onClick={() => void exportNow(null)}>Exportar</Button>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Arquivo</th><th>Formato</th><th>Caminho</th></tr></thead>
          <tbody>
            {files.map((file) => (
              <tr key={file.path}>
                <td>{file.name}</td>
                <td>{file.format}</td>
                <td className="mono">{file.path}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {collision && (
        <Modal title="O arquivo já existe" onClose={() => setCollision(null)}>
          <p>{collision.message}</p>
          <p className="mono">{collision.path}</p>
          <div className="row">
            <Button kind="danger" onClick={() => void exportNow("replace")}>Substituir</Button>
            <Button onClick={() => void exportNow("version")}>Nova versão</Button>
            <Button kind="secondary" onClick={() => void exportNow("rename")}>Renomear</Button>
            <Button kind="ghost" onClick={() => setCollision(null)}>Cancelar</Button>
          </div>
        </Modal>
      )}
    </section>
  );
}

function BrowserPane({ initialUrl }: { initialUrl: string }) {
  const slot = useRef<HTMLDivElement>(null);
  const [url, setUrl] = useState(initialUrl);
  const [zoom, setZoom] = useState(1);
  const [message, setMessage] = useState("");
  const [checked, setChecked] = useState("");

  useEffect(() => setUrl(initialUrl), [initialUrl]);

  useEffect(() => {
    if (!window.cpmh) return;
    const publish = () => {
      const rect = slot.current?.getBoundingClientRect();
      if (!rect) return;
      void window.cpmh?.browserAttach({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });
    };
    publish();
    window.addEventListener("resize", publish);
    window.addEventListener("scroll", publish, true);
    return () => {
      window.removeEventListener("resize", publish);
      window.removeEventListener("scroll", publish, true);
      void window.cpmh?.browserAttach(null);
    };
  }, []);

  async function validate() {
    setMessage("");
    try {
      const result = await api<{ url: string; host: string }>("/security/validate-url", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      setChecked(`${result.host} aceito`);
      if (window.cpmh) {
        const state = await window.cpmh.browserNavigate(result.url);
        setMessage(state.title || result.url);
      }
    } catch (cause) {
      setChecked("");
      setMessage(isApiError(cause) ? cause.message : "URL recusada.");
    }
  }

  return (
    <section className="panel stack">
      <p>A vista mostra o endereço autorizado. A captura sequencial, o fim do documento e o registro das páginas acontecem no processamento, com Playwright. Esta vista não desativa proteção de conteúdo.</p>
      <div className="row">
        <Button kind="secondary" onClick={() => void window.cpmh?.browserBack()} disabled={!window.cpmh}>Voltar</Button>
        <Button kind="secondary" onClick={() => void window.cpmh?.browserForward()} disabled={!window.cpmh}>Avançar</Button>
        <Button kind="secondary" onClick={() => void window.cpmh?.browserReload()} disabled={!window.cpmh}>Atualizar</Button>
        <input className="field grow mono" value={url} onChange={(event) => setUrl(event.target.value)} />
        <Button onClick={() => void validate()}>Abrir</Button>
      </div>
      <div className="row">
        <Field label="Zoom">
          <input className="field" type="range" min={0.5} max={2} step={0.1} value={zoom} onChange={(event) => {
            const next = Number(event.target.value);
            setZoom(next);
            void window.cpmh?.browserZoom(next);
          }} />
        </Field>
        <span>{Math.round(zoom * 100)}%</span>
        {checked && <span className="badge ok">{checked}</span>}
      </div>
      {message && <Notice>{message}</Notice>}
      {!window.cpmh && <Notice kind="warn">O Chromium embutido aparece na janela do aplicativo. Nesta página do navegador, a validação do endereço continua ativa, mas a vista não é desenhada por cima.</Notice>}
      <div className="browser-slot" ref={slot} />
    </section>
  );
}
