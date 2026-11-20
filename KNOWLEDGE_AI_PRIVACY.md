# CPMH Knowledge AI — privacidade

O processamento da biblioteca é local.

- O texto do documento não é enviado a um serviço externo.
- Não há telemetria de conteúdo.
- Nenhum modelo é baixado sem `consent: true`.
- A API continua em `127.0.0.1` e exige `X-CPMH-Token`.
- O download de modelo usa a validação de URL já existente: rejeita endereço local, IP privado e redirecionamento para esses destinos.
- A pasta de relatório passa por `assert_output_dir_allowed`.
- Apagar um modelo só remove arquivo dentro de `data/models`.

## Isolamento

A busca de um projeto lê a biblioteca daquele projeto. A busca de um documento lê só aquele documento. A biblioteca global é um escopo explícito e alcança os documentos desta instalação. Uma conversa recusa pergunta de outro escopo, outro projeto ou outro documento.

O teste automatizado colocou um identificador secreto em outro projeto e perguntou, inclusive com uma ordem para ignorar regras. A resposta do projeto consultado não continha o identificador. Depois da exclusão do documento, o identificador também não voltou na busca global.

## Texto do documento

O trecho recuperado entra no contexto como dado, entre marcadores, com a instrução de não executar pedidos contidos nele. A resposta extrativa cita o trecho; não obedece ao que o trecho pede. Uma citação que o modelo inventar e que não esteja no conjunto recuperado é descartada.

## Logs

Falha de indexação registra a exceção técnica. O conteúdo do documento não é o objeto do log de aplicação.

## Limites

Quem escolhe o escopo global vê todos os documentos locais. Isso é o próprio acervo do usuário neste computador, não um envio para fora. O aplicativo não tem contas separadas.
