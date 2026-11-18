# -*- coding: utf-8 -*-
"""
Analise dos cenarios ja resolvidos. Nao resolve o modelo de novo: le a base e as solucoes gravadas.

1. Situacao atual (AS-IS)
   - cobertura da APS pelo parametro do exercicio (3.000 pessoas por eSF) e pelo metodo do Ministerio da
     Saude (Nota Tecnica 301/2022: 3.500 por eSF, 2.625 por eAP de 30 h, 1.750 por eAP de 20 h);
   - custo anual da rede atual pelas mesmas regras de custo do modelo (DefCusto1 a DefCusto3 do .mod
     aplicadas as quantidades atuais);
   - capacidade atual x necessidade (eSF, especialistas, equipamentos, leitos);
   - tempo ate a UBS existente mais proxima.
2. Acessibilidade espacial da APS (G2SFCA: duas etapas com area de captacao flutuante e decaimento
   gaussiano; Luo e Wang 2003; Dai 2010). Oferta = eSF de cada UBS; demanda = populacao do setor;
   area de captacao = 25 min (a pe nos setores urbanos, de carro nos rurais), o limite de tempo da APS.
3. Avaliacao de cada cenario nos 1.924 setores: cada setor herda a UBS do seu ponto agregado.
4. Saidas: relatorio/fig/*.png, resultados/analise/*.csv|json e mapa/dados_mapa.json (mapa interativo).

Uso
  python codigo/analise_cenarios.py [--resultados PASTA]
  PASTA padrao: resultados/gurobi_2026-11-03 (rodada oficial do Gurobi).
"""
import argparse
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
DADOS = RAIZ / "dados"
XL = DADOS / "base_uberlandia.xlsx"
GPKG = DADOS / "_cache" / "udi_setores.gpkg"
FIG = RAIZ / "relatorio" / "fig"
TAB = RAIZ / "resultados" / "analise"
MAPA = RAIZ / "mapa"

CENARIOS = [  # (pasta, rotulo curto, demanda, folga)
    ("agregado_caderno_modo1", "Caderno · custo mínimo", "caderno", 0.00),
    ("agregado_caderno_modo2_folga05", "Caderno · +5%", "caderno", 0.05),
    ("agregado_caderno_modo2_folga10", "Caderno · +10%", "caderno", 0.10),
    ("agregado_observada_modo1", "Observada · custo mínimo", "observada", 0.00),
    ("agregado_observada_modo2_folga05", "Observada · +5%", "observada", 0.05),
    ("agregado_observada_modo2_folga10", "Observada · +10%", "observada", 0.10),
]
T0 = 25.0              # area de captacao da APS (min)
POP_POR_ESF = 3000     # parametro do exercicio
NT301 = dict(eSF=3500, eAP30=2625, eAP20=1750)   # Nota Tecnica 301/2022-CGESF/DESF/SAPS/MS


# ----------------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------------
def ler_base():
    xl = pd.ExcelFile(XL)
    st = xl.parse("Setores", dtype={"CD_SETOR": str})
    T = xl.parse("t01_min").set_index("setor")
    D = xl.parse("d01_km").set_index("setor")
    T, D = T.loc[st.id_modelo], D.loc[st.id_modelo]
    j1 = xl.parse("APS_J1")
    j2 = xl.parse("Secundaria_J2")
    j3 = xl.parse("Terciaria_J3")
    d123 = xl.parse("d12_d23")
    return st, T, D, j1, j2, j3, d123


