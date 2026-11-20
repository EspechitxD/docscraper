# CPMH Document Intelligence

Aplicativo desktop para captura autorizada, OCR, revisão e reconstrução de documentos.

*Intelligent Document Capture, Recognition & Reconstruction.*

O processamento essencial roda no computador. Não há servidor remoto obrigatório e nenhum documento é enviado para fora sem consentimento explícito.

## O que está implementado

- Projetos, URLs, listas TXT/CSV e importação de PDF ou imagem local.
- Validação de URL com bloqueio de rede local, loopback e metadados.
- PDF digital lido pela camada de texto; PDF sem texto passa por OCR.
- Captura sequencial de visualizador HTML com Playwright e Chrome, parando por contador ou botão seguinte desabilitado.
- Overlay de revisão com coordenadas normalizadas, edição, restauração e reprocessamento.
- Estrutura documental, tabelas, fórmulas simples e continuidade entre páginas.
- Tradução por glossário. Argos Translate é opcional e não está instalado neste ambiente.
- Exportação DOCX, PDF, TXT, JSON e pacote ZIP, sem sobrescrever arquivo em silêncio.
- Fila persistente, pausa, retomada, cancelamento e recuperação de tarefa interrompida.
- Interface React com a marca oficial da CPMH e processo Electron que sobe o backend local.

## Tecnologias

- Electron, React, TypeScript e Vite.
- Python, FastAPI, SQLAlchemy e SQLite.
- pypdfium2, Pillow, OpenCV, Tesseract, python-docx e ReportLab.
- Playwright com o Chrome já instalado.

Tesseract foi escolhido no lugar de PaddleOCR: os quatro idiomas prioritários (português, inglês, chinês simplificado e chinês tradicional) estão disponíveis no pacote do sistema, e o runtime cabe num aplicativo desktop sem o peso dos modelos Paddle.

## Desenvolvimento

Requisitos locais: Python 3.12, Node.js 22, Tesseract com `por`, `eng`, `chi_sim` e `chi_tra`, e Google Chrome para a captura HTML.

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r requirements.txt
npm install
```

Backend isolado:

```bash
export CPMH_API_TOKEN="$(openssl rand -hex 32)"
export PYTHONPATH=backend
backend/.venv/bin/python -m cpmh_backend
```

Interface e janela desktop, com o Electron gerando o token e a porta:

```bash
npm run dev
```

Para abrir só a interface no navegador, aponte `VITE_CPMH_API` e `VITE_CPMH_TOKEN` para o backend já iniciado.

Os dados ficam fora da pasta do programa: `%APPDATA%\CPMH Document Intelligence` no Windows e `~/.local/share/cpmh-document-intelligence` no Linux. `CPMH_DATA_DIR` substitui esse caminho.

## Testes

```bash
cd /caminho/do/projeto
PYTHONPATH=backend backend/.venv/bin/pytest tests -q
```

Os resultados medidos nesta máquina estão em [TESTING.md](TESTING.md). O instalador Windows está configurado e não foi executado aqui: este ambiente é Linux.

## Limites conhecidos

- Sem máquina Windows, a instalação em Windows 10/11 não foi testada.
- Argos Translate não está instalado. A tradução disponível é a do glossário e fica marcada como parcial.
- Os limiares de confiança 85 e 60 são pontos de partida, não uma calibração universal.
- Não há percentual de precisão de OCR medido num corpus público. O teste de página digitalizada confirma a leitura da palavra de referência usada na fixture.
