# -*- coding: utf-8 -*-
"""
Parametros do modelo para Uberlandia, com a origem de cada numero.

Classificacao usada na planilha:
  EXERCICIO  - fixado pelo enunciado do trabalho (nao e calculado)
  DECISAO    - escolha do grupo, confirmada em out/2026
  NORMATIVO  - lei, portaria ou caderno de parametros do MS
  DADO       - medido em base publica (IBGE, CNES, ANS, OSRM, SIH, SIA, CAGED, SPDM, Novo PAC)
  INFERIDO   - hipotese de modelagem, com o raciocinio registrado (trocar por dado local quando houver)
"""
import math

DOC = []          # linhas da aba "Parametros" do .xlsx


def reg(grupo, nome, valor, unidade, classe, fonte, raciocinio=""):
    DOC.append(dict(grupo=grupo, parametro=nome, valor=valor, unidade=unidade, classificacao=classe,
                    fonte=fonte, raciocinio=raciocinio))
    return valor


def crf(i, n):
    """Fator de recuperacao de capital: transforma um investimento em parcela anual equivalente."""
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
reg("Acesso", "dmax01 / tmax01", "5 km / 25 min", "-", "EXERCICIO", "enunciado", "Limites fixos, nao derivados de velocidade.")
reg("Acesso", "dmax12 / tmax12", "30 km / 60 min", "-", "EXERCICIO", "enunciado",
    "Coincide com o criterio do Caderno 1 para RM: '60 minutos ou 30 km' (item 6.7).")
reg("Acesso", "dmax23 / tmax23", "60 km / 120 min", "-", "EXERCICIO", "enunciado", "")
reg("Acesso", "regra_acesso", 2, "-", "EXERCICIO", "enunciado: '30 km ou 1 hora'", "Basta cumprir distancia OU tempo.")
reg("Acesso", "peso01 / peso12 / peso23", "1 / 1 / 1", "-", "DECISAO", "Decisao do grupo (out/2026)",
    "Distancia total = soma simples dos tres trechos, sem ponderacao.")
reg("Acesso", "modo casa -> UBS", "a pe (setores urbanos); carro (setores rurais)", "-", "DECISAO",
    "OSRM perfis foot e car sobre o OpenStreetMap",
    "Velocidade coerente com o contexto: na cidade o acesso a UBS e a pe; na zona rural dispersa (62 setores, "
    "~10 mil pessoas em 3.800 km2) o acesso e por veiculo/transporte sanitario. A pe, quase todo setor rural "
    "exigiria uma UBS propria.")
reg("Acesso", "modo UBS -> secundaria -> hospital", "carro", "-", "INFERIDO", "OSRM perfil car (fluxo livre)",
    "Encaminhamento por transporte sanitario ou veiculo. Nao inclui transito.")
reg("Acesso", "vel01 / vel12 / vel23 (so se faltar tempo)", "4,5 / 30 / 30 km/h", "km/h", "INFERIDO",
    "caminhada adulta ~4,5-5 km/h; carro urbano ~30 km/h", "Nao usados com esta base: os tempos vem do OSRM.")

# ---------------------------------------------------------------------------
# Anualizacao do investimento
# ---------------------------------------------------------------------------
TSD = reg("Anualizacao", "taxa de desconto (i)", 0.085, "a.a. (real)", "NORMATIVO",
          "Taxa Social de Desconto - Nota Tecnica SEI 19911/2020/ME (Guia Geral de ACB do Governo Federal)",
          "Custo de oportunidade social do capital publico usado para comparar investimento e custeio no mesmo ano.")
VIDA_PREDIO = reg("Anualizacao", "vida util de edificacoes (n)", 25, "anos", "NORMATIVO",
                  "IN RFB 1.700/2017, Anexo III (edificacoes: 4% a.a.)", "Prazo de depreciacao fiscal de predios.")
VIDA_EQUIP = reg("Anualizacao", "vida util de equipamentos medicos (n)", 10, "anos", "NORMATIVO",
                 "IN RFB 1.700/2017, Anexo III (aparelhos medicos: 10% a.a.)", "")
CRF_PREDIO = reg("Anualizacao", "CRF predio = i(1+i)^n/((1+i)^n-1)", round(crf(TSD, VIDA_PREDIO), 5), "1/ano", "INFERIDO",
                 "calculo", "Parcela anual que, durante n anos a taxa i, devolve o investimento (anuidade).")
CRF_EQUIP = reg("Anualizacao", "CRF equipamento", round(crf(TSD, VIDA_EQUIP), 5), "1/ano", "INFERIDO", "calculo", "")
CUSTEIO_PREDIAL = 0.08   # hipotese antiga, mantida so para comparacao na aba Anualizacao
reg("Anualizacao", "custeio predial (8% do investimento/ano)", "substituido", "-", "DADO",
    "Contratos de gestao da SMS (388/2023, 16o TA, out/2026)",
    "O custeio das UBS e da policlinica agora vem do gasto real das unidades (custo fixo operacional), nao de % da obra.")
MANUT_EQUIP = reg("Anualizacao", "manutencao de equipamentos", 0.10, "fracao do investimento/ano", "INFERIDO", "hipotese",
                  "Contratos de manutencao de imagem costumam ficar entre 8% e 12% do valor do equipamento por ano.")

# ---------------------------------------------------------------------------
# Custo de pessoal: salario mensal -> custo anual do empregador
# ---------------------------------------------------------------------------
# Planilha de custos do contrato de gestao 388/2023 (OS Missao Sal da Terra, Setor Leste), 16o termo aditivo, out/2026:
# total do setor = salarios R$ 7.126.604,38/mes; encargos e provisoes sem INSS patronal (a OS e filantropica e isenta)
ENCARGOS_OS = {"FGTS": 554543.37, "seguro de vida": 1298.27, "1/3 ferias": 157281.52, "13o": 467086.79,
               "maternidade/paternidade": 40853.15, "reposicao de ausentes": 687362.92, "multa FGTS": 222715.50,
               "vale alimentacao": 223829.74, "vale transporte": 36908.31, "provisao de rescisao": 426909.89}
SALARIOS_OS = 7126604.38
FATOR_ANUAL = reg("Pessoal", "fator salario mensal -> custo anual", round(12 * (1 + sum(ENCARGOS_OS.values()) / SALARIOS_OS), 3),
                  "x salario mensal", "DADO",
                  "Contrato de gestao 388/2023 (Setor Leste), 16o TA, planilha de custos out/2026: encargos e provisoes "
                  "= 39,6% da folha, sem INSS patronal (OS filantropica)",
                  "12 x 1,396. Antes: 13,333 x 1,358 = 18,1 (CLT com INSS). Toda a APS e o ambulatorio municipal sao geridos por OS.")
SM_2026 = reg("Pessoal", "salario minimo 2026", 1621.0, "R$/mes", "NORMATIVO", "Decreto 12.797/2025", "")


def custo_anual(salario_mensal):
    return round(salario_mensal * FATOR_ANUAL, 2)


