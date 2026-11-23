# Revisão: como o texto é construído

Data: 21 de novembro de 2026. Origem: DOCX de teste gerado de uma norma técnica digitalizada em duas colunas.

## Como o texto nasce

1. `pdf_analysis` decide por página: camada de texto do PDF ou OCR (Tesseract).
2. Palavras viram linhas. Linhas viram parágrafos (`layout.py`).
3. `classify_blocks` dá a categoria: título, subtítulo, parágrafo, cabeçalho, ruído etc.
4. `reading_order` fixa a ordem. `_rebuild_elements` cria os elementos e liga parágrafos entre colunas e páginas.
5. `exporting` escreve DOCX, PDF, TXT e JSON.

## Pontos fortes (mantidos)

- Texto digital: camada de texto lida direto, sem OCR. Confiança 99.
- Honestidade: tabela sem células estáveis guarda a imagem e não inventa valor. Fórmula complexa preserva o recorte.
- Revisão: cada região guarda original e edição. A exportação lê a região viva, sem novo OCR.
- Segurança de rede, fila persistente, recuperação, exportação sem sobrescrever em silêncio.
- Testes honestos sobre o que foi medido, e lista de problemas abertos (`SCIELO_ISSUES.md`).

## Pontos fracos encontrados e o que foi feito

| # | Sintoma no DOCX | Causa no código | Correção |
| --- | --- | --- | --- |
| 1 | "immeitely", "nates", "ISO 1093-11", "Parentheses" | Página renderizada em escala 2 (144 DPI) antes do Tesseract | Renderização em ~300 DPI só para OCR, contraste e deskew |
| 2 | "1. Scope 1.1 … 1.2 Inclusions 1.2.1 …" num bloco | Toda linha próxima era colada; cláusula, recuo e linha curta não contavam | `starts_new_paragraph` em `layout.py` |
| 3 | Colunas intercaladas: texto da coluna 2 entre linhas da coluna 1 | `_page_flow` reordenava tudo por `y` | Elementos mantêm a ordem de leitura; só tabela/imagem/fórmula são encaixadas |
| 4 | Frases do meio do corpo em fonte gigante ("ing processes for medical devices…") | Altura do box do OCR usada como tamanho de fonte | Percentil 75 das palavras e filtro de fragmento |
| 5 | "1.3.1.1 Validation … medi-" como título | Regra "começa com número e não termina em ponto" | Forma de título: curta, maiúscula inicial, sem hífen final |
| 6 | Tabelas falsas com texto de duas colunas misturado | Vão da calha lido como colunas de tabela; o texto real era apagado | Página em colunas não gera tabela sem linhas; texto não é apagado |
| 7 | Palavras da célula embaralhadas (S7) | Ordenação por `(round(y,3), x)` | Agrupar por linha, depois por x |
| 8 | "Atualize o sumário no Word…" e sumário vazio | TOC sempre inserido; títulos no estilo Subtitle, fora do sumário | Sumário só com 3+ títulos, preenchido, com Heading 1–3 |
| 9 | "Designation: F3127" vs "E3127" no corpo | OCR sem consenso entre ocorrências | Reparo só com maioria clara (empate fica como está) |
| 10 | "Devices!" no título | Nota sobrescrita lida como "!" | `clean_heading_text` |
| 11 | "< 一", "ER" e outros restos da figura | OCR de desenho sem filtro | Categoria `noise` fora da exportação |

## Ainda aberto

- Não tenho o PDF original da norma. As correções foram verificadas numa página sintética em duas colunas, não no arquivo real. O DOCX enviado tem erros de leitura que não dá para reconstruir sem a fonte. Reprocese o PDF com esta versão.
- Número de cláusula lido sem pontos ("735" por "7.3.5") não é reconhecido como início de cláusula.
- Tabela em fluxograma (Apêndice X2) depende de linhas desenhadas e de boa leitura; mude para 300 DPI ajuda, mas não há medição.
- Tesseract foi testado só com `eng` neste ambiente. Português e chinês seguem sem medição.
- Sem acesso ao Windows, o instalador segue sem teste. Três testes falham neste ambiente por motivo externo: fonte chinesa (`WQY`) e DNS (`example.com`). Falhavam antes.
