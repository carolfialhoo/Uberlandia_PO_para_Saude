# =============================================================================
#  MODELO HIERARQUICO DE LOCALIZACAO-ALOCACAO DA REDE DE ATENCAO A SAUDE
#  Versao 0.2  -  GNU MathProg (GLPK / GUSEK)
#  Disciplina: EPD899 - Operations Research for Health Care (DEP/UFMG)
#
#  Mudancas em relacao a v0.1 (so padroes e comentarios; equacoes iguais):
#   - regra_acesso passa a valer 2 por padrao: o limite e "distancia OU tempo";
#   - os limites de acesso sao fixados pelo exercicio, nao derivados de formula;
#   - velocidades padrao realistas (caminhada 4,5 km/h; carro urbano 30 km/h),
#     usadas apenas quando a matriz de tempos nao for informada;
#   - R2 e R3 sao "recursos": profissionais (horas), equipamentos (exames) e
#     leitos (leito-dia). A restricao de capacidade vale para todos.
#
#  Fluxo unico e obrigatorio (single-flow, Sahin & Sural 2007):
#     setor censitario (nivel 0) -> APS (nivel 1) -> secundaria (nivel 2)
#                                -> terciaria (nivel 3)
#  Hierarquia de servicos: exclusiva (cada nivel oferece os seus servicos).
#
#  Premissas principais
#   1) 100% da populacao de cada setor e vinculada a exatamente uma unidade de
#      APS (UBS), dentro do limite de acesso (5 km OU 25 min);
#   2) cada eSF cobre no maximo pop_por_ESF pessoas (padrao 3.000);
#      cada ACS cobre no maximo pop_por_ACS pessoas (padrao 750, PNAB 2017);
#   3) a UBS tem um porte p em 1..5, definido por faixas de eSF, eSB, ACS e
#      e-Multi; cada porte tem um custo de estrutura;
#   4) so a fracao 100% SUS da populacao (prop_SUS) gera demanda nos niveis
#      2 e 3; as taxas por servico vem dos parametros da Portaria GM/MS
#      1.631/2015 (Caderno 1 de Parametros SUS, preenchidos no .dat);
#   5) a capacidade dos niveis 2 e 3 e dada pelos recursos (horas disponiveis
#      x horas consumidas por atendimento; o mesmo vale para exames por
#      equipamento e leito-dia por leito) e o custo e custo fixo + recursos;
#   6) limites de acesso (exercicio): APS->sec 30 km OU 60 min;
#      sec->ter 60 km OU 120 min.
#
#  Dois modos de otimizacao (lexicografico):
#   modo = 1 : minimiza o CUSTO anual da rede (define quantas unidades abrir,
#              portes e quadro de pessoal);
#   modo = 2 : minimiza a DISTANCIA ponderada pela demanda, com o custo limitado
#              a 'orcamento' (use o custo do modo 1, com ou sem folga).
#  Motivo: minimizar so distancia abriria todos os candidatos; o custo (ou o
#  orcamento) e o que define a "quantidade ideal" de estabelecimentos.
#
#  Convencao: comentarios sem acento (compatibilidade com o editor do GUSEK).
# =============================================================================


# -----------------------------------------------------------------------------
# 1. CONJUNTOS
# -----------------------------------------------------------------------------

set I;              # setores censitarios (pontos de demanda)
set J1;             # locais de APS: UBS existentes + candidatos
set J2;             # locais de atencao secundaria (ex.: centros de especialidades)
set J3;             # locais de atencao terciaria (hospitais)

set PORTE := 1..5;  # portes possiveis da UBS

set S2;             # servicos do nivel secundario (ex.: consulta especializada)
set S3;             # servicos do nivel terciario  (ex.: internacao)
set R2;             # recursos do nivel secundario (profissionais, equipamentos)
set R3;             # recursos do nivel terciario (profissionais, leitos)