MEDICO_40H = reg("Pessoal", "medico 40h (APS, especialista e hospitalar)", round(18219.27 * 40 / 38, 2), "R$/mes", "DADO",
                 "CAGED via salario.com.br: medico da ESF (CBO 225142), media Brasil set/2025-ago/2026 = R$ 18.219,27 por 38 h",
                 "Convertido para 40 h. Medico clinico (CBO 225125): R$ 10.303 por 25 h = R$ 16,5 mil em 40 h, mesma ordem. "
                 "Nao ha serie publica gratuita para Uberlandia.")
SAL = {
    "medico_aps": MEDICO_40H,
    "medico_esp": MEDICO_40H,
    "medico_hosp": MEDICO_40H,
    "enfermeiro": reg("Pessoal", "enfermeiro (piso)", 4750.0, "R$/mes", "NORMATIVO", "Lei 14.434/2022 (piso da enfermagem)",
                      "CAGED Brasil (set/25-ago/26): R$ 4.503 por 38 h. O piso vale no SUS com complementacao federal."),
    "tec_enf": reg("Pessoal", "tecnico de enfermagem (piso)", 3325.0, "R$/mes", "NORMATIVO", "Lei 14.434/2022 (70% do piso)",
                   "CAGED Brasil: R$ 2.552 por 38 h (abaixo do piso)."),
    "acs": reg("Pessoal", "ACS (piso = 2 salarios minimos)", 2 * SM_2026, "R$/mes", "NORMATIVO",
               "EC 120/2022 + Decreto 12.797/2025", ""),
    "dentista": reg("Pessoal", "cirurgiao-dentista 40h", 8000.0, "R$/mes", "INFERIDO", "mercado SUS", ""),
    "asb": reg("Pessoal", "auxiliar de saude bucal 40h", 2400.0, "R$/mes", "INFERIDO", "mercado SUS", ""),
    "tec_radiol": reg("Pessoal", "tecnico em radiologia 24h (2 SM + 40% insalubridade)", round(2 * SM_2026 * 1.4, 2), "R$/mes",
                      "NORMATIVO", "Lei 7.394/1985 (piso de 2 SM, jornada de 24 h, insalubridade 40%)", ""),
    "nivel_sup_emulti": reg("Pessoal", "profissional de nivel superior da e-Multi 40h", 6000.0, "R$/mes", "INFERIDO", "mercado SUS",
                            "Assistente social APS 30 h na rede = R$ 4.651,53 (lista salarial do 16o TA) -> R$ 6,2 mil em 40 h."),
    "aux_adm": reg("Pessoal", "auxiliar administrativo 40h", 1784.45, "R$/mes", "DADO",
                   "Contrato 388/2023, 16o TA: lista salarial jul/2026 (auxiliar administrativo, 180 h/mes)", ""),
}

# Horas produtivas por ano de um FTE
HORAS_40 = reg("Pessoal", "horas produtivas/ano (40 h/sem)", round((40 * 52.14 - 171 - 80) * 0.85), "h/ano", "INFERIDO",
               "40 h x 52,14 sem - ferias (30 dias = 171 h) - feriados (10 dias uteis = 80 h); x 0,85",
               "0,85 = indice de seguranca tecnica de 15% para ausencias (Resolucao COFEN 543/2017).")
HORAS_24 = reg("Pessoal", "horas produtivas/ano (24 h/sem)", round((24 * 52.14 - 103 - 48) * 0.85), "h/ano", "INFERIDO",
               "mesma conta para a jornada legal de 24 h do tecnico em radiologia", "")

# ---------------------------------------------------------------------------
# APS: portes, equipes e custos
# ---------------------------------------------------------------------------
INV_UBS = {1: 2012825.0, 2: 2435976.0, 3: 2765371.0, 4: 5291345.0, 5: 6584873.0}
reg("APS", "investimento UBS Tipo I..V (Sudeste)", "; ".join(f"T{p}: {v:,.0f}" for p, v in INV_UBS.items()), "R$",
    "NORMATIVO", "Novo PAC Saude - valores para construcao de nova UBS (MS, 2024), regiao Sudeste",
    "Os 5 tipos do Novo PAC viram os portes 1..5 do modelo. Sem terreno, equipamentos e mobiliario.")
# Custo real das UBSF do Setor Leste (contrato 388/2023, 16o TA, planilha de custos out/2026, "gastos totais" mensais,
# ja sem INSS patronal) e equipes de cada unidade (eSF, eSB e e-Multi do CNES out/2026; ACS do Anexo I do contrato;
# eAPP = equipe prisional, contada como meia eSF). Ipanema I (R$ 471 mil/mes com 1 eSF) e Ipanema III (sem CNES) ficam
# de fora; as UBS tradicionais (Tibery, Custodio Pereira) tambem, por terem pediatra/GO/clinico alem das equipes.
UBSF_LESTE_2026 = {  # unidade: (gasto mensal, eSF, eSB, ACS, eMulti, eAPP, despesas operacionais, servicos de terceiros)
    "Aclimacao": (173263.38, 1, 1, 7, 0, 0, 24634.43, 826.79),
    "Alvorada + Presidio Jacy de Assis": (259740.44, 2, 1, 6, 0, 1, 33240.32, 1088.90),
    "Dom Almir": (337511.12, 2, 2, 12, 1, 0, 34040.40, 1113.27),
    "Joana Darc + Penitenciaria Pimenta da Veiga": (488934.21, 3, 2, 10, 1, 1, 40221.74, 1301.54),
    "Morumbi I e II": (578343.88, 3, 3, 18, 1, 0, 41682.81, 1346.04),
    "Morumbi III": (150054.01, 1, 0, 6, 0, 0, 22938.46, 775.12),
    "Morumbi IV": (125359.93, 1, 0, 6, 0, 0, 23789.96, 801.06),
    "Morumbi V": (151129.41, 1, 0, 6, 0, 0, 23494.28, 792.05),
    "Ipanema II": (112450.92, 1, 0, 6, 0, 0, 22822.99, 771.61),
    "Tapuirama (rural)": (176387.54, 1, 1, 5, 0, 0, 44185.24, 1422.25),
}
INSS_DESP_OPER = 1869.06   # INSS patronal do pessoal rateado nas despesas operacionais (igual em todas as UBSF; e excluido)


def _eq(v):
    return v[1] + 0.5 * v[5]


def _ols(x, y):
    xm, ym = sum(x) / len(x), sum(y) / len(y)
    b = sum((a - xm) * (c - ym) for a, c in zip(x, y)) / sum((a - xm) ** 2 for a in x)
    return ym - b * xm, b


# Custo fixo operacional da unidade: intercepto de (despesas operacionais + servicos de terceiros) x eSF-equivalentes.
# Tapuirama (rural, transporte e refeicoes de deslocamento) fica fora do ajuste.
_urb = [v for k, v in UBSF_LESTE_2026.items() if "rural" not in k]
F_UBS, _F_POR_EQ = _ols([_eq(v) for v in _urb], [12 * (v[6] + v[7] - INSS_DESP_OPER) for v in _urb])
F_UBS = reg("APS", "custo fixo operacional da UBS", round(F_UBS, 2), "R$/ano", "DADO",
            "Contrato 388/2023, 16o TA (out/2026): despesas operacionais + servicos de terceiros de 9 UBSF urbanas "
            f"= {F_UBS:,.0f} + {_F_POR_EQ:,.0f} x eSF",
            "Portaria, limpeza, vigilancia, manutencao predial, TI, materiais e pessoal administrativo rateado da OS. "
            "A parte que cresce com o numero de equipes entra no custo_ESF. Substitui o custeio predial de 8% do investimento.")

