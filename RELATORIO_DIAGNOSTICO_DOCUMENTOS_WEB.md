# Relatório: diagnóstico de documentos em visualizadores web

Data: 21 de novembro de 2026.

## 1. Arquitetura anterior
A captura por navegador (`capture.py`) lia o DOM e a captura de HTML (`pages_from_downloaded_html`) lia o texto. Ambas só distinguiam "interface" de "documento" por tamanho dos blocos. O resultado era `interface_only` ou recusa, sem diagnóstico do motivo nem de caminhos legítimos.

## 2. Problemas encontrados
- Nenhuma distinção entre PDF acessível, PDF.js, imagem, canvas, login, CAPTCHA e pagamento.
- Páginas informadas pelo site apareciam sem separação das páginas processadas.
- Não havia contagem de caracteres documentais contra caracteres de interface, nem nota de qualidade.

## 3. Arquivos criados
`services/document_source_analyzer.py`, `browser_inspector.py`, `document_recovery.py`, `document_statistics.py`, `document_validator.py`, `document_report.py`, `diagnose.py`, `frontend/src/components/WebDocumentDiagnosis.tsx`, `tests/test_web_document_diagnosis.py`, este relatório.

## 4. Arquivos modificados
`api.py` (2 rotas), `frontend/src/screens/Diagnostics.tsx`, `CHANGELOG.md`.

## 5. Mapeamento do prompt
| Item | Situação |
|---|---|
| DocumentSourceAnalyzer, estados da seção 6 | Feito |
| Inspeção no Chromium | Código feito; **não executado** (sem Chrome no ambiente) |
| Estratégias A a F | Seleção feita. Execução automática só existia para HTML e imagens de página; PDF acessível e PDF.js indicam o caminho, mas o download automático não foi implementado |
| OCR (rotação, contraste, colunas, ordem de leitura, cabeçalho e rodapé) | Feito na rodada anterior |
| OCR: detecção automática de idioma, japonês | **Não feito** |
| Validação e qualidade | Feito |
| Contagens (páginas, caracteres, palavras) | Feito |
| Interface: seção de diagnóstico | Feita (tipos verificados) |
| Interface: comparação página a página com edição | Já existe na tela de revisão; não alterada |
| Testes com fixtures locais | 19 novos, todos aprovados |
| Teste DOC88 no Chromium | **Não executado** |

## 6. Testes
Suíte completa: 90 aprovados, 3 reprovados. Os 3 já reprovavam antes: fonte chinesa ausente (`WQY`) e DNS bloqueado no ambiente (`example.com`). Os testes de overlay e de captura HTML real exigem o Chrome e não foram rodados.

## 7. Resultado do teste DOC88
**A análise real no Chromium não foi executada.** O ambiente não tem Chrome nem acesso ao site. O que existe:
- A busca de texto da página retornou só interface, 452 caracteres em 69 blocos, e o site declara 16 páginas e 4000 pontos para baixar. O analisador, aplicado a esse texto, diagnostica `access_restricted`, com pagamento como restrição, 16 páginas informadas, 0 acessíveis e 0 processadas. Isso vale só para o texto, não para o que o Chrome veria (iframes, canvas, imagens).
- Para a análise real, rode no seu computador: `python -m cpmh_backend.diagnose https://www.doc88.com/p-20454998901780.html --out doc88.json`. O JSON mostra iframes, canvas, imagens e respostas de rede encontrados.

## 8. Limitações
- Sem execução em navegador real, o inspetor e a captura empilhada de folhas são código não exercitado.
- O inspetor conta como página só imagem já carregada. Visualizador que só carrega páginas após clique ou rolagem longa pode ser subestimado.
- Documento que o site mostra só em parte e exige pagamento para o resto fica como `partial_document` com `access_restricted`. O sistema não tenta o resto.
- OCR testado só com inglês neste ambiente.

## 9. Próximas melhorias
1. Rodar o diagnóstico do DOC88 no Windows e ajustar com o resultado.
2. Download automático de PDF acessível (estratégia B) reaproveitando a importação de arquivo.
3. Detecção automática de idioma e pacote de japonês no OCR.
4. Teste de integração com Chromium em CI, usando páginas locais que simulem PDF.js, canvas e imagens.
