# Changelog

## Verificação por controle deslizante — 22 de novembro de 2026

- Defeito: `classify` só reconhecia CAPTCHA por widget conhecido (reCAPTCHA, hCaptcha, Turnstile) ou por frases em inglês e português. A tela "请完成滑动验证后阅读文档" ("conclua a verificação deslizante para ler o documento") passava como acesso liberado: a captura fotografava a tela de verificação e o OCR a tratava como páginas do documento.
- `classify` reconhece agora o texto de verificação por controle deslizante, em chinês, inglês e português, e devolve `CAPTCHA_DETECTED` (provedor `slider`). A captura pausa sem gravar páginas. Só vale para páginas com menos de 2000 caracteres de texto visível, para que um documento que cite "verificação de segurança" não seja confundido.
- O programa continua sem resolver, arrastar ou contornar o controle. Isso nunca existiu no código e é decisão de projeto (`WEB_ACCESS.md`).
- 2 testes novos (97 aprovados; as mesmas 3 falhas do ambiente).

## Localizador do Tesseract — 22 de novembro de 2026

- Defeito: o Tesseract só era procurado no PATH (`shutil.which`). O instalador do Windows não o põe lá, e a captura caía em `TesseractNotFoundError` com um traceback.
- `find_tesseract` procura em `CPMH_TESSERACT_PATH`, PATH, `Program Files\Tesseract-OCR`, LocalAppData, Scoop, Chocolatey e Homebrew. `configure_tesseract` aponta o pytesseract para o executável e o `tessdata` ao lado.
- Novo `OcrUnavailable`: a falha vira uma mensagem com o comando `winget install --id UB-Mannheim.TesseractOCR -e` e a variável de ambiente, e o documento guarda essa mensagem.
- `tesseract_status` informa caminho e como corrigir, e guarda o resultado em cache (antes rodava o programa duas vezes por página). A tela Diagnóstico mostra caminho, navegador encontrado e a dica.
- Japonês (`jpn`) aceito na lista de idiomas do OCR.
- 2 testes novos (95 aprovados; as mesmas 3 falhas do ambiente).

## Busca do navegador no Windows — 22 de novembro de 2026

- Defeito: `browser_status` procurava o Chrome só pelos nomes `google-chrome`, `google-chrome-stable` e `chromium` no PATH. No Windows o Chrome é `chrome.exe` em Program Files e não está no PATH, então a captura e o diagnóstico diziam "sem Chrome" mesmo com ele instalado.
- `find_browser` procura em Program Files, Program Files (x86) e LocalAppData, aceita o Microsoft Edge (já vem no Windows) e a variável `CPMH_CHROME_PATH`. O navegador é aberto pelo caminho encontrado (`launch_browser`).
- A mensagem agora diz o que falta: o pacote `playwright` ou o navegador. Antes dizia "Chromium ou Playwright".
- 3 testes novos (93 aprovados; as mesmas 3 falhas do ambiente de antes).

## Diagnóstico de documentos em visualizadores web — 21 de novembro de 2026

- Novo `document_source_analyzer.py`: a partir do que o navegador observou, identifica HTML documental, PDF acessível por rede, PDF em iframe (citado, mas não verificado), PDF.js com ou sem camada de texto, imagens de página, canvas, CAPTCHA, login, pagamento e acesso negado. Escolhe a estratégia A a F. Nenhuma estratégia contorna restrição.
- Novo `browser_inspector.py`: inspeção no Chrome com Playwright. Só observa (DOM, iframes, canvas, imagens, respostas de rede, erros) e rola a página um pouco para o carregamento preguiçoso. Não lê cookies nem cabeçalhos de autorização; mascara tokens nas URLs. Sem Chrome, devolve erro e nunca um resultado simulado.
- Novo `document_recovery.py` e `python -m cpmh_backend.diagnose URL`: diagnóstico por linha de comando com relatório JSON.
- Novos `document_statistics.py` e `document_validator.py`: páginas informadas pelo site, acessíveis, processadas, com e sem texto; caracteres com e sem espaço; palavras (omitidas em chinês, japonês e coreano); interface descartada. Nota de qualidade Excelente, Boa, Parcial ou Insuficiente, com verificação de páginas vazias, repetição, numeração, tabelas e confiança do OCR.
- API: `POST /api/diagnostics/web-document` e `GET /api/documents/{id}/report`.
- Frontend: seção "Diagnóstico de documentos web" na tela de Diagnóstico (`WebDocumentDiagnosis.tsx`). Verificada só com `tsc --noEmit`; não foi aberta num Electron.
- Testes: 19 novos em `tests/test_web_document_diagnosis.py`, com fixtures locais. Provam a lógica de interpretação, não o funcionamento em sites reais.

## Captura de visualizador de documentos — 21 de novembro de 2026

Origem: um DOCX com 131 blocos de menus e botões em chinês de um site visualizador ("ASTM F 3127 - 16", 16 páginas), sem uma linha da norma.