PORTES = {}
for p in range(1, 6):
    eq_max = p if p < 5 else 6
    PORTES[p] = dict(minESF=p, maxESF=eq_max, minESB=0, maxESB=2 * eq_max, minACS=0, maxACS=12 * eq_max,
                     minEMU=0 if p <= 2 else 1, maxEMU=1 if p <= 4 else 2,
                     custo_porte=round(F_UBS + INV_UBS[p] * CRF_PREDIO, 2))
reg("APS", "faixa de eSF por porte", "p1=1, p2=2, p3=3, p4=4, p5=5-6", "equipes", "NORMATIVO",
    "PNAB/Novo PAC: UBS Tipo p comporta no minimo p equipes", "Teto de 6 no porte 5 e INFERIDO (UBS de ~1.000 m2).")
reg("APS", "faixa de eSB por porte", "0 a 2 x maxESF", "equipes", "INFERIDO", "PNAB (eSB vinculada a eSF/eAP)",
    "Teto largo para acomodar as UBS tradicionais que ja tem mais eSB que eAP.")
reg("APS", "faixa de ACS por porte", "0 a 12 x maxESF", "agentes", "NORMATIVO", "PNAB 2011 (ate 12 ACS por eSF)",
    "O minimo de fato vem da restricao R20 (750 pessoas por ACS).")
reg("APS", "faixa de e-Multi por porte", "p1-p2: 0-1; p3-p4: 1; p5: 1-2", "equipes", "NORMATIVO",
    "Portaria GM/MS 635/2023: e-Multi Estrategica (1-2 eq.), Complementar (3-4), Ampliada (5-9)",
    "UBS com 3 ou mais equipes passa a exigir uma e-Multi.")
reg("APS", "custo_porte (candidato)", "; ".join(f"p{p}: {v['custo_porte']:,.0f}" for p, v in PORTES.items()), "R$/ano",
    "DADO", "custo fixo operacional (contratos) + investimento Novo PAC x CRF predio",
    "UBS nova paga a obra anualizada mais o custo fixo de operar a unidade.")
reg("APS", "custo_fixo1 (UBS existente)", "custo fixo operacional + ampliacao anualizada", "R$/ano", "DADO", "",
    "Obra existente e custo afundado: paga o custo fixo operacional + CRF x (investimento do porte novo - do atual).")

EQUIPES = {
    "custo_ESB": reg("APS", "custo_ESB modalidade I (dentista + ASB)", custo_anual(SAL["dentista"] + SAL["asb"]), "R$/ano",
                     "INFERIDO", "PNAB 2017",
                     "Cirurgiao-dentista da rede (lista salarial do 16o TA): R$ 7.834,92 por 100 h/mes, servidor antigo."),
    "custo_ACS": reg("APS", "custo_ACS", custo_anual(SAL["acs"]), "R$/ano", "NORMATIVO", "piso nacional do ACS", ""),
    "custo_EMU": reg("APS", "custo_EMU (e-Multi Complementar, 200 h/sem = 5 FTE)", custo_anual(5 * SAL["nivel_sup_emulti"]),
                     "R$/ano", "INFERIDO", "Portaria GM/MS 635/2023 (carga minima da modalidade)", ""),
}
# custo_ESF calibrado: o unico parametro livre que faz o custo do modelo reproduzir o gasto real das 10 UBSF
# (gasto = F_UBS + c_ESF x eSF-eq + custo_ESB x eSB + custo_ACS x ACS + custo_EMU x eMulti), minimos quadrados.
_x = [_eq(v) for v in UBSF_LESTE_2026.values()]
_r = [12 * v[0] - F_UBS - EQUIPES["custo_ESB"] * v[2] - EQUIPES["custo_ACS"] * v[3] - EQUIPES["custo_EMU"] * v[4]
      for v in UBSF_LESTE_2026.values()]
_C_ESF = sum(a * b for a, b in zip(_x, _r)) / sum(a * a for a in _x)
EQUIPE_MIN_ESF = custo_anual(SAL["medico_aps"] + SAL["enfermeiro"] + 2 * SAL["tec_enf"] + SAL["aux_adm"])
EQUIPES["custo_ESF"] = reg(
    "APS", "custo_ESF (por equipe, tudo incluido)", round(_C_ESF, 2), "R$/ano", "DADO",
    "Calibrado no gasto real de 10 UBSF do Setor Leste (contrato 388/2023, 16o TA, out/2026); minimos quadrados",
    f"Equipe minima praticada (medico + enfermeiro + 2 tec. enf. + aux. adm.) = R$ {EQUIPE_MIN_ESF:,.0f}; o restante "
    "e apoio (servicos gerais, gerente, farmacia), multiprofissional fracionado, tutoria e operacao que cresce com a "
    "unidade. Os ACS ficam a parte (custo_ACS). Erro do ajuste por unidade: -14% a +31%; no total, +1%.")
CALIB_APS = [(k, 12 * v[0], F_UBS + EQUIPES["custo_ESF"] * _eq(v) + EQUIPES["custo_ESB"] * v[2]
              + EQUIPES["custo_ACS"] * v[3] + EQUIPES["custo_EMU"] * v[4]) for k, v in UBSF_LESTE_2026.items()]

# UBS tradicionais (equipes eAP com pediatra, ginecologista e clinico): gasto real acima do que o modelo cobra por
# eSF-equivalente. Mesma planilha out/2026; equipes do CNES (eAP-eq = eSF-equivalente pela carga do medico).
UBS_TRAD_LESTE_2026 = {  # unidade: (gasto mensal, eAP-eq, eSB, ACS, eMulti)
    "UBS Tibery": (802749.26, 4.75, 6, 6, 0),
    "UBS Custodio Pereira": (713015.65, 3.0, 6, 6, 1),
}
_exc = {k: 12 * v[0] - (F_UBS + EQUIPES["custo_ESF"] * v[1] + EQUIPES["custo_ESB"] * v[2] + EQUIPES["custo_ACS"] * v[3]
                       + EQUIPES["custo_EMU"] * v[4]) for k, v in UBS_TRAD_LESTE_2026.items()}
CUSTO_EXTRA_EAP = reg(
    "APS", "custo adicional da UBS tradicional (por eAP-equivalente)",
    round(sum(_exc.values()) / sum(v[1] for v in UBS_TRAD_LESTE_2026.values()), 2), "R$/ano por eAP-eq", "DADO",
    "Contrato 388/2023, 16o TA (out/2026): UBS Tibery e UBS Custodio Pereira, gasto real menos o custo do modelo",
    "; ".join(f"{k}: R$ {v / 1e6:.2f} mi/ano a mais" for k, v in _exc.items()) + ". Entra no custo fixo das UBS existentes "
    "com eAP (constante: as equipes atuais sao obrigatorias pela R12). Aproximacao: so 2 unidades na amostra.")
