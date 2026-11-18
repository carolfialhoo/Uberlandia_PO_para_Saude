# Rede hierárquica do SUS em Uberlândia (MG)

Trabalho da disciplina EPD899 – *Operations Research for Health Care* (DEP/UFMG, prof. João Flávio de Freitas Almeida).
Autores: Arthur Navarro Bessa, Carolina Fialho e Kevin Patrocinio.

O modelo decide quantas UBS abrir, onde e com que porte, quais unidades secundárias e hospitais abrir e para onde cada setor censitário e cada unidade encaminha.

## Por onde começar

1. **`relatorio/Artigo_EPD899_Rede_SUS_Uberlandia.pdf`**: o artigo (30 páginas, sem código, como pedido pelo professor): diagnóstico da rede atual (cobertura oficial, cobertura geográfica e acessibilidade nos três níveis, orçamento), formulação matemática, resultados e os 108 parâmetros com fonte.
2. **`relatorio/relatorio.html`**: relatório técnico em HTML, mais extenso, com o código e o passo a passo de cada conta.
3. **`mapa/mapa_rede_sus.html`**: o mapa interativo, com a rede atual e os seis cenários.

## Pastas

| Pasta | O que tem |
|---|---|
| `relatorio/` | Artigo em PDF (`Artigo_EPD899_Rede_SUS_Uberlandia.pdf`), relatório em HTML (`relatorio.html`), figuras (`fig/`) e os arquivos que montam o relatório (`relatorio_fonte.html`, `montar_relatorio.py`) |
| `mapa/` | Mapa interativo (`mapa_rede_sus.html`) e os arquivos que o montam |
| `modelo/` | Modelo em GMPL (`modelo_rede_saude_v02.mod`) e dados fictícios para teste rápido no GUSEK (`dados_exemplo_ficticio.dat`) |
| `codigo/` | Scripts Python: parâmetros, geração da base, solução dos cenários e análise |
| `dados/` | Bases do modelo (`.dat`), documentação dos parâmetros (`base_uberlandia.xlsx`) e malha do IBGE (`_cache/`) |
| `dados/orcamento/` | RREO da saúde de Uberlândia (Anexos 2 e 12) |
| `dados/cobertura_aps/` | Cobertura oficial da APS e de ACS de Uberlândia (e-Gestor AB, jan./2024 a ago./2026) |
| `dados/contratos_gestao/` | Contratos de gestão das OS, de onde saem os custos da APS (fora do pacote de entrega pelo tamanho) |
| `resultados/gurobi_2026-11-03/` | Rodada oficial: resumo dos seis cenários e, por cenário, relatório, CSVs e mapa |
| `resultados/highs_2026-10-29/` | Resumo da rodada anterior com o HiGHS (só para a comparação da Tabela 17) |
| `resultados/analise/` | Situação atual e acessibilidade espacial da APS (G2SFCA) por cenário e por setor; cobertura geográfica e acessibilidade dos três níveis (`acesso_niveis.csv`, `acesso_niveis_captacao15.csv`, `calibracao_tempo_carro.csv`) |
| `referencial_teorico/` | Artigos da bibliografia (`artigos/`) e slides das aulas 2 a 6 e 8 (`aulas_EPD899/`) |

## Como rodar

Os comandos rodam a partir desta pasta (Python 3.12). A lista completa está no Apêndice A do relatório.

```bash
python codigo/rodar_cenarios.py --base agregado --partidas --resultados resultados/nova_rodada   # resolve (Gurobi ou HiGHS)
python codigo/analise_cenarios.py      # situação atual e acessibilidade da APS (lê resultados/gurobi_2026-11-03)
python codigo/medidas_acesso_niveis.py # cobertura geográfica e G2SFCA nos três níveis (Aula 8) e Figura 8 do artigo
python mapa/montar_mapa.py             # refaz o mapa
python relatorio/montar_relatorio.py   # refaz o relatório
```

No GUSEK, abra `modelo/modelo_rede_saude_v02.mod` e associe `dados/dados_uberlandia_agregado.dat` (ou `modelo/dados_exemplo_ficticio.dat` para um teste em segundos).

## Anotações do professor e onde estão no artigo

| Anotação | Onde |
|---|---|
| Cobertura atual: não foi calculada, o governo tem a informação | Seção 4.3 e Tabela 1 (e-Gestor: 58,46% em ago./2026); 55,8% só como conferência |
| 62% SUS-dependentes (população − planos de saúde) | Seção 4.1 (ANS: π = 0,6216) |
| Agregação por k-means: ~1.900 setores → 392 pontos | Seção 5.3 (1.924 setores; 300 grupos + 92 setores) |
| 71 UBS e 31 candidatos; disponibilidade de terreno | Seção 5.4 (terrenos públicos nos níveis 2 e 3; UBS sem verificação de terreno, declarado como limitação) |
| Serviços de cada nível e demanda por serviço | Seção 3.2 e Quadro 2 |
| 108 parâmetros (26 inferidos, 7 decisão, 6 exercício) | Seção 5.2, Tabela 6 e Apêndice A |
| Unidades existentes fixadas | Quadro 1, seções 4.2 e 6.4 |
| Acessibilidade e utilização dos níveis 1, 2 e 3; medir cobertura e acessibilidade (Aula 8) | Seções 2.1–2.4 e 4.4, Tabelas 2 e 3; Tabelas 9 e 10 nos cenários |
| LOA e gastos com saúde (atenção primária × especializada) | Seção 4.5, Tabelas 4 e 5 |
| Arquivo .dat do modelo .mod | Seção 5.8; `dados/*.dat` |
| Lado alto (cenário observada, × 1,14) | Seção 5.7 e 7.3 |
| APS 537 + nível 2 61 + hospitais 733 = R$ 1,331 bi/ano; % federal, estadual e municipal | Seções 7.1 e 7.5, Tabela 11 |
