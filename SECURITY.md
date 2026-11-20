# Segurança e privacidade

O aplicativo processa documentos cuja captura o usuário declara estar autorizado a fazer. Ele não contorna DRM, paywall, autenticação ou controle de acesso, e não desativa proteção de conteúdo.

## URLs

Só entram `http` e `https`, sem usuário ou senha na URL. São recusados loopback, redes privadas, link-local, multicast, endereço não especificado e o metadado `169.254.169.254`, inclusive quando escrito em decimal, octal ou hexadecimal. A resolução DNS é rejeitada se qualquer endereço retornado estiver bloqueado. Redirecionamentos são revalidados, com limite de cinco saltos. A preferência “permitir rede local” libera endereços privados e de loopback, mas o metadado de nuvem continua bloqueado.

Downloads têm timeout e tamanho máximo. Assinaturas de executável MZ e ELF são recusadas. Arquivos importados passam por extensão e assinatura.

## Processo

O backend escuta apenas em `127.0.0.1`, `localhost` ou `::1` e exige `CPMH_API_TOKEN`. A comparação do token é em tempo constante. O Chromium embutido usa sandbox, isolamento de contexto e sem integração com Node. Permissões de câmera, microfone e localização são negadas. Cada navegação e cada redirecionamento voltam à validação da API.

A captura Playwright aplica a mesma validação a cada requisição da página.

## Dados

Senhas, tokens, cookies e chaves não são gravados no log. O relatório técnico não inclui o texto dos documentos. Exportações não são escritas dentro da pasta de instalação nem em diretórios de sistema. Arquivo existente só é substituído se o usuário escolher substituir. Caso contrário a API responde `409 name_collision`.

Tradução externa exige URL configurada e consentimento na tarefa. Sem isso, nenhum texto sai do computador. Neste ambiente não há provedor externo configurado nem Argos instalado. O aplicativo não baixa modelos de tradução nem binários de OCR por conta própria.

A exclusão de uma imagem só apaga o arquivo se nenhuma outra imagem, tabela ou fórmula apontar para o mesmo caminho. O aplicativo empacotado não executa o Python instalado na máquina quando o backend congelado está ausente.

A retenção do cache é uma preferência. Documentos do usuário não são apagados na desinstalação prevista: o instalador NSIS está com `deleteAppDataOnUninstall` desligado. Esse instalador ainda não foi executado.