# -----------------------------------------------------------------------------
# 2. CONTROLE DA EXECUCAO
# -----------------------------------------------------------------------------

param modo, integer, >= 1, <= 2, default 1;

# Limite de custo usado no modo 2 (mesma unidade monetaria dos custos)
param orcamento, >= 0, default 0;

# Desempates (termos pequenos somados ao objetivo):
#  eps_dist  (modo 1): favorece a menor distancia entre solucoes de mesmo custo;
#  eps_custo (modo 2): evita gastar a folga do orcamento sem ganho de distancia
#                      (ex.: contratar ACS a mais so porque "cabe" no orcamento).
param eps_dist,  >= 0, default 0;
param eps_custo, >= 0, default 1e-6;

# 1 = sistema coerente: cada UBS encaminha para UMA unidade secundaria e cada
#     unidade secundaria para UM hospital (regionalizacao/referencia fixa);
# 0 = o encaminhamento pode ser dividido entre varias unidades.
param coerente, binary, default 1;

# Pesos de cada trecho na distancia total (unidades diferentes:
# pessoas.km no trecho 0-1 e atendimentos.km nos trechos 1-2 e 2-3)
param peso01, >= 0, default 1;
param peso12, >= 0, default 1;
param peso23, >= 0, default 1;


# -----------------------------------------------------------------------------
# 3. POPULACAO, DISTANCIAS E TEMPOS
# -----------------------------------------------------------------------------

# Matriz setor x (POP + locais de APS):
#   matriz01[i,"POP"] = populacao residente no setor i (Censo 2022)
#   matriz01[i,j]     = distancia (km) do setor i ao local de APS j
set COL01 := {"POP"} union J1;
param matriz01{i in I, c in COL01}, >= 0;

param pop{i in I} := matriz01[i,"POP"];
param d01{i in I, j in J1} := matriz01[i,j];

# Distancias (km) entre niveis
param d12{j in J1, k in J2}, >= 0;
param d23{k in J2, h in J3}, >= 0;

# Tempos (min). O ideal e informar a matriz de um roteador (ORS/OSRM).
# Se faltarem, sao estimados pela distancia e por uma velocidade media
# realista (km/h): caminhada ate a UBS; carro em area urbana nos demais trechos.
param vel01, > 0, default 4.5;
param vel12, > 0, default 30;
param vel23, > 0, default 30;
param t01{i in I, j in J1}, >= 0, default 60 * d01[i,j] / vel01;
param t12{j in J1, k in J2}, >= 0, default 60 * d12[j,k] / vel12;
param t23{k in J2, h in J3}, >= 0, default 60 * d23[k,h] / vel23;

# Limites de acesso fixados pelo exercicio (nao sao convertidos entre si)
param dmax01, > 0, default 5;    param tmax01, > 0, default 25;
param dmax12, > 0, default 30;   param tmax12, > 0, default 60;
param dmax23, > 0, default 60;   param tmax23, > 0, default 120;

# Regra de acesso: 1 = distancia E tempo; 2 = distancia OU tempo (exercicio);
#                  3 = somente distancia; 4 = somente tempo
param regra_acesso, integer, >= 1, <= 4, default 2;

param ok01{i in I, j in J1}, binary :=
    if (regra_acesso = 1 and d01[i,j] <= dmax01 and t01[i,j] <= tmax01)
    or (regra_acesso = 2 and (d01[i,j] <= dmax01 or t01[i,j] <= tmax01))
    or (regra_acesso = 3 and d01[i,j] <= dmax01)
    or (regra_acesso = 4 and t01[i,j] <= tmax01)
    then 1 else 0;

param ok12{j in J1, k in J2}, binary :=
    if (regra_acesso = 1 and d12[j,k] <= dmax12 and t12[j,k] <= tmax12)
    or (regra_acesso = 2 and (d12[j,k] <= dmax12 or t12[j,k] <= tmax12))
    or (regra_acesso = 3 and d12[j,k] <= dmax12)
    or (regra_acesso = 4 and t12[j,k] <= tmax12)
    then 1 else 0;