def ler_dat(caminho):
    """Le do .dat so os parametros de custo, quantidades atuais e demanda (formatos usados pelo gerador)."""
    txt = caminho.read_text(encoding="ascii", errors="replace")

    def bloco(nome):
        m = re.search(rf"param {nome} :=(.*?);", txt, re.S)
        return m.group(1) if m else ""

    def lista(nome, chave2=False):
        out = {}
        for ln in bloco(nome).splitlines():
            ln = ln.split("#")[0].strip()
            if not ln:
                continue
            if chave2:
                m = re.match(r"\[([^,\]]+),([^\]]+)\]\s+([-\d.e+]+)", ln)
                if m:
                    a, b = m.group(1), m.group(2)
                    out[(a, int(b) if b.isdigit() else b)] = float(m.group(3))
            else:
                p = ln.split()
                if len(p) >= 2:
                    out[p[0]] = float(p[1])
        return out

    def tabela(cols):
        m = re.search(r"param:\s+" + r"\s+".join(cols) + r"\s*:=(.*?);", txt, re.S)
        out = {}
        for ln in m.group(1).splitlines():
            p = ln.split("#")[0].split()
            if len(p) == len(cols) + 1:
                out[p[0]] = dict(zip(cols, map(float, p[1:])))
        return out

    num = lambda nome: float(re.search(rf"param {nome} := ([-\d.e+]+);", txt).group(1))
    return dict(
        prop_SUS=num("prop_SUS"), c=dict(ESF=num("custo_ESF"), ESB=num("custo_ESB"), ACS=num("custo_ACS"),
                                         EMU=num("custo_EMU")),
        existente1=lista("existente1"), porte_min1=lista("porte_min1"), ESF_atual=lista("ESF_atual"),
        ESB_atual=lista("ESB_atual"), ACS_atual=lista("ACS_atual"), EMU_atual=lista("EMU_atual"),
        cf1=lista("custo_fixo1", True), cf2=lista("custo_fixo2"), cf3=lista("custo_fixo3"),
        existente2=lista("existente2"), existente3=lista("existente3"),
        r2=tabela(["salario2", "carga2", "n2_max_padrao"]), r3=tabela(["salario3", "carga3", "n3_max_padrao"]),
        consumo2=lista("consumo2", True), consumo3=lista("consumo3", True),
        n2_atual=lista("n2_atual", True), n3_atual=lista("n3_atual", True),
        taxa2=tabela(["taxa2", "escala2"]), prop23=lista("prop23", True))


def ler_cenario(pasta):
    sol = json.loads((pasta / "solucao.json").read_text(encoding="utf-8"))
    resumo = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
    ubs = pd.read_csv(pasta / "res_ubs.csv")
    vinc = pd.read_csv(pasta / "res_setores.csv")

    def var(prefixo, n):
        out = {}
        for k, v in sol.items():
            if k.startswith(prefixo + "["):
                partes = k[len(prefixo) + 1:-1].split(",")
                out[tuple(partes) if n > 1 else partes[0]] = v
        return out

    return dict(sol=sol, resumo=resumo, ubs=ubs, vinc=vinc, z12=[k for k, v in var("z12", 2).items() if v > 0.5],
                z23=[k for k, v in var("z23", 2).items() if v > 0.5], n2=var("n2", 2), n3=var("n3", 2),
                rec2=var("rec2", 2), rec3=var("rec3", 2), a2=var("a2", 1), a3=var("a3", 1))


# ----------------------------------------------------------------------------
# Acessibilidade espacial (G2SFCA)
# ----------------------------------------------------------------------------
def peso_gauss(T, t0=T0):
    """Decaimento gaussiano de Dai (2010): 1 no ponto, 0 no limite t0, 0 alem dele."""
    T = np.asarray(T, float)
    w = (np.exp(-0.5 * (T / t0) ** 2) - np.exp(-0.5)) / (1 - np.exp(-0.5))
    return np.where(np.isfinite(T) & (T <= t0), w, 0.0)


def g2sfca(T, pop, oferta, t0=T0):
    """Etapa 1: razao oferta/demanda de cada UBS (R_j = S_j / soma_i P_i W_ij).
    Etapa 2: acessibilidade do setor (A_i = soma_j R_j W_ij). Devolve A_i em eSF por pessoa."""
    W = peso_gauss(T, t0)
    dem = pop @ W
    R = np.divide(oferta, dem, out=np.zeros_like(oferta, dtype=float), where=dem > 0)
    return W @ R, R, dem


