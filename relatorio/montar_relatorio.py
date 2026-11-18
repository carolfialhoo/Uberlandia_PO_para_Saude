# -*- coding: utf-8 -*-
"""
Monta relatorio/relatorio.html a partir de relatorio/relatorio_fonte.html.

Substitui os marcadores:
  <!--CODIGO:caminho-->  listagem completa do arquivo (caminho relativo a pasta do projeto), dentro de <details>
  <!--PARAMETROS-->      tabela dos 108 parametros da aba Parametros de base_uberlandia.xlsx, com link ou arquivo de
                         cada fonte (mapa FONTES abaixo)

Uso: python relatorio/montar_relatorio.py
"""
import html
import re
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent

# Fonte (trecho do texto da coluna Fonte) -> (rotulo, link ou None, arquivo na pasta ou None). A primeira regra que casa vale.
CONTRATOS = "https://www.uberlandia.mg.gov.br/portal-da-transparencia/contratos-de-gestao-de-saude/"
FONTES = [
    (r"enunciado", ("Enunciado do exercicio (EPD899)", None, None)),
    (r"Decisao do grupo", ("Decisao do grupo (out/2026)", None, "secao 5.5 do artigo")),
    (r"Nota Tecnica SEI 19911|NT SEI 19911", ("Nota tecnica da Taxa Social de Desconto",
                                             "https://www.gov.br/gestao/pt-br/central-de-conteudo/publicacoes/notas-tecnicas/2020/nt_taxa-social_vf.pdf", None)),
    (r"IN RFB 1\.700", ("IN RFB 1.700/2017", "http://normas.receita.fazenda.gov.br/sijut2consulta/link.action?idAto=81268", None)),
    (r"Contrato 388/2023|contrato 388/2023|Contrato de gestao 388/2023|388/2023",
     ("Contratos de gestao (Portal da Transparencia)", CONTRATOS,
      "dados/contratos_gestao/16°-ADITIVO-AO-CONTRATO-No-388-2023-Missao-Sal-da-Terra.pdf; dados/contratos_gestao/Contrato-388-2023-MISSÃO-SAL-DA-TERRA-1.pdf")),
    (r"Contratos de gestao", ("Contratos de gestao (Portal da Transparencia)", CONTRATOS,
                              "dados/contratos_gestao/16°-ADITIVO-AO-CONTRATO-No-388-2023-Missao-Sal-da-Terra.pdf")),
    (r"Decreto 12\.797", ("Decreto 12.797/2025 (salario minimo 2026)", "https://legislacao.presidencia.gov.br/", None)),
    (r"EC 120/2022|piso nacional do ACS", ("Emenda Constitucional 120/2022",
                      "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc120.htm", None)),
    (r"Lei 14\.434", ("Lei 14.434/2022", "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2022/lei/l14434.htm", None)),
    (r"Lei 7\.394", ("Lei 7.394/1985", "https://www.planalto.gov.br/ccivil_03/leis/l7394.htm", None)),
    (r"CAGED", ("Novo CAGED", "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/estatisticas-trabalho/novo-caged", None)),
    (r"COFEN 543", ("Resolucao COFEN 543/2017", "https://www.cofen.gov.br/resolucao-cofen-5432017/", None)),
    (r"Novo PAC", ("Novo PAC Saude", "https://www.gov.br/saude/pt-br/assuntos/novo-pac-saude", "dados/base_uberlandia.xlsx, aba Projetos_aprovados")),
    (r"Policlinica de Uberlandia", ("Novo PAC Saude", "https://www.gov.br/saude/pt-br/assuntos/novo-pac-saude", None)),
    (r"Portaria GM/MS 635", ("Portaria GM/MS 635/2023 (nota do COSEMS-SC)",
                             "https://www.cosemssc.org.br/wp-content/uploads/2023/05/nota-informativa-e-multi-portaria-635-2023-1684936021.pdf", None)),
    (r"PNAB", ("PNAB, Portaria 2.436/2017", "https://bvsms.saude.gov.br/bvs/saudelegis/gm/2017/prt2436_22_09_2017.html",
               "referencial_teorico/aulas_EPD899/EPD899_aula02_normas-MS.pdf")),
    (r"Portaria 1\.101", ("Caderno 1 e Portaria 1.101/2002",
                          "https://mapadasaude.goias.gov.br/documentos/Caderno-1-Criterios-e-Parametros-ASSISTENCIAIS-1-revisao.pdf", None)),
    (r"Caderno 1|Caderno", ("Caderno 1 de Parametros SUS (MS, 2017)",
                            "https://mapadasaude.goias.gov.br/documentos/Caderno-1-Criterios-e-Parametros-ASSISTENCIAIS-1-revisao.pdf", None)),
    (r"RDC ANVISA", ("RDC ANVISA 7/2010", "https://bvsms.saude.gov.br/bvs/saudelegis/anvisa/2010/res0007_24_02_2010.html", None)),
    (r"PNCP|Pregoes", ("PNCP (atas e pregoes)", "https://pncp.gov.br/app/editais", None)),
    (r"SMS Sao Paulo", ("Diario Oficial da Cidade de Sao Paulo", "https://diariooficial.prefeitura.sp.gov.br/", None)),
    (r"SPDM", ("SPDM, relatorios e transparencia", "https://www.spdm.org.br/", None)),
    (r"SIA", ("TabNet (producao ambulatorial SIA)", "https://datasus.saude.gov.br/informacoes-de-saude-tabnet/", "aba Validacao")),
    (r"SIH", ("SIH/SUS, microdados RD", "https://datasus.saude.gov.br/transferencia-de-arquivos/", "aba Validacao")),
    (r"SIDRA|estimativas populacionais", ("IBGE SIDRA 6579", "https://sidra.ibge.gov.br/tabela/6579", None)),
    (r"Registro Civil", ("IBGE SIDRA 2612", "https://sidra.ibge.gov.br/tabela/2612", None)),
    (r"Censo 2022, malha", ("IBGE, malha de setores 2022",
                            "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/malha_com_atributos/setores/gpkg/UF/MG/",
                            "dados/_cache/udi_setores.gpkg")),
    (r"ANS", ("ANS, dados abertos (PDA 047)", "https://dadosabertos.ans.gov.br/FTP/PDA/taxa_de_cobertura_de_planos_de_saude-047/", None)),
    (r"CNES|cnes\.datasus", ("CNES", "https://cnes.datasus.gov.br/", "aba APS_J1")),
    (r"OSRM|OpenStreetMap", ("OSRM / OpenStreetMap", "https://project-osrm.org/", "abas d01_km, t01_min, d12_d23")),
    (r"Prefeitura de Uberlandia", ("Portal da Prefeitura de Uberlandia", "https://www.uberlandia.mg.gov.br/", None)),
    (r"repositorio UFU", ("Repositorio institucional da UFU", "https://repositorio.ufu.br/", None)),
    (r"MEC", ("MEC (2025), noticia de obra de hospital universitario", None, None)),
    (r"Sahin|SBPO|Simposio", ("Padrao SBPO (SOBRAPO)", "https://www.sobrapo.org.br/", None)),
]