param ok23{k in J2, h in J3}, binary :=
    if (regra_acesso = 1 and d23[k,h] <= dmax23 and t23[k,h] <= tmax23)
    or (regra_acesso = 2 and (d23[k,h] <= dmax23 or t23[k,h] <= tmax23))
    or (regra_acesso = 3 and d23[k,h] <= dmax23)
    or (regra_acesso = 4 and t23[k,h] <= tmax23)
    then 1 else 0;

param Pop_total := sum{i in I} pop[i];

# Fracao da populacao exclusivamente dependente do SUS (0 a 1)
param prop_SUS, > 0, <= 1;


# -----------------------------------------------------------------------------
# 4. ATENCAO PRIMARIA (NIVEL 1): STATUS, PORTES, EQUIPES E CUSTOS
# -----------------------------------------------------------------------------

param existente1{J1}, binary, default 0;   # 1 = UBS ja existe (fica aberta)
param elegivel1{J1},  binary, default 1;   # 0 = candidato descartado
param porte_min1{J1}, integer, >= 0, <= 5, default 0;  # porte minimo (existentes)

# Faixas de composicao de cada porte
param minESF{PORTE}, integer, >= 0;   param maxESF{PORTE}, integer, >= 0;
param minESB{PORTE}, integer, >= 0;   param maxESB{PORTE}, integer, >= 0;
param minACS{PORTE}, integer, >= 0;   param maxACS{PORTE}, integer, >= 0;
param minEMU{PORTE}, integer, >= 0;   param maxEMU{PORTE}, integer, >= 0;

# Quantidades atuais (nao podem ser reduzidas)
param ESF_atual{J1}, integer, >= 0, default 0;
param ESB_atual{J1}, integer, >= 0, default 0;
param ACS_atual{J1}, integer, >= 0, default 0;
param EMU_atual{J1}, integer, >= 0, default 0;

# Custos anuais: estrutura por porte (pode ser sobrescrito por local) e equipes
param custo_porte{PORTE}, >= 0;
param custo_fixo1{j in J1, p in PORTE}, >= 0, default custo_porte[p];
param custo_ESF, >= 0;
param custo_ESB, >= 0;
param custo_ACS, >= 0;
param custo_EMU, >= 0;

# Capacidades populacionais (0 desliga a restricao correspondente)
param pop_por_ESF, > 0,  default 3000;
param pop_por_ACS, >= 0, default 750;
param pop_por_ESB, >= 0, default 0;


# -----------------------------------------------------------------------------
# 5. DEMANDA DOS NIVEIS 2 E 3 (PORTARIA GM/MS 1.631/2015)
# -----------------------------------------------------------------------------

# taxa2[s]: atendimentos do servico s por 'escala2[s]' habitantes SUS/ano
#   ex.: taxa2 = 0.5, escala2 = 1    -> 0,5 por habitante/ano
#        taxa2 = 80,  escala2 = 1000 -> 80 por mil habitantes/ano
param taxa2{S2}, >= 0;
param escala2{S2}, > 0, default 1;
param coef2{s in S2} := taxa2[s] / escala2[s];

# prop23[s,q]: fracao dos atendimentos secundarios s encaminhada ao servico
# terciario q (0 quando a transicao nao existe na linha de cuidado)
param prop23{S2, S3}, >= 0, <= 1, default 0;

# Demandas totais esperadas (atendimentos/ano) e limites big-M derivados
param Dem2{s in S2} := prop_SUS * Pop_total * coef2[s];
param Dem3{q in S3} := sum{s in S2} prop23[s,q] * Dem2[s];
param Dem2_total := sum{s in S2} Dem2[s];
param Dem3_total := sum{q in S3} Dem3[q];


