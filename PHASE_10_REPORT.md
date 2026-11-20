# Fase 10 — relatório

Data da execução: 20 de novembro de 2026, horário de Brasília. Máquina: Linux x64, Python 3.12.3, Node 22. A branch é `cursor/cpmh-phase-10-776e`, criada a partir da PR #1. Não houve merge.

## Problemas e causas

A auditoria está em `PHASE_10_AUDIT.md`. O ponto que quebrava a confiança do produto era este: a revisão gravava `OCRRegion`, e DOCX, PDF, TXT, JSON e o pacote liam `DocumentElement`, que só era refeito no fim do OCR.

Os modos `portuguese` e `selected` da interface não eram os modos `portuguese_only` e `selection` da exportação. A tarefa não recebia os IDs selecionados. O projeto não escolhia o glossário na tela.

## O que passou a acontecer

- Cada edição, reclassificação, movimento, exclusão, criação, restauração ou reprocessamento grava `region_revisions` e reconstrói os elementos na mesma transação da sessão. A exportação reconstrói de novo antes de ler, para não publicar cache antigo.
- O OCR original permanece em `original_text` e `original_category`. O histórico guarda operação, origem, valores e data.
- Os modos canônicos são `none`, `selected_regions`, `document_pt_br` e `bilingual`. Os nomes antigos continuam aceitos e são convertidos. A seleção vazia e um ID de outro documento recebem erro 400. O glossário do projeto prevalece sobre um glossário enviado na tarefa. Sem glossário associado, o glossário inicial continua disponível; o de outro projeto não entra.
- Tradução só de glossário fica com estado `partial`. O endpoint `/api/translation/runtime` informa que o Argos não está instalado e que não há download automático.
- Uma fórmula linear confiável, como `E = mc²`, entra no DOCX como OMML e o recorte original é mantido quando existe. Integral, somatório, produtório e raiz continuam como recorte e nota de revisão. Não há OCR matemático novo.
- O classificador deixa a maior fonte de fora da mediana do corpo. No PDF de duas linhas, “Manual tecnico de ancoragem” passou a ser título. O conjunto sintético anotado à mão teve 13 de 13 acertos neste teste. Isso não é precisão de um corpus externo.
- A estrutura ganhou painel de imagem: pré-visualização, zoom, nome, categoria, legenda, revisão, exclusão confirmada e cópia para uma pasta. O arquivo só é apagado se nenhuma outra imagem, tabela ou fórmula apontar para ele.
- O navegador embutido injeta `electron/overlay.js` no documento. A caixa é `normalizado × scrollWidth/scrollHeight`. Zoom do Chromium e rolagem movem a página e o SVG juntos. No Chrome desta máquina, a diferença medida entre o alvo e a caixa foi 0 px nos fatores 0,5, 1, 1,5 e 2 e depois da rolagem. O teste automatizado exige no máximo 3 px e passou, incluindo 75%, 125% e redimensionamento. O visualizador nativo de PDF do Chrome não recebe essa camada; a revisão desses arquivos continua na imagem capturada.
- Aplicativo empacotado não cai mais no Python do sistema. Se `cpmh-backend` não estiver em `resources/backend`, a janela mostra que a instalação está incompleta. O processo grava `backend.pid` e `logs/backend.log` e encerra um PID anterior.
- `scripts/stage_runtime.py` escreve `build/runtime/manifest.json` com versão, tamanho e SHA-256 do Tesseract 5.3.4 e dos modelos encontrados. Não copia esses binários para o instalador e não baixa nada. `windows_installer_tested` permanece falso.

## Migração

`SCHEMA_VERSION` passou de 1 para 2. A tabela `region_revisions` é criada por `create_all`. A coluna `ocr_regions.evidence` é acrescentada com `ALTER TABLE` quando falta. O teste criou um SQLite antigo com a linha `r1` / `original`, migrou e leu a mesma linha.

## Testes executados

Comando: `PYTHONPATH=backend backend/.venv/bin/pytest tests -q`

Resultado nesta execução: 26 testes aprovados, nenhum falhou, cerca de 28 segundos. Os 16 testes anteriores continuam na suíte. Os novos cobrem:

| Operação | DOCX | PDF | TXT | JSON | Pacote |
| --- | --- | --- | --- | --- | --- |
| Editar texto | texto novo | texto novo | texto novo | texto novo | texto novo |
| Excluir região | ausente | ausente | ausente | ausente | ausente |
| Alterar classificação | estilo Title | — | — | — | — |
| Criar região | presente | presente | presente | presente | presente |
| Restaurar original | — | — | texto original | histórico | — |
| Mover caixa | — | — | — | bbox 0,2 e 0,62 | — |

A reclassificação foi conferida pelo estilo do parágrafo no DOCX, não só pelo JSON. PDF, TXT, JSON e pacote foram abertos e lidos.

Também passaram: seleção vazia, ID de outro documento, glossário do projeto contra o de outro, desassociação, exportação bilíngue, runtime neural indisponível, 13/13 no conjunto de layout, título no PDF de duas linhas, geometria do overlay, exclusão e exportação de imagem, OMML em `E = mc²` e ausência de OMML na integral.

`npx tsc` da interface e do Electron concluiu sem erro antes da suíte.

## Limitações

- O instalador NSIS não foi gerado nem executado. Não há Windows nesta máquina. O workflow `.github/workflows/desktop.yml` ainda não rodou aqui. A etapa Windows só congela o backend; a suíte completa permanece no Linux porque Tesseract, modelos e as fontes dos PDFs de teste não foram baixados no runner.
- PyInstaller não foi executado nesta sessão. O spec está em `packaging/cpmh-backend.spec`. Um freezer Linux não serve o instalador Windows.
- Argos Translate não foi instalado. Não existe tradução neural local verificada. O glossário continua parcial de propósito.
- Não há reconhecimento de fórmulas complexas. Não foi substituído por texto aproximado.
- O conjunto de layout tem 13 blocos sintéticos e um PDF de duas linhas. Não há precisão, recall ou F1 fora desse conjunto, e não há corpus externo.
- A janela Electron não foi aberta nesta rodada. A medição do overlay usou o mesmo script no Chrome, com `--no-sandbox` apenas porque o processo desta máquina é root. O produto não desativa o sandbox.
- No Chrome, a tela do documento recusou traduzir a seleção vazia, marcou uma região, mostrou a pré-visualização da imagem, gravou a legenda “Placa conferida na tela” e o estado `reviewed`. A tela do projeto desassociou e reassociou o glossário. Não houve erro de JavaScript. A janela de 390×844 também foi aberta. Isso não substitui a leitura dos arquivos exportados, que os testes já fazem.

## Como executar

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r requirements.txt
PYTHONPATH=backend backend/.venv/bin/pytest tests -q
npm install
npm run dev
```

## Como preparar o instalador

```bash
python3 scripts/stage_runtime.py
npm run dist:win
```

No Windows, depois dos testes daquele sistema:

```bash
backend\.venv\Scripts\pyinstaller packaging\cpmh-backend.spec --noconfirm --distpath dist --workpath build\pyinstaller
```

O executável esperado é `dist\cpmh-backend\cpmh-backend.exe`, e o Electron o procura em `resources/backend/cpmh-backend.exe`. Enquanto esse arquivo não existir, o aplicativo empacotado recusa iniciar com o Python do sistema. Isso ainda não foi observado num Windows.
