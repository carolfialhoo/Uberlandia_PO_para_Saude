# -*- coding: utf-8 -*-
"""Cobertura geografica e acessibilidade espacial nos tres niveis (rede atual e cenarios do Caderno).

Medidas de Guagliardo (2004), conforme a Aula 8 de EPD899:
  - populacao dentro do limite de acesso do exercicio e a ate 10/15 min;
  - distancia e tempo ate a unidade mais proxima (media ponderada pela populacao);
  - indice G2SFCA (Luo e Wang, 2003; Dai, 2010): no nivel 1, 3.000 x eSF acessiveis por pessoa (t0 = 25 min);
    nos niveis 2 e 3, capacidade anual ao alcance / necessidade do Caderno 1 (1,0 = oferta igual a necessidade),
    com t0 = limite do exercicio (60 e 120 min) e, como sensibilidade, captacao local de 15 min.
Tempo setor -> nivel 2/3: distancia em linha reta calibrada nas rotas OSRM entre unidades (aba d12_d23).

Uso (a partir da pasta do projeto):  python codigo/medidas_acesso_niveis.py
Saidas: resultados/analise/acesso_niveis.csv, acesso_niveis_captacao15.csv e relatorio/fig/fig_tempo_nivel2.png
"""
import json, numpy as np, pandas as pd, openpyxl
from pathlib import Path
P = Path(__file__).resolve().parents[1]; X = P/'dados/base_uberlandia.xlsx'
RES = P/'resultados/gurobi_2026-11-03'
def aba(n):
    rows = list(openpyxl.load_workbook(X, read_only=True)[n].iter_rows(values_only=True))
    return pd.DataFrame(rows[1:], columns=rows[0])