# -----------------------------------------------------------------------------
# 6. NIVEIS 2 E 3: STATUS, PESSOAL, PRODUTIVIDADE E CUSTOS
# -----------------------------------------------------------------------------

param existente2{J2}, binary, default 0;
param elegivel2{J2},  binary, default 1;
param custo_fixo2{J2}, >= 0, default 0;          # estrutura (R$/ano)
param salario2{R2}, >= 0;                         # custo anual por unidade do recurso r
param carga2{R2}, > 0;                            # capacidade/ano de 1 unidade (h ou exames)
param consumo2{S2, R2}, >= 0, default 0;          # uso de r por atendimento s (mesma unidade)
param n2_max_padrao{R2}, integer, >= 0;
param n2_max{k in J2, r in R2}, integer, >= 0, default n2_max_padrao[r];
param n2_min{J2, R2}, integer, >= 0, default 0;
param n2_atual{J2, R2}, integer, >= 0, default 0;

param existente3{J3}, binary, default 0;
param elegivel3{J3},  binary, default 1;
param custo_fixo3{J3}, >= 0, default 0;
param salario3{R3}, >= 0;                         # custo anual por unidade do recurso r
param carga3{R3}, > 0;                            # leito: 365 x ocupacao (leito-dia); pessoal: h/ano
param consumo3{S3, R3}, >= 0, default 0;          # leito: dias por internacao; pessoal: h
param n3_max_padrao{R3}, integer, >= 0;
param n3_max{h in J3, r in R3}, integer, >= 0, default n3_max_padrao[r];
param n3_min{J3, R3}, integer, >= 0, default 0;
param n3_atual{J3, R3}, integer, >= 0, default 0;


# -----------------------------------------------------------------------------
# 7. CONJUNTOS DERIVADOS (ARCOS VIAVEIS)
#    Variaveis so sao criadas para arcos que respeitam o limite de acesso.
#    Isso reduz muito o tamanho do modelo com dados reais (milhares de setores).
# -----------------------------------------------------------------------------

set J1d := {j in J1: existente1[j] = 1 or elegivel1[j] = 1};
set J2d := {k in J2: existente2[k] = 1 or elegivel2[k] = 1};
set J3d := {h in J3: existente3[h] = 1 or elegivel3[h] = 1};

set A01 := {i in I,   j in J1d: ok01[i,j] = 1};
set A12 := {j in J1d, k in J2d: ok12[j,k] = 1};
set A23 := {k in J2d, h in J3d: ok23[k,h] = 1};


# -----------------------------------------------------------------------------
# 8. VARIAVEIS DE DECISAO
# -----------------------------------------------------------------------------

# Nivel 1
var a1{J1d}, binary;                  # 1 se a UBS j esta aberta
var x1{J1d, PORTE}, binary;           # 1 se a UBS j tem porte p
var nESF{J1d}, integer, >= 0;         # equipes de Saude da Familia
var nESB{J1d}, integer, >= 0;         # equipes de Saude Bucal
var nACS{J1d}, integer, >= 0;         # agentes comunitarios de saude
var nEMU{J1d}, integer, >= 0;         # equipes e-Multi
var y{A01}, binary;                   # 1 se o setor i e vinculado a UBS j
var popAPS{J1d}, >= 0;                # populacao adscrita a UBS j (auxiliar)

# Nivel 2
var a2{J2d}, binary;
var n2{J2d, R2}, integer, >= 0;
var f12{A12, S2}, >= 0;               # atendimentos/ano encaminhados j -> k
var z12{(j,k) in A12: coerente = 1}, binary;   # referencia fixa j -> k
var rec2{J2d, S2}, >= 0;              # atendimentos recebidos em k (auxiliar)

# Nivel 3
var a3{J3d}, binary;
var n3{J3d, R3}, integer, >= 0;
var f23{A23, S3}, >= 0;               # atendimentos/ano encaminhados k -> h
var z23{(k,h) in A23: coerente = 1}, binary;
var rec3{J3d, S3}, >= 0;

