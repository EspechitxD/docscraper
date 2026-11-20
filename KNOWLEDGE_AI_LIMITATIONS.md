# CPMH Knowledge AI — limitações

O que está em uso e o que não está.

## Implementado e testado

- Indexação do documento já processado, inclusive tabela estruturada, figura com a ressalva de pixels e fórmula sem transcrição.
- Atualização do índice quando a região OCR muda. O texto antigo sai da resposta.
- Busca no documento, no projeto e na biblioteca global, com conversa persistente.
- Recusa quando não há termo distintivo no acervo.
- Comparação por documento, sem misturar o número de uma fonte na coluna da outra.
- Relatório DOCX com as fontes que passaram no filtro.
- Exclusão do documento remove o texto da busca.
- A biblioteca continua consultável depois de reabrir o banco.
- Download de modelo recusado sem consentimento e recusado para `127.0.0.1`.

## Experimental ou ausente

- Não há modelo de linguagem local carregado. A resposta padrão é extrativa. Ela não redige um parecer.
- O embedding não é neural. Paráfrase fora do léxico fixo pode falhar ou cair na recusa.
- Não foram medidos Recall@K, Precision@K nem MRR num conjunto grande anotado. O arquivo de benchmark lista só as perguntas que o teste executou.
- Imagens não são interpretadas. A legenda é texto; os pixels não entram no modelo.
- Fórmula complexa não vira LaTeX.
- O grafo cobre poucos padrões e marca coocorrência como inferida.
- Fine-tuning não roda. O portão só armazena exemplo aprovado e rejeita resposta crua do modelo.
- llama.cpp não é distribuído. O instalador Windows não foi executado.
- Não há cancelamento de geração no sentido de interromper um modelo, porque a resposta extrativa termina na própria requisição.
- RAM, VRAM e velocidade de um LLM não foram medidas.

## O que não se deve concluir

Indexar não treina. Consultar um documento não faz o modelo “aprender” de forma permanente. Uma citação só existe se o identificador foi recuperado pela aplicação.
