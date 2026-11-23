# Problemas do benchmark SciELO

Origem de cada item: a primeira exportação automática em `benchmark_scielo/first_pass/`, comparada com o PDF e com a passagem em `benchmark_scielo/corrected/`.

## Corrigidos nesta rodada

| Id | Prioridade | Origem | O que acontecia | Correção |
| --- | --- | --- | --- | --- |
| S1 | P0 | Classificação | O título de quatro linhas, repetido como cabeçalho nas páginas seguintes, virava cabeçalho também na página 1. “Resumo” ocupava o estilo Título. | A mediana do corpo passa a pesar pelo volume de caracteres. Um bloco bem maior que o cabeçalho corrido não é rebaixado. Teste `test_repeated_running_header_does_not_demote_the_title`. |
| S2 | P0 | Tabela | Lacunas de texto distantes formavam uma grade da página inteira e apagavam o corpo. Páginas 6 e 9 quase sumiram do texto. | A grade de texto só fecha numa faixa contígua. Quando há linhas desenhadas, as células seguem essas linhas e o texto de fora permanece. Teste `test_distant_gaps_do_not_swallow_the_page`. |
| S3 | P1 | Layout | “Universidade” saía “Uni versidade” porque o marcador sobrescrito “a” fixava a linha-base e a letra “v” abria outra linha. | A linha usa o caractere mais alto como referência de base. Teste `test_superscript_marker_does_not_split_the_word`. |
| S4 | P1 | Imagem | O fluxograma vetorial não gerava figura. | Várias caixas próximas viram um recorte de diagrama, com a legenda de cima ou de baixo. O texto interno do desenho sai do corpo para não duplicar letras soltas. |
| S5 | P1 | Exportação | Legenda alterada na revisão e o texto das tabelas não entravam no TXT. | O TXT passa a incluir células e a legenda da imagem quando ela ainda não está no corpo. Teste `test_plain_text_includes_a_changed_image_caption`. |
| S6 | P2 | Classificação | Linha de referência com ano, volume e DOI virava título. | Linha bibliográfica não entra na regra de título. Seção numerada vira subtítulo antes da regra de título. |

Nenhuma correção é uma exceção com o nome deste artigo. Os testes usam blocos e caixas sintéticas.

## Ainda abertos

| Id | Prioridade | Origem | Impacto | Próximo passo | Aceite |
| --- | --- | --- | --- | --- | --- |
| S7 | P2 | Tabela | **Corrigido em 21/11/2026** (`_grid_from_ruled_box` usa `lines_from_words`). Dentro da célula, a ordem das palavras ainda mistura a segunda linha com a primeira. Exemplo real: “Population população?) (que”. | Ordenar as palavras da célula por linha e, dentro da linha, da esquerda para a direita, com uma tolerância de base. | A frase “(que população?)” aparece contínua na célula do quadro PICO. |
| S8 | P2 | Classificação | A primeira linha de uma referência, quando o ano está na linha seguinte, pode sair como subtítulo. Acontece com Xiao e Watson. | Tratar bloco em caixa alta seguido de “review.” ou de DOI na região seguinte como referência. | Essa linha deixa de usar estilo de subtítulo. |
| S9 | P2 | Imagem | Os rótulos de dentro do fluxograma não são texto selecionável. Estão no recorte. | Manter o recorte e, se a caixa tiver texto horizontal estável, acrescentar uma transcrição marcada como texto de figura. | O TXT declara que aqueles tokens estão na figura, ou os transcreve sem partir as palavras. |
| S10 | P3 | Exportação | O PDF editável tem 23 páginas, não 27. O JSON tem as 27. | Não tratar o PDF refluído como facsimile. Um modo visual página a página seria outro produto. | O relatório de exportação diz que a contagem do PDF editável pode diferir. |
| S11 | P3 | Classificação | **Corrigido em 21/11/2026** (`looks_like_fragment`). “Respondendo à QI que norteou este estudo –” ficou subtítulo. É um começo de parágrafo curto e sem ponto. | Exigir que subtítulo sem numeração não termine em travessão. | Esse trecho volta a parágrafo. |

Não há P0 aberto neste artigo depois da segunda passagem.