CAP_APS = {
    "pop_por_ESF": reg("APS", "pop_por_ESF", 3000, "pessoas/eSF", "EXERCICIO", "enunciado; PNAB 2017 admite 2.000-3.500", ""),
    "pop_por_ACS": reg("APS", "pop_por_ACS", 750, "pessoas/ACS", "EXERCICIO", "enunciado; PNAB 2017", ""),
    "pop_por_ESB": reg("APS", "pop_por_ESB", 3000, "pessoas/eSB", "DECISAO", "Decisao do grupo (out/2026)",
                       "eSB na mesma proporcao da eSF (1 eSB para cada 3.000 pessoas)."),
}


def eap_equiv(horas_medico):
    """eSF-equivalente de uma eAP pela carga horaria do medico (PNAB 2017)."""
    return 0.5 if horas_medico <= 24 else 0.75 if horas_medico <= 34 else 1.0


reg("APS", "equivalencia eAP -> eSF", "por equipe: 20 h = 0,5; 30 h = 0,75; 35 h ou mais = 1,0", "eSF por eAP", "DADO",
    "CNES, membros de cada eAP (carga horaria do medico); regra da PNAB 2017 (modalidades I e II)",
    "Uberlandia: 31 eAP de 20 h, 18 de 30-33 h e 22 de 35 h ou mais (media 0,72). ESF_atual = eSF + soma arredondada.")
ACS_TOTAL = reg("APS", "ACS existentes no municipio", 500, "agentes", "DADO",
                "Prefeitura de Uberlandia (mar/2025): ~500 ACS em capacitacao; ~550 em 2022",
                "O CNES vincula so ~210 a equipes (sub-registro). ACS_atual = CNES da UBS + rateio dos demais "
                "proporcional as eSF da UBS.")

# ---------------------------------------------------------------------------
# Nivel 2: atencao ambulatorial especializada (Caderno 1 de Parametros SUS, secoes IV e VI)
# ---------------------------------------------------------------------------
CONSULTAS_Q35 = {"Angiologia": 1700, "Cardiologia": 6000, "Dermatologia": 3800, "Endocrinologia": 2500,
                 "Gastroenterologia": 1400, "Proctologia": 1600, "Nefrologia": 1600, "Neurologia": 6500,
                 "Oftalmologia": 13800, "Ortopedia": 15000, "Otorrinolaringologia": 3600, "Pneumologia": 2500,
                 "Urologia": 3500, "Reumatologia": 1000}
TC_Q35 = {"TC cranio": 2200, "TC coluna cervical": 100, "TC coluna lombo-sacra": 150, "TC coluna toracica": 25,
          "TC MMSS": 15, "TC MMII": 50, "TC pelve/bacia": 400, "TC torax": 400, "TC sela turcica": 7}

S2 = ["CONS_ESP", "US", "TC", "RM"]
TAXA2 = {  # (taxa, escala)
    "CONS_ESP": (sum(CONSULTAS_Q35.values()), 100000),
    "US": (150, 1000),
    "TC": (sum(TC_Q35.values()), 100000),
    "RM": (30, 1000),
}
reg("Nivel 2", "S2", ", ".join(S2), "-", "NORMATIVO", "Caderno 1 Parametros SUS (2017), secoes IV e VI",
    "Consulta medica especializada + os 3 exames com parametro de necessidade e de produtividade de equipamento.")
reg("Nivel 2", "taxa2[CONS_ESP]", "64.500 / 100 mil", "consultas/hab SUS/ano", "NORMATIVO",
    "Caderno 1, Quadro 35 (soma das 14 especialidades)", " + ".join(f"{k} {v}" for k, v in CONSULTAS_Q35.items()))
reg("Nivel 2", "taxa2[US]", "150 / mil", "exames/hab SUS/ano", "NORMATIVO", "Caderno 1, item 6.4", "")
reg("Nivel 2", "taxa2[TC]", "3.347 / 100 mil", "exames/hab SUS/ano", "NORMATIVO", "Caderno 1, Quadro 35 (procedimentos de TC)",
    " + ".join(f"{k} {v}" for k, v in TC_Q35.items()))
reg("Nivel 2", "taxa2[RM]", "30 / mil", "exames/hab SUS/ano", "NORMATIVO", "Caderno 1, item 6.7", "")
reg("Nivel 2", "base populacional das taxas", "populacao SUS-dependente", "-", "INFERIDO", "",
    "O Caderno expressa as taxas por habitante total; aqui elas sao aplicadas a prop_SUS x populacao, "
    "porque o modelo dimensiona so a rede SUS (beneficiarios de planos usam a rede privada).")

R2 = ["MED_ESP", "ENFERMEIRO", "TEC_RADIOL", "EQ_US", "EQ_TC", "EQ_RM"]
CARGA2 = {"MED_ESP": HORAS_40, "ENFERMEIRO": HORAS_40, "TEC_RADIOL": HORAS_24,
          "EQ_US": 3024, "EQ_TC": TAXA2["TC"][0], "EQ_RM": 5000}
reg("Nivel 2", "R2", ", ".join(R2), "-", "INFERIDO", "",
    "Recursos que limitam a producao: profissionais (horas) e equipamentos (exames). "
    "A restricao R31 vale para qualquer recurso se consumo e carga estiverem na mesma unidade.")
reg("Nivel 2", "carga2[EQ_US]", 3024, "exames/equipamento/ano", "NORMATIVO", "Caderno 1, item 6.4", "")
reg("Nivel 2", "carga2[EQ_TC]", TAXA2["TC"][0], "exames/equipamento/ano", "NORMATIVO",
    "Caderno 1, item 6.2 e Portaria 1.101/2002, 2.7.5: 1 tomografo por 100 mil hab.",
    "Capacidade = necessidade de 100 mil habitantes (3.347 exames).")
reg("Nivel 2", "carga2[EQ_RM]", 5000, "exames/equipamento/ano", "NORMATIVO", "Caderno 1, item 6.7", "")
META_CONS_ESP = 336   # consultas/mes de um medico especialista de 20 h/semana (meta contratual da SMS)
CONSUMO2 = {  # horas de profissional ou exames de equipamento por atendimento
    ("CONS_ESP", "MED_ESP"): round(HORAS_40 / (META_CONS_ESP * 2 * 12), 4), ("CONS_ESP", "ENFERMEIRO"): 0.10,
    ("US", "MED_ESP"): 1 / 3, ("US", "EQ_US"): 1,
    ("TC", "MED_ESP"): 0.25, ("TC", "TEC_RADIOL"): 0.50, ("TC", "EQ_TC"): 1,
    ("RM", "MED_ESP"): 1 / 3, ("RM", "TEC_RADIOL"): 0.75, ("RM", "EQ_RM"): 1,
}
reg("Nivel 2", "consumo2[CONS_ESP,MED_ESP]", CONSUMO2[("CONS_ESP", "MED_ESP")], "h produtiva/consulta", "DADO",
    "Contrato de gestao 388/2023, Anexo I, Quadro 3: medico especialista 20 h/sem = 336 consultas/mes "
    "(8.064 consultas/ano por FTE de 40 h)",
    "Equivale a 3,9 consultas por hora contratada, proximo das 4/h da Portaria 1.101/2002. O valor por hora produtiva "
    "(1.559 h/ano) fica em 0,19 h. Antes: 0,25 h por hora produtiva (6.236 consultas/ano por FTE).")
