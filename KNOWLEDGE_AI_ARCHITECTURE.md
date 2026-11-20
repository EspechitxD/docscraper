# CPMH Knowledge AI — arquitetura

O Knowledge AI é um módulo do CPMH Document Intelligence. Ele não substitui a captura, o OCR, a classificação nem a exportação. A biblioteca é construída com o que esses estágios já gravaram.

## O que “aprender” significa aqui

Há três mecanismos separados.

1. **Recuperação.** O documento entra no índice. Uma pergunta busca trechos e a resposta só pode usar esses trechos. Os pesos de um modelo de linguagem não mudam.
2. **Memória persistente.** Segmentos, vetores, conversas, entidades e relações ficam no SQLite do aplicativo. Fechar o programa não apaga a biblioteca.
3. **Fine-tuning.** Existe apenas um portão de exemplos aprovados. Nenhum treino é executado. Importar um PDF não é treinamento.

## Fluxo

```text
Pipeline existente
    elementos, tabelas, imagens, fórmulas, revisões
        ↓
Segmentação pela estrutura já reconhecida
        ↓
FTS5 + vetor local cpmh-hash-v1
        ↓
Busca híbrida limitada ao escopo
        ↓
Resposta com citações validadas, ou recusa
```

A indexação ocorre no fim do processamento e de novo quando uma região é editada, reclassificada ou apagada. A exclusão do documento remove os segmentos e as linhas do FTS5. Uma falha do índice não cancela o processamento nem a revisão: a operação fica num savepoint.

## Onde o código mora

- `backend/cpmh_backend/knowledge/` — índice, busca, resposta, grafo, runtime, relatório e treino.
- Tabelas no mesmo `Base` do SQLAlchemy. A versão de schema passou de 2 para 3.
- `knowledge_fts` é uma tabela virtual FTS5, criada na migração aditiva.
- A API entra por `backend/cpmh_backend/main.py`, no mesmo prefixo `/api` e com o mesmo token `X-CPMH-Token`.
- A tela fica em `frontend/src/screens/Knowledge.tsx`, rota `/knowledge`.

## Segmento

Cada segmento guarda documento, página, seção, tipo, texto, região de origem quando existe, versão de revisão e hash do conteúdo. Um segmento cujo hash não mudou mantém o vetor. Texto alterado gera outro vetor. O segmento antigo sai do índice.

Tabelas viram linhas `coluna: célula`. Imagens guardam a legenda e a frase de que o modelo de texto não vê os pixels. Fórmula sem texto confiável permanece como recorte, sem transcrição inventada.

## Busca

A pergunta passa por uma expansão lexical fixa e por dois sinais:

- sobreposição de termos e BM25 do FTS5;
- cosseno do vetor `cpmh-hash-v1`, de 256 dimensões.

O vetor é uma projeção local de termos e trigrama. Não é um modelo neural e não foi baixado. Uma resposta só segue se houver um termo distintivo em comum com o trecho. Sem esse apoio, a resposta é a recusa padrão. A expansão ajuda paráfrases cadastradas, como força de ruptura e resistência à tração. Ela não cobre paráfrase livre.

## Escopos

- `document` — um documento.
- `project` — a biblioteca daquele projeto.
- `library` — uma biblioteca.
- `global` — os documentos desta instalação. É uma escolha explícita do usuário, não o padrão de uma conversa de projeto.

Uma conversa não aceita pergunta de outro escopo.

## Runtime

O aplicativo consulta `127.0.0.1:11434` por no máximo 0,4 s para ver se o Ollama já está no ar. Não o instala e não o inicia. Sem modelo local, a resposta é extrativa: frases dos trechos recuperados, com o identificador do segmento. Se um modelo responder, citações cujo identificador não esteja no conjunto recuperado são descartadas. Sem citação válida, volta a resposta extrativa.

## Grafo

Entidades saem de padrões do texto (instituição “Universidade de …”, DOI, título de seção). Relação de coocorrência no mesmo trecho fica marcada como `inferred`. Isso não é um fato documentado.