- Texto de interface (menus, botões, rodapé) não é mais tratado como documento. Em `pages_from_downloaded_html` e no texto do DOM, `looks_like_interface_text` reconhece rótulos curtos e palavras como 下载, login, baixar. Com isso, o HTML devolve `interface_only`, nada é exportado e o aviso diz o que fazer. Antes o arquivo saía marcado como "completo".
- No navegador, texto de interface no DOM é descartado e a imagem da página vai para o OCR.
- Contador de páginas: com vários "N / M" na tela (busca "1 / 1" e páginas "3 / 16"), vale o maior total (`pick_counter`). O "1 / 1" do campo de busca encerrava a captura na primeira página.
- Visualizador que empilha as páginas como imagens: `_capture_stacked_pages` captura cada folha na ordem da tela. Se o contador indica mais páginas do que as capturadas, o resultado fica `inconclusive`.
- Sem teste em navegador real: o Chrome não existe no ambiente de desenvolvimento. As funções puras têm teste (4 novos); o caminho do Playwright não foi executado.

## Construção do texto em documentos digitalizados — 21 de novembro de 2026

Origem: um DOCX gerado a partir de uma norma técnica digitalizada em duas colunas (24 páginas). Detalhes em `REVISAO_CONSTRUCAO_DO_TEXTO.md`.

- OCR lê a página em cerca de 300 DPI (antes, 144 DPI), com contraste automático e correção de inclinação de até 6 graus. A imagem guardada passa a ser a página endireitada.
- Novo `layout.py`: calhas entre colunas, ordem de leitura por zonas (faixa de largura total, depois cada coluna) e montagem de parágrafos por número de cláusula, recuo, linha final curta e salto vertical. Antes, toda linha próxima era colada: "1. Scope 1.1 … 1.2 Exclusions 1.2.1 …".
- A exportação DOCX e PDF não reordena mais por `y`. Tabelas, imagens e fórmulas entram na ordem de leitura já fixada. Esse reordenamento misturava as duas colunas.
- Título e subtítulo: fragmento de frase (começa em minúscula, termina em hífen ou em "and", "of") nunca é título. Numeração só vira título se a linha for curta e começar em maiúscula. Primeira linha de cláusula cortada pela quebra de coluna volta a ser parágrafo.
- A altura do box do OCR passa a ser o percentil 75 das palavras da linha, não o box inteiro. A tolerância de fonte para OCR é maior.
- Título ganha nível pela numeração (`1.` = Título 1, `1.2` = Título 2, `1.2.3` = Título 3). Antes saía no estilo decorativo "Subtitle", que o sumário do Word ignora.
- O sumário só aparece com três títulos ou mais, já preenchido com os nomes. A frase "Atualize o sumário no Word…" saiu.
- Duas colunas de texto corrido não viram mais tabela. Tabela deduzida só do alinhamento do OCR não apaga mais o texto da página.
- S7 e S11 do benchmark SciELO fechados: palavras da célula ordenadas por linha; subtítulo sem numeração não termina em travessão.
- Nova categoria `noise` para resto de figura lido como texto. Fica fora de DOCX, PDF e TXT, e continua visível na revisão.
- Hífen de fim de linha: "clean-" + "ing" junta; "non-" + "specific" mantém o hífen. Parágrafo aberto no fim de uma coluna é ligado ao topo da coluna seguinte.
- `ocr_repair.py`: código de norma só é corrigido com maioria clara no próprio documento (E/F, I/1, O/0). `F2457` nunca vira `F2459`. Texto editado pelo revisor não é tocado.
- Testes novos em `tests/test_text_construction.py` (15), com uma página digitalizada sintética em duas colunas.

## Recuperação de acesso — 20 de novembro de 2026

- O diagnóstico separa CAPTCHA, desafio, limite, JavaScript, sessão expirada, login, bloqueio, rede e falha do navegador.
- Pedidos bloqueados não são repetidos. Erro temporário tem no máximo três tentativas; um 429 curto tem uma.
- O `robots.txt` é respeitado quando está disponível. Um PDF indicado pela própria página pode ser usado. Não há disfarce de automação nem busca por outras fontes.

## Acesso web — 20 de novembro de 2026

- A captura classifica CAPTCHA, verificação humana, login, bloqueio e limite de pedidos antes de extrair.
- A tarefa pausa, preserva o que já foi coletado e só retoma depois de uma checagem da própria captura.
- O navegador integrado abre a URL numa sessão isolada por projeto e tarefa. O aplicativo não resolve o desafio nem copia cookies.

## Knowledge AI — 20 de novembro de 2026

- Biblioteca local em cima dos documentos já processados: segmentos, FTS5, vetor `cpmh-hash-v1` e respostas com citação validada.
- Revisão de região atualiza o índice. Excluir o documento tira o texto da busca.
- Consulta por documento, projeto, biblioteca e acervo global, com conversas persistentes.
- Sem modelo de linguagem instalado, a resposta é extrativa. Não há download automático nem fine-tuning.
- A suíte passou com 37 testes. O artigo SciELO de 27 páginas foi indexado em 3,184 s nesta máquina.

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
