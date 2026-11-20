import { useEffect, useState } from "react";
import { api, isApiError } from "../api";
import { Button, Field, Notice } from "../components/ui";

type Prefs = Record<string, unknown>;

export function SettingsScreen() {
  const [values, setValues] = useState<Prefs>({});
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profileName, setProfileName] = useState("Perfil de trabalho CPMH");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function load() {
    const payload = await api<{ values: Prefs; profiles: string[] }>("/preferences");
    setValues(payload.values);
    setProfiles(payload.profiles);
  }

  useEffect(() => {
    load().catch((cause) => setError(isApiError(cause) ? cause.message : "Preferências indisponíveis."));
  }, []);

  function update(key: string, value: unknown) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    setError("");
    try {
      const payload = await api<{ values: Prefs }>("/preferences", { method: "PUT", body: JSON.stringify({ values }) });
      setValues(payload.values);
      setInfo("Preferências gravadas neste computador.");
    } catch (cause) {
      setError(isApiError(cause) ? cause.message : "Não foi possível gravar.");
    }
  }

  async function saveProfile() {
    await api("/preferences/profiles", { method: "POST", body: JSON.stringify({ name: profileName }) });
    setInfo(`Perfil “${profileName}” salvo com os valores atuais.`);
    await load();
  }

  async function apply(name: string) {
    const payload = await api<{ values: Prefs }>(`/preferences/profiles/${encodeURIComponent(name)}/apply`, { method: "POST" });
    setValues(payload.values);
    setInfo(`Perfil “${name}” aplicado.`);
  }

  const languages = Array.isArray(values.ocr_languages) ? (values.ocr_languages as string[]) : [];

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Configurações</h1>
          <p>Limiares de confiança 85 e 60 são pontos de partida deste conjunto, não uma calibração universal.</p>
        </div>
        <Button onClick={() => void save()}>Salvar</Button>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {info && <Notice>{info}</Notice>}
      <div className="layout">
        <section className="panel stack">
          <h2>Trabalho</h2>
          <Field label="Idioma da interface">
            <select className="select" value={String(values.ui_language || "pt-BR")} onChange={(event) => update("ui_language", event.target.value)}>
              <option value="pt-BR">Português (Brasil)</option>
            </select>
          </Field>
          <Field label="Pasta padrão de exportação">
            <input className="field" value={String(values.default_output_dir || "")} onChange={(event) => update("default_output_dir", event.target.value)} />
          </Field>
          <div className="row">
            <Field label="Formato padrão">
              <select className="select" value={String(values.default_format || "docx")} onChange={(event) => update("default_format", event.target.value)}>
                <option value="docx">DOCX</option>
                <option value="pdf">PDF</option>
                <option value="txt">TXT</option>
                <option value="json">JSON</option>
                <option value="package">Pacote</option>
              </select>
            </Field>
            <Field label="Modo padrão">
              <select className="select" value={String(values.default_export_mode || "editable")} onChange={(event) => update("default_export_mode", event.target.value)}>
                <option value="editable">Editável</option>
                <option value="visual">Fidelidade visual</option>
                <option value="translated">Traduzido</option>
              </select>
            </Field>
          </div>
          <Field label="Idiomas do OCR">
            <div className="row">
              {["por", "eng", "chi_sim", "chi_tra"].map((code) => (
                <label key={code} className="check">
                  <input
                    type="checkbox"
                    checked={languages.includes(code)}
                    onChange={(event) => {
                      const next = new Set(languages);
                      if (event.target.checked) next.add(code);
                      else next.delete(code);
                      update("ocr_languages", [...next]);
                    }}
                  />
                  {code}
                </label>
              ))}
            </div>
          </Field>
          <div className="row">
            <Field label="Confiança alta"><input className="field" type="number" value={Number(values.confidence_high ?? 85)} onChange={(event) => update("confidence_high", Number(event.target.value))} /></Field>
            <Field label="Confiança intermediária"><input className="field" type="number" value={Number(values.confidence_medium ?? 60)} onChange={(event) => update("confidence_medium", Number(event.target.value))} /></Field>
          </div>
          <Field label="Modo de tradução padrão">
            <select className="select" value={String(values.translation_mode || "none")} onChange={(event) => update("translation_mode", event.target.value)}>
              <option value="none">Sem tradução</option>
              <option value="selected">Somente selecionados</option>
              <option value="full">Documento completo</option>
              <option value="side_by_side">Original e tradução</option>
              <option value="portuguese">Somente português</option>
            </select>
          </Field>
        </section>
        <section className="panel stack">
          <h2>Limites e privacidade</h2>
          <Field label="Tarefas simultâneas (1–4)"><input className="field" type="number" min={1} max={4} value={Number(values.max_concurrent_jobs ?? 1)} onChange={(event) => update("max_concurrent_jobs", Number(event.target.value))} /></Field>
          <Field label="Máximo de páginas"><input className="field" type="number" value={Number(values.max_pages ?? 50)} onChange={(event) => update("max_pages", Number(event.target.value))} /></Field>
          <Field label="Download máximo (MB)"><input className="field" type="number" value={Number(values.max_download_mb ?? 80)} onChange={(event) => update("max_download_mb", Number(event.target.value))} /></Field>
          <Field label="Timeout (s)"><input className="field" type="number" value={Number(values.timeout_seconds ?? 30)} onChange={(event) => update("timeout_seconds", Number(event.target.value))} /></Field>
          <Field label="Retenção do cache (dias)"><input className="field" type="number" value={Number(values.retention_days_cache ?? 14)} onChange={(event) => update("retention_days_cache", Number(event.target.value))} /></Field>
          <label className="check">
            <input type="checkbox" checked={Boolean(values.allow_local_network)} onChange={(event) => update("allow_local_network", event.target.checked)} />
            Permitir rede local. Metadados de nuvem continuam bloqueados.
          </label>
          <label className="check">
            <input type="checkbox" checked={Boolean(values.open_folder_after_export)} onChange={(event) => update("open_folder_after_export", event.target.checked)} />
            Abrir a pasta depois da exportação
          </label>
          <Field label="URL de tradução externa (opcional)">
            <input className="field" value={String(values.external_translation_url || "")} onChange={(event) => update("external_translation_url", event.target.value)} placeholder="vazio = não enviar" />
          </Field>
          <Notice>Nenhum documento é enviado automaticamente. A tradução externa pede consentimento em cada tarefa.</Notice>
          <h2>Perfil de trabalho CPMH</h2>
          <Field label="Nome do perfil"><input className="field" value={profileName} onChange={(event) => setProfileName(event.target.value)} /></Field>
          <div className="row">
            <Button kind="secondary" onClick={() => void saveProfile()}>Salvar perfil</Button>
            {profiles.map((item) => (
              <Button key={item} kind="ghost" onClick={() => void apply(item)}>{item}</Button>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