# Componentes do objetivo
var Custo1 >= 0;   var Custo2 >= 0;   var Custo3 >= 0;   var CustoTotal >= 0;
var Dist01 >= 0;   var Dist12 >= 0;   var Dist23 >= 0;   var DistTotal  >= 0;


# -----------------------------------------------------------------------------
# 9. CUSTOS, DISTANCIAS E FUNCAO OBJETIVO
# -----------------------------------------------------------------------------

s.t. DefCusto1:
    Custo1 = sum{j in J1d, p in PORTE} custo_fixo1[j,p] * x1[j,p]
           + sum{j in J1d} ( custo_ESF * nESF[j] + custo_ESB * nESB[j]
                           + custo_ACS * nACS[j] + custo_EMU * nEMU[j] );

s.t. DefCusto2:
    Custo2 = sum{k in J2d} custo_fixo2[k] * a2[k]
           + sum{k in J2d, r in R2} salario2[r] * n2[k,r];

s.t. DefCusto3:
    Custo3 = sum{h in J3d} custo_fixo3[h] * a3[h]
           + sum{h in J3d, r in R3} salario3[r] * n3[h,r];

s.t. DefCustoTotal: CustoTotal = Custo1 + Custo2 + Custo3;

# Distancia ponderada pela demanda em cada trecho
s.t. DefDist01: Dist01 = sum{(i,j) in A01} pop[i] * d01[i,j] * y[i,j];
s.t. DefDist12: Dist12 = sum{(j,k) in A12, s in S2} d12[j,k] * f12[j,k,s];
s.t. DefDist23: Dist23 = sum{(k,h) in A23, q in S3} d23[k,h] * f23[k,h,q];
s.t. DefDistTotal:
    DistTotal = peso01 * Dist01 + peso12 * Dist12 + peso23 * Dist23;

minimize Objetivo:
    if modo = 1 then CustoTotal + eps_dist * DistTotal
               else DistTotal  + eps_custo * CustoTotal;

# Modo 2: limita o custo ao orcamento (ex.: custo otimo do modo 1)
s.t. Orcamento{z in 1..1: modo = 2}: CustoTotal <= orcamento;


# -----------------------------------------------------------------------------
# 10. RESTRICOES - NIVEL 1 (APS)
# -----------------------------------------------------------------------------

# Um porte por UBS aberta; UBS existentes permanecem abertas
s.t. R01_Porte{j in J1d}:        sum{p in PORTE} x1[j,p] = a1[j];
s.t. R02_MantemUBS{j in J1d: existente1[j] = 1}: a1[j] = 1;
s.t. R03_PorteMinimo{j in J1d: porte_min1[j] > 0}:
    sum{p in PORTE} p * x1[j,p] >= porte_min1[j];

# Composicao das equipes dentro da faixa do porte escolhido
s.t. R04_ESFmin{j in J1d}: nESF[j] >= sum{p in PORTE} minESF[p] * x1[j,p];
s.t. R05_ESFmax{j in J1d}: nESF[j] <= sum{p in PORTE} maxESF[p] * x1[j,p];
s.t. R06_ESBmin{j in J1d}: nESB[j] >= sum{p in PORTE} minESB[p] * x1[j,p];
s.t. R07_ESBmax{j in J1d}: nESB[j] <= sum{p in PORTE} maxESB[p] * x1[j,p];
s.t. R08_ACSmin{j in J1d}: nACS[j] >= sum{p in PORTE} minACS[p] * x1[j,p];
s.t. R09_ACSmax{j in J1d}: nACS[j] <= sum{p in PORTE} maxACS[p] * x1[j,p];
s.t. R10_EMUmin{j in J1d}: nEMU[j] >= sum{p in PORTE} minEMU[p] * x1[j,p];
s.t. R11_EMUmax{j in J1d}: nEMU[j] <= sum{p in PORTE} maxEMU[p] * x1[j,p];