reg("Nivel 2", "consumo2[US,MED_ESP]", round(1 / 3, 4), "h/exame", "INFERIDO", "Caderno 1, 6.4",
    "3.024 exames/ano = 12 por dia em um turno de 4 h -> 3 por hora.")
reg("Nivel 2", "consumo2 (enfermeiro, TC, RM)", "0,10 h/consulta; laudo TC 0,25 h; RM 0,33 h; tecnico TC 0,5 h; RM 0,75 h",
    "h/atendimento", "INFERIDO", "duracao tipica dos exames", "Trocar por tempos-padrao do servico, se houver.")
SAL2 = {"MED_ESP": custo_anual(SAL["medico_esp"]), "ENFERMEIRO": custo_anual(SAL["enfermeiro"]),
        "TEC_RADIOL": custo_anual(SAL["tec_radiol"])}
# IPCA numero-indice (IBGE/SIDRA, tabela 1737): corrige precos antigos para set/2026
IPCA = {"2021-01": 5574.49, "2023-09": 6700.66, "2023-11": 6735.55, "2025-06": 7312.97, "2026-09": 7695.82}
INV_EQ = {
    "EQ_US": reg("Nivel 2", "investimento ultrassom com doppler colorido", 178000.0, "R$", "DADO",
                 "Pregoes municipais de 2025 (PNCP): Ubatuba R$ 209.742; Maria da Fe (MG) R$ 164.667; Sandovalina R$ 159.500",
                 "Media arredondada dos tres valores."),
    "EQ_TC": reg("Nivel 2", "investimento tomografo 64 canais", round(2519000.0 * IPCA["2026-09"] / IPCA["2023-11"], 2), "R$",
                 "DADO", "PNCP: SES-PR, ata 223/2023, 10 tomografos 64 canais/128 cortes homologados a R$ 2.519.000 (nov/2023)",
                 "Corrigido pelo IPCA ate set/2026. Conceicao do Mato Dentro (MG, 2024) estimou R$ 3,43 mi."),
    "EQ_RM": reg("Nivel 2", "investimento ressonancia 1,5 T", 6220000.0, "R$", "DADO",
                 "Ata de registro de precos da SMS Sao Paulo (Diario Oficial da Cidade): R$ 6.220.000 por RM 1,5 T",
                 "Outras referencias: Caxias do Sul R$ 6,5 mi. Os precos sugeridos do RENEM nao tem acesso automatizado."),
}
for r, v in INV_EQ.items():
    SAL2[r] = round(v * (CRF_EQUIP + MANUT_EQUIP), 2)
reg("Nivel 2", "salario2 (custo anual por recurso)", "; ".join(f"{k}: {v:,.0f}" for k, v in SAL2.items()), "R$/ano",
    "DADO", "salario x fator anual das OS; equipamento x (CRF equip. + manutencao)", "")
N2_MAX = {"MED_ESP": 38, "EQ_US": 4, "EQ_TC": 1, "EQ_RM": 1}
# enfermeiro e tecnico: o necessario para operar consultorios e equipamentos no teto
N2_MAX["ENFERMEIRO"] = math.ceil(N2_MAX["MED_ESP"] * HORAS_40 / CONSUMO2[("CONS_ESP", "MED_ESP")]
                                 * CONSUMO2[("CONS_ESP", "ENFERMEIRO")] / HORAS_40)
N2_MAX["TEC_RADIOL"] = math.ceil((N2_MAX["EQ_TC"] * CARGA2["EQ_TC"] * CONSUMO2[("TC", "TEC_RADIOL")]
                                  + N2_MAX["EQ_RM"] * CARGA2["EQ_RM"] * CONSUMO2[("RM", "TEC_RADIOL")]) / HORAS_24)
reg("Nivel 2", "n2_max_padrao (policlinica candidata)", "; ".join(f"{k}: {v}" for k, v in N2_MAX.items()),
    "FTE ou equipamentos", "DADO",
    "Programa das policlinicas do Novo PAC: 25 consultorios, 4 salas de ultrassom, tomografia e ressonancia "
    "(SESAB 2024; Tribuna de Petropolis 2026)",
    "MED_ESP: 25 consultorios x 60 h/semana (7h-19h) / 40 h = 38 FTE. Enfermeiro = horas de enfermagem das consultas "
    "que 38 especialistas fazem; tecnico de radiologia = horas para operar 1 TC + 1 RM na capacidade (jornada de 24 h). "
    "Unidades existentes: max(padrao, atual).")
reg("Nivel 2", "cesta de equipamentos da policlinica", f"R$ {INV_EQ['EQ_RM'] + INV_EQ['EQ_TC'] + 4 * INV_EQ['EQ_US']:,.0f}",
    "R$", "DADO", "Novo PAC: investimento medio de R$ 30 mi por policlinica (obra, equipamentos e mobiliario)",
    "RM + TC + 4 US cabem nos ~R$ 13 mi que sobram depois da obra de Uberlandia (R$ 16,9 mi): validacao dos precos.")
INV_POLI = reg("Nivel 2", "investimento policlinica (obra)", 16900000.0, "R$", "DADO",
               "Policlinica de Uberlandia (Novo PAC, termo de compromisso set/2025, ordem de servico 26/08/2026): "
               "~R$ 16,9 mi federais para a construcao",
               "Os equipamentos de imagem entram a parte, como recurso EQ_*.")
# Centro Especializado em Reabilitacao (CER, ambulatorio especializado do Setor Leste), out/2026:
# despesas operacionais R$ 55.786,80 + servicos de terceiros R$ 1.263,91 - INSS do pessoal rateado R$ 3.385,42 (por mes)
CF2_EXIST = reg("Nivel 2", "custo_fixo2 existente (custo fixo operacional)", round(12 * (55786.80 + 1263.91 - 3385.42), 2),
                "R$/ano", "DADO",
                "Contrato 388/2023, 16o TA (out/2026): despesas operacionais + servicos de terceiros do CER "
                "(ambulatorio especializado municipal)",
                "Limpeza, vigilancia, portaria, manutencao, locacao de equipamentos, materiais e pessoal administrativo "
                "rateado. Antes: 8% da obra (R$ 1,35 mi).")
CF2_CAND = reg("Nivel 2", "custo_fixo2 candidato", round(CF2_EXIST + INV_POLI * CRF_PREDIO, 2), "R$/ano", "DADO",
               "custo fixo operacional (CER) + obra da policlinica x CRF predio", "")

