# Estado do desenvolvimento

Versão de trabalho: 0.1.0. Data da verificação: 20 de novembro de 2026, horário de Brasília.

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

## Pendências

- Produzir o backend congelado no Windows e rodar o NSIS numa instalação limpa.
- Instalar e medir Argos, ou outro tradutor local, antes de apresentar tradução neural.
- Medir OCR e tabelas num conjunto de referência externo, se ele for obtido com licença de uso.
- Exercitar o navegador embutido do Electron numa janela real.

## Decisões

- Tesseract em vez de PaddleOCR, pelos idiomas já instalados e pelo tamanho do runtime.
- PDF com texto não é fotografado de novo para extrair esse texto.
- Fórmula complexa não é substituída por aproximação.
- Captura sem sinal de fim fica inconclusiva.
