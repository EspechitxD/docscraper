import { NavLink, Outlet } from "react-router-dom";

const LINKS = [
  ["/", "Início"],
  ["/projects", "Projetos"],
  ["/queue", "Fila"],
  ["/glossary", "Glossário"],
  ["/settings", "Configurações"],
  ["/diagnostics", "Diagnóstico"],
  ["/about", "Sobre"],
];

export function Shell() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img src="/branding/cpmh-mark-192.png" alt="" />
          <div>
            <strong>CPMH</strong>
            <span>Document Intelligence</span>
          </div>
        </div>
        <nav className="nav">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">Processamento local. Captura somente de conteúdo autorizado.</div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="top-brand">
            <img src="/branding/cpmh-mark-192.png" alt="" />
            <strong>CPMH Digital</strong>
          </div>
          <p>Intelligent Document Capture, Recognition & Reconstruction</p>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
