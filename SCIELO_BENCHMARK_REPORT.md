# Benchmark SciELO — relatório

Data: 20 de novembro de 2026, horário de Brasília. Branch `cursor/cpmh-phase-10-776e`.

## Documento

- Título: Avaliação externa de escolas e sua relação com políticas e práticas inclusivas: uma revisão sistemática da literatura.
- URL: https://www.scielo.br/j/ensaio/a/nnh5ntMHZWGrC3qDVJ4LHrJ/?format=pdf&lang=pt
- DOI: 10.1590/S0104-40362025003305115
- Obtido às 08:55 (horário de Brasília) pelo Chrome aberto com Playwright. O `curl` recebeu HTTP 403 da CDN (BunnyCDN, código 112). O arquivo guardado começa com `%PDF-1.7`.
- SHA-256: `c3d13372a45637a51311e07593148c3661e8a0dabbf07b325db1441053fee5fd`
- Tamanho: 676380 bytes. Páginas lidas no arquivo: 27. Todas em retrato, 425,2 × 637,79 pt. Todas têm camada de texto (1376 a 3068 caracteres na extração do pdfium).
- Metadados do PDF: Adobe InDesign 20.3, Adobe PDF Library 17.0, criação 23 de maio de 2025. Título e autor no dicionário do PDF estão vazios.
- Cópia intacta: `tests/fixtures/external/scielo/original.pdf` e `benchmark_scielo/first_pass/original.pdf`.

O artigo tem texto digital, título, autores, resumo, seções numeradas, quadros, o fluxograma PRISMA na página 8, a lista de estudos e referências. Não há fórmula matemática. As figuras do fluxograma são vetoriais, não uma imagem embutida.

## Ambiente

- Linux x86_64, Python 3.12.3, Node 22.23.4, aplicativo 0.1.0, Electron 33 declarado no `package.json`.
- Tesseract 5.3.4 com `por`, `eng`, `chi_sim`, `chi_tra` e `osd`.
- 4 CPUs. A leitura de memória no início mostrou 15 GiB, com cerca de 4,4 GiB livres.
- O PDF é digital. Nenhuma página caiu no OCR, porque todas tinham mais de 8 caracteres na camada de texto.
- A janela Electron não foi aberta neste benchmark. O processamento usou o mesmo backend que o Electron sobe: projeto, importação, fila e exportação em `127.0.0.1:8771`.
- A suíte já existente, antes de qualquer correção desta rodada, passou: 26 testes. Depois das correções, a suíte completa passou com 30 testes, em cerca de 25 segundos.

## Processamento

Projeto `Benchmark SciELO — Avaliação de políticas inclusivas`, id `d81089d1-d3ad-4ee8-be23-c1e07755d766`.

Documento `f51a8e87-7cc3-4f5c-aaf3-245a463b149b`, origem arquivo, idioma `por`, tradução `none`.

Primeiro job `6f2edf7e-1d12-4de8-9d99-890a5b24c99f`, concluído às 08:56 (Brasília), estado `awaiting_review`. Checkpoint: páginas 1 a 27. Tradução ignorada. Nenhuma revisão manual antes dessa exportação.

A saída automática ficou em `benchmark_scielo/first_pass/`. O reprocessamento depois das correções terminou às 09:19 (Brasília) e está em `benchmark_scielo/corrected/`. Uma janela medida do job corrigido foi das 09:16:01 às 09:16:04 (Brasília), cerca de 3 segundos para as 27 páginas.

## O que a primeira passagem fez

- 27 páginas, na ordem, sem duplicar página. Captura `complete`.
- 342 regiões. O título principal saiu como cabeçalho. “Resumo” saiu como título. Os autores saíram como subtítulo.
- 8 tabelas marcadas como confiáveis. Várias comiam o corpo da página, inclusive o cabeçalho corrido. As páginas 6 e 9 ficaram com 3 e 2 regiões.
- Nenhuma imagem. O fluxograma não é um bitmap embutido.
- DOCX de 61195 bytes, sem imagem, com “Resumo” no estilo Título. PDF reconstruído com 24 páginas. TXT com 51957 caracteres.
- Recall de tokens do corpo, contra o `pypdf`, 0,8416 (1421 tokens ausentes em 8973). CER médio por página, comparando regiões com o `pypdf`, 0,2561. O `pypdf` avisou falta de fontTools na fonte Segoe UI; a conta usa o texto que ele devolveu.

## O que a passagem corrigida fez

- 27 páginas de novo, na mesma ordem.
- O título da página 1 ficou na categoria título e no estilo Título do DOCX.
- “Universidade de Aveiro” ficou inteiro. Na primeira passagem aparecia “Uni versidade”.
- Quadros das páginas 4, 6 e 9–10 viraram tabelas com linhas reais. O corpo fora da grade permaneceu texto.
- O fluxograma da página 8 virou uma imagem de diagrama, com a legenda “Figura - Fluxograma para expor os procedimentos e resultados”. O recorte está em `benchmark_scielo/corrected/extracted_images/prisma-page-8.png`.
- DOCX com 3 tabelas e a figura. PDF reconstruído com 23 páginas: é refluxo editável, não uma cópia página a página. As 27 páginas de origem continuam no JSON.
- Recall de tokens do corpo no TXT: 0,9853 (132 ausentes, 20 a mais, em 8973). CER médio das regiões: 0,1511. Os 132 tokens que faltam concentram-se no texto desenhado dentro do fluxograma, que ficou na imagem.

## Revisão

Depois de guardar a exportação corrigida, três alterações:

1. No resumo, `webQDA` passou a `webQDA (revisado no benchmark)`.
2. O título em inglês da página 21 passou de título para subtítulo.
3. A legenda da figura passou a `Fluxograma PRISMA conferido na revisão`.

As três aparecem no DOCX, no PDF, no TXT, no JSON e no pacote em `benchmark_scielo/reviewed/`. O histórico da região guarda o resumo original com `webQDA` e a operação `reclassify` do título em inglês.

## Decisão

Resultado A. O fluxo processou o artigo inteiro, as exportações abrem e são utilizáveis, a revisão persiste e não restou falha P0. A Fase 11 pode começar pela preparação do instalador Windows. Isso não aprova o instalador: ele não foi executado em Windows. O resultado C fica fora por esse motivo.
