# Comparação com o PDF original

Ferramenta independente: `pypdf`  (PdfReader.extract_text), mais `python-docx` para abrir o DOCX e o pdfium só para conferir a contagem de páginas do original. O processamento do aplicativo usa pdfium e a fila do backend. A comparação não altera o original.

O `pypdf` emitiu aviso de que fontTools não está instalado para as fontes Segoe UI do artigo. Os números abaixo usam o texto que ele devolveu mesmo assim.

## Texto

Tokens do corpo: linhas que aparecem em 8 ou mais páginas foram tiradas da referência, para não contar o expediente repetido (faixa da revista e cabeçalho corrido) como texto perdido. O TXT do aplicativo coloca esse expediente uma vez, no cabeçalho e no rodapé do DOCX.

| Medida | Primeira passagem | Depois da correção |
| --- | --- | --- |
| Tokens de referência | 8973 | 8973 |
| Tokens ausentes no TXT | 1421 | 132 |
| Tokens a mais no TXT | 18 | 20 |
| Recall | 0,8416 | 0,9853 |
| CER médio por página, regiões contra pypdf | 0,2561 | 0,1511 |
| Pior CER de página | 0,954 (página 9) | 0,612 (página 9) |

O CER alto da página 9, mesmo depois da correção, vem da lista de estudos ter ido para a tabela. O TXT passa a trazer essas células (`Artigo | Autores` está no arquivo corrigido). O CER das regiões não vê a célula; o recall do TXT vê.

Amostras conferidas no TXT corrigido: título, “Jennifer Silva”, “Universidade de Aveiro”, “webQDA”, DOI `10.1590`, “Considerações Finais”, “XIAO” e “Fluxograma”.

Não houve OCR neste arquivo. Os erros da primeira passagem foram de classificação, de junção de caracteres e de tabela, não de reconhecimento de glifo.

## Páginas

O original e o documento processado têm 27 páginas, sequências 1 a 27, sem duplicata. O PDF exportado tem 23 páginas na passagem corrigida e 24 na primeira. Esse PDF é o documento editável refluído, não uma impressão página a página. O JSON guarda as 27 páginas de origem, com largura e altura.

## Imagem

A página 8 não tem imagem embutida. O fluxograma é desenho vetorial. A primeira passagem não extraiu figura. A passagem corrigida recortou o conjunto de caixas, incluindo a faixa “Identificação de estudos…” e os rótulos laterais Identificação, Rastreio e Inclusão. A legenda associada é a da figura. O texto miúdo das caixas não volta como parágrafo; fica no recorte. Isso explica parte dos 132 tokens ausentes (`estudos`, `bases`, `dados`).

## Tabelas

Primeira passagem: 8 grades marcadas como confiáveis, com o cabeçalho da revista dentro da grade e o corpo da página removido do texto.

Passagem corrigida: as grades seguem as linhas desenhadas. O quadro PICO, o quadro de procedimentos de busca e a lista de artigos foram exportados. A ordem das palavras dentro de algumas células ainda troca o complemento de lugar, por exemplo “(que população?)” e “A0 1”. O conteúdo está na célula; a ordem interna não está fiel. Há uma grade sem linhas de texto, marcada como não confiável e sem entrar no DOCX.

## Formatação

No DOCX corrigido o título do artigo usa o estilo Título. “1 Introdução”, “2 Metodologia”, “3 Resultados” e “5 Considerações Finais” usam subtítulo. As legendas dos quadros e da figura usam legenda. “Referências” ficou como título de seção. Uma linha de referência que começa sem o ano, “XIAO, Y.; WATSON, M. Guidance…”, ainda sai como subtítulo; a continuação com ano, volume e DOI sai como referência.

Acentuação de “Avaliação”, “práticas”, “sistemática” e “Universidade” está preservada no TXT corrigido.
