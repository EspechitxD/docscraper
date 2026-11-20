# CPMH Knowledge AI — verificação

Data: 20 de novembro de 2026, horário de Brasília. Máquina: Linux x86_64, 4 CPUs. Nenhum modelo neural carregado. A suíte completa, `PYTHONPATH=backend backend/.venv/bin/pytest tests -q`, terminou com 37 testes aprovados em 27,9 s. Os 30 testes anteriores continuam nessa conta.

Os números abaixo saíram de `/tmp/cpmh-knowledge-metrics.json`, gravado pelos testes, e das asserções que passaram. Não há métrica de um conjunto maior do que essas perguntas.

## Perguntas executadas

| Caso | Material | Resultado observado |
| --- | --- | --- |
| A, objetivo | Artigo SciELO, 27 páginas, fixture `tests/fixtures/external/scielo/original.pdf` | Resposta extrativa com citações nas páginas 1, 2 e 14. A página 1 contém o resumo (“pretende analisar o impacto”). |
| A, metodologia | O mesmo artigo | Houve citação. O teste exigiu resposta diferente da recusa. |
| A, informação ausente | “ponto de fusão do nylon” no mesmo artigo | Recusa exatamente com a frase padrão. |
| Biblioteca e paráfrase | PDF sintético com “resistência à tração … 80 MPa” | A pergunta “força antes de romper” devolveu 80, com 2 citações do mesmo documento. |
| Tabela | Linhas Material/Tração gravadas como `TableRecord` e reindexadas | A resposta contém “80 MPa”. |
| Fórmula sem texto | `FormulaRecord` com texto vazio | A resposta diz que não há transcrição confiável. |
| D, outro tema | Temperatura de fusão do cobre no relatório de nylon | Recusa padrão. |
| C, comparação | Três PDFs, 70 MPa, 110 MPa e 40 MPa | Cada coluna ficou com o próprio valor. 110 não apareceu na coluna do artigo de 70. |
| E, revisão | Região “80 MPa … antes da ruptura” alterada para “95 MPa … correção de revisão” | A resposta passou a ter 95 MPa. “antes da ruptura” não voltou. |
| H, injeção | Outro projeto com `CPMH-SIGILO-8841` e uma pergunta pedindo para ignorar as regras | O identificador não apareceu na resposta do projeto consultado. |
| F, persistência | PDF com `KAI-PERSIST-441`, banco reaberto noutro processo | O identificador continuou na resposta. |
| G, offline | As consultas acima | Não houve download nem API externa. A sonda do Ollama só tenta `127.0.0.1`. |
| Consentimento | Download sem `consent` e download para `127.0.0.1` | Ambos recusados com HTTP 400. |
| Treino | Exemplo de saída de modelo sem aprovação | Recusado. O estado segue `training_executed: false`. |

## Tempos medidos

| Medida | Valor |
| --- | --- |
| Processar e indexar dois PDFs de uma página | 0,21 s |
| Uma consulta de recuperação nesse acervo | 0,011 s |
| Processar e indexar o artigo SciELO de 27 páginas | 3,184 s |
| Modo da resposta de tração | `extractive` |
| Páginas citadas na pergunta de objetivo | 1, 2, 2, 14 |
| RAM do modelo | não medida |
| VRAM | não medida |

Recall@K, Precision@K e MRR não foram calculados. O conjunto de referência é a tabela acima, não um banco anotado à parte.

## Limite desta rodada

A paráfrase da tração funciona porque o léxico acrescenta “resistência à tração” à consulta. Isso não é um embedding semântico. A pergunta sobre o objetivo do artigo SciELO chega ao resumo porque “objetivo” expande para “pretende” e as primeiras páginas ganham um acréscimo de pontuação. Uma paráfrase fora dessa lista pode ser recusada mesmo quando o assunto está no documento.
