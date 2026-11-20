# CPMH Knowledge AI — API

Todas as rotas ficam em `/api` e exigem `X-CPMH-Token`. O frontend não abre o banco nem um modelo.

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/knowledge/status` | Documentos, segmentos, runtime e estado do treino |
| GET | `/api/knowledge/libraries` | Bibliotecas por projeto |
| GET | `/api/knowledge/documents` | Documentos indexados; `project_id` filtra |
| POST | `/api/knowledge/documents/{id}/index` | Reindexa a partir da representação atual |
| DELETE | `/api/knowledge/documents/{id}` | Remove o documento da biblioteca, sem apagar o arquivo do CPMH |
| POST | `/api/knowledge/ask` | Pergunta. Corpo: `question`, `scope` (`document`, `project`, `library`, `global`) e o identificador do escopo |
| GET, POST | `/api/knowledge/conversations` | Lista e cria conversa |
| PATCH, DELETE | `/api/knowledge/conversations/{id}` | Renomeia ou apaga |
| GET | `/api/knowledge/conversations/{id}/messages` | Histórico, com citações gravadas |
| POST | `/api/knowledge/compare` | Dois a oito documentos e uma pergunta. Devolve trechos por documento |
| POST | `/api/knowledge/reports` | DOCX com a resposta e as fontes. Exige `output_dir` permitido |
| GET | `/api/knowledge/models` | Runtime real, arquivos registrados e catálogo não baixado |
| POST | `/api/knowledge/models/download` | Exige `consent: true`. Recusa URL local e hash divergente |
| POST | `/api/knowledge/models/{id}/activate` | Marca o registro ativo. Não cria um processo de inferência |
| DELETE | `/api/knowledge/models/{id}` | Apaga o registro e o arquivo se estiver em `models/` |
| GET | `/api/knowledge/graph` | Entidades e relações, com `origin` |
| POST | `/api/knowledge/training/examples` | Só grava exemplo `approved: true` |
| GET | `/api/knowledge/training/status` | `training_executed` permanece falso |

A resposta de `/ask` traz `answer`, `citations`, `mode` e `hits`. `mode` pode ser `extractive`, `local_llm` ou `insufficient_evidence`. A recusa sem evidência é exatamente:

`Não encontrei informações suficientes na biblioteca documental para responder com segurança.`

Cada citação tem `document_id`, `page`, `section`, `chunk_id` e `element_type`. O identificador precisa pertencer aos trechos recuperados. Na interface, o link abre `/documents/{id}?page={página}` na revisão.
