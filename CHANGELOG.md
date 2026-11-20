# Changelog

## Benchmark SciELO — 20 de novembro de 2026

- O artigo da SciELO (27 páginas, DOI 10.1590/S0104-40362025003305115) foi processado pelo backend e comparado com o `pypdf`.
- O título que também é cabeçalho corrido deixa de ser rebaixado. Uma grade de texto não pode mais apagar o corpo entre duas lacunas distantes.
- Tabelas com linhas desenhadas usam essas linhas para as células. Um desenho feito de várias caixas vira recorte de diagrama.
- O marcador sobrescrito deixa de partir a palavra seguinte. O TXT inclui as células da tabela e a legenda revisada da imagem.
- Decisão registrada em PHASE_11_READINESS.md: resultado A para preparar o instalador, sem teste Windows.

## Fase 10 — 20 de novembro de 2026

- A CI Linux instala a fonte WQY usada no PDF em chinês. O spec do PyInstaller resolve o backend a partir da raiz do repositório.
- A revisão de uma região passa a atualizar a representação usada por DOCX, PDF, TXT, JSON e pacote.
- Histórico de revisão e migração aditiva para a coluna de evidência.
- Modos de tradução unificados, seleção por ID e glossário escolhido no projeto.
- Painel de revisão de imagens, equação OMML só para fórmula linear confiável e overlay medido no Chrome.
- O aplicativo empacotado deixa de recorrer ao Python do sistema. O instalador Windows continua sem teste real.

## 0.1.0 — 20 de novembro de 2026

- Primeira versão de trabalho do CPMH Document Intelligence.
- Backend local com projetos, fila, OCR, captura HTML, glossário, exportação e diagnóstico.
- Interface desktop com a marca oficial da CPMH. O SVG Conecta do cabeçalho do site ficou de fora de propósito.
- Testes automatizados das fixtures locais, incluindo lotes de 50 e 100 PDFs pequenos.
- Configuração do instalador NSIS ainda sem execução em Windows.
