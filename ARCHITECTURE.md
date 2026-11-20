# Arquitetura

O CPMH Document Intelligence é um aplicativo desktop local. O Electron abre a janela, gera um token e sobe o backend Python em `127.0.0.1`. A interface fala com esse processo pela API `/api`, enviando o cabeçalho `X-CPMH-Token`.

## Componentes

- `electron/main.ts` cria a janela, o token, a porta livre e o processo Python. Também hospeda o `WebContentsView` usado como navegador visível. Cada navegação passa antes por `POST /api/security/validate-url`.
- `frontend/` é a interface React. Em desenvolvimento o Vite serve a tela em `127.0.0.1:5173`. No pacote, o FastAPI serve os arquivos estáticos no mesmo endereço do backend.
- `backend/cpmh_backend` é o FastAPI. O worker da fila roda no mesmo processo e respeita `max_concurrent_jobs` (1 a 4).

## Fluxo de um documento

1. A entrada grava um `Document` com URL validada ou arquivo local.
2. A tarefa passa por validação, obtenção da fonte, captura ou análise, estrutura, tradução opcional e exportação opcional.
3. Se a resposta for PDF, o arquivo é analisado direto. Imagem isolada vai para OCR. HTML entra na captura sequencial.
4. Cada página guarda PNG, hash, hash perceptual, regiões normalizadas e metadados.
5. A reconstrução lê as regiões na ordem de leitura, inclusive em duas colunas, e liga parágrafos que continuam na página seguinte.
6. A exportação reutiliza o que já está no banco. Não dispara novo OCR.

## Banco

SQLite em modo WAL, com chaves estrangeiras. As tabelas cobrem projetos, documentos, páginas, capturas, regiões, elementos, imagens, tabelas, fórmulas, traduções, glossários, tarefas, passos, logs, exportações e preferências. A versão do esquema está em `schema_migrations`. Na abertura, tarefa que ficou em estado intermediário volta para `paused`, com o checkpoint preservado.

## Captura

`decide_capture` combina contador, botão seguinte desabilitado, hash, página em branco ou parcial e o limite de páginas. Contador no fim ou botão desabilitado encerra a captura. Três páginas idênticas sem sinal de fim ficam inconclusivas. A interface não declara o documento completo nesse caso.

O navegador visível do Electron não é a fonte das coordenadas. O overlay usa a imagem capturada e caixas de 0 a 1.

## OCR e layout

A camada de texto do PDF recebe confiança 99 e origem `pdf_text`. Página com menos de 8 caracteres vai para o Tesseract, com OSD para rotação de 90, 180 ou 270 graus. Tabelas com colunas regulares da camada de texto podem ser marcadas como confiáveis. Tabela só de linhas, sem células estáveis, guarda a imagem e não inventa valores. Fórmula com integral, somatório, produtório ou raiz fica inconclusiva e preserva o recorte.

## Tradução

O glossário local protege códigos, normas, unidades e termos marcados como intraduzíveis. Sem Argos e sem URL externa, o resultado é parcial. URL externa só é chamada se a tarefa trouxer consentimento e o endereço passar pela mesma validação de SSRF.

## Dados

Diretórios de usuário: `database/`, `projects/`, `cache/`, `inbox/` e `logs/`. Backup diário do SQLite, mantendo cinco cópias. A exportação só grava em pasta escolhida fora do diretório de instalação e fora de caminhos de sistema.
