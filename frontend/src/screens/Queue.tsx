import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isApiError } from "../api";
import { Button, Notice, Progress } from "../components/ui";
import { formatWhen, isActiveState, stateLabel } from "../labels";
import type { Job } from "../types";

export function QueueScreen() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");

  async function load() {
    setJobs(await api<Job[]>("/jobs"));
  }

  useEffect(() => {
    load().catch((cause) => setError(isApiError(cause) ? cause.message : "Fila indisponível."));
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  async function act(id: string, action: "pause" | "resume" | "cancel" | "retry") {
    await api(`/jobs/${id}/${action}`, { method: "POST" });
    await load();
  }

  async function move(index: number, direction: -1 | 1) {
    const next = jobs.slice();
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    const [item] = next.splice(index, 1);
    next.splice(target, 0, item);
    await api("/jobs/reorder", { method: "POST", body: JSON.stringify({ ids: next.map((job) => job.id) }) });
    await load();
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Fila de processamento</h1>
          <p>A fila fica no SQLite. Tarefas interrompidas voltam como pausadas na próxima abertura.</p>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th></th><th>Documento</th><th>Estado</th><th>Progresso</th><th>Tentativas</th><th>Início</th><th></th></tr>
            </thead>
            <tbody>
              {jobs.map((job, index) => (
                <tr key={job.id}>
                  <td className="row">
                    <Button kind="ghost" onClick={() => void move(index, -1)}>↑</Button>
                    <Button kind="ghost" onClick={() => void move(index, 1)}>↓</Button>
                  </td>
                  <td><Link to={`/documents/${job.document_id}`}>{job.document_id.slice(0, 8)}</Link><div className="mono">{job.error}</div></td>
                  <td>{stateLabel(job.state)} <span className="badge">{stateLabel(job.stage)}</span></td>
                  <td><Progress value={job.progress} /></td>
                  <td>{job.attempts}</td>
                  <td>{formatWhen(job.started_at || job.created_at)}</td>
                  <td className="row">
                    {isActiveState(job.state) && job.state !== "paused" && <Button kind="secondary" onClick={() => void act(job.id, "pause")}>Pausar</Button>}
                    {job.state === "paused" && <Button onClick={() => void act(job.id, "resume")}>Retomar</Button>}
                    {job.state !== "cancelled" && job.state !== "completed" && <Button kind="danger" onClick={() => void act(job.id, "cancel")}>Cancelar</Button>}
                    {(job.state === "failed" || job.state === "cancelled") && <Button kind="secondary" onClick={() => void act(job.id, "retry")}>Reprocessar</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!jobs.length && <div className="empty">A fila está vazia.</div>}
        </div>
      </section>
    </section>
  );
}