# Capacidade existente do nivel 2 pela producao SUS (SIA/TabNet, Uberlandia, ago/2025-jul/2026, qtd. aprovada)
SIA = {  # prestador: (consultas medicas especializadas 0301010072, US 0205, TC 0206, RM 0207)
    "municipal": (257005, 23369, 9346, 2550),
    "hc_ufu": (219286, 18304, 15314 + 1160, 1922),      # empresa publica (EBSERH) + federal
    "amvap": (1194, 2261, 1511, 1166),                  # administracao publica - outros (consorcio)
    "privado": (65055 + 6989 + 5252, 51122 + 49, 8783, 7329),
}
reg("Nivel 2", "producao SUS de Uberlandia (12 meses)", "consultas esp. 554.781; US 95.105; TC 36.114; RM 12.967", "por ano",
    "DADO", "SIA/SUS via TabNet (producao ambulatorial por local de atendimento, MG, ago/2025-jul/2026, qtd. aprovada)",
    "Por esfera juridica: municipal, HC-UFU (empresa publica), consorcio AMVAP e privados contratados.")
SIA_DESTINO = {"municipal": 4684281, "hc_ufu": 2146339, "amvap": 6102174, "privado": 4684281}
reg("Nivel 2", "capacidade existente (n2_atual)", "producao x parcela de residentes / produtividade", "FTE e equipamentos",
    "DADO", "SIA (producao) + SIH (parcela de residentes) + produtividades do Caderno 1 e da Portaria 1.101",
    "Substitui a carga horaria do CNES, que superestima o ambulatorio de ensino do HC-UFU (~860 consultas por "
    "especialista/ano contra ~6.200 no parametro). Producao municipal -> CEM; HC-UFU -> Amelio Marques; consorcio -> "
    "AMVAP; privados contratados (maioria no centro) -> CEM.")

# ---------------------------------------------------------------------------
# Nivel 3: atencao hospitalar (Caderno 1, secao V)
# ---------------------------------------------------------------------------
S3 = ["INT_CLIN", "INT_CIR", "INT_OBST", "INT_PED", "INT_NEO"]
R3 = ["LEITO_CLIN", "LEITO_CIR", "LEITO_OBST", "LEITO_PED", "LEITO_UCI_N", "LEITO_UTI_A", "LEITO_UTI_P", "LEITO_UTI_N",
      "MEDICO", "ENFERMEIRO", "TEC_ENF"]
mid = lambda a, b: (a + b) / 2
TI = {"clin_15_59": mid(13.8, 24.6), "clin_60": mid(72.4, 116.8), "cir_15_59": mid(21.5, 35.7), "cir_60": mid(44.0, 72.6),
      "ped_clin": mid(27.8, 48.8), "ped_cir": mid(8.4, 19.4), "neo": mid(82.4, 168.0)}          # por mil
TMP = {"obst": mid(2.4, 3.1), "neo": mid(6.5, 8.2), "ped_clin": mid(4.6, 5.7), "ped_cir": mid(2.4, 3.9),
       "clin_15_59": mid(6.5, 8.5), "clin_60": mid(7.4, 9.7), "cir_15_59": mid(3.6, 4.4), "cir_60": mid(4.6, 6.5)}
P_UTI = {"neo": mid(.2354, .3979), "ped_clin": mid(.0234, .0504), "ped_cir": mid(.0310, .0561), "obst": mid(.0005, .0066),
         "clin_15_59": mid(.0428, .0624), "clin_60": mid(.0603, .0985), "cir_15_59": mid(.0488, .0625), "cir_60": mid(.0992, .1846)}
TMP_UTI = {"neo": mid(8.8, 11.9), "ped_clin": mid(7.78, 14.1), "ped_cir": mid(5.97, 8.36), "obst": mid(2.87, 4.59),
           "clin_15_59": mid(6.79, 9.08), "clin_60": mid(7.39, 9.52), "cir_15_59": mid(4.48, 5.92), "cir_60": mid(4.64, 6.24)}
reg("Nivel 3", "S3", ", ".join(S3), "-", "NORMATIVO", "Caderno 1, Quadros 37-38 (tipos de leito geral)",
    "Clinica e cirurgica adulto (15-59 e 60+ ponderados), obstetricia, pediatria (clinica + cirurgica) e neonatologia.")
reg("Nivel 3", "taxa de internacao (TI)", "ponto medio da faixa do Quadro 39", "internacoes/mil hab SUS/ano", "NORMATIVO",
    "Caderno 1, Quadro 39", "Ponto medio entre o P25 e o P75 das capitais. Obstetricia: TI = 1,0 por gestante (Quadro 38).")
reg("Nivel 3", "TMP e UTI", "pontos medios dos Quadros 40, 41 e 42", "dias; %", "NORMATIVO", "Caderno 1", "")
RHO_GERAL = reg("Nivel 3", "taxa de ocupacao leito geral", 0.815, "-", "NORMATIVO",
                "Caderno 1, Quadro 43 (media ponderada, recusa de 5%)", "")
RHO_UTI = reg("Nivel 3", "taxa de ocupacao UTI/UCI", 0.655, "-", "NORMATIVO",
              "Caderno 1, Quadro 43 (10-20 leitos, recusa de 5%)", "Unidades de terapia intensiva sao pequenas.")
reg("Nivel 3", "FR e DF", 1.0, "-", "NORMATIVO", "Caderno 1 (simulacoes usam FR = DF = 1)", "")
FRAC_HCUFU = reg("Nivel 3", "fracao do HC-UFU usada por residentes de Uberlandia", 0.753, "-", "DADO",
                 "SIH/SUS, microdados RD MG set/2025-ago/2026: 15.231 de 20.220 internacoes do HC-UFU (75,3%)",
                 "Equivale ao Fnr do Caderno. Aplicada aos leitos, a equipe hospitalar e a producao ambulatorial do HC-UFU. "
                 "Os demais hospitais tem 99-100% de residentes (Municipal 99,5%; Triangulo 99,9%; Int. Pediatrica 100%).")
FRAC_RES_SIA = {"municipal": 1.0, "hc_ufu": 0.72, "amvap": 0.84, "privado": 1.0}
reg("Nivel 2", "parcela de residentes na producao ambulatorial", "municipal e privados 1,0; HC-UFU 0,72; AMVAP 0,84",
    "-", "DADO",
    "SIA/TabNet MG ago/2025-jul/2026: producao individualizada (BPA-I/APAC) dos residentes de Uberlandia (por local de "
    "residencia) x producao atendida em Uberlandia por esfera juridica (por local de atendimento)",
    "Rede municipal e contratados exigem comprovante de residencia (contratos de gestao, Anexo III, 1.5) -> 100%. "
    "HC-UFU e AMVAP estimados juntos por minimos quadrados nas consultas especializadas, US, TC e RM. HC-UFU fica "
    "estavel (0,72 consultas; 0,74 US; 0,76 TC) e confirma o SIH (0,753). AMVAP tem pouco volume: estimativa imprecisa.")
POP_IBGE = {"Censo 2022": 713224, "estimativa 2024": 754954, "estimativa 2025": 761835, "estimativa 2026": 768339}
FATOR_POP = reg("Demanda", "fator de populacao 2026 / Censo 2022", round(POP_IBGE["estimativa 2026"] / POP_IBGE["Censo 2022"], 5),
                "-", "DADO", "IBGE, estimativas populacionais (SIDRA tabela 6579): Uberlandia 768.339 hab. em 2026",
                "Aplicado de forma uniforme a todos os setores e faixas etarias (a distribuicao espacial e etaria continua "
                "a do Censo 2022 - INFERIDO). Corrige tambem a cobertura de planos: beneficiarios da ANS de 2026 / populacao 2026.")