# Recursos atuais nao sao retirados
s.t. R12_ESFatual{j in J1d: ESF_atual[j] > 0}: nESF[j] >= ESF_atual[j];
s.t. R13_ESBatual{j in J1d: ESB_atual[j] > 0}: nESB[j] >= ESB_atual[j];
s.t. R14_ACSatual{j in J1d: ACS_atual[j] > 0}: nACS[j] >= ACS_atual[j];
s.t. R15_EMUatual{j in J1d: EMU_atual[j] > 0}: nEMU[j] >= EMU_atual[j];

# Cobertura de 100%: cada setor vinculado a exatamente uma UBS acessivel
s.t. R16_Cobertura{i in I}:
    sum{j in J1d: (i,j) in A01} y[i,j] = 1;

# So se vincula a UBS aberta
s.t. R17_Vinculo{(i,j) in A01}: y[i,j] <= a1[j];

# Populacao adscrita a cada UBS
s.t. R18_PopAPS{j in J1d}:
    popAPS[j] = sum{i in I: (i,j) in A01} pop[i] * y[i,j];

# Capacidade das equipes (eSF: 3.000 pessoas; ACS: 750 pessoas)
s.t. R19_CapESF{j in J1d}:                      popAPS[j] <= pop_por_ESF * nESF[j];
s.t. R20_CapACS{j in J1d: pop_por_ACS > 0}:     popAPS[j] <= pop_por_ACS * nACS[j];
s.t. R21_CapESB{j in J1d: pop_por_ESB > 0}:     popAPS[j] <= pop_por_ESB * nESB[j];


# -----------------------------------------------------------------------------
# 11. RESTRICOES - NIVEL 2 (ATENCAO SECUNDARIA)
# -----------------------------------------------------------------------------

# Toda a demanda SUS gerada na UBS j e encaminhada a unidades secundarias
s.t. R22_Gera2{j in J1d, s in S2}:
    sum{k in J2d: (j,k) in A12} f12[j,k,s] = prop_SUS * coef2[s] * popAPS[j];

# Demanda recebida em k
s.t. R23_Rec2{k in J2d, s in S2}:
    rec2[k,s] = sum{j in J1d: (j,k) in A12} f12[j,k,s];

# Unidade fechada nao recebe demanda
s.t. R24_Aberta2{k in J2d}:
    sum{s in S2} rec2[k,s] <= Dem2_total * a2[k];

# Sistema coerente: uma unica referencia secundaria por UBS
s.t. R25_UmaRef2{j in J1d: coerente = 1}:
    sum{k in J2d: (j,k) in A12} z12[j,k] <= 1;
s.t. R26_Ref2{(j,k) in A12, s in S2: coerente = 1}:
    f12[j,k,s] <= Dem2[s] * z12[j,k];

s.t. R27_Mantem2{k in J2d: existente2[k] = 1}: a2[k] = 1;

# Quadro de pessoal
s.t. R28_N2min{k in J2d, r in R2}: n2[k,r] >= n2_min[k,r] * a2[k];
s.t. R29_N2max{k in J2d, r in R2}: n2[k,r] <= n2_max[k,r] * a2[k];
s.t. R30_N2atual{k in J2d, r in R2: n2_atual[k,r] > 0}: n2[k,r] >= n2_atual[k,r];

# Capacidade produtiva: uso <= capacidade, por recurso (horas ou exames)
s.t. R31_Cap2{k in J2d, r in R2}:
    sum{s in S2} consumo2[s,r] * rec2[k,s] <= carga2[r] * n2[k,r];


# -----------------------------------------------------------------------------
# 12. RESTRICOES - NIVEL 3 (ATENCAO TERCIARIA)
# -----------------------------------------------------------------------------

