# Estado do desenvolvimento

Versão de trabalho: 0.1.0. Knowledge AI está na branch `cursor/cpmh-knowledge-ai-776e`, sobre a Fase 10. Data da verificação: 20 de novembro de 2026, horário de Brasília.

## Fases

| Fase | Estado |
| --- | --- |
| 0 Inspeção, marca e arquitetura | Feita. A marca e as cores estão em DESIGN_SYSTEM.md. |
| 1 Fundação desktop | Feita no código: Electron, React, FastAPI, SQLite, token, logs e preferências. A interface foi exercida no Chrome. |
| 2 Navegador e captura | Captura Playwright testada num visualizador HTML local. A vista embutida do Electron valida a URL, mas não foi exercida visualmente. |
| 3 Overlay | Implementado sobre a imagem capturada, com seleção, desenho, ajuste, edição, restauração e reprocessamento. A seleção foi vista no roteiro de interface. |
| 4 Inteligência documental | Testada nas fixtures de texto, tabela, colunas, continuidade, OCR e chinês. |
| 5 Tradução | Glossário testado. Tradução neural indisponível porque o Argos não está instalado. |
| 6 Reconstrução | DOCX, PDF, TXT, JSON e pacote implementados. DOCX, PDF, TXT e JSON do manual digital passaram no teste. |
| 7 Fila | 10 documentos com recuperação, mais 50 e 100 PDFs pequenos, todos concluídos no teste. |
| 8 Instalador | Configuração NSIS escrita. Não executada e não testada em Windows. |
| 9 Validação final | Parcial. Os testes deste ambiente passaram. Windows, precisão estatística e Argos continuam em aberto. |
| 10 Integridade, tradução, distribuição e revisão | A revisão chega aos cinco formatos. Os modos de tradução são únicos. O overlay foi medido no Chrome. O instalador Windows segue não testado. Argos segue ausente. |
| 10.5 Benchmark SciELO | Feito em 20 de novembro de 2026. O artigo de 27 páginas foi processado no backend real. A primeira passagem perdia texto em tabelas falsas; a correção subiu o recall do corpo para 0,9853. Decisão: resultado A, iniciar a Fase 11 sem aprovar o instalador. |
| Knowledge AI | Módulo local integrado. Indexa o que o pipeline já extraiu, busca no SQLite e responde com citação ou com a recusa padrão. Sem LLM neural nesta máquina: a resposta medida é extrativa. Fine-tuning não executa. O instalador Windows segue sem teste. |
| Acesso web | Detecção e pausa diante de CAPTCHA, login, bloqueio e limite. A verificação humana usa o Chromium já integrado, sem quebra de desafio. Testado com páginas locais, não com CAPTCHAs de produção. |

## Pendências

- Produzir o backend congelado no Windows e rodar o NSIS numa instalação limpa. O spec e o workflow existem; nenhum dos dois foi executado aqui.
- Instalar e medir Argos, ou outro tradutor local, antes de apresentar tradução neural. O estado atual é `unavailable`.
- Medir OCR num conjunto digitalizado. O artigo SciELO desta rodada é texto digital; o Tesseract não entrou. O conjunto sintético de layout continua em 13 de 13 e não autoriza uma taxa geral.
- Abrir a janela Electron e conferir o overlay injetado. A medição atual usou o script no Chrome.
- Medir um modelo GGUF real, com consentimento, antes de publicar RAM, VRAM ou um perfil de hardware. O embedding ativo é `cpmh-hash-v1`, não um modelo BGE.

## Decisões

- Tesseract em vez de PaddleOCR, pelos idiomas já instalados e pelo tamanho do runtime.
- PDF com texto não é fotografado de novo para extrair esse texto.
- Fórmula complexa não é substituída por aproximação.
- Captura sem sinal de fim fica inconclusiva.