reg("Escopo", "urgencia e emergencia (UAI/UPA, pronto-atendimento)", "fora do modelo", "-", "DECISAO", "Decisao do grupo (out/2026)",
    "As ~20 mil internacoes curtas por ano nas UAIs (SIH) nao entram na demanda hospitalar.")
reg("Escopo", "cobertura rural", "100% a 5 km OU 25 min, de carro", "-", "DECISAO", "Decisao do grupo (out/2026)",
    "Mantida mesmo que crie UBS pequenas na zona rural.")
reg("Escopo", "referencia hospitalar", "unica por unidade secundaria (coerente = 1)", "-", "DECISAO", "Decisao do grupo (out/2026)", "")
reg("Demanda", "distribuicao espacial do crescimento 2022-2026", "uniforme entre setores", "-", "INFERIDO",
    "nao ha estimativa do IBGE abaixo do municipio",
    "Aproximacao aceita: o crescimento e de 7,7% em 4 anos e as UBS operam com folga media de 8% "
    "(2.754 hab. por eSF na solucao de custo minimo, contra o teto de 3.000), entao o erro de localizacao do "
    "crescimento muda pouco o numero de equipes. Se a Prefeitura tiver crescimento por bairro, trocar.")
reg("Nivel 3", "pontos das faixas do Caderno 1", "ponto medio (TI, TMP, % UTI); ocupacao com fila de 5%", "-", "INFERIDO",
    "Caderno 1, Quadros 37-43", "Escolha neutra dentro da norma. O lado alto da demanda fica coberto pelo cenario "
    "'observada' (x1,14). A ocupacao real do Hospital Municipal (85-88%) acima da meta indica fila, nao sobra de leitos.")
reg("Acesso", "transito nos tempos de carro", "nao aplicado (velocidade livre do OSRM)", "-", "INFERIDO", "OSRM",
    "Nao muda decisoes: nivel 2 -> hospital no maximo 20 min (limite 120); UBS -> nivel 2 na cidade com mediana de "
    "13 min (limite 60); os trechos longos sao rurais, em rodovia sem congestionamento, e ja viaveis pela distancia; "
    "o objetivo do modelo usa km, nao minutos.")
reg("Escopo", "formato do artigo", "SBPO: ate 12 paginas, modelo da SOBRAPO", "-", "INFERIDO",
    "padrao de artigo completo do Simposio Brasileiro de Pesquisa Operacional",
    "A pasta nao tem enunciado com formato. Adotado o padrao brasileiro de PO (introducao, revisao, modelo, dados, "
    "resultados, conclusao). Trocar se o professor indicar outro.")
reg("Nivel 3", "validacao da demanda com o SIH", "Caderno 33.191 internacoes x observado 39.950 em hospitais (+19.860 nas UAIs)",
    "internacoes/ano", "DADO", "SIH/SUS RD MG set/2025-ago/2026, residentes de Uberlandia",
    "Leito-dia: Caderno 187 mil x observado 213 mil nos hospitais (+14%). Cirurgica observada 1,7x o Caderno; clinica, "
    "obstetrica e pediatrica proximas. As internacoes curtas das UAIs (TMP 3,3 dias) sao rede de urgencia, fora do modelo.")
FATOR_DEMANDA3 = 1.0   # valor da base principal; o gerador grava tambem a base do cenario observado
CENARIOS_DEMANDA3 = {"caderno": 1.0, "observada": 1.14}
reg("Nivel 3", "cenarios de demanda hospitalar", "caderno = 1,00 (base principal); observada = 1,14", "-", "DECISAO",
    "Decisao do grupo (out/2026): rodar os dois cenarios",
    "1,14 = leito-dia hospitalar dos residentes no SIH / leito-dia do Caderno 1. O gerador grava um .dat para cada cenario.")
reg("Nivel 3", "leito como recurso", "carga = 365 x rho (leito-dia/ano); consumo = dias por internacao", "-", "INFERIDO",
    "Caderno 1, Equacoes 1 a 3: NL = NI x TMP / (365 x rho)",
    "A restricao R41 do modelo reproduz exatamente a equacao de leitos do Caderno.")

ENF_H = {"geral": 5.0, "uci": 10.0, "uti": 18.0}
ENF_PCT = {"geral": 0.33, "uci": 0.42, "uti": 0.52}
MED_H = {"geral": 1.2, "uci": 1.5, "uti": 2.8}
MED_PROC = {"INT_CIR": 6.0, "INT_OBST": 4.0}
reg("Nivel 3", "horas de enfermagem por paciente-dia", "geral 5 h (33% enfermeiro); UCI 10 h (42%); UTI 18 h (52%)", "h",
    "NORMATIVO", "Resolucao COFEN 543/2017", "Geral = media entre cuidados minimos (4 h) e intermediarios (6 h).")
reg("Nivel 3", "horas medicas por paciente-dia", "geral 1,2 h; UCI 1,5 h; UTI 2,8 h", "h", "INFERIDO",
    "UTI: RDC ANVISA 7/2010 (1 diarista + 1 plantonista por 10 leitos)",
    "Enfermaria: diarista 4 h/10 leitos + plantonista 24 h/30 leitos.")
reg("Nivel 3", "horas medicas por procedimento", "cirurgia 6 h (2 h x 3 medicos); parto 4 h", "h/internacao", "INFERIDO", "", "")
SAL3 = {"MEDICO": custo_anual(SAL["medico_hosp"]), "ENFERMEIRO": custo_anual(SAL["enfermeiro"]),
        "TEC_ENF": custo_anual(SAL["tec_enf"])}
INV_LEITO = reg("Nivel 3", "obra por leito", 604000.0, "R$/leito", "DADO",
                "MEC (2025): hospital universitario de 260 leitos por R$ 157 mi", "")
EQ_LEITO = {"geral": 30000.0, "uci": 100000.0, "uti": 144502.0}
reg("Nivel 3", "equipamento por leito", "geral 30 mil (INFERIDO); UCI 100 mil (INFERIDO); UTI 144.502", "R$/leito", "DADO",
    "UTI: Analise de custo medio de equipamentos para leitos de UTI (repositorio UFU, 2024-2025)", "")
DESPESA_HMM = reg("Nivel 3", "despesa anual Hospital Municipal + anexo Santa Catarina", round(247399214.08 * 12 / 11, 2),
                  "R$/ano", "DADO", "SPDM, Registros de receitas e despesas 2025 (jan-nov = R$ 247,4 mi), anualizado",
                  "Gasto com pessoal CLT ~R$ 15,5 mi/mes (69%); 1.986 empregados em ago/2026, ~580 de apoio/administracao.")
