import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { configureApi } from "./api";
import { Shell } from "./components/Shell";
import { Notice } from "./components/ui";
import { AboutScreen } from "./screens/About";
import { DiagnosticsScreen } from "./screens/Diagnostics";
import { DocumentScreen } from "./screens/Document";
import { GlossaryScreen } from "./screens/Glossary";
import { HomeScreen } from "./screens/Home";
import { KnowledgeScreen } from "./screens/Knowledge";
import { ProjectScreen } from "./screens/Project";
import { ProjectsScreen } from "./screens/Projects";
import { QueueScreen } from "./screens/Queue";
import { SettingsScreen } from "./screens/Settings";

export function App() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (window.cpmh) {
          configureApi(await window.cpmh.getSession());
        } else {
          configureApi({
            apiBase: import.meta.env.VITE_CPMH_API || "http://127.0.0.1:8765",
            token: import.meta.env.VITE_CPMH_TOKEN || "",
          });
        }
        if (!cancelled) setReady(true);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Falha ao obter a sessão local.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="content">
        <Notice kind="error">{error}</Notice>
      </div>
    );
  }
  if (!ready) {
    return <div className="content">Conectando ao backend local…</div>;
  }
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<HomeScreen />} />
        <Route path="projects" element={<ProjectsScreen />} />
        <Route path="projects/:projectId" element={<ProjectScreen />} />
        <Route path="documents/:documentId" element={<DocumentScreen />} />
        <Route path="queue" element={<QueueScreen />} />
        <Route path="glossary" element={<GlossaryScreen />} />
        <Route path="knowledge" element={<KnowledgeScreen />} />
        <Route path="settings" element={<SettingsScreen />} />
        <Route path="diagnostics" element={<DiagnosticsScreen />} />
        <Route path="about" element={<AboutScreen />} />
      </Route>
    </Routes>
  );
}