# Parte da demanda atendida no nivel 2 e encaminhada ao nivel 3
s.t. R32_Gera3{k in J2d, q in S3}:
    sum{h in J3d: (k,h) in A23} f23[k,h,q] = sum{s in S2} prop23[s,q] * rec2[k,s];

s.t. R33_Rec3{h in J3d, q in S3}:
    rec3[h,q] = sum{k in J2d: (k,h) in A23} f23[k,h,q];

s.t. R34_Aberta3{h in J3d}:
    sum{q in S3} rec3[h,q] <= Dem3_total * a3[h];

s.t. R35_UmaRef3{k in J2d: coerente = 1}:
    sum{h in J3d: (k,h) in A23} z23[k,h] <= 1;
s.t. R36_Ref3{(k,h) in A23, q in S3: coerente = 1}:
    f23[k,h,q] <= Dem3[q] * z23[k,h];

s.t. R37_Mantem3{h in J3d: existente3[h] = 1}: a3[h] = 1;

s.t. R38_N3min{h in J3d, r in R3}: n3[h,r] >= n3_min[h,r] * a3[h];
s.t. R39_N3max{h in J3d, r in R3}: n3[h,r] <= n3_max[h,r] * a3[h];
s.t. R40_N3atual{h in J3d, r in R3: n3_atual[h,r] > 0}: n3[h,r] >= n3_atual[h,r];

# Capacidade por recurso. Para leitos reproduz NL = NI x TMP / (365 x ocupacao)
# do Caderno 1 de Parametros SUS (Portaria 1.631/2015)
s.t. R41_Cap3{h in J3d, r in R3}:
    sum{q in S3} consumo3[q,r] * rec3[h,q] <= carga3[r] * n3[h,r];


# -----------------------------------------------------------------------------
# 13. VERIFICACOES DOS DADOS (antes de resolver)
# -----------------------------------------------------------------------------

check: Pop_total > 0;
check{p in PORTE}: maxESF[p] >= minESF[p] and maxESB[p] >= minESB[p]
               and maxACS[p] >= minACS[p] and maxEMU[p] >= minEMU[p];
check{s in S2}: sum{q in S3} prop23[s,q] <= 1 + 1e-9;
check: modo = 1 or orcamento > 0;

# Diagnostico de inviabilidade de acesso (listado antes do 'check')
printf{i in I: card({j in J1d: (i,j) in A01}) = 0}
    "AVISO: setor %s nao tem UBS dentro do limite de acesso\n", i;
printf{j in J1d: card({k in J2d: (j,k) in A12}) = 0}
    "AVISO: UBS %s nao alcanca nenhuma unidade secundaria\n", j;
printf{k in J2d: card({h in J3d: (k,h) in A23}) = 0}
    "AVISO: unidade secundaria %s nao alcanca nenhum hospital\n", k;
check{i in I}: card({j in J1d: (i,j) in A01}) >= 1;

solve;


# -----------------------------------------------------------------------------
# 14. RELATORIO
# -----------------------------------------------------------------------------

printf "\n================================================================\n";
printf " REDE HIERARQUICA DE ATENCAO A SAUDE  -  modo %d (%s)\n",
       modo, if modo = 1 then "min custo" else "min distancia";
printf "================================================================\n";
printf "Populacao total ............ %12.0f\n", Pop_total;
printf "Proporcao 100%% SUS ......... %11.1f%%\n", 100 * prop_SUS;
printf "Demanda secundaria (ano) ... %12.0f\n", Dem2_total;
printf "Demanda terciaria (ano) .... %12.0f\n", Dem3_total;
printf "Custo total (ano) .......... %12.2f\n", CustoTotal;
printf "   APS / Sec / Ter ......... %.2f / %.2f / %.2f\n", Custo1, Custo2, Custo3;
printf "Distancia media casa-UBS ... %12.3f km\n", Dist01 / Pop_total;
printf "Distancia media UBS-sec .... %12.3f km\n",
       if Dem2_total > 0 then Dist12 / Dem2_total else 0;