def classes_acess(indice, pop):
    """Percentual da populacao por faixa do indice (1,0 = 1 eSF acessivel para cada 3.000 pessoas)."""
    tot = pop.sum()
    f = lambda m: float(pop[m].sum() / tot)
    return dict(sem_acesso=f(indice <= 1e-9), abaixo_05=f((indice > 1e-9) & (indice < 0.5)),
                de_05_a_1=f((indice >= 0.5) & (indice < 1.0)), adequado=f(indice >= 1.0),
                media=float((indice * pop).sum() / tot), mediana=float(np.median(np.repeat(indice, (pop // 10).astype(int)))))


# ----------------------------------------------------------------------------
# Situacao atual
# ----------------------------------------------------------------------------
def custo_atual(p):
    """Custo anual da rede existente pelas regras do .mod (DefCusto1-3) com as quantidades atuais."""
    ex1 = [j for j, v in p["existente1"].items() if v == 1]
    c = p["c"]
    aps_fixo = sum(p["cf1"][(j, int(max(1, p["porte_min1"].get(j, 1))))] for j in ex1)
    aps_eq = {k: sum(p[k + "_atual"].get(j, 0) for j in ex1) for k in ("ESF", "ESB", "ACS", "EMU")}
    aps_eq_custo = {k: c[k] * v for k, v in aps_eq.items()}
    c1 = aps_fixo + sum(aps_eq_custo.values())
    ex2 = [k for k, v in p["existente2"].items() if v == 1]
    c2 = sum(p["cf2"][k] for k in ex2) + sum(p["r2"][r]["salario2"] * v for (k, r), v in p["n2_atual"].items())
    ex3 = [h for h, v in p["existente3"].items() if v == 1]
    c3 = sum(p["cf3"][h] for h in ex3) + sum(p["r3"][r]["salario3"] * v for (h, r), v in p["n3_atual"].items())
    return dict(c1=c1, c2=c2, c3=c3, total=c1 + c2 + c3, aps_fixo=aps_fixo, aps_equipes=aps_eq,
                aps_equipes_custo=aps_eq_custo)


def necessidade(p, pop_total):
    """Recursos necessarios para a demanda do cenario (uso / capacidade de uma unidade), sem arredondar."""
    dem2 = {s: p["prop_SUS"] * pop_total * v["taxa2"] / v["escala2"] for s, v in p["taxa2"].items()}
    dem3 = {}
    for (s, q), v in p["prop23"].items():
        dem3[q] = dem3.get(q, 0) + v * dem2[s]
    n2 = {r: sum(p["consumo2"].get((s, r), 0) * dem2[s] for s in dem2) / p["r2"][r]["carga2"] for r in p["r2"]}
    n3 = {r: sum(p["consumo3"].get((q, r), 0) * dem3[q] for q in dem3) / p["r3"][r]["carga3"] for r in p["r3"]}
    atual2 = {r: sum(v for (k, rr), v in p["n2_atual"].items() if rr == r) for r in p["r2"]}
    atual3 = {r: sum(v for (k, rr), v in p["n3_atual"].items() if rr == r) for r in p["r3"]}
    leito_dia = sum(p["consumo3"].get((q, r), 0) * dem3[q] for q in dem3 for r in p["r3"]
                    if r.startswith("LEITO") and not r.startswith(("LEITO_UTI", "LEITO_UCI")))
    return dict(dem2=dem2, dem3=dem3, n2=n2, n3=n3, atual2=atual2, atual3=atual3, leito_dia_enfermaria=leito_dia)


def oferta_e_utilizacao(cob, nec, prop_sus, pop_total):
    """Tabela 2 do artigo: razao oferta/populacao e utilizacao registrada / necessidade normativa (rede atual).

    Utilizacao registrada: SIA/TabNet ago/2025-jul/2026 por local de atendimento (inclui pacientes de outros
    municipios) e SIH/SUS set/2025-ago/2026, internacoes e leito-dia de residentes (aba Validacao da base).
    """
    import parametros_uberlandia as PU
    pop_sus = prop_sus * pop_total
    a2, a3 = nec["atual2"], nec["atual3"]
    leitos = sum(v for r, v in a3.items() if r.startswith("LEITO"))
    sia = {s: sum(v[i] for v in PU.SIA.values()) for i, s in enumerate(("CONS_ESP", "US", "TC", "RM"))}
    sih_internacoes, sih_leito_dia = 39950, 213000
    return dict(
        hab_por_eSF_eq=pop_total / cob["eSF_eq"],
        especialistas_por_10mil_sus=1e4 * a2["MED_ESP"] / pop_sus,
        rm_por_100mil_sus=1e5 * a2["EQ_RM"] / pop_sus,
        leitos_por_mil_sus=1e3 * leitos / pop_sus,
        uso_registrado={**sia, "internacoes": sih_internacoes, "leito_dia": sih_leito_dia},
        uso_sobre_necessidade={**{s: sia[s] / nec["dem2"][s] for s in sia},
                               "internacoes": sih_internacoes / sum(nec["dem3"].values()),
                               # Aqui a necessidade e so de leitos de enfermaria (sem UTI/UCI): 205 mil -> 1,04.
                               # O artigo (Tabela 2, p. 8, e validacao, p. 14) compara com 209 mil leitos-dia do Caderno para
                               # 2026 -> 1,02. A diferenca e de escopo da necessidade, nao erro de conta.
                               "leito_dia_enfermaria": sih_leito_dia / nec["leito_dia_enfermaria"]})


def cobertura_atual(j1, pop_total):
    ex = j1[j1.existente == 1]
    eAP = int(ex.eAP.sum())
    eAP_eq = float(ex.eAP_eq.sum())
    eq_exercicio = int(ex.ESF_atual.sum())
    return dict(ubs=len(ex), eSF=int(ex.eSF.sum()), eAP=eAP, eAP_eq=eAP_eq, eSF_eq=eq_exercicio,
                eSB=int(ex.eSB.sum()), ACS=int(ex.ACS.sum()), eMulti=int(ex.eMulti.sum()),
                pessoas_exercicio=eq_exercicio * POP_POR_ESF, cobertura_exercicio=eq_exercicio * POP_POR_ESF / pop_total)


# ----------------------------------------------------------------------------
# Principal
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resultados", type=Path, default=RAIZ / "resultados" / "gurobi_2026-11-03")
    a = ap.parse_args()
    for d in (FIG, TAB, MAPA):
        d.mkdir(parents=True, exist_ok=True)

    st, T, D, j1, j2, j3, d123 = ler_base()
    pop = st.populacao.values.astype(float)
    P = pop.sum()
    cols = list(T.columns)
    jx = {j: k for k, j in enumerate(cols)}
    j1 = j1.set_index("id").loc[cols].reset_index()
    ex = (j1.existente == 1).values
    Tv, Dv = T.values.astype(float), D.values.astype(float)
    p_cad = ler_dat(DADOS / "dados_uberlandia_agregado.dat")
    p_obs = ler_dat(DADOS / "dados_uberlandia_agregado_demanda_obs.dat")
    saida = dict(resultados=Path(os.path.relpath(a.resultados.resolve(), RAIZ)).as_posix())

    # ---------------- 1. Situacao atual ----------------
    cob = cobertura_atual(j1, P)
    # modalidade das eAP pela carga do medico (mesma regra do gerador: 20 h = 0,5; 30 h = 0,75; 35 h ou + = 1,0).
    # Contagem do CNES registrada na aba Parametros (equivalencia eAP -> eSF): 31 de 20 h, 18 de 30-33 h e
    # 22 de 35 h ou mais (31 x 0,5 + 18 x 0,75 + 22 x 1,0 = 51 eSF-equivalentes). A NT 301/2022 so tem as
    # modalidades de 20 h e 30 h; as de 35 h ou mais entram como 30 h.
    n20, n30, n40 = 31, 18, 22
    pessoas_nt301 = cob["eSF"] * NT301["eSF"] + n20 * NT301["eAP20"] + (n30 + n40) * NT301["eAP30"]
    cob.update(eAP_20h=n20, eAP_30h=n30, eAP_35h=n40, pessoas_nt301=pessoas_nt301,
               cobertura_nt301=pessoas_nt301 / P, pop_2026=P)
    Tex = np.where(ex[None, :], Tv, np.inf)
    jm = Tex.argmin(1)
    t_atual = Tex[np.arange(len(st)), jm]
    d_atual = Dv[np.arange(len(st)), jm]
    ok_atual = (Dv[:, ex] <= 5).any(1) | (Tv[:, ex] <= 25).any(1)
    urb = (st.situacao == "Urbana").values
    oferta_atual = np.where(ex, j1.ESF_atual.values.astype(float), 0.0)
    A0, R0, dem0 = g2sfca(Tv, pop, oferta_atual)
    idx0 = A0 * POP_POR_ESF
    est_atual = dict(
        t_medio=float((t_atual * pop).sum() / P),
        pop_ate_15=float(pop[t_atual <= 15].sum() / P), pop_ate_25=float(pop[t_atual <= 25].sum() / P),
        pop_sem_ubs_no_limite=float(pop[~ok_atual].sum()), setores_sem_ubs_no_limite=int((~ok_atual).sum()),
        urbana_ate_25=float(pop[urb & (t_atual <= 25)].sum() / pop[urb].sum()),
        acess=classes_acess(idx0, pop))
    custo0 = custo_atual(p_cad)
    nec_cad, nec_obs = necessidade(p_cad, P), necessidade(p_obs, P)
    saida.update(cobertura=cob, atual=est_atual, custo_atual=custo0, nec_caderno=nec_cad, nec_observada=nec_obs,
                 oferta_utilizacao=oferta_e_utilizacao(cob, nec_cad, p_cad["prop_SUS"], P))

    # ---------------- 2-3. Cenarios ----------------
    linhas, estados = [], {"atual": dict(ubs_idx=jm, t=t_atual, idx=idx0, oferta=oferta_atual)}
    cen_json = {}
    for pasta, rot, dem, folga in CENARIOS:
        c = ler_cenario(a.resultados / pasta)
        vinc = dict(zip(c["vinc"].setor, c["vinc"].ubs))
        u_set = st.ponto_agregado.map(vinc)
        assert u_set.notna().all(), pasta
        ui = u_set.map(jx).values
        t = Tv[np.arange(len(st)), ui]
        d = Dv[np.arange(len(st)), ui]
        fora = ~((d <= 5) | (t <= 25))
        ofe = np.zeros(len(cols))
        for _, r in c["ubs"].iterrows():
            ofe[jx[r.ubs]] = r.eSF
        A, R, dm = g2sfca(Tv, pop, ofe)
        idx = A * POP_POR_ESF
        acc = classes_acess(idx, pop)
        res = c["resumo"]
        ln = dict(cenario=pasta, rotulo=rot, demanda=dem, folga=folga, custo_bi=res["custo_total"] / 1e9,
                  aps_mi=res["custo_aps"] / 1e6, n2_mi=res["custo_sec"] / 1e6, n3_mi=res["custo_ter"] / 1e6,
                  gap=res["gap"], eSF=res["eSF_total"], ubs_novas=res["ubs_novas"], n2_novas=res["sec_novas"],
                  hosp_novos=res["hosp_novos"], dist_casa_ubs=float((d * pop).sum() / P),
                  dist_ubs_n2=res["dist_ubs_sec_km"], dist_n2_hosp=res["dist_sec_ter_km"],
                  tempo_medio_urbano=float((t[urb] * pop[urb]).sum() / pop[urb].sum()),
                  pop_ate_15_urbana=float(pop[urb & (t <= 15)].sum() / pop[urb].sum()),
                  pop_acima_25_urbana=float(pop[urb & (t > 25)].sum() / pop[urb].sum()),
                  setores_fora_limite=int(fora.sum()), pop_fora_limite=float(pop[fora].sum()),
                  acess_media=acc["media"], acess_mediana=acc["mediana"], acess_sem=acc["sem_acesso"],
                  acess_abaixo_05=acc["abaixo_05"], acess_05_1=acc["de_05_a_1"], acess_adequado=acc["adequado"])
        linhas.append(ln)
        estados[pasta] = dict(ubs_idx=ui, t=t, idx=idx, oferta=ofe)
        cen_json[pasta] = dict(c=c, ln=ln, R=R)
    tab = pd.DataFrame(linhas)
    acc0 = est_atual["acess"]
    tab = pd.concat([pd.DataFrame([dict(cenario="atual", rotulo="Rede atual (AS-IS)", demanda="-", folga=np.nan,
                                         custo_bi=custo0["total"] / 1e9, aps_mi=custo0["c1"] / 1e6,
                                         n2_mi=custo0["c2"] / 1e6, n3_mi=custo0["c3"] / 1e6, eSF=cob["eSF_eq"],
                                         ubs_novas=0, n2_novas=0, hosp_novos=0,
                                         dist_casa_ubs=float((d_atual * pop).sum() / P),
                                         tempo_medio_urbano=float((t_atual[urb] * pop[urb]).sum() / pop[urb].sum()),
                                         pop_ate_15_urbana=float(pop[urb & (t_atual <= 15)].sum() / pop[urb].sum()),
                                         pop_acima_25_urbana=float(pop[urb & (t_atual > 25)].sum() / pop[urb].sum()),
                                         setores_fora_limite=int((~ok_atual).sum()),
                                         pop_fora_limite=float(pop[~ok_atual].sum()),
                                         acess_media=acc0["media"], acess_mediana=acc0["mediana"],
                                         acess_sem=acc0["sem_acesso"], acess_abaixo_05=acc0["abaixo_05"],
                                         acess_05_1=acc0["de_05_a_1"], acess_adequado=acc0["adequado"])]), tab],
                    ignore_index=True)
    tab.to_csv(TAB / "cenarios_acessibilidade.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    pd.DataFrame(dict(setor=st.CD_SETOR, pop=pop, **{f"idx_{k}": v["idx"].round(3) for k, v in estados.items()},
                      **{f"tempo_{k}": v["t"].round(1) for k, v in estados.items()})).to_csv(
        TAB / "acessibilidade_por_setor.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    saida["cenarios"] = linhas
    (TAB / "analise.json").write_text(json.dumps(saida, indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o),
                                                 ensure_ascii=False), encoding="utf-8")

    figuras(st, j1, j2, j3, estados, cen_json)
    exportar_mapa(st, j1, j2, j3, d123, estados, cen_json, cob, est_atual, custo0, nec_cad, p_cad, tab)
    imprimir(saida, tab)


# ----------------------------------------------------------------------------
# Figuras do relatorio
# ----------------------------------------------------------------------------
def _malha(st):
    import geopandas as gpd
    g = gpd.read_file(GPKG)[["CD_SETOR", "geometry"]].to_crs(4326)
    g["CD_SETOR"] = g.CD_SETOR.astype(str)
    return g.merge(st[["CD_SETOR"]].reset_index(), on="CD_SETOR").sort_values("index").reset_index(drop=True)


def figuras(st, j1, j2, j3, estados, cen_json):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    g = _malha(st)
    urb = j1[j1.existente == 1]
    zoom = (urb.lon.quantile(0.02) - 0.03, urb.lon.quantile(0.98) + 0.03,
            urb.lat.quantile(0.02) - 0.03, urb.lat.quantile(0.98) + 0.03)
    # paleta sequencial do relatorio (indice de acessibilidade: 0 a 1,5+)
    lim = [0, 1e-9, 0.25, 0.5, 0.75, 1.0, 1.25, 10]
    cores = ["#b8b2a7", "#7a1f2b", "#c4513a", "#e9a15a", "#cfe0b4", "#6fb59a", "#1f7a6d"]
    cmap, norm = ListedColormap(cores), BoundaryNorm(lim, 7)
    paineis = [("atual", "A. Rede atual (AS-IS)"), ("agregado_caderno_modo1", "B. Custo mínimo (Caderno)"),
               ("agregado_caderno_modo2_folga05", "C. Orçamento +5% (Caderno)")]
    fig, axs = plt.subplots(1, 3, figsize=(16, 6.2))
    for ax, (k, tit) in zip(axs, paineis):
        g.assign(v=estados[k]["idx"]).plot(column="v", cmap=cmap, norm=norm, ax=ax, linewidth=0.03, edgecolor="#ffffff")
        of = estados[k]["oferta"]
        on = of > 0
        ax.scatter(j1.lon[on], j1.lat[on], s=6 + 7 * of[on], facecolors="none", edgecolors="#14212b", linewidths=0.8,
                   zorder=3)
        ax.set_xlim(zoom[0], zoom[1]); ax.set_ylim(zoom[2], zoom[3]); ax.set_axis_off()
        acc = classes_acess(estados[k]["idx"], st.populacao.values.astype(float))
        ax.set_title(f"{tit}\n{100 * acc['adequado']:.0f}% da população com índice ≥ 1,0; "
                     f"{100 * acc['sem_acesso']:.0f}% sem UBS a 25 min", fontsize=10.5, loc="left")
    rot = ["sem UBS a 25 min", "< 0,25", "0,25–0,5", "0,5–0,75", "0,75–1,0", "1,0–1,25", "≥ 1,25"]
    hs = [plt.Rectangle((0, 0), 1, 1, color=c) for c in cores]
    fig.legend(hs, rot, loc="lower center", ncol=7, frameon=False, fontsize=9.5,
               title="Índice de acessibilidade G2SFCA (1,0 = 1 eSF ao alcance para cada 3.000 pessoas; círculos = UBS, tamanho = nº de eSF)",
               title_fontsize=9.5)
    fig.tight_layout(rect=(0, 0.09, 1, 0.96))
    fig.savefig(FIG / "fig_acessibilidade.png", dpi=130)
    plt.close(fig)

    # situacao atual: tempo ate a UBS existente mais proxima
    lim_t = [0, 10, 15, 20, 25, 1e9]
    cores_t = ["#d9ece4", "#9fcfbe", "#f1d58b", "#e8925a", "#a8323a"]
    cmap_t, norm_t = ListedColormap(cores_t), BoundaryNorm(lim_t, 5)
    fig, axs = plt.subplots(1, 2, figsize=(15, 7), gridspec_kw=dict(width_ratios=[1, 1.15]))
    for ax, z in zip(axs, (None, zoom)):
        g.assign(v=estados["atual"]["t"]).plot(column="v", cmap=cmap_t, norm=norm_t, ax=ax, linewidth=0.03,
                                               edgecolor="#ffffff")
        ax.scatter(urb.lon, urb.lat, s=8 + 9 * urb.ESF_atual, c="#14212b", zorder=3, alpha=0.85)
        e2 = j2[j2.existente == 1]
        ax.scatter(e2.lon, e2.lat, s=110, marker="s", c="#2f55a4", edgecolors="white", zorder=4)
        e3 = j3[j3.existente == 1]
        ax.scatter(e3.lon, e3.lat, s=120, marker="^", c="#7a3b69", edgecolors="white", zorder=4)
        if z:
            ax.set_xlim(z[0], z[1]); ax.set_ylim(z[2], z[3])
        ax.set_axis_off()
    axs[0].set_title("A. Município (setores rurais: tempo de carro)", loc="left", fontsize=11)
    axs[1].set_title("B. Sede urbana (tempo a pé)", loc="left", fontsize=11)
    rot = ["até 10 min", "10–15 min", "15–20 min", "20–25 min", "mais de 25 min"]
    hs = [plt.Rectangle((0, 0), 1, 1, color=c) for c in cores_t]
    hs += [plt.Line2D([], [], marker="o", ls="", color="#14212b", ms=7),
           plt.Line2D([], [], marker="s", ls="", color="#2f55a4", ms=8),
           plt.Line2D([], [], marker="^", ls="", color="#7a3b69", ms=8)]
    rot += ["UBS existente (tamanho = eSF-equivalentes)", "ambulatório especializado", "hospital"]
    fig.legend(hs, rot, loc="lower center", ncol=4, frameon=False, fontsize=9.5,
               title="Tempo da casa até a UBS existente mais próxima", title_fontsize=10)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    fig.savefig(FIG / "fig_atual_tempo.png", dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Dados do mapa interativo
# ----------------------------------------------------------------------------
def exportar_mapa(st, j1, j2, j3, d123, estados, cen_json, cob, est_atual, custo0, nec, p, tab):
    from shapely.geometry import mapping
    g = _malha(st).to_crs(31982)
    g["geometry"] = g.geometry.simplify(12, preserve_topology=True)
    g = g.to_crs(4326)

    def arred(o):
        if isinstance(o, (list, tuple)):
            return [arred(x) for x in o]
        return round(o, 5)

    ordem = ["atual"] + [c[0] for c in CENARIOS]
    feats = []
    area = st.AREA_KM2.values
    for i, r in st.iterrows():
        geo = mapping(g.geometry[i])
        feats.append(dict(type="Feature", geometry=dict(type=geo["type"], coordinates=arred(geo["coordinates"])),
                          properties=dict(s=r.CD_SETOR, p=int(r.populacao), b=str(r.bairro), di=str(r.distrito),
                                          r=1 if r.situacao == "Rural" else 0, g=str(r.ponto_agregado),
                                          de=round(float(r.populacao / max(area[i], 1e-6)), 0),
                                          u=[int(estados[k]["ubs_idx"][i]) for k in ordem],
                                          t=[round(float(estados[k]["t"][i]), 1) for k in ordem],
                                          a=[round(float(estados[k]["idx"][i]), 3) for k in ordem])))
    # UBS
    ubs = []
    for k, r in j1.iterrows():
        e = dict(id=r.id, nome=str(r.nome).title(), cnes=None if pd.isna(r.cnes) else int(r.cnes),
                 lon=round(r.lon, 5), lat=round(r.lat, 5), ex=int(r.existente),
                 atual=dict(eSF=int(r.eSF), eAP=int(r.eAP), eAP_eq=float(r.eAP_eq), eSF_eq=int(r.ESF_atual),
                            eSB=int(r.eSB), ACS=int(r.ACS), eMulti=int(r.eMulti)) if r.existente == 1 else None,
                 end=None if pd.isna(r.endereco_cnes) else str(r.endereco_cnes).title(), cen={})
        ubs.append(e)
    uix = {u["id"]: k for k, u in enumerate(ubs)}
    n2 = [dict(id=r.id, nome=str(r.nome), ex=int(r.existente), lon=round(r.lon, 5), lat=round(r.lat, 5),
               atual={c[6:]: int(r[c]) for c in j2.columns if c.startswith("atual_")}, cen={}) for _, r in j2.iterrows()]
    n3 = [dict(id=r.id, nome=str(r.nome), ex=int(r.existente), lon=round(r.lon, 5), lat=round(r.lat, 5),
               atual={c[6:]: int(r[c]) for c in j3.columns if c.startswith("atual_")}, cen={}) for _, r in j3.iterrows()]
    i2 = {u["id"]: k for k, u in enumerate(n2)}
    i3 = {u["id"]: k for k, u in enumerate(n3)}
    for pasta, *_ in CENARIOS:
        c = cen_json[pasta]["c"]
        R = cen_json[pasta]["R"]
        ref2 = dict(c["z12"])
        ref3 = dict(c["z23"])
        for _, r in c["ubs"].iterrows():
            ubs[uix[r.ubs]]["cen"][pasta] = dict(porte=int(r.porte), eSF=int(r.eSF), eSB=int(r.eSB), ACS=int(r.ACS),
                                               eMulti=int(r.eMulti), pop=int(round(r.pop_adscrita)),
                                               ref=ref2.get(r.ubs), R=round(float(R[uix[r.ubs]] * POP_POR_ESF), 3))
        for u in n2:
            k = u["id"]
            if c["a2"].get(k, 0) > 0.5:
                u["cen"][pasta] = dict(n={r: int(round(v)) for (kk, r), v in c["n2"].items() if kk == k},
                                       rec={s: round(v) for (kk, s), v in c["rec2"].items() if kk == k},
                                       ref=ref3.get(k))
        for u in n3:
            k = u["id"]
            if c["a3"].get(k, 0) > 0.5:
                u["cen"][pasta] = dict(n={r: int(round(v)) for (kk, r), v in c["n3"].items() if kk == k},
                                       rec={s: round(v) for (kk, s), v in c["rec3"].items() if kk == k})
    # uso dos recursos (mesma conta do relatorio do .mod)
    for u in n2:
        for pasta, cc in u["cen"].items():
            cc["uso"] = {r: round(sum(p["consumo2"].get((s, r), 0) * cc["rec"].get(s, 0) for s in p["taxa2"])
                                  / (p["r2"][r]["carga2"] * n), 2) for r, n in cc["n"].items() if n > 0}
    for u in n3:
        for pasta, cc in u["cen"].items():
            S3 = sorted({q for (q, _) in p["consumo3"]})
            cc["uso"] = {r: round(sum(p["consumo3"].get((q, r), 0) * cc["rec"].get(q, 0) for q in S3)
                                  / (p["r3"][r]["carga3"] * n), 2) for r, n in cc["n"].items() if n > 0}
    tab_j = tab.replace({np.nan: None}).to_dict(orient="records")
    dados = dict(ordem=ordem, rotulos=["Rede atual (AS-IS)"] + [c[1] for c in CENARIOS], cenarios=tab_j,
                 setores=dict(type="FeatureCollection", features=feats), ubs=ubs, n2=n2, n3=n3,
                 cobertura=cob, atual=est_atual, custo_atual={k: v for k, v in custo0.items() if k != "aps_equipes_custo"},
                 necessidade=dict(n2={k: round(v, 1) for k, v in nec["n2"].items()},
                                  n3={k: round(v, 1) for k, v in nec["n3"].items()},
                                  atual2=nec["atual2"], atual3=nec["atual3"],
                                  dem2={k: round(v) for k, v in nec["dem2"].items()},
                                  dem3={k: round(v) for k, v in nec["dem3"].items()}))
    (MAPA / "dados_mapa.json").write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":"),
                                                     default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                                          encoding="utf-8")


def imprimir(saida, tab):
    c = saida["cobertura"]
    print(f"Cobertura (3.000/eSF): {c['eSF_eq']} eSF-eq x 3000 = {c['pessoas_exercicio']:,} / {c['pop_2026']:,.0f} "
          f"= {100 * c['cobertura_exercicio']:.1f}%")
    print(f"Cobertura (NT 301/2022): {c['pessoas_nt301']:,} = {100 * c['cobertura_nt301']:.1f}%")
    ca = saida["custo_atual"]
    print(f"Custo da rede atual (regras do modelo): {ca['total'] / 1e6:.1f} mi "
          f"(APS {ca['c1'] / 1e6:.1f}; N2 {ca['c2'] / 1e6:.1f}; N3 {ca['c3'] / 1e6:.1f})")
    print(json.dumps(saida["atual"], indent=1, ensure_ascii=False))
    n = saida["nec_caderno"]
    print("N2 necessario x atual:", {r: (round(v, 1), n["atual2"][r]) for r, v in n["n2"].items()})
    print("N3 necessario x atual:", {r: (round(v, 1), n["atual3"][r]) for r, v in n["n3"].items()})
    print("Dem3 caderno:", {k: round(v) for k, v in n["dem3"].items()}, round(sum(n["dem3"].values())),
          "leito-dia enf.:", round(n["leito_dia_enfermaria"]))
    o = saida["nec_observada"]
    print("Dem3 observada:", round(sum(o["dem3"].values())), "leito-dia enf.:", round(o["leito_dia_enfermaria"]))
    ou = saida["oferta_utilizacao"]
    print(f"Oferta/populacao: 1 eSF-eq para {ou['hab_por_eSF_eq']:,.0f} hab.; "
          f"{ou['especialistas_por_10mil_sus']:.2f} especialista/10 mil SUS; {ou['rm_por_100mil_sus']:.2f} RM/100 mil SUS; "
          f"{ou['leitos_por_mil_sus']:.2f} leito/mil SUS")
    print("Utilizacao registrada / necessidade:", {k: round(v, 2) for k, v in ou["uso_sobre_necessidade"].items()})
    pd.set_option("display.width", 250)
    print(tab.drop(columns=["cenario"]).round(3).to_string())


if __name__ == "__main__":
    main()
