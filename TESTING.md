# Testes

Ambiente: Linux `6.12.113+`, x86_64, Python 3.12.3, Tesseract 5.3.4, Google Chrome, Node 22.23.4. Não é uma máquina Windows.

Comando:

```bash
PYTHONPATH=backend backend/.venv/bin/pytest tests -q --durations=12
```

Resultado em 20 de novembro de 2026: 16 testes aprovados, nenhum falhou. A execução completa levou cerca de 21 segundos.

## Durações medidas

| Teste | Tempo |
| --- | --- |
| Lote de 100 PDFs de uma página | 9,03 s |
| Lote de 50 PDFs de uma página | 5,02 s |
| Captura HTML local de duas páginas | 2,03 s |
| Fila de 10 documentos com interrupção e retomada | 1,18 s |
| OCR de página digitalizada e PDFs em chinês | 1,00 s |
| Manual digital, tabela, fórmula e exportação | 0,45 s |
| Parágrafo dividido e duas colunas | 0,42 s |

Esses lotes usam PDFs pequenos de uma página gerados no teste. Eles verificam persistência, estado e contagem. Não medem estabilidade de 100 manuais grandes.

## O que cada grupo cobre

- Segurança: loopback, metadados, redes privadas, IP ofuscado, `file:`, usuário na URL e DNS misto.
- Idioma, colunas, continuidade, fim de captura, tabela e fórmula simples. Integral não é tratada como fórmula confiável.
- Glossário: “plate” vira “placa” e `Ti6Al4V` e `2,0 mm` permanecem.
- Manual digital exportado em DOCX, PDF, TXT e JSON. Nome existente responde 409; a opção de nova versão cria outro arquivo.
- Página só de imagem: o OCR leu `ANCORAGEM` na fixture. Não há taxa de acerto calculada além desse acerto pontual.
- Chinês simplificado e tradicional na camada de texto, com idioma detectado em `chi_sim`, `chi_tra`, `zh` ou `mul`.
- Visualizador HTML em `127.0.0.1`, com a preferência de rede local ligada no teste. Duas páginas, contador “1 de 2” e “2 de 2”, botão seguinte desabilitado na última, estado `complete`.

## Interface

Com o backend em `127.0.0.1:8765` e o Vite em `127.0.0.1:5173`, o Chrome automatizado:

- abriu a tela inicial e leu os contadores reais do banco;
- criou o projeto “Verificação de interface”;
- recusou `http://127.0.0.1/secreto` com a mensagem de rede bloqueada;
- importou uma URL pública e um PDF local;
- processou o PDF até “Aguardando revisão”, com idioma `por` e 1 página;
- mostrou duas regiões sobre a imagem e o texto “Manual tecnico de ancoragem” e “A placa e o parafuso fixam o componente.”;
- conferiu a tela Diagnóstico, inclusive “Instalador Windows testado: não”;
- checou a largura útil em 1920×1080, 1600×900 e 1366×768 sem cortar o título nem a grade.

Não houve erro de JavaScript nessas navegações. A janela Electron em si não foi o alvo desse roteiro; o roteiro usou a mesma interface que o Electron carrega.

## Fase 10

Nova execução da suíte completa, no mesmo dia: 26 testes aprovados, cerca de 28 segundos. Além dos 16 anteriores, a suíte abre os arquivos exportados depois de editar, apagar, reclassificar, criar, mover e restaurar região. Também cobre os modos de tradução, o glossário do projeto, a migração aditiva, a imagem exportada e removida, o OMML de `E = mc²` e o conjunto de layout.

O conjunto de layout tem 13 blocos anotados. O teste exigiu 13 acertos e passou, com os dois títulos previstos entre eles. O PDF de duas linhas classificou “Manual tecnico de ancoragem” como título. Não há outra taxa de acerto.

O overlay, medido no Chrome com o script `electron/overlay.js`, ficou a 0 px do alvo nos fatores 0,5, 1, 1,5 e 2 e após rolagem. O teste automatizado percorre também 75%, 125% e o redimensionamento e falha se a diferença passar de 3 px. Essa execução passou. O `--no-sandbox` desse teste existe porque o processo da máquina é root. O aplicativo não usa essa flag.

A mesma sessão de Chrome abriu a interface em `127.0.0.1:5174` contra o backend em `127.0.0.1:8766`. A seleção vazia foi recusada na tela, uma região foi marcada, a imagem extraída apareceu no painel e a legenda gravada voltou na API como “Placa conferida na tela”, com revisão `reviewed`. O glossário do projeto foi retirado e colocado de novo. Não houve erro de JavaScript. A vista de 390×844 mostrou o painel de imagens.

## Não validado

- Instalador NSIS em Windows 10 ou 11.
- Precisão percentual de OCR, tabela ou tradução num conjunto público.
- Lotes de 50 ou 100 documentos grandes ou digitalizados.
- Argos Translate e qualquer API paga de tradução.
- O `WebContentsView` do Electron, porque o roteiro visual rodou no Chrome, não dentro da janela desktop.