def fonte_link(texto):
    texto = "" if pd.isna(texto) else str(texto)
    for padrao, (rot, link, arq) in FONTES:
        if re.search(padrao, texto):
            return rot, link, arq
    if re.search(r"calculo|hipotese|mercado|duracao|^$|nao ha estimativa|caminhada|^-$|CRF|salario x|ferias|mesma conta",
                 texto):
        return "Calculo ou hipotese do grupo (raciocinio na ultima coluna)", None, "codigo/parametros_uberlandia.py"
    return None, None, None


CLASSE = {"EXERCICIO": "exe", "DECISAO": "dec", "NORMATIVO": "norm", "DADO": "dado", "INFERIDO": "inf"}


def tabela_parametros():
    p = pd.read_excel(RAIZ / "dados" / "base_uberlandia.xlsx", sheet_name="Parametros")
    p = p[p.Parametro.notna()]
    e = html.escape
    linhas = []
    for k, r in enumerate(p.itertuples(index=False), 1):
        rot, link, arq = fonte_link(r.Fonte)
        onde = []
        if link:
            onde.append(f'<a href="{e(link)}" target="_blank" rel="noopener">{e(rot)}</a>')
        elif rot:
            onde.append(e(rot))
        if arq:
            onde.append(f"<code>{e(arq)}</code>")
        cl = CLASSE.get(str(r.Classificacao), "inf")
        val = "" if pd.isna(r.Valor) else str(r.Valor)
        und = "" if pd.isna(r.Unidade) or r.Unidade == "-" else f" <span class=\"cm\">{e(str(r.Unidade))}</span>"
        rac = "" if pd.isna(r.Raciocinio) else e(str(r.Raciocinio))
        fon = "" if pd.isna(r.Fonte) else e(str(r.Fonte))
        linhas.append(f"<tr><td class=\"num\">{k}</td><td>{e(str(r.Grupo))}</td><td>{e(str(r.Parametro))}</td>"
                      f"<td>{e(val)}{und}</td><td><span class=\"cl {cl}\">{e(str(r.Classificacao).lower())}</span></td>"
                      f"<td>{fon}</td><td>{'<br>'.join(onde) or '—'}</td><td>{rac}</td></tr>")
    cab = ("<tr><th class=\"num\">#</th><th>Grupo</th><th>Parâmetro</th><th>Valor</th><th>Classe</th><th>Fonte</th>"
           "<th>Link ou arquivo</th><th>Raciocínio</th></tr>")
    return (f'<p class="tabcap"><b>Tabela C1.</b> Parâmetros da base de Uberlândia ({len(linhas)} linhas)</p>'
            f'<div class="rolar larga"><table class="tab-par"><thead>{cab}</thead><tbody>{"".join(linhas)}</tbody></table></div>'
            '<p class="fonte">As linhas do grupo "Dados" são as entradas brutas (populacao, matrizes, prop_SUS, CNES) que a '
            'planilha lista à parte. Arquivos citados estão na pasta do projeto; abas, em <code>dados/base_uberlandia.xlsx</code>.</p>')


def listagem(caminho):
    arq = RAIZ / caminho
    txt = arq.read_text(encoding="utf-8", errors="replace")
    n = txt.count("\n") + (0 if txt.endswith("\n") else 1)
    return (f'<details><summary><code>{html.escape(caminho)}</code> <span>({n} linhas)</span></summary>'
            f'<pre><code>{html.escape(txt)}</code></pre></details>')


def main():
    fonte = (AQUI / "relatorio_fonte.html").read_text(encoding="utf-8")
    saida = re.sub(r"<!--CODIGO:([^>]+?)-->", lambda m: listagem(m.group(1).strip()), fonte)
    saida = saida.replace("<!--PARAMETROS-->", tabela_parametros())
    (AQUI / "relatorio.html").write_text(saida, encoding="utf-8")
    print(f"relatorio.html: {len(saida) / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
