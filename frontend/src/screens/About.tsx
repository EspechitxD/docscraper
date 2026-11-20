import { useEffect, useState } from "react";
import { api } from "../api";

export function AboutScreen() {
  const [version, setVersion] = useState("0.1.0");
  useEffect(() => {
    api<{ version: string }>("/health").then((item) => setVersion(item.version)).catch(() => undefined);
  }, []);
  return (
    <section>
      <div className="home-hero">
        <img className="home-mark" src="/branding/cpmh-mark-512.png" alt="Marca CPMH" />
        <div>
          <h1>CPMH Document Intelligence</h1>
          <p className="lede">Intelligent Document Capture, Recognition & Reconstruction. Versão {version}.</p>
        </div>
      </div>
      <section className="panel stack">
        <h2>Marca</h2>
        <p>A marca compacta é o favicon oficial de https://www.cpmh.com.br/. O arquivo mestre publicado tem 50×50 px; as versões 192 e 512 são ampliações do Wix, não um redesenho. O nome “CPMH Digital” ao lado da marca está composto na fonte da interface.</p>
        <p>O SVG laranja embutido no cabeçalho do site aponta para conecta.cpmhdigital.com.br e desenha a palavra Conecta. Ele não é o logotipo da CPMH e não é usado aqui. O SVG indicado como logotipo do negócio no dado estruturado do site respondeu HTTP 403, então não há wordmark vetorial público adicional.</p>
        <div className="row">
          <img src="/branding/cpmh-mark-50.png" width={50} height={50} alt="Favicon oficial 50 px" />
          <img src="/branding/cpmh-mark-192.png" width={64} height={64} alt="Rendition 192" />
        </div>
        <p>As fontes de interface são Space Grotesk, Gantari e JetBrains Mono, sob licença SIL Open Font License. Zalando Sans Expanded aparece no site e não é redistribuída.</p>
        <p>O arquivo de mídia com degradê laranja não é o logotipo e não é usado.</p>
        <h2>Uso</h2>
        <p>O aplicativo processa documentos cuja captura e utilização o usuário declara estar autorizado a fazer. Ele não contorna DRM, paywall, autenticação ou controle de acesso.</p>
      </section>
    </section>
  );
}
