# Acesso web e verificação humana

O CPMH Document Intelligence classifica o que a URL devolve antes de extrair o documento. Ele não resolve CAPTCHA, não contrata serviço de quebra, não falsifica impressão digital, não usa proxy para escapar de bloqueio e não copia cookies da sessão do usuário para o backend.

## O que a captura faz

1. Um PDF, uma imagem ou um HTML público segue o fluxo que já existia.
2. Se a resposta for 401, 403, 429 ou 503, ou se a página mostrar um desafio, a tarefa fica pausada e nenhuma página é gravada.
3. O usuário pode abrir a URL no Chromium já integrado ao aplicativo, numa partição isolada por projeto e tarefa.
4. A checagem que libera a retomada é uma nova abertura feita pela captura. O que aparece no navegador do usuário fica só no histórico.
5. Se a captura passar, a retomada manual continua de `pages_done` e não grava de novo uma sequência já armazenada.
6. Três bloqueios seguidos, ou uma verificação com mais de 30 minutos, impedem a retomada automática. O caminho restante é importar o arquivo.

## Estados

`ACCESS_GRANTED`, `CAPTCHA_DETECTED`, `HUMAN_VERIFICATION_REQUIRED`, `AUTHENTICATION_REQUIRED`, `ACCESS_DENIED`, `RATE_LIMITED`, `UNKNOWN_BLOCK`, `NAVIGATION_ERROR`.

O script de um provedor, sozinho, não conta como CAPTCHA ativo. reCAPTCHA v2, hCaptcha e Turnstile entram quando há widget ou iframe. reCAPTCHA v3, que normalmente não mostra widget, não é tratado como bloqueio. O desafio da Cloudflare exige formulário e texto de verificação, ou redirecionamento para a URL de desafio junto com esse texto.

## O que foi testado

Páginas locais controladas, sem CAPTCHA real:

- página aberta;
- script de reCAPTCHA sem widget;
- widget de reCAPTCHA v2;
- widget de hCaptcha, inclusive com a extração pausada e retomada depois que a URL passou a responder o documento;
- widget de Turnstile;
- desafio simulado da Cloudflare;
- formulário de senha;
- HTTP 401 e 429;
- erro de navegação;
- verificação expirada e bloqueio repetido.

A suíte completa passou nesta máquina. Não há suporte universal a CAPTCHAs de produção. Um site que só libera o navegador em que a pessoa concluiu o desafio continua bloqueado para a captura, de propósito: a sessão do Electron não é exportada.

## Compatibilidade e recuperação

A captura continua usando o Chromium e o Playwright que já existem. O JavaScript da página é executado e a primeira carga espera o DOM e, por até três segundos, a rede ficar ociosa. Isso não muda o identificador do navegador.

Antes do download, o aplicativo lê o `robots.txt` quando ele está disponível. Um caminho proibido não é pedido. Há um limite de pedidos simultâneos por domínio e um timeout opcional por domínio, em Configurações.

Erros temporários de rede e respostas 5xx podem ser repetidos no máximo três vezes, com espera crescente e um pequeno intervalo aleatório. Um HTTP 429 com `Retry-After` de até 30 segundos tem no máximo uma nova tentativa. HTTP 401, 403, CAPTCHA, desafio, login e sessão expirada não são repetidos. Uma resposta pública já obtida pode ser reaproveitada por dois minutos, sem guardar página de bloqueio.

Se a própria página indicar um PDF no mesmo site, o painel oferece esse arquivo. A captura não procura espelhos nem outras fontes. O painel mostra o domínio, o estado, a proteção detectada, o método autorizado, as tentativas, a próxima ação e o histórico.

Os cenários locais cobrem desafio, CAPTCHA, 429, 403, sessão expirada, JavaScript obrigatório, PDF público, robots.txt, falha de rede e o limite de concorrência. Não há compatibilidade universal com proteções de sites.