PESO_LEITO = {"geral": 1.0, "uci": 1.667, "uti": 2.5}
reg("Nivel 3", "custeio por leito (calibrado)", "(despesa real - pessoal assistencial do modelo) / leitos SUS", "R$/leito/ano",
    "DADO", "SPDM 2025 + CNES (leitos e FTE do Hospital Municipal e anexo)",
    "Inclui apoio, administracao, materiais, medicamentos, pronto-socorro e SADT do hospital. Pesos relativos "
    "geral 1 : UCI 1,67 : UTI 2,5 (INFERIDO). Calculado em gerar_base_uberlandia.py.")
CUSTEIO_LEITO = {}


def classe_leito(r):
    return "uti" if r.startswith("LEITO_UTI") else "uci" if r == "LEITO_UCI_N" else "geral"


def calibra_custeio_leito(custo_pessoal_assist, leitos_por_tipo):
    """Custeio por leito tal que (pessoal assistencial do modelo + leitos x custeio) = despesa real do HMM."""
    if CUSTEIO_LEITO:
        return
    residual = DESPESA_HMM - custo_pessoal_assist
    peso_total = sum(q * PESO_LEITO[classe_leito(r)] for r, q in leitos_por_tipo.items())
    base = residual / peso_total
    for c, w in PESO_LEITO.items():
        CUSTEIO_LEITO[c] = round(base * w, 2)
    for r in R3:
        if r.startswith("LEITO"):
            c = classe_leito(r)
            SAL3[r] = round(INV_LEITO * CRF_PREDIO + EQ_LEITO[c] * CRF_EQUIP + CUSTEIO_LEITO[c], 2)
    reg("Nivel 3", "custeio por leito resultante", "; ".join(f"{k}: {v:,.0f}" for k, v in CUSTEIO_LEITO.items()),
        "R$/leito/ano", "DADO", "calibracao SPDM 2025", f"residual de R$ {residual:,.0f} sobre {sum(leitos_por_tipo.values())} leitos")
    reg("Nivel 3", "salario3 (custo anual por recurso)", "; ".join(f"{k}: {v:,.0f}" for k, v in SAL3.items()), "R$/ano",
        "DADO", "pessoal: salario x fator; leito: obra x CRF + equip. x CRF + custeio calibrado", "")
CARGA3 = {r: (HORAS_40 if not r.startswith("LEITO") else round(365 * (RHO_UTI if classe_leito(r) != "geral" else RHO_GERAL), 2))
          for r in R3}
N3_MAX = {"LEITO_CLIN": 200, "LEITO_CIR": 200, "LEITO_OBST": 60, "LEITO_PED": 60, "LEITO_UCI_N": 30, "LEITO_UTI_A": 60,
          "LEITO_UTI_P": 20, "LEITO_UTI_N": 30, "MEDICO": 600, "ENFERMEIRO": 800, "TEC_ENF": 2500}
reg("Nivel 3", "n3_max_padrao", "; ".join(f"{k}: {v}" for k, v in N3_MAX.items()), "leitos ou FTE", "INFERIDO", "",
    "Hospital geral de ~450 leitos. Existentes ampliaveis: max(padrao, atual); contratados/especializados: = atual.")
CF3_POR_LEITO_EXIST = reg("Nivel 3", "custo_fixo3 existente", 0.0, "R$/leito SUS/ano", "DADO", "calibracao SPDM 2025",
                          "Zero: apoio e administracao ja estao no custeio por leito calibrado.")
CF3_CAND = reg("Nivel 3", "custo_fixo3 candidato", round(40e6 * CRF_PREDIO, 2), "R$/ano", "INFERIDO",
               "area de apoio de R$ 40 mi (~25% do hospital de referencia) x CRF",
               "So o capital: o custeio de apoio vem no custo por leito.")
reg("Nivel 3", "capacidade de expansao do Hospital Municipal", "245 leitos instalados; projeto preve mais de 500", "leitos", "DADO",
    "SPDM, Relatorio de Atividades 2025", "Ocupacao real 2025: 85-88% (meta contratual >= 85%).")


def demanda_hospitalar(idade, ans, nv):
    """Internacoes esperadas por tipo (Caderno 1, Eq. 1) e coeficientes do modelo."""
    sus = {"0-14": idade["0-14"] * (1 - ans["cob_0_14"]), "15-59": idade["15-59"] * (1 - ans["cob_15_59"]),
           "60+": idade["60+"] * (1 - ans["cob_60"])}
    nv_sus = nv * (1 - ans["cob_0_14"])
    gest_sus = nv * 1.0 * (1 - ans["cob_15_59"])
    g = {}
    g["clin_15_59"] = sus["15-59"] * TI["clin_15_59"] / 1000
    g["clin_60"] = sus["60+"] * TI["clin_60"] / 1000
    g["cir_15_59"] = sus["15-59"] * TI["cir_15_59"] / 1000
    g["cir_60"] = sus["60+"] * TI["cir_60"] / 1000
    g["ped_clin"] = sus["0-14"] * TI["ped_clin"] / 1000
    g["ped_cir"] = sus["0-14"] * TI["ped_cir"] / 1000
    g["obst"] = gest_sus * 1.0
    g["neo"] = nv_sus * TI["neo"] / 1000
    grupos = {"INT_CLIN": ["clin_15_59", "clin_60"], "INT_CIR": ["cir_15_59", "cir_60"], "INT_OBST": ["obst"],
              "INT_PED": ["ped_clin", "ped_cir"], "INT_NEO": ["neo"]}
    NI, tmp, uti = {}, {}, {}
    for q, gs in grupos.items():
        NI[q] = sum(g[x] for x in gs)
        tmp[q] = sum(g[x] * TMP[x] for x in gs) / NI[q]
        uti[q] = sum(g[x] * P_UTI[x] * TMP_UTI[x] for x in gs) / NI[q]
    return NI, tmp, uti, sus, g


def consumo3(tmp, uti):
    C = {}
    leito_ward = {"INT_CLIN": "LEITO_CLIN", "INT_CIR": "LEITO_CIR", "INT_OBST": "LEITO_OBST", "INT_PED": "LEITO_PED",
                  "INT_NEO": "LEITO_UCI_N"}
    leito_uti = {"INT_CLIN": "LEITO_UTI_A", "INT_CIR": "LEITO_UTI_A", "INT_OBST": "LEITO_UTI_A", "INT_PED": "LEITO_UTI_P",
                 "INT_NEO": "LEITO_UTI_N"}
    for q in S3:
        cw = "uci" if q == "INT_NEO" else "geral"
        C[(q, leito_ward[q])] = round(tmp[q], 4)
        C[(q, leito_uti[q])] = round(uti[q], 4)
        C[(q, "ENFERMEIRO")] = round(tmp[q] * ENF_H[cw] * ENF_PCT[cw] + uti[q] * ENF_H["uti"] * ENF_PCT["uti"], 4)
        C[(q, "TEC_ENF")] = round(tmp[q] * ENF_H[cw] * (1 - ENF_PCT[cw]) + uti[q] * ENF_H["uti"] * (1 - ENF_PCT["uti"]), 4)
        C[(q, "MEDICO")] = round(tmp[q] * MED_H[cw] + uti[q] * MED_H["uti"] + MED_PROC.get(q, 0), 4)
    return C
