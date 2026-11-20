# CPMH Knowledge AI — uso

O módulo acompanha o backend que o aplicativo já sobe. Não há instalador separado e não é preciso instalar Python, Node.js ou Ollama para consultar a biblioteca.

## Primeiro uso

1. Processe um documento como já se faz no CPMH Document Intelligence.
2. Ao terminar, o documento entra na biblioteca do projeto.
3. Abra **Knowledge AI**.
4. Escolha o escopo e faça a pergunta.

A tela mostra a contagem vinda de `/api/knowledge/status`. Se o modelo de linguagem aparecer como “não instalado”, as respostas são extraídas dos trechos. Isso é o comportamento esperado nesta versão.

## Modelo de linguagem

Nenhum modelo é baixado na instalação. O download só ocorre se o usuário chamar `POST /api/knowledge/models/download` com `consent: true` e uma URL pública. O endereço passa pela mesma validação que bloqueia rede local e redirecionamento para endereço privado. O arquivo fica em `models/` dentro do diretório de dados. Ativar o registro não carrega um GGUF: sem llama.cpp ou Ollama com modelo já presente, `llm_ready` continua falso.

Ollama, se o usuário já o tiver em execução em `127.0.0.1:11434`, pode ser usado. O aplicativo não inicia esse processo e não o deixa rodando ao encerrar, porque não foi ele quem o criou.

## Offline

Depois que os documentos estão processados, a indexação, a busca e a resposta extrativa não precisam de rede. A sonda do Ollama tenta o endereço local e segue sem ele. Não há telemetria.

## Dados

Tudo fica no SQLite já usado pelo aplicativo (`CPMH_DATA_DIR`). A tabela `knowledge_fts` é recriada na abertura se ainda não existir. Documentos antigos continuam válidos; passam a ser indexados quando forem processados ou revisados.

## O que não está pronto para distribuição

O instalador Windows não foi executado. llama.cpp não é empacotado. Nenhum peso de modelo é enviado no repositório.
