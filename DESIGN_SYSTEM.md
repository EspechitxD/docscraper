# Design system

A interface usa a identidade publicada em https://www.cpmh.com.br/. As cores abaixo foram lidas do HTML e dos arquivos do site em 20 de novembro de 2026. Nenhuma foi inventada para “parecer” a marca.

## Arquivos oficiais

- Marca compacta: favicon `e6ca22_78930b3b2c57439dbf25721724f85dfa`. O mestre publicado tem 50×50 px. As cópias de 192 e 512 px são ampliações do Wix. O pixel opaco dominante da marca é `#F1551F`, próximo da cor de tema `color_13` `#F25620`.
- Ícone Windows: `assets/icons/cpmh.ico`, gerado a partir da ampliação de 512 px, sem redesenhar o símbolo.
- O SVG inline do cabeçalho, viewBox `0 0 798.61 180.45`, preenchimento `#ff5000`, é o logotipo Conecta. O link em volta dele aponta para `https://conecta.cpmhdigital.com.br/login`. Está guardado em `assets/branding/conecta-header.svg` e não entra na interface.
- O SVG indicado como logotipo do negócio no JSON-LD (`e6ca22_7b8d5fc5966a4de19273eb663ce2e827.svg`) respondeu HTTP 403. Não há wordmark vetorial público da CPMH neste repositório.
- O PNG de degradê associado ao nome de arquivo `cpmhdigital.com.br` não é logotipo e não é usado.

O nome “CPMH Digital” na barra é texto da interface, composto ao lado da marca oficial.

## Cores do tema Wix

| Token do site | Hex | Uso na interface |
| --- | --- | --- |
| `color_11` | `#FFFFFF` | superfícies |
| `color_12` | `#000000` | não é o fundo principal |
| `color_13` | `#F25620` | laranja de tema |
| `color_14` | `#EA2F14` | erro e destaque profundo |
| `color_15` | `#29282A` | texto |
| `color_16` | `#D1D4D1` | linhas |
| `color_17` | `#A5A9A6` | apoio |
| `color_18` | `#EDEDED` | fundo |
| `color_19` / botão `--bg` | `#FF5000` / `rgb(255, 80, 0)` | ação primária e preenchimento do SVG Conecta |
| `color_20` | `#575757` | texto secundário |
| rampa | `#22272A`, `#434E54`, `#65767F`, `#879DA9`, `#BFCCD4` | barra lateral e traços |

A barra lateral usa `#22272A`. O raio dos controles é 2 px. Não há gradiente decorativo.

## Tipografia

Space Grotesk nos títulos, Gantari no texto e JetBrains Mono em endereços e identificadores. As três estão no pacote `@fontsource`, licença SIL Open Font License. Zalando Sans Expanded aparece no site e não é redistribuída.

## Categorias do overlay

As caixas usam o laranja, o vermelho profundo, o carvão e os cinzas da rampa, com traço contínuo, tracejado ou pontilhado para separar categorias próximas. Não há uma cor nova por categoria.

## Estados

Sucesso permanece no carvão. Alerta usa `#F25620`. Erro usa `#EA2F14`. Confiança alta, intermediária e baixa compara o escore do motor com os limiares gravados nas preferências.

## Janela

Mínimo de 1100×680. A grade de indicadores passa a três colunas em 1366 px de largura. A verificação visual feita neste ambiente está em TESTING.md.
