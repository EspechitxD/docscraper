# Benchmark SciELO — plano

Data: 20 de novembro de 2026, horário de Brasília. Branch: `cursor/cpmh-phase-10-776e` (commit de partida `1bdde31`). Não havia alterações locais por commitar.

## Documento

- Título: Avaliação externa de escolas e sua relação com políticas e práticas inclusivas: uma revisão sistemática da literatura.
- Origem: SciELO, Ensaio: Avaliação e Políticas Públicas em Educação.
- URL: https://www.scielo.br/j/ensaio/a/nnh5ntMHZWGrC3qDVJ4LHrJ/?format=pdf&lang=pt
- DOI: 10.1590/S0104-40362025003305115
- O `curl` recebeu HTTP 403 da CDN (desafio BunnyCDN, código 112). O Chrome aberto pelo Playwright recebeu o PDF (`application/pdf`, 676380 bytes). O arquivo guardado começa com `%PDF-1.7`.
- SHA-256: `c3d13372a45637a51311e07593148c3661e8a0dabbf07b325db1441053fee5fd`
- Páginas confirmadas no arquivo: 27. Todas em retrato, 425,2 × 637,79 pt. Todas têm camada de texto (1376 a 3068 caracteres).
- Metadados do PDF: Creator Adobe InDesign 20.3, Producer Adobe PDF Library 17.0, criação 23 de maio de 2025. Título e autor no dicionário do PDF estão vazios.

## Ambiente

- Linux x86_64, Python 3.12.3, Node 22.23.4, Tesseract 5.3.4.
- Modelos OCR presentes: por, eng, chi_sim, chi_tra, osd.
- 4 CPUs. Memória da máquina: 15 GiB, com cerca de 4,4 GiB disponíveis no momento da leitura.
- O PDF é digital. O OCR entra só se uma página tiver menos de 8 caracteres na camada de texto. Neste arquivo, nenhuma página está nesse caso.
- Electron: a versão declarada no projeto é 33. A janela não é o caminho deste benchmark; o processamento usa os mesmos serviços que o Electron sobe.

## Procedimento

1. Rodar a suíte existente.
2. Criar o projeto pelo API do aplicativo e enviar o PDF.
3. Processar com tradução `none`, sem revisão prévia.
4. Exportar DOCX, PDF, TXT, JSON e pacote.
5. Comparar com o texto extraído de forma independente.
6. Fazer um ciclo de revisão em três regiões e reexportar.
7. Corrigir só falhas reproduzíveis de comportamento geral.
8. Decidir a Fase 11 com base no que os arquivos mostrarem.

A execução está em SCIELO_BENCHMARK_REPORT.md. A decisão foi o resultado A.
