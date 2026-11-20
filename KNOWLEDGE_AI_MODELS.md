# CPMH Knowledge AI — modelos

Nenhum peso foi baixado nem medido nesta máquina. A matriz abaixo separa o que está em execução do que é apenas uma sugestão de catálogo.

## Em execução

| Peça | Identificador | Tipo | Tamanho | Licença | Medido aqui |
| --- | --- | --- | --- | --- | --- |
| Embedding ativo | `cpmh-hash-v1` | projeção local, 256 dimensões | código do aplicativo, sem arquivo de pesos | código do repositório | gera vetor normalizado sem rede |
| Linguagem | nenhum | — | — | — | `llm_ready` falso; Ollama e llama.cpp ausentes |
| Embedding neural | nenhum | — | — | — | `neural_embedding` falso |

O vetor ativo não é da família BGE e não é multilíngue no sentido neural. Termos iguais ou expandidos pelo léxico se encontram. Uma paráfrase fora do léxico pode não ser recuperada. Trocar o identificador do embedding no futuro invalida os vetores: a busca só usa vetores do modelo ativo, e a reindexação regrava os segmentos.

## Catálogo, não instalado

A tela lista sugestões. O aplicativo não busca esses arquivos.

| Perfil | Sugestão | Por que está na lista | Licença a conferir no arquivo | Medição |
| --- | --- | --- | --- | --- |
| Compacto | Qwen2.5 0.5B Instruct, quantização Q4 | modelo pequeno, instrução, licença permissiva da família Qwen2.5 | Apache-2.0, conferir o arquivo antes de distribuir | não medido: sem RAM, VRAM nem velocidade |
| Equilibrado | Qwen2.5 3B Instruct, quantização Q4 | janela e instrução melhores que o 0.5B, ainda distribuível depois, com consentimento | Apache-2.0, conferir o arquivo antes de distribuir | não medido |

Llama, Gemma e Mistral também cabem no runtime, se o arquivo for GGUF e o usuário consentir o download. Não foram escolhidos como padrão porque nenhum foi executado em português neste ambiente. Não há requisito mínimo de hardware publicado: ele só pode ser escrito depois de medir um arquivo real.

## Ollama e llama.cpp

- Ollama é opcional e só entra se já estiver escutando em `127.0.0.1:11434` com um modelo instalado pelo usuário.
- llama.cpp não está empacotado. Sem o binário, um GGUF baixado fica registrado e não é carregado.

## Ambiente da verificação

Linux x86_64, 4 CPUs, em 20 de novembro de 2026. Nenhum modelo neural foi carregado, então RAM e VRAM de inferência não foram medidas.