st = aba('Setores').dropna(subset=['id_modelo']); st['populacao'] = st.populacao.astype(float)
j1 = aba('APS_J1'); j2 = aba('Secundaria_J2'); j3 = aba('Terciaria_J3'); dd = aba('d12_d23')
PI = 0.6216
pop = st.populacao.values; popsus = PI*pop
def hav(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    a = np.sin((lat2-lat1)/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 6371*2*np.arcsin(np.sqrt(a))
# --- calibracao do tempo de carro (OSRM) sobre os pares UBS->nivel 2 e nivel 2->hospital
xy = {r.id: (r.lon, r.lat) for r in pd.concat([j1[['id','lon','lat']], j2[['id','lon','lat']], j3[['id','lon','lat']]]).itertuples()}
dd = dd[dd.origem.isin(xy) & dd.destino.isin(xy)].copy()
dd['h'] = [hav(*xy[o], *xy[d]) for o, d in zip(dd.origem, dd.destino)]
dd = dd[dd.h > 0.2]
k_km = np.sum(dd.km*dd.h)/np.sum(dd.h**2)                       # km_osrm = k*hav
A = np.vstack([np.ones(len(dd)), dd.km]).T; a_min, b_min = np.linalg.lstsq(A, dd['min'], rcond=None)[0]
pred = a_min + b_min*k_km*dd.h; mape = np.mean(np.abs(pred-dd['min'])/dd['min'])
r2 = 1-np.sum((pred-dd['min'])**2)/np.sum((dd['min']-dd['min'].mean())**2)
CAL = dict(pares=len(dd), fator_km=k_km, min_fixo=a_min, min_por_km=b_min, erro_medio_pct=100*mape, r2=r2)
def carro(lon, lat):
    h = hav(st.lon.values[:, None], st.lat.values[:, None], np.array(lon)[None, :], np.array(lat)[None, :])
    km = k_km*h; return km, a_min + b_min*km
def gauss(t, t0):
    w = (np.exp(-0.5*(t/t0)**2)-np.exp(-0.5))/(1-np.exp(-0.5)); return np.where(t <= t0, w, 0.0)
def g2sfca(S, t, P, t0):
    W = gauss(t, t0); R = S/np.maximum((P[:, None]*W).sum(0), 1e-9); return (W*R).sum(1)
def q(x, w, p): o = np.argsort(x); c = np.cumsum(w[o])/w.sum(); return x[o][np.searchsorted(c, p)]
# --- oferta por unidade
CAP2 = {'MED_ESP': ('CONS', 1559/0.1933, 0.645), 'EQ_US': ('US', 3024, 0.150), 'EQ_TC': ('TC', 3347, 0.03347), 'EQ_RM': ('RM', 5000, 0.030)}
GER = ['LEITO_CLIN','LEITO_CIR','LEITO_OBST','LEITO_PED']; INT = ['LEITO_UCI_N','LEITO_UTI_A','LEITO_UTI_P','LEITO_UTI_N']
NEC = {'ger': 368+207+45+68, 'int': 18+58+7+8}   # leitos necessarios (Caderno, 2026)
def rede(cen):
    if cen == 'atual':
        u1 = j1[j1.existente == 1].copy(); u1['S'] = u1.ESF_atual.astype(float)
        u2 = j2[j2.existente == 1].copy(); u3 = j3[j3.existente == 1].copy()
        for r in CAP2: u2[r] = u2['atual_'+r].astype(float)
        for r in GER+INT: u3[r] = u3['atual_'+r].astype(float)
        return u1, u2, u3
    s = json.load(open(RES/cen/'solucao.json'))
    u1 = j1.copy(); u1['S'] = [s.get(f'nESF[{i}]', 0) if s.get(f'a1[{i}]', 0) > .5 else 0 for i in u1.id]; u1 = u1[u1.S > 0]
    u2 = j2[[s.get(f'a2[{i}]', 0) > .5 for i in j2.id]].copy()
    for r in CAP2: u2[r] = [s.get(f'n2[{i},{r}]', 0) for i in u2.id]
    u3 = j3[[s.get(f'a3[{i}]', 0) > .5 for i in j3.id]].copy()
    for r in GER+INT: u3[r] = [s.get(f'n3[{i},{r}]', 0) for i in u3.id]
    return u1, u2, u3
# tempo setor->UBS (matriz OSRM do projeto)
d01 = aba('d01_km').set_index('setor').loc[st.id_modelo]; t01 = aba('t01_min').set_index('setor').loc[st.id_modelo]
out = []; porsetor = {}
for cen, rot in [('atual','Rede atual'), ('agregado_caderno_modo1','Custo mínimo'), ('agregado_caderno_modo2_folga05','Folga de 5%'), ('agregado_caderno_modo2_folga10','Folga de 10%')]:
    u1, u2, u3 = rede(cen); o = dict(cenario=rot, n_ubs=len(u1), n_n2=len(u2), n_n3=len(u3))
    D1 = d01[u1.id].values.astype(float); T1 = t01[u1.id].values.astype(float)
    ok1 = ((D1 <= 5) | (T1 <= 25)).any(1)
    o['n1_dentro_limite'] = pop[ok1].sum()/pop.sum(); o['n1_t_med'] = np.average(T1.min(1), weights=pop)
    o['n1_km_med'] = np.average(D1.min(1), weights=pop)
    o['n1_ate15'] = pop[T1.min(1) <= 15].sum()/pop.sum()
    a1 = 3000*g2sfca(u1.S.values, T1, pop, 25); o['n1_g2_med'] = np.average(a1, weights=pop); o['n1_g2_ge1'] = pop[a1 >= 1].sum()/pop.sum()
    for niv, u, lim_km, lim_t in [('n2', u2, 30, 60), ('n3', u3, 60, 120)]:
        K, T = carro(u.lon.astype(float).values, u.lat.astype(float).values)
        o[f'{niv}_dentro_limite'] = pop[((K <= lim_km) | (T <= lim_t)).any(1)].sum()/pop.sum()
        tm = T.min(1); km = K.min(1)
        o[f'{niv}_km_med'] = np.average(km, weights=pop); o[f'{niv}_t_med'] = np.average(tm, weights=pop)
        o[f'{niv}_t_p95'] = q(tm, pop, .95); o[f'{niv}_t_max'] = tm.max()
        o[f'{niv}_ate10'] = pop[tm <= 10].sum()/pop.sum(); o[f'{niv}_ate15'] = pop[tm <= 15].sum()/pop.sum()
        o[f'{niv}_ate20'] = pop[tm <= 20].sum()/pop.sum()
        if niv == 'n2':
            for r, (nome, cap, taxa) in CAP2.items():
                S = u[r].values.astype(float)*cap
                a = g2sfca(S, T, popsus, lim_t)/taxa       # 1,0 = oferta ao alcance igual a necessidade
                o[f'g2_{nome}_med'] = np.average(a, weights=pop); o[f'g2_{nome}_min'] = a.min(); o[f'g2_{nome}_max'] = a.max()
                o[f'g2_{nome}_ge1'] = pop[a >= 1].sum()/pop.sum()
                porsetor[(cen, nome)] = a
        else:
            for grp, cols in [('ger', GER), ('int', INT)]:
                S = u[cols].values.astype(float).sum(1)
                a = g2sfca(S, T, popsus, lim_t)/(NEC[grp]/popsus.sum())
                o[f'g2_{grp}_med'] = np.average(a, weights=pop); o[f'g2_{grp}_min'] = a.min(); o[f'g2_{grp}_max'] = a.max()
                o[f'g2_{grp}_ge1'] = pop[a >= 1].sum()/pop.sum()
        porsetor[(cen, niv+'_t')] = tm
    out.append(o)
df = pd.DataFrame(out); pd.set_option('display.width', 250); pd.set_option('display.max_columns', 80)
print(CAL); print(df.T.to_string())
SAI = P/'resultados/analise'; SAI.mkdir(parents=True, exist_ok=True)
df.to_csv(SAI/'acesso_niveis.csv', index=False)
pd.DataFrame([CAL]).to_csv(SAI/'calibracao_tempo_carro.csv', index=False)

# --- sensibilidade: captacao local (t0 = 15 min de carro) nos niveis 2 e 3
sens = []
for cen, rot in [('atual','Rede atual'), ('agregado_caderno_modo1','Custo mínimo'), ('agregado_caderno_modo2_folga05','Folga de 5%'), ('agregado_caderno_modo2_folga10','Folga de 10%')]:
    u1, u2, u3 = rede(cen); o = dict(cenario=rot)
    K, T = carro(u2.lon.astype(float).values, u2.lat.astype(float).values)
    for r, (nome, cap, taxa) in CAP2.items():
        a = g2sfca(u2[r].values.astype(float)*cap, T, popsus, 15)/taxa
        o[f'{nome}_p10'] = q(a, pop, .10); o[f'{nome}_p50'] = q(a, pop, .5); o[f'{nome}_p90'] = q(a, pop, .9)
        o[f'{nome}_lt05'] = pop[a < .5].sum()/pop.sum(); o[f'{nome}_ge1'] = pop[a >= 1].sum()/pop.sum()
    K, T = carro(u3.lon.astype(float).values, u3.lat.astype(float).values)
    for grp, cols in [('ger', GER), ('int', INT)]:
        a = g2sfca(u3[cols].values.astype(float).sum(1), T, popsus, 15)/(NEC[grp]/popsus.sum())
        o[f'{grp}_p10'] = q(a, pop, .10); o[f'{grp}_p50'] = q(a, pop, .5); o[f'{grp}_p90'] = q(a, pop, .9)
        o[f'{grp}_lt05'] = pop[a < .5].sum()/pop.sum(); o[f'{grp}_ge1'] = pop[a >= 1].sum()/pop.sum()
    sens.append(o)
sd = pd.DataFrame(sens); print(sd.T.to_string()); sd.to_csv(SAI/'acesso_niveis_captacao15.csv', index=False)


# --- mapa (Figura 8 do artigo): tempo de carro ate o nivel 2 mais proximo
import sqlite3, struct, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt; plt.rcParams['font.family'] = 'serif'
from matplotlib.collections import PolyCollection
from matplotlib.colors import BoundaryNorm, ListedColormap

c = sqlite3.connect(str(P/'dados/_cache/udi_setores.gpkg'))
def wkb_polys(b):
    flags = b[3]; env = {0:0,1:32,2:48,3:48,4:64}[(flags >> 1) & 7]; o = 8+env; out = []
    def rd(o):
        bo = '<' if b[o] == 1 else '>'; t = struct.unpack(bo+'I', b[o+1:o+5])[0] % 1000; o += 5
        if t == 3:
            n = struct.unpack(bo+'I', b[o:o+4])[0]; o += 4; rings = []
            for _ in range(n):
                m = struct.unpack(bo+'I', b[o:o+4])[0]; o += 4
                rings.append(np.frombuffer(b[o:o+16*m], dtype=bo+'f8').reshape(m, 2)); o += 16*m
            out.append(rings[0]); return o
        if t == 6:
            n = struct.unpack(bo+'I', b[o:o+4])[0]; o += 4
            for _ in range(n): o = rd(o)
            return o
        raise ValueError(t)
    rd(o); return out
geo = {}
for cd, g in c.execute("select CD_SETOR, geom from udi_setores"):
    geo[str(cd)] = wkb_polys(g)
st = st.reset_index(drop=True); ps = porsetor; st['cd'] = st.CD_SETOR.astype(str)
sede = (st.situacao == 'Urbana') & (st.distrito == 'Uberlândia')
bins = [0, 5, 10, 15, 20, 1e9]; cmap = ListedColormap(['#ffffff', '#cfcfcf', '#9a9a9a', '#5a5a5a', '#1a1a1a']); norm = BoundaryNorm(bins, cmap.N)
fig, axs = plt.subplots(1, 2, figsize=(10, 5.2))
U2 = j2
import json
s5 = json.load(open(RES/'agregado_caderno_modo2_folga05'/'solucao.json'))
for ax, (cen, tit, ids) in zip(axs, [('atual', '(A) Rede atual', U2[U2.existente == 1].id), ('agregado_caderno_modo2_folga05', '(B) Folga de 5%', [i for i in U2.id if s5.get(f'a2[{i}]', 0) > .5])]):
    t = ps[(cen, 'n2_t')]; polys = []; vals = []
    for i in np.where(sede)[0]:
        for pg in geo.get(st.cd[i], []): polys.append(pg); vals.append(t[i])
    pc = PolyCollection(polys, array=np.array(vals), cmap=cmap, norm=norm, edgecolors='#808080', linewidths=0.08)
    ax.add_collection(pc); ax.autoscale_view(); ax.set_aspect(1/np.cos(np.radians(18.9)))
    u = U2[U2.id.isin(ids)]
    ax.scatter(u.lon, u.lat, marker='s', s=34, facecolor='white', edgecolor='black', linewidth=1.2, zorder=3)
    ax.set_title(tit, fontsize=10, loc='left'); ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values(): sp.set_visible(False)
from matplotlib.patches import Patch
h = [Patch(facecolor=cmap(k), edgecolor='#808080', label=l) for k, l in enumerate(['até 5 min', '5 a 10 min', '10 a 15 min', '15 a 20 min', 'mais de 20 min'])]
h.append(plt.Line2D([], [], marker='s', ls='', markerfacecolor='white', markeredgecolor='black', label='unidade de nível 2'))
fig.legend(handles=h, loc='lower center', ncol=6, fontsize=8, frameon=False)
plt.tight_layout(rect=[0, 0.06, 1, 1]); plt.savefig(P/'relatorio/fig/fig_tempo_nivel2.png', dpi=200)
print('ok', len(geo))