printf "Distancia media sec-ter .... %12.3f km\n",
       if Dem3_total > 0 then Dist23 / Dem3_total else 0;
printf "eSF totais: %d (minimo teorico ceil(Pop/%d) = %d)\n",
       sum{j in J1d} nESF[j], pop_por_ESF, ceil(Pop_total / pop_por_ESF);
printf{z in 1..1: modo = 1}
    ">> Proximo passo: rode o modo 2 com orcamento = %.2f (ou com folga)\n",
    CustoTotal;

printf "\n--- APS: UBS abertas ---\n";
printf{j in J1d, p in PORTE: x1[j,p] > 0.5}
    "%-12s %s porte=%d  eSF=%d eSB=%d ACS=%d eMulti=%d  pop=%.0f (%.0f%% da cap. eSF)\n",
    j, if existente1[j] = 1 then "[exist]" else "[NOVA] ", p,
    nESF[j], nESB[j], nACS[j], nEMU[j], popAPS[j],
    if nESF[j] > 0 then 100 * popAPS[j] / (pop_por_ESF * nESF[j]) else 0;

printf "\n--- Vinculo setor -> UBS ---\n";
printf{(i,j) in A01: y[i,j] > 0.5}
    "%-10s -> %-12s pop=%7.0f  %5.2f km  %5.1f min\n",
    i, j, pop[i], d01[i,j], t01[i,j];

printf "\n--- Atencao secundaria ---\n";
printf{k in J2d: a2[k] > 0.5}
    "%-12s %s atendimentos/ano=%.0f\n",
    k, if existente2[k] = 1 then "[exist]" else "[NOVA] ", sum{s in S2} rec2[k,s];
printf{k in J2d, r in R2: n2[k,r] > 0.5}
    "    %-12s %-14s %3d  (uso %.0f%%)\n", k, r, n2[k,r],
    100 * sum{s in S2} consumo2[s,r] * rec2[k,s] / (carga2[r] * n2[k,r]);
printf{(j,k) in A12, s in S2: f12[j,k,s] > 1e-6}
    "    %-12s -> %-12s %-16s %9.1f  (%.1f km)\n", j, k, s, f12[j,k,s], d12[j,k];

printf "\n--- Atencao terciaria ---\n";
printf{h in J3d: a3[h] > 0.5}
    "%-12s %s atendimentos/ano=%.0f\n",
    h, if existente3[h] = 1 then "[exist]" else "[NOVA] ", sum{q in S3} rec3[h,q];
printf{h in J3d, r in R3: n3[h,r] > 0.5}
    "    %-12s %-14s %3d  (uso %.0f%%)\n", h, r, n3[h,r],
    100 * sum{q in S3} consumo3[q,r] * rec3[h,q] / (carga3[r] * n3[h,r]);
printf{(k,h) in A23, q in S3: f23[k,h,q] > 1e-6}
    "    %-12s -> %-12s %-16s %9.1f  (%.1f km)\n", k, h, q, f23[k,h,q], d23[k,h];

# Saidas em CSV (para mapas / Power BI). Gravadas na pasta de execucao.
table T_setores {(i,j) in A01: y[i,j] > 0.5} OUT "CSV" "res_setores.csv":
    i ~ setor, j ~ ubs, pop[i] ~ pop, d01[i,j] ~ dist_km, t01[i,j] ~ tempo_min;

table T_ubs {j in J1d, p in PORTE: x1[j,p] > 0.5} OUT "CSV" "res_ubs.csv":
    j ~ ubs, existente1[j] ~ existente, p ~ porte, nESF[j] ~ eSF, nESB[j] ~ eSB,
    nACS[j] ~ ACS, nEMU[j] ~ eMulti, popAPS[j] ~ pop_adscrita;

end;
