# -*- coding: utf-8 -*-
"""
Roda os cenarios do modelo_rede_saude_v02.mod com a base de Uberlandia e gera resumo e mapas.

Cenarios
  demanda hospitalar: caderno (dados_uberlandia_<base>.dat) e observada (dados_uberlandia_<base>_demanda_obs.dat)
  objetivo: modo 1 (minimo custo) e modo 2 (minima distancia com orcamento = custo do modo 1 x (1 + folga))

Solver
  Gurobi (gurobipy ou gurobi_cl no PATH): modelo completo.
  Sem Gurobi: HiGHS em 3 fases.
    0) (modo 1) vinculo setor -> UBS: guloso (UBS existente mais proxima primeiro, ate 6 eSF por UBS) e MIP so da APS,
       os dois refinados por busca local, que move pontos entre UBS para reduzir o arredondamento das equipes;
       fica o vinculo de menor custo da APS;
    1) vinculo fixo; o resto (portes, equipes, niveis 2-3) e otimizado;
    2) cada ponto pode escolher entre as K UBS acessiveis mais proximas, partindo da solucao da fase 1;
    3) modelo completo, partindo da melhor solucao. Da um limitante inferior valido.
  Limitante do modo 1 = max(limitante da fase 3, LB_APS + LB_23), em que LB_APS vem do MIP da APS e LB_23 do modelo
  com as variaveis da APS continuas e objetivo Custo2 + Custo3 (o minimo da soma >= a soma dos minimos).
  O modo 2 pula a fase 0. A fase 1 gera partidas por soma ponderada (custo + mu x distancia, mu = 15, 40, 100):
  vinculo da APS pelo MIP da APS + busca local com esse peso; com o vinculo fixo, o resto minimiza a mesma soma.
  Concorre tambem a solucao do modo 1 com a sobra do orcamento gasta nos niveis 2-3. Fica a de menor distancia
  entre as que cabem no orcamento.

  Com Gurobi e --partidas, o modo 2 tambem comeca pelas partidas por soma ponderada (funcao partidas_modo2) e o Gurobi
  parte da melhor delas. Na rodada oficial de 03/11/2026 isso foi feito so no cenario Caderno +5%.

Saidas em resultados/rodada_AAAA-MM-DD/ (data do dia) ou na pasta de --resultados.
  A rodada oficial do Gurobi (03/11/2026) esta em resultados/gurobi_2026-11-03/.
  resumo_cenarios.csv e, por cenario: relatorio.txt (printf do .mod), res_setores.csv, res_ubs.csv e mapa.png.

Uso
  python codigo/rodar_cenarios.py [--base agregado|setores] [--tempo 1200] [--tempo2 1200] [--folgas 0.05 0.10]
                           [--demandas caderno observada] [--k 4] [--gap 0.005] [--reusar-modo1] [--partidas]
                           [--resultados PASTA]
A biblioteca GLPK do Python nao abre caminhos com acento: o script trabalha numa pasta temporaria.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import swiglpk as g

AQUI = Path(__file__).resolve().parent          # codigo/
RAIZ = AQUI.parent
DADOS = RAIZ / "dados"
MOD = RAIZ / "modelo" / "modelo_rede_saude_v02.mod"
RES = RAIZ / "resultados" / f"rodada_{time.strftime('%Y-%m-%d')}"   # padrao; --resultados troca
CACHE = Path(os.environ.get("EPD_CACHE", DADOS / "_cache"))
DAT = {"caderno": "dados_uberlandia_{}.dat", "observada": "dados_uberlandia_{}_demanda_obs.dat"}
TETO_ESF = 6 * 3000          # pessoas por UBS no vinculo guloso (porte 5 com 6 eSF)


# ----------------------------------------------------------------------------
# Leitura do .dat (so o necessario para o vinculo da APS)
# ----------------------------------------------------------------------------
def ler_dat(caminho):
    txt = open(caminho, encoding="ascii", errors="replace").read()

    def corpo(nome):
        return re.search(rf"param {nome} :=(.*?);", txt, re.S).group(1)

    def matriz(nome):
        linhas, cols = {}, None
        for ln in corpo(nome).splitlines():
            ln = ln.split("#")[0].strip()
            if not ln:
                continue
            if ln.startswith("[*,*]:"):
                cols = ln[len("[*,*]:"):].replace(":=", "").split()
                continue
            p = ln.split()
            linhas.setdefault(p[0], {}).update(zip(cols, map(float, p[1:])))
        return pd.DataFrame(linhas).T

    def lista(nome):
        return {p[0]: float(p[1]) for ln in corpo(nome).splitlines()
                if len(p := ln.split("#")[0].split()) >= 2}

    m01 = matriz("matriz01")
    num = lambda nome: float(re.search(rf"param {nome} := ([\d.e+-]+);", txt).group(1))
    t01 = matriz("t01").loc[m01.index]
    cf1 = {}
    for ln in corpo("custo_fixo1").splitlines():
        m = re.match(r"\s*\[([^,\]]+),(\d)\]\s+([\d.]+)", ln)
        if m:
            cf1[(m.group(1), int(m.group(2)))] = float(m.group(3))
    portes = {}
    for ln in re.search(r"param:\s+minESF.*?:=(.*?);", txt, re.S).group(1).splitlines():
        p = ln.split()
        if len(p) == 10:
            portes[int(p[0])] = dict(zip(["minESF", "maxESF", "minESB", "maxESB", "minACS", "maxACS", "minEMU", "maxEMU",
                                          "custo_porte"], map(float, p[1:])))
    return dict(pop=m01.pop("POP"), D=m01, T=t01[m01.columns],
                existente={k: int(v) for k, v in lista("existente1").items()},
                dmax=num("dmax01"), tmax=num("tmax01"), eps_dist=num("eps_dist"),
                porte_min=lista("porte_min1"), ESF_atual=lista("ESF_atual"), ESB_atual=lista("ESB_atual"),
                ACS_atual=lista("ACS_atual"), EMU_atual=lista("EMU_atual"), cf1=cf1, portes=portes,
                c=dict(ESF=num("custo_ESF"), ESB=num("custo_ESB"), ACS=num("custo_ACS"), EMU=num("custo_EMU")),
                pop_por=dict(ESF=num("pop_por_ESF"), ESB=num("pop_por_ESB"), ACS=num("pop_por_ACS")))


def vinculo_guloso(dd):
    """Cada ponto vai para a UBS existente acessivel mais proxima com folga; senao, para o candidato mais proximo."""
    D, T, pop = dd["D"].values, dd["T"].values, dd["pop"].values
    ok = (D <= dd["dmax"]) | (T <= dd["tmax"])
    ex = np.array([dd["existente"].get(j, 0) == 1 for j in dd["D"].columns])
    carga, escolha = np.zeros(D.shape[1]), np.full(D.shape[0], -1)
    for i in sorted(range(D.shape[0]), key=lambda i: (ok[i].sum(), -pop[i])):
        for j in sorted(np.where(ok[i])[0], key=lambda j: (0 if ex[j] else 1, D[i, j])):
            if carga[j] + pop[i] <= TETO_ESF:
                escolha[i] = j
                break
        if escolha[i] < 0:
            escolha[i] = min(np.where(ok[i])[0], key=lambda j: carga[j])
        carga[escolha[i]] += pop[i]
    I, J = list(dd["D"].index), list(dd["D"].columns)
    return {I[i]: J[escolha[i]] for i in range(len(I))}, ok


def k_proximas(dd, ok, k):
    D, I, J = dd["D"].values, list(dd["D"].index), list(dd["D"].columns)
    return {I[i]: {J[j] for j in sorted(np.where(ok[i])[0], key=lambda j: D[i, j])[:k]} for i in range(len(I))}


# ----------------------------------------------------------------------------
# APS: custo exato de uma UBS em funcao da populacao adscrita, busca local e limitante
# ----------------------------------------------------------------------------
def custo_ubs(dd, j, P):
    """Custo anual minimo da UBS j com populacao P (mesmas regras do .mod: R01-R21). inf se inviavel."""
    ex = dd["existente"].get(j, 0) == 1
    if P <= 1e-9 and not ex:
        return 0.0
    c, pp = dd["c"], dd["pop_por"]
    req = dict(ESF=max(dd["ESF_atual"].get(j, 0), np.ceil(P / pp["ESF"] - 1e-9)),
               ESB=max(dd["ESB_atual"].get(j, 0), np.ceil(P / pp["ESB"] - 1e-9) if pp["ESB"] > 0 else 0),
               ACS=max(dd["ACS_atual"].get(j, 0), np.ceil(P / pp["ACS"] - 1e-9) if pp["ACS"] > 0 else 0),
               EMU=dd["EMU_atual"].get(j, 0))
    melhor = np.inf
    for p in range(max(1, int(dd["porte_min"].get(j, 0))), 6):
        q = dd["portes"][p]
        n = {k: max(req[k], q["min" + k]) for k in req}
        if any(n[k] > q["max" + k] for k in n):
            continue
        melhor = min(melhor, dd["cf1"].get((j, p), q["custo_porte"]) + sum(c[k] * n[k] for k in n))
    return melhor


def custo_aps(dd, escolha):
    J = list(dd["D"].columns)
    P = dict.fromkeys(J, 0.0)
    for i, j in escolha.items():
        P[j] += dd["pop"][i]
    dist = sum(dd["pop"][i] * dd["D"].at[i, j] for i, j in escolha.items())
    return sum(custo_ubs(dd, j, P[j]) for j in J), dist


def busca_local(dd, escolha, ok, passes=30, seed=0, mu=None):
    """Move pontos entre UBS acessiveis enquanto o custo da APS + mu x pessoas.km cair (mu padrao = eps_dist).
    Ataca o arredondamento de equipes: cada UBS paga o teto de ceil(pop/3000) eSF, ceil(pop/750) ACS etc."""
    I, J = list(dd["D"].index), list(dd["D"].columns)
    jx = {j: k for k, j in enumerate(J)}
    D, pop, eps = dd["D"].values, dd["pop"].values, dd["eps_dist"] if mu is None else mu
    esc = np.array([jx[escolha[i]] for i in I])
    P = np.zeros(len(J))
    np.add.at(P, esc, pop)
    custo = np.array([custo_ubs(dd, J[k], P[k]) for k in range(len(J))])
    arcos = [np.where(ok[i])[0] for i in range(len(I))]
    rng = np.random.default_rng(seed)
    for _ in range(passes):
        mudou = False
        for i in rng.permutation(len(I)):
            a = esc[i]
            ca = custo_ubs(dd, J[a], P[a] - pop[i])
            melhor, alvo = -1e-6, None
            for b in arcos[i]:
                if b == a:
                    continue
                cb = custo_ubs(dd, J[b], P[b] + pop[i])
                d = (ca - custo[a]) + (cb - custo[b]) + eps * pop[i] * (D[i, b] - D[i, a])
                if d < melhor:
                    melhor, alvo, cbn = d, b, cb
            if alvo is not None:
                P[a] -= pop[i]
                P[alvo] += pop[i]
                custo[a], custo[alvo] = ca, cbn
                esc[i] = alvo
                mudou = True
        if not mudou:
            break
    return {I[i]: J[esc[i]] for i in range(len(I))}


def mip_aps(dd, ok, tempo, pasta, inicio=None, mu=0.0):
    """MIP simplificado da APS (sem porte e sem niveis 2-3), resolvido pelo HiGHS.
    Da (1) um limitante inferior VALIDO para o custo da APS (com mu = 0) e (2) um vinculo alternativo.
    inicio: vinculo {ponto: UBS} usado como solucao de partida. mu: peso de pessoas.km no objetivo (modo 2)."""
    import highspy
    I, J = list(dd["D"].index), list(dd["D"].columns)
    pop, c, pp, D = dd["pop"].values, dd["c"], dd["pop_por"], dd["D"].values
    ex = [dd["existente"].get(j, 0) == 1 for j in J]
    # custo fixo minimo de cada UBS aberta: custo do porte + e-Multi minima, no porte permitido mais barato
    fixo = [min(dd["cf1"].get((j, p), dd["portes"][p]["custo_porte"])
                + c["EMU"] * max(dd["EMU_atual"].get(j, 0), dd["portes"][p]["minEMU"])
                for p in range(max(1, int(dd["porte_min"].get(j, 0))), 6)) for j in J]
    const = sum(f for f, e in zip(fixo, ex) if e)   # UBS existentes ficam abertas (R02)
    L = ["Minimize", " obj: " + " + ".join(
        [f"{c['ESF']} n{k} + {c['ESB']} e{k} + {c['ACS']} s{k}" for k in range(len(J))] +
        [f"{fixo[k]} a{k}" for k in range(len(J)) if not ex[k]] +
        ([f"{mu * pop[i] * D[i, k]:.4f} y{i}_{k}" for i in range(len(I)) for k in np.where(ok[i])[0]] if mu else [])),
         "Subject To"]
    col = {k: [] for k in range(len(J))}
    for i in range(len(I)):
        arcs = np.where(ok[i])[0]
        L.append(f" c{i}: " + " + ".join(f"y{i}_{k}" for k in arcs) + " = 1")
        for k in arcs:
            col[k].append(i)
            if not ex[k]:
                L.append(f" v{i}_{k}: y{i}_{k} - a{k} <= 0")
            # cortes validos: o ponto sozinho ja exige ceil(pop/cap) equipes na UBS que o recebe
            for v, cap in (("n", pp["ESF"]), ("e", pp["ESB"]), ("s", pp["ACS"])):
                m = np.ceil(pop[i] / cap - 1e-9) if cap > 0 else 0
                if m > 1:
                    L.append(f" {v}{i}_{k}: {v}{k} - {m:.0f} y{i}_{k} >= 0")
    for k in range(len(J)):
        termo = " - ".join(f"{pop[i]} y{i}_{k}" for i in col[k]) or "0 n0"
        for v, cap in (("n", pp["ESF"]), ("e", pp["ESB"]), ("s", pp["ACS"])):
            if cap > 0 and col[k]:
                L.append(f" {v}c{k}: {cap} {v}{k} - {termo} >= 0")
        if not ex[k]:
            L.append(f" o{k}: n{k} - a{k} >= 0")
    L.append("Bounds")
    topo = dd["portes"][5]["maxESF"]
    for k, j in enumerate(J):
        plb = max(1, int(dd["porte_min"].get(j, 0)))
        lo = max(dd["ESF_atual"].get(j, 0), dd["portes"][plb]["minESF"]) if ex[k] else 0
        L.append(f" {lo} <= n{k} <= {max(topo, lo)}")
        L.append(f" e{k} >= {dd['ESB_atual'].get(j, 0)}")
        L.append(f" s{k} >= {dd['ACS_atual'].get(j, 0)}")
    L.append("General")
    L += [f" n{k} e{k} s{k}" for k in range(len(J))]
    L.append("Binary")
    L += [f" a{k}" for k in range(len(J)) if not ex[k]]
    L += [f" y{i}_{k}" for i in range(len(I)) for k in np.where(ok[i])[0]]
    L.append("End")
    (pasta / "aps.lp").write_text("\n".join(L))
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.readModel(str(pasta / "aps.lp"))
    h.setOptionValue("time_limit", float(tempo))
    h.setOptionValue("mip_rel_gap", 1e-4)
    if inicio:
        P = dict.fromkeys(range(len(J)), 0.0)
        jx = {j: k for k, j in enumerate(J)}
        v = {}
        for i, j in enumerate(I):
            k = jx[inicio[j]]
            v[f"y{i}_{k}"] = 1.0
            P[k] += pop[i]
        for k, j in enumerate(J):
            if P[k] > 0 or ex[k]:
                v[f"a{k}"] = 1.0
                plb = max(1, int(dd["porte_min"].get(j, 0)))
                lo = max(dd["ESF_atual"].get(j, 0), dd["portes"][plb]["minESF"]) if ex[k] else 1
                v[f"n{k}"] = max(lo, np.ceil(P[k] / pp["ESF"] - 1e-9))
                v[f"e{k}"] = max(dd["ESB_atual"].get(j, 0), np.ceil(P[k] / pp["ESB"] - 1e-9) if pp["ESB"] > 0 else 0)
                v[f"s{k}"] = max(dd["ACS_atual"].get(j, 0), np.ceil(P[k] / pp["ACS"] - 1e-9) if pp["ACS"] > 0 else 0)
        s = highspy.HighsSolution()
        s.col_value = [v.get(nm, 0.0) for nm in h.getLp().col_names_]
        s.value_valid = True
        h.setSolution(s)
    h.run()
    info = h.getInfo()
    lb = const + info.mip_dual_bound
    esc = None
    if info.primal_solution_status == 2:
        nomes = list(h.getLp().col_names_)
        val = dict(zip(nomes, h.getSolution().col_value))
        esc = {}
        for i in range(len(I)):
            arcs = np.where(ok[i])[0]
            esc[I[i]] = J[max(arcs, key=lambda k: val.get(f"y{i}_{k}", 0))]
    return lb, esc


def limitante_niveis23(mps, tempo):
    """Limitante VALIDO do custo dos niveis 2-3: modelo completo com as variaveis da APS continuas e objetivo
    Custo2 + Custo3. Somado ao limitante da APS da um limitante do custo total (min da soma >= soma dos min)."""
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.readModel(str(mps))
    nomes = list(h.getLp().col_names_)
    aps = ("a1[", "x1[", "nESF[", "nESB[", "nACS[", "nEMU[", "y[")
    idx = np.array([k for k, n in enumerate(nomes) if n.startswith(aps)], dtype=np.int32)
    h.changeColsIntegrality(len(idx), idx, np.array([highspy.HighsVarType.kContinuous] * len(idx)))
    h.changeColsCost(len(nomes), np.arange(len(nomes), dtype=np.int32),
                     np.array([1.0 if n in ("Custo2", "Custo3") else 0.0 for n in nomes]))
    h.setOptionValue("time_limit", float(tempo))
    h.run()
    return h.getInfo().mip_dual_bound


# ----------------------------------------------------------------------------
# Solvers
# ----------------------------------------------------------------------------
def tem_gurobi():
    try:
        import gurobipy  # noqa: F401
        return "gurobipy"
    except ImportError:
        return "gurobi_cl" if shutil.which("gurobi_cl") else None


def rodar_gurobi(mps, tempo, gap, inicio, pasta):
    if tem_gurobi() == "gurobipy":
        import gurobipy as gp
        m = gp.read(str(mps))
        m.Params.TimeLimit, m.Params.MIPGap, m.Params.OutputFlag = tempo, gap, 0
        if inicio:
            for v in m.getVars():
                if v.VarName in inicio:
                    v.Start = inicio[v.VarName]
        m.optimize()
        if m.SolCount == 0:
            return None
        return dict(obj=m.ObjVal, bound=m.ObjBound, gap=m.MIPGap, sol={v.VarName: v.X for v in m.getVars()})
    args = ["gurobi_cl", f"TimeLimit={tempo}", f"MIPGap={gap}", "ResultFile=sol.sol", "LogFile=gurobi.log"]
    if inicio:
        with open(pasta / "inicio.mst", "w") as f:
            f.writelines(f"{k} {v}\n" for k, v in inicio.items())
        args.append("InputFile=inicio.mst")
    subprocess.run(args + [str(mps)], cwd=pasta, capture_output=True)
    if not (pasta / "sol.sol").exists():
        return None
    sol = {}
    for ln in open(pasta / "sol.sol"):
        if ln.strip() and not ln.startswith("#"):
            k, v = ln.split()
            sol[k] = float(v)
    log = open(pasta / "gurobi.log").read()
    m = re.findall(r"Best objective ([-\d.e+]+), best bound ([-\d.e+]+), gap ([\d.]+)%", log)
    obj, bound, gp_ = (float(m[-1][0]), float(m[-1][1]), float(m[-1][2]) / 100) if m else (np.nan, np.nan, np.nan)
    return dict(obj=obj, bound=bound, gap=gp_, sol=sol)


def valor(mps, sol):
    """Valor da funcao objetivo do .mps para uma solucao {coluna: valor}."""
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.readModel(str(mps))
    lp = h.getLp()
    return float(np.dot(lp.col_cost_, [sol.get(n, 0.0) for n in lp.col_names_]) + lp.offset_)


def rodar_highs(mps, tempo, gap, inicio=None, zerar=(), objetivo=None, livres=()):
    """objetivo: {coluna: custo} troca a funcao objetivo; o 'obj' devolvido continua sendo o do .mps.
    livres: nomes de restricoes que deixam de valer (ex.: 'Orcamento[1]')."""
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.readModel(str(mps))
    h.setOptionValue("time_limit", float(tempo))
    h.setOptionValue("mip_rel_gap", gap)
    nomes = list(h.getLp().col_names_)
    for k, nm in enumerate(h.getLp().row_names_):
        if nm in livres:
            h.changeRowBounds(k, -highspy.kHighsInf, highspy.kHighsInf)
    if objetivo:
        n = len(nomes)
        h.changeColsCost(n, np.arange(n, dtype=np.int32), np.array([objetivo.get(x, 0.0) for x in nomes]))
    if zerar:
        idx = np.array([k for k, n in enumerate(nomes) if n in zerar], dtype=np.int32)
        h.changeColsBounds(len(idx), idx, np.zeros(len(idx)), np.zeros(len(idx)))
    if inicio:
        s = highspy.HighsSolution()
        s.col_value = [inicio.get(n, 0.0) for n in nomes]
        s.value_valid = True
        h.setSolution(s)
    h.run()
    info = h.getInfo()
    if info.primal_solution_status != 2:
        return None
    sol = dict(zip(nomes, h.getSolution().col_value))
    if objetivo:
        return dict(obj=valor(mps, sol), bound=np.nan, gap=np.nan, sol=sol)
    return dict(obj=info.objective_function_value, bound=info.mip_dual_bound, gap=info.mip_gap, sol=sol)


def fmt(r, campo="obj"):
    return f"{r[campo]:.6g}" if r else "-"


def partidas_modo2(dat_txt, nomes_y, inicio, dd, escolha, ok, tempo, gap):
    """Partidas do modo 2 por soma ponderada (usadas pelo HiGHS e, com --partidas, antes do Gurobi).
    Com orcamento apertado o solver nao consegue refazer o vinculo da APS nem achar quais unidades de nivel 2-3 abrir.
    Para cada peso mu (R$ por pessoa.km ou atendimento.km): vinculo da APS pelo MIP da APS + busca local com
    custo + mu x distancia; com o vinculo fixo, o resto minimiza CustoTotal + mu x DistTotal sem o orcamento.
    Vale a de menor distancia entre as que cabem no orcamento; a do modo 1 (com a sobra gasta nos niveis 2-3) tambem
    concorre. Trabalha no 'modelo.mps' da pasta corrente. Devolve (solucao, partes do log)."""
    pasta = Path.cwd()
    orc = float(re.search(r"param orcamento := ([\d.e+]+);", dat_txt).group(1))
    vinc = lambda sol: dict(nm[2:-1].split(",") for nm in nomes_y if sol.get(nm, 0) > 0.5)
    fixa = lambda v: y_fora(nomes_y, {i: {j} for i, j in v.items()})
    melhor, vmelhor = inicio, valor("modelo.mps", inicio)
    rb = rodar_highs("modelo.mps", 0.075 * tempo, gap, inicio=inicio, zerar=fixa(vinc(inicio)))
    partes = [f"modo1={fmt(rb)}"]
    if rb and rb["obj"] < vmelhor:
        melhor, vmelhor = rb["sol"], rb["obj"]
    for mu in (15, 40, 100):
        _, e = mip_aps(dd, ok, 0.05 * tempo, pasta, inicio=busca_local(dd, escolha, ok, mu=mu), mu=mu)
        e = busca_local(dd, e or escolha, ok, mu=mu)
        rm = rodar_highs("modelo.mps", 0.075 * tempo, gap, zerar=fixa(e),
                         objetivo={"CustoTotal": 1.0, "DistTotal": float(mu)}, livres=("Orcamento[1]",))
        if rm is None or rm["sol"]["CustoTotal"] > orc + 1e-6:
            partes.append(f"mu{mu}=" + ("-" if rm is None else f"fora({rm['sol']['CustoTotal'] / 1e6:.0f}mi)"))
            continue
        partes.append(f"mu{mu}={rm['obj']:.6g}")
        if rm["obj"] < vmelhor:
            melhor, vmelhor = rm["sol"], rm["obj"]
    return melhor, partes


def y_fora(nomes_y, permitidos):
    """Colunas y[i,j] que nao estao no conjunto permitido de cada ponto i."""
    fora = set()
    for n in nomes_y:
        i, j = n[2:-1].split(",")
        if j not in permitidos.get(i, ()):
            fora.add(n)
    return fora


# ----------------------------------------------------------------------------
# Um cenario
# ----------------------------------------------------------------------------
def resolver(dat_txt, nome, tempo, gap, k, dd, inicio=None, modo=1, partidas=False):
    pasta = Path(tempfile.mkdtemp(prefix="epd_"))
    shutil.copy(MOD, pasta / "m.mod")
    (pasta / "d.dat").write_text(dat_txt, encoding="ascii")
    cwd = os.getcwd()
    os.chdir(pasta)
    t0 = time.time()
    try:
        g.glp_term_out(g.GLP_OFF)
        tran, lp = g.glp_mpl_alloc_wksp(), g.glp_create_prob()
        assert g.glp_mpl_read_model(tran, "m.mod", 1) == 0 and g.glp_mpl_read_data(tran, "d.dat") == 0
        assert g.glp_mpl_generate(tran, None) == 0
        g.glp_mpl_build_prob(tran, lp)
        g.glp_write_mps(lp, g.GLP_MPS_FILE, None, "modelo.mps")
        n = g.glp_get_num_cols(lp)
        nomes = [g.glp_get_col_name(lp, j) for j in range(1, n + 1)]
        nomes_y = [x for x in nomes if x.startswith("y[")]
        solver, log, r = tem_gurobi(), [], None
        if solver:
            try:
                t_gurobi = tempo
                if partidas and inicio is not None and modo == 2:
                    # rodada de 03/11, cenario Caderno +5%: o Gurobi parte da melhor partida por soma ponderada
                    # (o tempo gasto nas partidas sai do limite do Gurobi)
                    t_p = time.time()
                    escolha, ok = vinculo_guloso(dd)
                    inicio, partes = partidas_modo2(dat_txt, nomes_y, inicio, dd, escolha, ok, tempo, gap)
                    log.append("partidas " + " ".join(partes) + f" ({time.time() - t_p:.0f}s)")
                    t_gurobi = max(60.0, tempo - (time.time() - t_p))
                r = rodar_gurobi(pasta / "modelo.mps", t_gurobi, gap, inicio, pasta)
                log.append(f"{solver}: obj={fmt(r)} bound={fmt(r, 'bound')}")
            except Exception as e:   # instalado sem licenca, por exemplo
                log.append(f"{solver} falhou ({e}); usando HiGHS")
                solver = None
        lb_aps = lb23 = np.nan
        if not solver:
            solver, r = "highs-3fases", None
            escolha, ok = vinculo_guloso(dd)
            if inicio is None:   # modo 1: melhora o vinculo da APS antes de chamar o modelo completo
                peso = lambda e: (lambda c, d: c + dd["eps_dist"] * d)(*custo_aps(dd, e))
                cands = {"guloso": escolha, "guloso+BL": busca_local(dd, escolha, ok)}
                lb_aps, esc_mip = mip_aps(dd, ok, 0.20 * tempo, pasta, inicio=cands["guloso+BL"])
                if esc_mip:
                    cands["MIP_APS+BL"] = busca_local(dd, esc_mip, ok)
                melhor = min(cands, key=lambda c: peso(cands[c]))
                escolha = cands[melhor]
                log.append("APS " + " ".join(f"{c}={custo_aps(dd, e)[0] / 1e6:.1f}" for c, e in cands.items())
                           + f" LB_APS={lb_aps / 1e6:.1f} -> {melhor}")
            perm_k = k_proximas(dd, ok, k)
            for i, j in escolha.items():
                perm_k[i].add(j)
            for nm in nomes_y:   # vinculos ja usados na solucao de partida continuam permitidos
                if inicio and inicio.get(nm, 0) > 0.5:
                    i, j = nm[2:-1].split(",")
                    perm_k[i].add(j)
            fixo = y_fora(nomes_y, {i: {j} for i, j in escolha.items()})
            if inicio is None:   # fase 1: vinculo fixo
                r = rodar_highs("modelo.mps", 0.20 * tempo, gap, zerar=fixo)
                log.append(f"fase1 obj={fmt(r)}")
                inicio = r["sol"] if r else None
            else:
                # modo 2: partidas por soma ponderada (ver partidas_modo2)
                inicio, partes = partidas_modo2(dat_txt, nomes_y, inicio, dd, escolha, ok, tempo, gap)
                log.append("fase1 " + " ".join(partes))
                for nm in nomes_y:
                    if inicio.get(nm, 0) > 0.5:
                        i, j = nm[2:-1].split(",")
                        perm_k[i].add(j)
            f2, f3 = (0.15, 0.15) if modo == 1 else (0.25, 0.15)
            r2 = rodar_highs("modelo.mps", f2 * tempo, gap, inicio=inicio, zerar=y_fora(nomes_y, perm_k))
            log.append(f"fase2 obj={fmt(r2)}")
            r = r2 if r2 and (r is None or r2["obj"] <= r["obj"] + 1e-6) else r
            r3 = rodar_highs("modelo.mps", f3 * tempo, gap, inicio=r["sol"] if r else inicio)
            log.append(f"fase3 obj={fmt(r3)} bound={fmt(r3, 'bound')}")
            if r3 and (r is None or r3["obj"] <= r["obj"] + 1e-6):
                r = r3
            elif r3:   # a fase 3 nao melhorou: guarda o limitante dela, que vale para o modelo completo
                r = dict(r, bound=r3["bound"])
            else:
                r = dict(r, bound=np.nan) if r else None
            if r and modo == 1:
                # limitante por decomposicao: min(C1 + C23) >= min C1 + min C23 (o desempate de distancia e >= 0)
                lb23 = limitante_niveis23("modelo.mps", 0.30 * tempo)
                log.append(f"LB23={lb23 / 1e6:.1f}")
                r = dict(r, bound=np.nanmax([r["bound"], lb_aps + lb23]))
            if r:
                r = dict(r, gap=(r["obj"] - r["bound"]) / max(abs(r["obj"]), 1e-9))
        if r is None:
            return None
        # devolve a solucao ao GLPK (inteiras fixas), reotimiza o resto e roda os printf/tabelas do .mod
        for j in range(1, n + 1):
            if g.glp_get_col_kind(lp, j) != g.GLP_CV:
                v = round(r["sol"].get(nomes[j - 1], 0.0))
                g.glp_set_col_bnds(lp, j, g.GLP_FX, v, v)
        p = g.glp_iocp()
        g.glp_init_iocp(p)
        p.presolve, p.msg_lev = g.GLP_ON, g.GLP_MSG_OFF
        g.glp_intopt(lp, p)
        if g.glp_mip_status(lp) not in (g.GLP_OPT, g.GLP_FEAS):
            log.append("AVISO: GLPK nao reproduziu a solucao com as inteiras fixas")
        g.glp_term_out(g.GLP_ON)
        g.glp_open_tee("relatorio.txt")
        g.glp_mpl_postsolve(tran, lp, g.GLP_MIP)
        g.glp_close_tee()
        destino = RES / nome
        destino.mkdir(parents=True, exist_ok=True)
        for f in ("relatorio.txt", "res_setores.csv", "res_ubs.csv"):
            if (pasta / f).exists():
                shutil.copy(pasta / f, destino / f)
        g.glp_mpl_free_wksp(tran)
        return dict(r, solver=solver, tempo=time.time() - t0, log="; ".join(log), destino=destino,
                    lb_aps=lb_aps, lb23=lb23)
    finally:
        os.chdir(cwd)
        shutil.rmtree(pasta, ignore_errors=True)


def resumir(destino):
    t = (destino / "relatorio.txt").read_text(encoding="latin-1")
    num = lambda pad: float(re.search(pad, t).group(1)) if re.search(pad, t) else np.nan
    aps, sec, ter = (map(float, re.search(r"APS / Sec / Ter \.+ ([\d.]+) / ([\d.]+) / ([\d.]+)", t).groups()))
    bloco = lambda a, b: t.split(a, 1)[1].split(b, 1)[0] if a in t else ""
    b_sec, b_ter = bloco("--- Atencao secundaria ---", "--- Atencao terciaria ---"), t.split("--- Atencao terciaria ---")[-1]
    abre = lambda b: re.findall(r"^(\S+)\s+\[(exist|NOVA)\]", b, re.M)
    ubs = pd.read_csv(destino / "res_ubs.csv")
    return dict(custo_total=num(r"Custo total \(ano\) \.+\s+([\d.]+)"), custo_aps=aps, custo_sec=sec, custo_ter=ter,
                dist_casa_ubs_km=num(r"Distancia media casa-UBS \.+\s+([\d.]+)"),
                dist_ubs_sec_km=num(r"Distancia media UBS-sec \.+\s+([\d.]+)"),
                dist_sec_ter_km=num(r"Distancia media sec-ter \.+\s+([\d.]+)"),
                eSF_total=int(ubs.eSF.sum()), ubs_abertas=len(ubs), ubs_novas=int((ubs.existente == 0).sum()),
                sec_abertas=len(abre(b_sec)), sec_novas=sum(1 for _, s in abre(b_sec) if s == "NOVA"),
                sec_novas_ids=" ".join(i for i, s in abre(b_sec) if s == "NOVA"),
                hosp_abertos=len(abre(b_ter)), hosp_novos=sum(1 for _, s in abre(b_ter) if s == "NOVA"),
                hosp_usados=" ".join(i for i, s in abre(b_ter)))


# ----------------------------------------------------------------------------
# Mapa
# ----------------------------------------------------------------------------
def mapa(destino, base, titulo):
    import geopandas as gpd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xl = DADOS / "base_uberlandia.xlsx"
    st = pd.read_excel(xl, sheet_name="Setores", dtype={"CD_SETOR": str})
    rs = pd.read_csv(destino / "res_setores.csv")
    st = st.merge(rs[["setor", "ubs", "dist_km", "tempo_min"]], left_on="ponto_agregado" if base == "agregado" else "id_modelo",
                  right_on="setor", how="left")
    gpkg = CACHE / "udi_setores.gpkg"
    if gpkg.exists():
        malha = gpd.read_file(gpkg)[["CD_SETOR", "geometry"]].to_crs(4326)
        malha["CD_SETOR"] = malha["CD_SETOR"].astype(str)
        st = malha.merge(st, on="CD_SETOR", how="inner")
    else:
        st = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=4326)
    ubs = pd.read_csv(destino / "res_ubs.csv").merge(pd.read_excel(xl, sheet_name="APS_J1")[["id", "lon", "lat"]],
                                                    left_on="ubs", right_on="id")
    t = (destino / "relatorio.txt").read_text(encoding="latin-1")
    b_sec = t.split("--- Atencao secundaria ---")[1].split("--- Atencao terciaria ---")[0]
    b_ter = t.split("--- Atencao terciaria ---")[1]
    abre = lambda b: dict(re.findall(r"^(\S+)\s+\[(exist|NOVA)\]", b, re.M))
    j2 = pd.read_excel(xl, sheet_name="Secundaria_J2")
    j3 = pd.read_excel(xl, sheet_name="Terciaria_J3")
    j2 = j2[j2.id.isin(abre(b_sec))].assign(nova=lambda x: x.id.map(abre(b_sec)) == "NOVA")
    j3 = j3[j3.id.isin(abre(b_ter))].assign(nova=lambda x: x.id.map(abre(b_ter)) == "NOVA")

    fig, axs = plt.subplots(1, 2, figsize=(15, 7.5), gridspec_kw=dict(width_ratios=[1, 1.15]))
    urb = ubs[ubs.existente == 1]
    zoom = (urb.lon.quantile(0.02) - 0.03, urb.lon.quantile(0.98) + 0.03,
            urb.lat.quantile(0.02) - 0.03, urb.lat.quantile(0.98) + 0.03)
    for ax, z in zip(axs, (None, zoom)):
        st.plot(column="tempo_min", cmap="YlOrRd", vmin=0, vmax=25, ax=ax, linewidth=0.05, edgecolor="#999999",
                legend=z is not None,
                legend_kwds=dict(label="tempo casa-UBS (min): a pe na cidade, de carro na zona rural", shrink=0.6),
                missing_kwds=dict(color="#eeeeee"))
        ax.scatter(urb.lon, urb.lat, s=10, c="black", label="UBS existente", zorder=3)
        nov = ubs[ubs.existente == 0]
        ax.scatter(nov.lon, nov.lat, s=40 + 25 * nov.porte, c="red", marker="*", label="UBS nova", zorder=4)
        for nova, cor in ((False, "white"), (True, "deepskyblue")):
            x = j2[j2.nova == nova]
            ax.scatter(x.lon, x.lat, s=90, c=cor, edgecolors="navy", marker="s", linewidths=1.5, zorder=5,
                       label="Nivel 2 " + ("novo" if nova else "existente"))
            x = j3[j3.nova == nova]
            ax.scatter(x.lon, x.lat, s=110, c="purple" if not nova else "magenta", marker="^", zorder=5,
                       label="Hospital " + ("novo" if nova else "existente"))
        if z:
            ax.set_xlim(z[0], z[1])
            ax.set_ylim(z[2], z[3])
            ax.set_title("Sede urbana")
        else:
            ax.set_title("Municipio")
            ax.legend(loc="lower left", fontsize=8)
        ax.set_axis_off()
    fig.suptitle(titulo, fontsize=12)
    fig.tight_layout()
    fig.savefig(destino / "mapa.png", dpi=140)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="agregado", choices=["agregado", "setores"])
    ap.add_argument("--tempo", type=float, default=1200, help="segundos no modo 1 (custo)")
    ap.add_argument("--tempo2", type=float, default=1200, help="segundos em cada cenario do modo 2 (distancia)")
    ap.add_argument("--gap", type=float, default=0.005)
    ap.add_argument("--k", type=int, default=4, help="UBS candidatas por ponto na fase 2 (sem Gurobi)")
    ap.add_argument("--folgas", type=float, nargs="*", default=[0.05, 0.10])
    ap.add_argument("--demandas", nargs="*", default=["caderno", "observada"])
    ap.add_argument("--reusar-modo1", action="store_true",
                    help="usa a solucao do modo 1 ja gravada na pasta de saida e roda so o modo 2")
    ap.add_argument("--partidas", action="store_true",
                    help="com Gurobi, gera partidas por soma ponderada antes de cada modo 2 (usado no Caderno +5%% de 03/11)")
    ap.add_argument("--resultados", type=Path, default=None,
                    help="pasta de saida (padrao: resultados/rodada_<data de hoje>)")
    a = ap.parse_args()
    global RES
    if a.resultados:
        RES = a.resultados.resolve()
    RES.mkdir(parents=True, exist_ok=True)
    for dem in a.demandas:
        arq = DADOS / DAT[dem].format(a.base)
        txt = arq.read_text(encoding="ascii")
        dd = ler_dat(arq)
        nome1 = f"{a.base}_{dem}_modo1"
        if a.reusar_modo1 and (RES / nome1 / "solucao.json").exists():
            s1 = json.loads((RES / nome1 / "resumo.json").read_text(encoding="utf-8"))
            r1 = dict(sol=json.loads((RES / nome1 / "solucao.json").read_text(encoding="utf-8")))
            print(f"[{time.strftime('%H:%M')}] {nome1}: reusado (custo {s1['custo_total']/1e6:.1f} mi)", flush=True)
        else:
            print(f"[{time.strftime('%H:%M')}] {nome1} ...", flush=True)
            r1 = resolver(txt, nome1, a.tempo, a.gap, a.k, dd)
            if r1 is None:
                print("  sem solucao viavel")
                continue
            s1 = resumir(r1["destino"])
            guardar(r1, s1, dem, 1, 0.0, a.base)
            print(f"  custo {s1['custo_total']/1e6:.1f} mi | gap {r1['gap']:.2%} | {r1['log']}", flush=True)
            mapa(r1["destino"], a.base, titulo(dem, 1, 0, s1))
        for f in a.folgas:
            orc = s1["custo_total"] * (1 + f)
            t2 = re.sub(r"param modo := \d+;", "param modo := 2;", txt)
            t2 = re.sub(r"param orcamento := [\d.e+]+;", f"param orcamento := {orc:.2f};", t2)
            nome2 = f"{a.base}_{dem}_modo2_folga{round(100 * f):02d}"
            print(f"[{time.strftime('%H:%M')}] {nome2} ...", flush=True)
            r2 = resolver(t2, nome2, a.tempo2, a.gap, a.k, dd, inicio=r1["sol"], modo=2, partidas=a.partidas)
            if r2 is None:
                print("  sem solucao viavel")
                continue
            s2 = resumir(r2["destino"])
            guardar(r2, s2, dem, 2, f, a.base)
            print(f"  custo {s2['custo_total']/1e6:.1f} mi | casa-UBS {s2['dist_casa_ubs_km']:.2f} km | {r2['log']}", flush=True)
            mapa(r2["destino"], a.base, titulo(dem, 2, f, s2))
    consolidar()


def titulo(dem, modo, folga, s):
    obj = "minimo custo" if modo == 1 else f"minima distancia, orcamento +{100 * folga:.0f}%"
    return (f"Demanda hospitalar {'do Caderno 1' if dem == 'caderno' else 'observada (SIH)'} - modo {modo} ({obj}): "
            f"R$ {s['custo_total'] / 1e9:.2f} bi/ano".replace(".", ",") +
            f" | casa-UBS {s['dist_casa_ubs_km']:.2f} km".replace(".", ","))


def refazer_mapas(base="agregado"):
    """Redesenha os mapas de todos os cenarios ja resolvidos (usa resumo.json de cada pasta)."""
    for p in sorted(RES.glob(f"{base}_*/resumo.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        mapa(p.parent, base, titulo(s["demanda"], s["modo"], s["folga"], s))


def guardar(r, s, dem, modo, folga, base):
    linha = dict(base=base, demanda=dem, modo=modo, folga=folga, solver=r["solver"], objetivo=r["obj"],
                 limitante=r["bound"], gap=r["gap"], limitante_aps=r.get("lb_aps"), limitante_niveis23=r.get("lb23"),
                 tempo_s=round(r["tempo"]), log=r["log"], **s)
    (r["destino"] / "resumo.json").write_text(json.dumps(linha, default=float, indent=1), encoding="utf-8")
    # solucao completa (valores nao nulos): permite rodar novas folgas do modo 2 sem resolver o modo 1 de novo
    (r["destino"] / "solucao.json").write_text(json.dumps({k: round(v, 6) for k, v in r["sol"].items() if abs(v) > 1e-9}),
                                               encoding="utf-8")


def consolidar():
    linhas = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RES.glob("*/resumo.json"))]
    if not linhas:
        return
    df = pd.DataFrame(linhas).sort_values(["base", "demanda", "modo", "folga"])
    df.to_csv(RES / "resumo_cenarios.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    curva(df)


def curva(df):
    """Fronteira custo x distancia (modo 1 = folga 0; modo 2 = folgas), uma linha por cenario de demanda."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.5))
    for (base, dem), x in df.groupby(["base", "demanda"]):
        x = x.sort_values("folga")
        rot = f"{'Caderno 1' if dem == 'caderno' else 'observada (SIH)'} ({base})"
        axs[0].plot(x.custo_total / 1e9, x.dist_casa_ubs_km, "o-", label=rot)
        axs[1].plot(x.custo_total / 1e9, x.dist_ubs_sec_km, "s--", label=rot)
        for _, r in x.iterrows():
            axs[0].annotate(f"+{100 * r.folga:.0f}%", (r.custo_total / 1e9, r.dist_casa_ubs_km), fontsize=8,
                            textcoords="offset points", xytext=(4, 4))
    axs[0].set_ylabel("distancia media casa-UBS (km)")
    axs[1].set_ylabel("distancia media UBS-nivel 2 (km)")
    for ax in axs:
        ax.set_xlabel("custo anual da rede (R$ bi)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Custo x acesso: modo 1 (folga 0) e modo 2 com orcamento = custo minimo x (1 + folga)")
    fig.tight_layout()
    fig.savefig(RES / "curva_custo_distancia.png", dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    main()
