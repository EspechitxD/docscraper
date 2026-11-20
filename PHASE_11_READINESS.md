# Prontidão para a Fase 11

Decisão: **resultado A — aprovado para iniciar a Fase 11**. Data: 20 de novembro de 2026, horário de Brasília.

O resultado C não se aplica. O instalador não foi executado em Windows, então não há release candidate.

## O que este benchmark valida

No Linux, com o backend real do CPMH Document Intelligence, o artigo SciELO de 27 páginas (SHA-256 `c3d13372a45637a51311e07593148c3661e8a0dabbf07b325db1441053fee5fd`) foi importado, processado sem tradução e exportado.

- As 27 páginas entraram, na ordem, sem página duplicada.
- O título principal ficou com estilo Título.
- O TXT corrigido recupera 0,9853 dos tokens do corpo medidos com `pypdf`, depois de descontar o expediente repetido.
- O fluxograma da página 8 saiu como figura com legenda.
- Três revisões (texto, categoria e legenda) apareceram em DOCX, PDF, TXT, JSON e pacote, e o texto anterior ficou no histórico.
- A suíte automatizada ficou em 30 testes aprovados.
- Não restou P0 neste documento.

Isso vale para este PDF digital, em português, neste ambiente. Não é uma taxa geral de OCR. O Tesseract não chegou a rodar neste arquivo.

## O que a Fase 11 ainda precisa fazer

A Fase 10 já deixou o spec `packaging/cpmh-backend.spec`, o script `scripts/stage_runtime.py` e o workflow `.github/workflows/desktop.yml`. Nenhum deles produz um instalador aprovado.

| Passo | Estado aqui |
| --- | --- |
| Congelar o backend com PyInstaller | O spec aponta para a raiz do repositório. O job Windows anterior não chegou a gerar `cpmh-backend.exe`. Não foi repetido nesta máquina. |
| Empacotar Tesseract, idiomas e modelos | O script de estágio registra o que encontra e não baixa nada. Não copia binários. |
| Chromium | O desenvolvimento usa o Chrome do sistema. O pacote ainda não carrega um Chromium próprio. |
| NSIS | A configuração existe. Não foi executada. |
| Teste em Windows limpo | Não houve. Não declarar o instalador pronto. |

A Fase 11 começa por esse empacotamento e por uma execução real em Windows. Até lá, a distribuição continua não testada.
