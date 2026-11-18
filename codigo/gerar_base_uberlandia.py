# -*- coding: utf-8 -*-
"""
Gera a base de dados de Uberlandia (MG) para o modelo_rede_saude_v02.mod.

Etapas
  1. Coleta (com cache): IBGE (setores 2022 com populacao, idade, nascidos vivos),
     CNES (estabelecimentos, equipes, profissionais, leitos, equipamentos),
     ANS (beneficiarios de planos) e geocodificacao por CEP.
  2. Geografia: pontos de demanda (setores), unidades existentes com coordenadas
     corrigidas, candidatos, e matrizes de distancia/tempo pelo OSRM
     (perfil a pe para casa->UBS e carro para UBS->secundaria->terciaria).
  3. Parametros (ver parametros_uberlandia.py) e escrita do .dat e do .xlsx.

Uso:  python codigo/gerar_base_uberlandia.py     (grava os .dat e o .xlsx em dados/; cache em dados/_cache)
      EPD_CACHE=<pasta> python codigo/gerar_base_uberlandia.py
"""
import json, os, re, time, hashlib, math
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import requests
from shapely.geometry import Point
from sklearn.cluster import KMeans

AQUI = Path(__file__).resolve().parent          # codigo/
DADOS = AQUI.parent / "dados"
CACHE = Path(os.environ.get("EPD_CACHE", DADOS / "_cache"))
(CACHE / "cnes").mkdir(parents=True, exist_ok=True)
(CACHE / "osrm").mkdir(parents=True, exist_ok=True)

COD_MUN7, COD_MUN6 = "3170206", 317020
CRS_M = 31982                      # SIRGAS 2000 / UTM 22S (metros)
CENTROIDE_MUN = (-48.27722, -18.91861)   # ponto padrao que o CNES/BrasilAPI usam quando nao ha coordenada
CEP_GENERICOS = [(-48.275380, -18.914608), (-48.271231, -18.917454)]
OSRM_FOOT = "https://routing.openstreetmap.de/routed-foot/table/v1/driving/"
OSRM_CAR = "https://router.project-osrm.org/table/v1/driving/"
H_CNES = {"Referer": "https://cnes.datasus.gov.br/", "Accept": "application/json"}


# ============================================================================
# 1. COLETA
# ============================================================================

def baixar(url, destino, timeout=1800):
    destino = Path(destino)
    if not destino.exists():
        print("  baixando", url)
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for bloco in r.iter_content(1 << 20):
                    f.write(bloco)
    return destino


def ibge_setores():
    """Malha de setores 2022 com atributos (v0001 = pessoas)."""
    fn = CACHE / "udi_setores.gpkg"
    if not fn.exists():
        mg = baixar("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/"
                    "malha_com_atributos/setores/gpkg/UF/MG/MG_setores_CD2022.gpkg", CACHE / "MG_setores_CD2022.gpkg")
        g = gpd.read_file(mg, where=f"CD_MUN = '{COD_MUN7}'")
        g.to_file(fn, driver="GPKG")
    return gpd.read_file(fn)


def sidra_idade():
    fn = CACHE / "udi_idade.json"
    if fn.exists():
        return json.load(open(fn))
    js = requests.get(f"https://apisidra.ibge.gov.br/values/t/9514/n6/{COD_MUN7}/v/93/p/2022/c2/all/c287/all/c286/113635",
                      timeout=120).json()
    ages = {}
    for x in js[1:]:
        ages.setdefault(x["D5N"], {})[x["D4N"]] = int(x["V"]) if x["V"].isdigit() else 0
    sing = {int(m.group(1)): v for k, v in ages.items() if (m := re.match(r"^(\d+) anos?$", k))}
    p = lambda a, b, s="Total": sum(sing.get(i, {}).get(s, 0) for i in range(a, b + 1))
    lt1 = ages["Menos de 1 ano"]["Total"]
    r = {"total": ages["Total"]["Total"], "<1": lt1, "0-14": lt1 + p(1, 14), "15-59": p(15, 59),
         "60+": ages["Total"]["Total"] - lt1 - p(1, 59), "F15-49": p(15, 49, "Mulheres")}
    json.dump(r, open(fn, "w"))
    return r


def sidra_nascidos_vivos():
    """Nascidos vivos de maes residentes (Estatisticas do Registro Civil, tabela 2612)."""
    fn = CACHE / "udi_nv.json"
    if fn.exists():
        return json.load(open(fn))
    js = requests.get(f"https://apisidra.ibge.gov.br/values/t/2612/n6/{COD_MUN7}/p/last%203/v/all", timeout=120).json()
    nv = {x["D2N"]: int(x["V"]) for x in js[1:] if x["MN"] == "Pessoas" and x["V"].isdigit()}
    json.dump(nv, open(fn, "w"))
    return nv


def ans_cobertura(idade):
    """Beneficiarios de planos de assistencia medica (ANS, PDA 047) / populacao do Censo 2022."""
    fn = CACHE / "ans_udi.json"
    if fn.exists():
        return json.load(open(fn))
    csv = baixar("https://dadosabertos.ans.gov.br/FTP/PDA/taxa_de_cobertura_de_planos_de_saude-047/pda-047-taxa_cobertura.csv",
                 CACHE / "ans_cobertura.csv")
    a = pd.read_csv(csv, sep=";", encoding="latin-1", dtype=str)
    u = a[a.CD_MUNICIPIO == str(COD_MUN6)].copy()
    u["B"] = u.BENEF_ASSISTENCIA_MEDICA.astype(int)
    per = u.PERIODO.max()
    g = u[u.PERIODO == per].groupby("FAIXA_ETARIA").B.sum().to_dict()
    b014 = sum(v for k, v in g.items() if k.startswith(("At", "1 a 4", "5 a 9", "10 a 14")))
    b60 = sum(v for k, v in g.items() if k.startswith(("60", "70", "80")))
    tot = sum(g.values())
    r = {"periodo": per, "benef": int(tot), "cob_total": tot / idade["total"], "cob_0_14": b014 / idade["0-14"],
         "cob_15_59": (tot - b014 - b60) / idade["15-59"], "cob_60": b60 / idade["60+"]}
    json.dump(r, open(fn, "w"))
    return r


def cnes_lista():
    """Estabelecimentos do municipio (API de dados abertos), por tipo de unidade."""
    fn = CACHE / "cnes_udi.json"
    if fn.exists():
        return pd.DataFrame(json.load(open(fn, encoding="utf-8"))).drop_duplicates("codigo_cnes")
    rows = []
    for t in [1, 2, 4, 5, 7, 15, 20, 21, 36, 39, 62, 70, 73]:
        off = 0
        while True:
            d = requests.get("https://apidadosabertos.saude.gov.br/cnes/estabelecimentos",
                             params=dict(codigo_municipio=COD_MUN6, codigo_tipo_unidade=t, limit=20, offset=off),
                             timeout=60).json().get("estabelecimentos", [])
            rows += d
            if len(d) < 20:
                break
            off += 20
    json.dump(rows, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    return pd.DataFrame(rows).drop_duplicates("codigo_cnes")


def cnes(ep, cod):
    """Servicos do CNES (cnes.datasus.gov.br/services/...), com cache por arquivo."""
    fn = CACHE / "cnes" / f"{ep.replace('/', '_')}_{cod}.json"
    if fn.exists():
        return json.load(open(fn, encoding="utf-8"))
    js = None
    for _ in range(3):
        try:
            r = requests.get(f"https://cnes.datasus.gov.br/services/{ep}/{COD_MUN6}{int(cod):07d}", headers=H_CNES, timeout=90)
            js = r.json() if r.status_code == 200 and r.text.strip() else None
            break
        except Exception:
            time.sleep(3)
    json.dump(js, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    return js


def membros_equipe(cod, e):
    """Membros de uma equipe (carga horaria por profissional), servico da ficha do CNES."""
    (CACHE / "cnes_eq").mkdir(exist_ok=True)
    fn = CACHE / "cnes_eq" / f"{cod}_{e['coEquipe']}.json"
    if not fn.exists():
        url = (f"https://cnes.datasus.gov.br/services/estabelecimentos-equipes/profissionais/{COD_MUN6}{int(cod):07d}"
               f"?coMun={COD_MUN6}&coArea={e['coArea']}&coEquipe={e['coEquipe']}")
        r = requests.get(url, headers=H_CNES, timeout=60)
        json.dump({"equipe": e, "cnes": cod, "membros": r.json() if r.status_code == 200 and r.text.strip() else None},
                  open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    return [p for p in (json.load(open(fn, encoding="utf-8"))["membros"] or []) if not p.get("dtDesligamento")]


def geocodifica_cep(ceps):
    fn = CACHE / "cep_cache.json"
    cache = json.load(open(fn, encoding="utf-8")) if fn.exists() else {}
    for c in ceps:
        if c and c not in cache:
            try:
                cache[c] = requests.get(f"https://cep.awesomeapi.com.br/json/{c}", timeout=30).json()
            except Exception:
                cache[c] = {}
            time.sleep(0.3)
    json.dump(cache, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    return cache


# ============================================================================
# 2. GEOGRAFIA
# ============================================================================

def pontos_setores(g):
    g = g[g.v0001.fillna(0).astype(float) > 0].copy()
    g["pop"] = g.v0001.astype(float).round().astype(int)
    gm = g.to_crs(CRS_M)
    rp = gm.geometry.representative_point()
    pts = gpd.GeoSeries(rp, crs=CRS_M).to_crs(4326)
    g["lon"], g["lat"] = pts.x.values, pts.y.values
    g["x"], g["y"] = rp.x.values, rp.y.values
    g["id"] = "S" + g.CD_SETOR.astype(str)
    return g[["id", "CD_SETOR", "pop", "SITUACAO", "CD_SIT", "NM_DIST", "NM_BAIRRO", "AREA_KM2", "lon", "lat", "x", "y"]].reset_index(drop=True)


def sem_acento(s):
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch)).upper()


def _xy(lon, lat):
    p = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(CRS_M).iloc[0]
    return p.x, p.y


def _dist_m(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def centroides_distritos(st):
    """Centro (ponderado pela populacao) da area urbana de cada distrito."""
    out = {}
    for d, s in st[st.SITUACAO == "Urbana"].groupby("NM_DIST"):
        w = s["pop"]
        x, y = (s.x * w).sum() / w.sum(), (s.y * w).sum() / w.sum()
        p = gpd.GeoSeries([Point(x, y)], crs=CRS_M).to_crs(4326).iloc[0]
        out[d] = (p.x, p.y)
    return out


def corrige_coordenadas(u, mun_poly, distritos):
    """Regra: usa CNES; se o ponto e o centroide padrao, esta fora do municipio ou falta,
    usa o CEP (AwesomeAPI); se o CEP tambem e generico, usa o centro do distrito/bairro."""
    cache = geocodifica_cep(u.cep.dropna().unique())
    cen = _xy(*CENTROIDE_MUN)
    gen = [_xy(*p) for p in CEP_GENERICOS] + [cen]
    lon_f, lat_f, fonte = [], [], []
    for _, r in u.iterrows():
        ok_cnes = False
        if not (pd.isna(r.lat) or pd.isna(r.lon)):
            pc = _xy(r.lon, r.lat)
            ok_cnes = _dist_m(pc, cen) > 400 and mun_poly.contains(Point(pc))
        dist = next((d for d in distritos if not d.startswith("Uberl") and sem_acento(d) in sem_acento(r.nome)),
                    None) if isinstance(r.nome, str) else None
        if dist:                                   # UBS de distrito: confere com a vila
            vx = _xy(*distritos[dist])
            if ok_cnes and _dist_m(_xy(r.lon, r.lat), vx) < 3000:
                lon_f.append(r.lon); lat_f.append(r.lat); fonte.append("CNES")
            else:
                lon_f.append(distritos[dist][0]); lat_f.append(distritos[dist][1]); fonte.append(f"IBGE: centro da vila de {dist}")
            continue
        if ok_cnes:
            lon_f.append(r.lon); lat_f.append(r.lat); fonte.append("CNES")
            continue
        c = cache.get(r.cep or "", {})
        if c.get("lat"):
            pe = _xy(float(c["lng"]), float(c["lat"]))
            if min(_dist_m(pe, q) for q in gen) > 600 and mun_poly.contains(Point(pe)):
                lon_f.append(float(c["lng"])); lat_f.append(float(c["lat"])); fonte.append("CEP (AwesomeAPI)")
                continue
        lon_f.append(np.nan); lat_f.append(np.nan); fonte.append("sem coordenada")
    u = u.copy()
    u["lon_f"], u["lat_f"], u["coord_fonte"] = lon_f, lat_f, fonte
    return u


def bairro_fallback(u, st):
    """Para unidades ainda sem coordenada: centro do bairro IBGE citado no endereco/nome."""
    for i, r in u[u.lon_f.isna()].iterrows():
        alvo = f"{r.nome} {r.get('end', '')}".upper()
        cand = st.groupby("NM_BAIRRO")
        melhor = None
        for b, s in cand:
            if isinstance(b, str) and len(b) > 3 and b.upper() in alvo:
                if melhor is None or len(b) > len(melhor[0]):
                    melhor = (b, s)
        if melhor:
            s = melhor[1]; w = s["pop"]
            x, y = (s.x * w).sum() / w.sum(), (s.y * w).sum() / w.sum()
            p = gpd.GeoSeries([Point(x, y)], crs=CRS_M).to_crs(4326).iloc[0]
            u.loc[i, ["lon_f", "lat_f", "coord_fonte"]] = [p.x, p.y, f"IBGE: centro do bairro {melhor[0]}"]
    return u


def osrm_tabela(base, src, dst, ns=100, nd=50):
    """Distancias (km) e tempos (min) entre listas de (lon, lat). Requisicoes em blocos, com cache."""
    D = np.full((len(src), len(dst)), np.nan)
    T = np.full((len(src), len(dst)), np.nan)
    for i0 in range(0, len(src), ns):
        for j0 in range(0, len(dst), nd):
            S, Dd = src[i0:i0 + ns], dst[j0:j0 + nd]
            coords = ";".join(f"{x:.6f},{y:.6f}" for x, y in list(S) + list(Dd))
            key = hashlib.md5((base + coords).encode()).hexdigest()
            fn = CACHE / "osrm" / f"{key}.json"
            if fn.exists():
                js = json.load(open(fn))
            else:
                for k in range(5):
                    try:
                        r = requests.get(base + coords, timeout=300, params={
                            "annotations": "duration,distance",
                            "sources": ";".join(map(str, range(len(S)))),
                            "destinations": ";".join(map(str, range(len(S), len(S) + len(Dd))))})
                        js = r.json()
                        if js.get("code") == "Ok":
                            break
                    except Exception:
                        pass
                    time.sleep(5 * (k + 1))
                json.dump(js, open(fn, "w"))
                time.sleep(1.0)
            dist = np.array(js["distances"], dtype=float) / 1000.0
            dur = np.array(js["durations"], dtype=float) / 60.0
            D[i0:i0 + len(S), j0:j0 + len(Dd)] = dist
            T[i0:i0 + len(S), j0:j0 + len(Dd)] = dur
    return D, T


def haversine_km(a, b):
    lon1, lat1 = np.radians(a[:, 0])[:, None], np.radians(a[:, 1])[:, None]
    lon2, lat2 = np.radians(b[:, 0])[None, :], np.radians(b[:, 1])[None, :]
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(h))


def preenche_falhas(D, T, src, dst, vel_kmh, fator=1.3):
    """Pares que o OSRM nao roteou: distancia em linha reta x fator de circuito."""
    hv = haversine_km(np.array(src), np.array(dst)) * fator
    m = np.isnan(D) | np.isnan(T)
    D[m] = hv[m]
    T[m] = 60 * hv[m] / vel_kmh
    return D, T, int(m.sum())


# ============================================================================
# 2b. UNIDADES POR NIVEL
# ============================================================================

CBO_APS_MED = {"225142", "225130", "225170"}         # medicos de familia/ESF/generalista (nao contam como especialista)

# Atencao secundaria existente: ambulatorios publicos multiespecialidade medica (CNES).
# O Centro de Especialidades Marta Evangelista (31577) fica de fora: e odontologico (sem medicos).
SEC_EXIST = {4684281: "CEM Centro de Especialidades Medicas",
             2146339: "Ambulatorio Amelio Marques (HC-UFU)",
             6102174: "AMVAP Saude (consorcio intermunicipal)"}
# Candidatos a policlinica regional: terrenos publicos das 8 UAIs
UAI = {3170527: "Martins", 2152959: "Roosevelt", 2152967: "Tibery", 3032191: "Morumbi",
       2152940: "Pampulha", 5617286: "Sao Jorge", 2153009: "Planalto", 2153017: "Luizote"}
# Hospitais com leitos SUS de internacao aguda (CNES). True = pode ampliar; False = n3_max = n3_atual
HOSP_EXIST = {2146355: ("Hospital de Clinicas UFU", True), 6601804: ("Hospital e Maternidade Municipal", True),
              2151855: ("Hospital Santa Catarina (anexo HMM)", True), 473502: ("Centro de Internacao Pediatrica", False),
              2151839: ("Hospital do Triangulo (contratado)", False)}
HOSP_CAND = {"LESTE": 3032191, "OESTE": 2153009}     # candidatos a hospital: terrenos das UAIs Morumbi e Planalto
# Projetos ja aprovados pela Prefeitura (Novo PAC / Avanca Uberlandia) que criam local novo
CAND_PROJETOS = [
    dict(id="CAND_AAE_POLICLINICA_JARAGUA", nivel="POLI", lon_f=-48.3017878, lat_f=-18.9241722,
         nome="Policlinica de Uberlandia - Jaragua (Novo PAC, ordem de servico 26/08/2026)",
         coord_fonte="OpenStreetMap (Photon): bairro Jaragua (terreno da Diretoria de Operacoes e Manutencao)"),
    dict(id="CAND_UBS_FRUTA_DO_CONDE", nivel="APS", lon_f=-48.3484435, lat_f=-18.9345118,
         nome="UBS Tipo I Fruta do Conde/Mansour (projeto aprovado, SES-MG/Prefeitura 2026)",
         coord_fonte="OpenStreetMap (Photon): localidade Fruta do Conde"),
]


def tabela_aps(lst):
    rows = []
    for _, r in lst.iterrows():
        c = r.codigo_cnes
        if str(r.descricao_natureza_juridica_estabelecimento)[:1] != "1":
            continue
        eqs = [e for e in (cnes("estabelecimentos-equipes", c) or []) if not e.get("dtDesativacao")]
        n = lambda t: sum(1 for e in eqs if e["tpEquipe"] == t)
        if n("70") + n("76") == 0:
            continue
        det = cnes("estabelecimentos", c) or {}
        prof = cnes("estabelecimentos-profissionais", c) or []
        # eSF-equivalente de cada eAP pela carga horaria do medico da equipe
        is_med = lambda p: p["cbo"][:4] in ("2251", "2252", "2253")
        eap_eq = sum(P.eap_equiv(sum(p["chAmb"] for p in membros_equipe(c, e) if is_med(p)))
                     for e in eqs if e["tpEquipe"] == "76")
        rows.append(dict(cnes=c, nivel="APS", nome=r.nome_fantasia, eSF=n("70"), eAP=n("76"), eAP_eq=eap_eq, eSB=n("71"),
                         eMulti=n("72"), ACS=sum(1 for p in prof if p["cbo"] == "515105"),
                         lat=float(det.get("nuLatitude") or np.nan), lon=float(det.get("nuLongitude") or np.nan),
                         cep=det.get("cep"), end=f'{det.get("noLogradouro")} {det.get("nuEndereco")}, {det.get("bairro")}'))
    return pd.DataFrame(rows)


def fte(prof, filtro, campo, horas=40.0):
    return sum(p[campo] for p in prof if filtro(p)) / horas


def tabela_outros():
    rows = []
    for c, nm in SEC_EXIST.items():
        rows.append(dict(cnes=c, nivel="SEC", nome=nm))
    for c, nm in UAI.items():
        rows.append(dict(cnes=c, nivel="UAI", nome=f"UAI {nm}"))
    for c, (nm, _) in HOSP_EXIST.items():
        rows.append(dict(cnes=c, nivel="HOSP", nome=nm))
    o = pd.DataFrame(rows)
    for i, r in o.iterrows():
        det = cnes("estabelecimentos", r.cnes) or {}
        o.loc[i, "lat"] = float(det.get("nuLatitude") or np.nan)
        o.loc[i, "lon"] = float(det.get("nuLongitude") or np.nan)
        o.loc[i, "cep"] = det.get("cep")
        o.loc[i, "end"] = f'{det.get("noLogradouro")} {det.get("nuEndereco")}, {det.get("bairro")}'
    return o


def recursos_existentes():
    """Quadro atual nos niveis 2 e 3 (CNES): FTE de 40 h, leitos SUS e equipamentos."""
    is_med = lambda p: p["cbo"][:4] in ("2251", "2252", "2253")
    # Capacidade existente = producao SUS (SIA, 12 meses) x parcela de residentes, convertida em recursos
    # pelas mesmas produtividades do modelo (consumo2 / carga2). A carga horaria do CNES fica so como referencia.
    sec = {c: {r: 0.0 for r in P.R2} for c in SEC_EXIST}
    for prest, prod in P.SIA.items():
        f = P.FRAC_RES_SIA[prest]
        qtd = dict(zip(P.S2, [v * f for v in prod]))
        for r in P.R2:
            uso = sum(P.CONSUMO2.get((s, r), 0) * qtd[s] for s in P.S2)
            sec[P.SIA_DESTINO[prest]][r] += uso / P.CARGA2[r]
    sec_cnes = {}
    for c in SEC_EXIST:
        prof = cnes("estabelecimentos-profissionais", c) or []
        if c == 2146339:   # ambulatorio da UFU: carga ambulatorial esta cadastrada no HC-UFU
            prof = prof + [dict(p, chAmb=p["chAmb"] * P.FRAC_HCUFU) for p in (cnes("estabelecimentos-profissionais", 2146355) or [])]
        sec_cnes[c] = fte(prof, lambda p: is_med(p) and p["cbo"] not in CBO_APS_MED, "chAmb")
    # hospitais: leitos SUS por tipo e FTE hospitalar
    mapa, hosp = [], {}
    for c in HOSP_EXIST:
        lt = cnes("estabelecimentos-hospitalar", c) or []
        prof = cnes("estabelecimentos-profissionais", c) or []
        d = dict(MEDICO=fte(prof, is_med, "chHosp"), ENFERMEIRO=fte(prof, lambda p: p["cbo"][:4] == "2235", "chHosp"),
                 TEC_ENF=fte(prof, lambda p: p["cbo"][:4] == "3222", "chHosp"))
        for x in lt:
            q, at, ds = int(x["qtSus"]), x["dsAtributo"], x["dsLeito"]
            r = None
            if at.startswith("ESPEC - CIRURG"): r = "LEITO_CIR"
            elif at.startswith("ESPEC - CLIN"): r = "LEITO_CLIN"
            elif at.startswith("OBST"): r = "LEITO_OBST"
            elif at.startswith("PEDI"): r = "LEITO_PED"
            elif at.startswith("COMPLEMENTAR"):
                if "NEONATAL" in ds and "UTI" in ds: r = "LEITO_UTI_N"
                elif "NEONATAL" in ds: r = "LEITO_UCI_N"
                elif "PED" in ds and "UTI" in ds: r = "LEITO_UTI_P"
                elif "PED" in ds: r = "LEITO_PED"
                elif "UTI" in ds or "UCO" in ds: r = "LEITO_UTI_A"
                else: r = "LEITO_CLIN"          # UCI adulto
            mapa.append(dict(cnes=c, hospital=HOSP_EXIST[c][0], atributo=at, leito=ds, qt_sus=q,
                             recurso=r or "(fora do modelo)"))
            if r and q > 0:
                d[r] = d.get(r, 0) + q
        if c == 2146355:                 # HC-UFU: referencia macrorregional
            d = {k: v * P.FRAC_HCUFU for k, v in d.items()}
        hosp[c] = d
    return sec, hosp, pd.DataFrame(mapa), sec_cnes


# ============================================================================
# 2c. CANDIDATOS E AGREGACAO
# ============================================================================

def candidatos_aps(st, exist_xy, k=30, raio_exist_m=700, seed=1):
    """Candidatos a UBS: centros (ponderados pela populacao) de k agrupamentos dos setores
    urbanos da sede, deslocados para o setor mais proximo; descarta os que ficam a menos
    de 700 m de uma UBS existente (a existente pode ser ampliada)."""
    s = st[(st.SITUACAO == "Urbana") & (st.NM_DIST.str.startswith("Uberl"))]
    km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(s[["x", "y"]].values, sample_weight=s["pop"].values)
    out = []
    for cx, cy in km.cluster_centers_:
        i = ((s.x - cx) ** 2 + (s.y - cy) ** 2).idxmin()
        if min(math.hypot(s.x[i] - ex, s.y[i] - ey) for ex, ey in exist_xy) >= raio_exist_m:
            out.append(i)
    return sorted(set(out))


def agrega_setores(st, n_sede=300, seed=1):
    """Agrupa setores em pontos de demanda para rodar no GLPK. Sede urbana: k-means ponderado
    pela populacao; distritos e area rural: cada setor continua sendo um ponto."""
    st = st.copy()
    sede = st.NM_DIST.str.startswith("Uberl") & (st.SITUACAO == "Urbana")
    km = KMeans(n_clusters=n_sede, n_init=10, random_state=seed).fit(st.loc[sede, ["x", "y"]].values,
                                                                     sample_weight=st.loc[sede, "pop"].values)
    st.loc[sede, "grupo"] = [f"G{l + 1:03d}" for l in km.labels_]
    st.loc[~sede, "grupo"] = "R" + st.loc[~sede, "CD_SETOR"].astype(str).str[-8:]
    return st


# ============================================================================
# 2d. MONTAGEM DA GEOGRAFIA
# ============================================================================

DMAX01, TMAX01 = 5.0, 25.0          # determinacao do exercicio (regra "OU")

# Unidades que nem o CNES nem o CEP localizam (endereco "Rodovia 497 km 33, zona rural")
COORD_MANUAL = {7774230: (-48.4241826, -18.9128077, "OpenStreetMap (Photon): localidade Rio das Pedras")}


def montar_geografia(k_cand=30):
    fn = CACHE / "geografia.pkl"
    if fn.exists():
        return pd.read_pickle(fn)
    print("1) setores IBGE")
    g = ibge_setores()
    st = pontos_setores(g)
    mun_poly = g.to_crs(CRS_M).union_all()
    distritos = centroides_distritos(st)

    print("2) unidades CNES")
    lst = cnes_lista()
    aps = tabela_aps(lst)
    u = pd.concat([aps, tabela_outros()], ignore_index=True)
    u = bairro_fallback(corrige_coordenadas(u, mun_poly, distritos), st)
    for c, (lon, lat, fonte) in COORD_MANUAL.items():
        u.loc[(u.cnes == c) & u.lon_f.isna(), ["lon_f", "lat_f", "coord_fonte"]] = [lon, lat, fonte]
    assert u.lon_f.notna().all(), u[u.lon_f.isna()]
    u["id"] = np.select([u.nivel == "APS", u.nivel == "SEC", u.nivel == "UAI", u.nivel == "HOSP"],
                        ["UBS_" + u.cnes.astype(str), "AAE_" + u.cnes.astype(str),
                         "CAND_AAE_" + u.nome.str.replace("UAI ", "").map(sem_acento).str.replace(" ", "_"),
                         "HOSP_" + u.cnes.astype(str)])
    u["existente"] = (u.nivel != "UAI").astype(int)
    for nome, c in HOSP_CAND.items():
        b = u[u.cnes == c].iloc[0]
        u = pd.concat([u, pd.DataFrame([dict(cnes=np.nan, nivel="HOSP", nome=f"Candidato hospital {nome} (terreno da {b.nome})",
                                             id=f"CAND_HOSP_{nome}", existente=0, lon_f=b.lon_f, lat_f=b.lat_f,
                                             coord_fonte=b.coord_fonte)])], ignore_index=True)
    u = pd.concat([u, pd.DataFrame([dict(p, existente=0) for p in CAND_PROJETOS if p["nivel"] == "POLI"])],
                  ignore_index=True)

    print("3) candidatos APS")
    ex = u[u.nivel == "APS"]
    exist_xy = [_xy(a, b) for a, b in zip(ex.lon_f, ex.lat_f)]
    idx = candidatos_aps(st, exist_xy, k=k_cand)
    cand = pd.DataFrame(dict(id=["CAND_UBS_" + st.CD_SETOR[i][-8:] for i in idx], nivel="APS", existente=0,
                             nome=[f"Candidato UBS (setor {st.CD_SETOR[i]}, {st.NM_BAIRRO[i]})" for i in idx],
                             lon_f=st.lon[idx].values, lat_f=st.lat[idx].values, coord_fonte="IBGE: ponto do setor (k-means)"))
    proj = pd.DataFrame([dict(p, existente=0) for p in CAND_PROJETOS if p["nivel"] == "APS"])
    j1 = pd.concat([u[u.nivel == "APS"], proj, cand], ignore_index=True)

    print("4) matriz setor -> APS (a pe nos setores urbanos; carro nos rurais)")
    src = list(zip(st.lon, st.lat))
    st["modo_acesso"] = np.where(st.SITUACAO == "Rural", "carro", "a pe")
    rur = np.where(st.modo_acesso == "carro")[0]
    D01, T01 = osrm_tabela(OSRM_FOOT, src, list(zip(j1.lon_f, j1.lat_f)))
    Dc, Tc = osrm_tabela(OSRM_CAR, [src[k] for k in rur], list(zip(j1.lon_f, j1.lat_f)))
    D01[rur], T01[rur] = Dc, Tc
    xy = st[["x", "y"]].values
    pj2 = list(zip(u[u.nivel.isin(["SEC", "UAI", "POLI"])].lon_f, u[u.nivel.isin(["SEC", "UAI", "POLI"])].lat_f))

    def alcanca_j2(pts):
        """True se o ponto chega a alguma unidade secundaria em 30 km OU 60 min (de carro)."""
        d, t = osrm_tabela(OSRM_CAR, pts, pj2)
        return ((np.nan_to_num(d, nan=1e9) <= 30) | (np.nan_to_num(t, nan=1e9) <= 60)).any(axis=1)

    # cobertura: acrescenta candidatos ate todo setor ter UBS acessivel (5 km OU 25 min) e que,
    # por sua vez, alcance a atencao secundaria; senao o modelo fica inviavel
    while True:
        Dt, Tt = np.nan_to_num(D01, nan=1e9), np.nan_to_num(T01, nan=1e9)
        desc = ~(((Dt <= DMAX01) | (Tt <= TMAX01)).any(axis=1))
        if not desc.any():
            break
        ii = np.where(desc)[0]
        ganho = [(st["pop"].values[ii] * (np.hypot(*(xy[ii] - xy[i]).T) <= 3500)).sum() for i in ii]
        alvo = ii[int(np.argmax(ganho))]
        i, fonte = alvo, "IBGE: ponto do setor (cobertura)"
        if not alcanca_j2([(st.lon[i], st.lat[i])])[0]:
            # procura o ponto de setor vizinho mais proximo que alcance o setor E a secundaria
            viz = np.where(np.hypot(*(xy - xy[alvo]).T) <= 40000)[0]
            dv, tv = osrm_tabela(OSRM_CAR, [src[alvo]], [src[k] for k in viz], ns=1, nd=100)
            acessa = (dv[0] <= DMAX01) | (tv[0] <= TMAX01)
            ok = acessa & alcanca_j2([src[k] for k in viz])
            if not ok.any():
                raise RuntimeError(f"setor {st.CD_SETOR[alvo]} nao tem local viavel com os limites do exercicio")
            i = viz[np.where(ok)[0][np.argmin(tv[0][ok])]]
            fonte = f"IBGE: ponto do setor vizinho {st.CD_SETOR[i]} (cobertura do setor {st.CD_SETOR[alvo]})"
        print(f"   setor sem cobertura: {int(desc.sum())}; novo candidato no setor {st.CD_SETOR[i]}")
        novo = pd.DataFrame([dict(id="CAND_UBS_" + st.CD_SETOR[i][-8:], nivel="APS", existente=0,
                                  nome=f"Candidato UBS (cobertura, setor {st.CD_SETOR[i]}, {st.NM_DIST[i]})",
                                  lon_f=st.lon[i], lat_f=st.lat[i], coord_fonte=fonte)])
        j1 = pd.concat([j1, novo], ignore_index=True)
        # roteia so os setores proximos (10 km a pe; 30 km de carro); os demais ficam inalcancaveis
        dist_reta = np.hypot(*(xy - xy[i]).T)
        d = np.full((len(src), 1), np.nan)
        t = np.full((len(src), 1), np.nan)
        for base, modo, raio in [(OSRM_FOOT, "a pe", 10000), (OSRM_CAR, "carro", 30000)]:
            perto = np.where((dist_reta <= raio) & (st.modo_acesso.values == modo))[0]
            if len(perto):
                dd, tt = osrm_tabela(base, [src[k] for k in perto], [(st.lon[i], st.lat[i])], ns=140, nd=1)
                d[perto], t[perto] = dd, tt
        D01, T01 = np.hstack([D01, d]), np.hstack([T01, t])
    assert j1.id.is_unique, j1.id[j1.id.duplicated()]
    D01, T01, f01 = preenche_falhas(D01, T01, src, list(zip(j1.lon_f, j1.lat_f)), vel_kmh=4.5)

    print("5) matrizes de carro APS -> secundaria -> terciaria")
    j2 = u[u.nivel.isin(["SEC", "UAI", "POLI"])].reset_index(drop=True)
    j3 = u[u.nivel == "HOSP"].reset_index(drop=True)
    p1, p2, p3 = list(zip(j1.lon_f, j1.lat_f)), list(zip(j2.lon_f, j2.lat_f)), list(zip(j3.lon_f, j3.lat_f))
    D12, T12 = osrm_tabela(OSRM_CAR, p1, p2)
    D23, T23 = osrm_tabela(OSRM_CAR, p2, p3)
    D12, T12, f12 = preenche_falhas(D12, T12, p1, p2, vel_kmh=30)
    D23, T23, f23 = preenche_falhas(D23, T23, p2, p3, vel_kmh=30)
    geo = dict(st=st, j1=j1.reset_index(drop=True), j2=j2, j3=j3, D01=D01, T01=T01, D12=D12, T12=T12,
               D23=D23, T23=T23, falhas=dict(f01=f01, f12=f12, f23=f23))
    pd.to_pickle(geo, fn)
    return geo


# ============================================================================
# 3. PARAMETROS E SAIDAS
# ============================================================================

import parametros_uberlandia as P


def montar_dados(geo, agregado=False, n_sede=300, fator_demanda3=None):
    """Monta conjuntos e parametros do .dat. agregado=True junta setores em pontos de demanda
    (distancia e tempo = media ponderada pela populacao dos setores do grupo).
    A populacao do Censo 2022 e levada a estimativa do IBGE de 2026 (P.FATOR_POP, uniforme)."""
    fator_demanda3 = P.FATOR_DEMANDA3 if fator_demanda3 is None else fator_demanda3
    st, j1, j2, j3 = geo["st"].copy(), geo["j1"].copy(), geo["j2"].copy(), geo["j3"].copy()
    st["pop_censo"] = st["pop"]
    st["pop"] = np.round(st["pop"] * P.FATOR_POP).astype(int)
    D01, T01 = geo["D01"], geo["T01"]
    if agregado:
        st = agrega_setores(st, n_sede=n_sede)
        w = st["pop"].values[:, None]
        grp = st.groupby("grupo").indices
        ids = sorted(grp)
        D01 = np.vstack([(D01[ix] * w[ix]).sum(0) / w[ix].sum() for ix in (grp[g] for g in ids)])
        T01 = np.vstack([(T01[ix] * w[ix]).sum(0) / w[ix].sum() for ix in (grp[g] for g in ids)])
        pop = np.array([st["pop"].values[grp[g]].sum() for g in ids])
    else:
        ids, pop = list(st.id), st["pop"].values

    idade_censo, nv = sidra_idade(), sidra_nascidos_vivos()
    ans_censo = ans_cobertura(idade_censo)
    # populacao 2026 por faixa etaria (crescimento uniforme) e cobertura de planos sobre a populacao 2026
    idade = {k: v * P.FATOR_POP for k, v in idade_censo.items()}
    ans = dict(ans_censo, **{k: ans_censo[k] / P.FATOR_POP for k in ("cob_total", "cob_0_14", "cob_15_59", "cob_60")})
    nv_ano = max(nv)
    NI, tmp, uti, sus, grupos = P.demanda_hospitalar(idade, ans, nv[nv_ano])
    pop_sus = sum(sus.values())
    prop_SUS = round(1 - ans["cob_total"], 4)
    coef_cons = P.TAXA2["CONS_ESP"][0] / P.TAXA2["CONS_ESP"][1]
    prop23 = {q: round(fator_demanda3 * NI[q] / pop_sus / coef_cons, 6) for q in P.S3}

    # ---------------- APS ----------------
    for c in ["eSF", "eAP", "eAP_eq", "eSB", "ACS", "eMulti"]:
        j1[c] = j1[c].fillna(0)
    j1["ESF_atual"] = (j1.eSF + np.floor(j1.eAP_eq + 0.5)).astype(int)
    # ACS: os do CNES + rateio do total informado pela Prefeitura, proporcional as eSF de cada UBS
    ex = j1.existente == 1
    j1["ACS_cnes"] = j1.ACS.astype(int)
    extra = max(0, P.ACS_TOTAL - int(j1.loc[ex, "ACS"].sum()))
    cota = extra * j1.loc[ex, "eSF"] / j1.loc[ex, "eSF"].sum()
    inteiro = np.floor(cota)
    resto = (cota - inteiro).sort_values(ascending=False)
    inteiro.loc[resto.index[:int(extra - inteiro.sum())]] += 1          # maiores restos
    j1.loc[ex, "ACS"] = j1.loc[ex, "ACS"] + inteiro
    for c in ["eSF", "eAP", "eSB", "ACS", "eMulti"]:
        j1[c] = j1[c].astype(int)
    j1["porte_min"] = np.where(ex, j1.ESF_atual.clip(1, 5), 0).astype(int)
    assert (j1.ESF_atual <= P.PORTES[5]["maxESF"]).all(), j1.ESF_atual.max()
    assert (j1.ACS <= np.array([P.PORTES[max(1, p)]["maxACS"] for p in j1.porte_min])).all()
    cf1 = {}
    for _, r in j1[j1.existente == 1].iterrows():
        pa = r.porte_min
        for p in range(1, 6):
            q = max(p, pa)
            cf1[(r.id, p)] = round(P.F_UBS + P.CUSTO_EXTRA_EAP * r.eAP_eq
                                   + P.CRF_PREDIO * max(0.0, P.INV_UBS[q] - P.INV_UBS[pa]), 2)

    # ---------------- Nivel 2 ----------------
    sec_atual, hosp_atual, mapa_leitos, sec_cnes = recursos_existentes()
    n2_atual, n2_max = {}, {}
    for _, r in j2.iterrows():
        if r.existente == 1:
            for k, v in sec_atual[int(r.cnes)].items():
                if round(v) > 0:
                    n2_atual[(r.id, k)] = int(round(v))
                    n2_max[(r.id, k)] = max(P.N2_MAX[k], int(round(v)))
    # ---------------- Nivel 3 ----------------
    # custeio por leito calibrado pela despesa real do Hospital Municipal + anexo Santa Catarina (SPDM 2025)
    hmm = [6601804, 2151855]
    pessoal = sum(hosp_atual[c].get(r, 0) * P.SAL3[r] for c in hmm for r in ("MEDICO", "ENFERMEIRO", "TEC_ENF"))
    leitos_hmm = {}
    for c in hmm:
        for k, v in hosp_atual[c].items():
            if k.startswith("LEITO"):
                leitos_hmm[k] = leitos_hmm.get(k, 0) + v
    P.calibra_custeio_leito(pessoal, leitos_hmm)
    n3_atual, n3_max, cf3 = {}, {}, {}
    for _, r in j3.iterrows():
        if r.existente == 1:
            c = int(r.cnes)
            amplia = HOSP_EXIST[c][1]
            for k in P.R3:
                v = int(round(hosp_atual[c].get(k, 0)))
                if v > 0:
                    n3_atual[(r.id, k)] = v
                n3_max[(r.id, k)] = max(P.N3_MAX[k], v) if amplia else v
            leitos = sum(v for k, v in hosp_atual[c].items() if k.startswith("LEITO"))
            cf3[r.id] = round(P.CF3_POR_LEITO_EXIST * leitos, 2)
        else:
            cf3[r.id] = P.CF3_CAND

    return dict(I=list(ids), pop=dict(zip(ids, pop.astype(int))), J1=list(j1.id), J2=list(j2.id), J3=list(j3.id),
                D01=D01, T01=T01, D12=geo["D12"], T12=geo["T12"], D23=geo["D23"], T23=geo["T23"],
                j1=j1, j2=j2, j3=j3, st=st, prop_SUS=prop_SUS, prop23=prop23, cf1=cf1,
                n2_atual=n2_atual, n2_max=n2_max, n3_atual=n3_atual, n3_max=n3_max, cf3=cf3,
                NI=NI, tmp=tmp, uti=uti, sus=sus, grupos=grupos, idade=idade, ans=ans, nv=nv, nv_ano=nv_ano,
                consumo3=P.consumo3(tmp, uti), sec_atual=sec_atual, hosp_atual=hosp_atual, mapa_leitos=mapa_leitos,
                sec_cnes=sec_cnes, agregado=agregado, fator_demanda3=fator_demanda3)


def _fmt(x):
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    return f"{x:.4f}".rstrip("0").rstrip(".") if abs(x - round(x)) > 1e-9 else str(int(round(x)))


def _matriz(f, nome, linhas, colunas, M, primeira_col=None):
    """Escreve param nome: tabela 2D no formato do GMPL (blocos de 40 colunas)."""
    f.write(f"param {nome} :=\n")
    blocos = [list(range(k, min(k + 40, len(colunas)))) for k in range(0, len(colunas), 40)]
    for b in blocos:
        cab = ([primeira_col[0]] if (primeira_col and b[0] == 0) else []) + [colunas[j] for j in b]
        f.write("[*,*]: " + " ".join(cab) + " :=\n")
        for i, l in enumerate(linhas):
            vals = ([_fmt(primeira_col[1][i])] if (primeira_col and b[0] == 0) else []) + [_fmt(M[i, j]) for j in b]
            f.write(f"{l} " + " ".join(vals) + "\n")
    f.write(";\n\n")


def escrever_dat(d, caminho):
    j1, j2, j3 = d["j1"], d["j2"], d["j3"]
    with open(caminho, "w", encoding="ascii", errors="replace") as f:
        w = f.write
        w("# =============================================================================\n")
        w("# DADOS DE UBERLANDIA (MG) - modelo_rede_saude_v02.mod\n")
        w(f"# {'Versao AGREGADA (pontos de demanda = grupos de setores)' if d['agregado'] else 'Versao COMPLETA (1 ponto por setor censitario)'}\n")
        w("# Gerado por codigo/gerar_base_uberlandia.py. Fontes e classificacao de\n")
        w("# cada parametro (EXERCICIO / DECISAO / NORMATIVO / DADO / INFERIDO) na planilha base_uberlandia.xlsx.\n")
        w(f"# Populacao: estimativa IBGE 2026 (Censo 2022 x {P.FATOR_POP}).\n")
        w(f"# Cenario de demanda hospitalar: x{d['fator_demanda3']:.2f} "
          f"({'Caderno 1' if d['fator_demanda3'] == 1 else 'observada no SIH'}).\n")
        w("# =============================================================================\n\ndata;\n\n")
        w("# ---------------- Conjuntos ----------------\n")
        for nome, lst in [("I", d["I"]), ("J1", d["J1"]), ("J2", d["J2"]), ("J3", d["J3"]),
                          ("S2", P.S2), ("S3", P.S3), ("R2", P.R2), ("R3", P.R3)]:
            w(f"set {nome} :=\n")
            for k in range(0, len(lst), 8):
                w("  " + " ".join(lst[k:k + 8]) + "\n")
            w(";\n")
        w("\n# ---------------- Controle ----------------\n")
        w("param modo := 1;\nparam orcamento := 0;\nparam coerente := 1;\n")
        w("param regra_acesso := 2;      # EXERCICIO: distancia OU tempo (30 km ou 1 h)\n")
        w("param eps_dist := 0.01;       # desempate no modo 1: R$ 0,01 por pessoa.km\n")
        w("param eps_custo := 0.000001;\nparam peso01 := 1;\nparam peso12 := 1;\nparam peso23 := 1;\n\n")
        w("# Limites de acesso (EXERCICIO)\n")
        w("param dmax01 := 5;   param tmax01 := 25;\nparam dmax12 := 30;  param tmax12 := 60;\nparam dmax23 := 60;  param tmax23 := 120;\n")
        w("# Velocidades usadas so se faltar algum tempo (os tempos abaixo vem do OSRM)\n")
        w("param vel01 := 4.5;   # caminhada\nparam vel12 := 30;    # carro em area urbana\nparam vel23 := 30;\n\n")
        w(f"param prop_SUS := {d['prop_SUS']};   # 1 - beneficiarios ANS / populacao 2026 (IBGE)\n\n")
        w("# ---------------- Populacao (Censo 2022) e distancia a pe (km, OSRM) ----------------\n")
        M = np.hstack([np.array([d["pop"][i] for i in d["I"]], dtype=float)[:, None], d["D01"]])
        _matriz(f, "matriz01", d["I"], ["POP"] + d["J1"], M)
        w("# Tempo a pe setor -> UBS (min, OSRM perfil foot)\n")
        _matriz(f, "t01", d["I"], d["J1"], d["T01"])
        w("# Distancia (km) e tempo (min) de carro UBS -> secundaria e secundaria -> hospital (OSRM)\n")
        _matriz(f, "d12", d["J1"], d["J2"], d["D12"])
        _matriz(f, "t12", d["J1"], d["J2"], d["T12"])
        _matriz(f, "d23", d["J2"], d["J3"], d["D23"])
        _matriz(f, "t23", d["J2"], d["J3"], d["T23"])

        w("# ---------------- APS ----------------\n")
        ex = j1[j1.existente == 1]
        for nome, col in [("existente1", None), ("porte_min1", "porte_min"), ("ESF_atual", "ESF_atual"),
                          ("ESB_atual", "eSB"), ("ACS_atual", "ACS"), ("EMU_atual", "eMulti")]:
            w(f"param {nome} :=\n")
            for _, r in ex.iterrows():
                v = 1 if col is None else int(r[col])
                if v > 0:
                    w(f"  {r.id} {v}\n")
            w(";\n")
        w("\n#        minESF maxESF minESB maxESB minACS maxACS minEMU maxEMU custo_porte (R$/ano)\n")
        w("param:   minESF maxESF minESB maxESB minACS maxACS minEMU maxEMU custo_porte :=\n")
        for p, v in P.PORTES.items():
            w(f"{p}  " + "  ".join(_fmt(v[k]) for k in ["minESF", "maxESF", "minESB", "maxESB", "minACS", "maxACS",
                                                         "minEMU", "maxEMU", "custo_porte"]) + "\n")
        w(";\n# UBS existentes: custeio do porte + ampliacao anualizada (a obra atual ja foi paga)\n")
        w("param custo_fixo1 :=\n")
        for (j, p), v in d["cf1"].items():
            w(f"  [{j},{p}] {_fmt(v)}\n")
        w(";\n")
        for k, v in P.EQUIPES.items():
            w(f"param {k} := {_fmt(v)};\n")
        for k, v in P.CAP_APS.items():
            w(f"param {k} := {_fmt(v)};\n")

        w("\n# ---------------- Nivel 2 (Caderno 1 de Parametros SUS) ----------------\n")
        w("param: taxa2 escala2 :=\n")
        for s in P.S2:
            w(f"  {s} {P.TAXA2[s][0]} {P.TAXA2[s][1]}\n")
        w(";\n# prop23 = internacoes esperadas por habitante SUS / consultas especializadas por habitante SUS\n")
        w("param prop23 :=\n")
        for q, v in d["prop23"].items():
            w(f"  [CONS_ESP,{q}] {_fmt(v)}\n")
        w(";\nparam existente2 :=\n")
        for _, r in j2[j2.existente == 1].iterrows():
            w(f"  {r.id} 1\n")
        w(";\nparam custo_fixo2 :=\n")
        for _, r in j2.iterrows():
            w(f"  {r.id} {_fmt(P.CF2_EXIST if r.existente == 1 else P.CF2_CAND)}\n")
        w(";\nparam:  salario2  carga2  n2_max_padrao :=\n")
        for r in P.R2:
            w(f"  {r} {_fmt(P.SAL2[r])} {_fmt(P.CARGA2[r])} {P.N2_MAX[r]}\n")
        w(";\nparam consumo2 :=\n")
        for (s, r), v in P.CONSUMO2.items():
            w(f"  [{s},{r}] {_fmt(v)}\n")
        w(";\nparam n2_atual :=\n")
        for (k, r), v in d["n2_atual"].items():
            w(f"  [{k},{r}] {v}\n")
        w(";\nparam n2_max :=\n")
        for (k, r), v in d["n2_max"].items():
            w(f"  [{k},{r}] {v}\n")
        w(";\n\n# ---------------- Nivel 3 (Caderno 1, secao V) ----------------\n")
        w("param existente3 :=\n")
        for _, r in j3[j3.existente == 1].iterrows():
            w(f"  {r.id} 1\n")
        w(";\nparam custo_fixo3 :=\n")
        for h, v in d["cf3"].items():
            w(f"  {h} {_fmt(v)}\n")
        w(";\n# Leitos: carga = 365 x taxa de ocupacao (leito-dia/ano); pessoal: horas produtivas/ano\n")
        w("param:  salario3  carga3  n3_max_padrao :=\n")
        for r in P.R3:
            w(f"  {r} {_fmt(P.SAL3[r])} {_fmt(P.CARGA3[r])} {P.N3_MAX[r]}\n")
        w(";\n# Leitos: dias por internacao; pessoal: horas por internacao\n")
        w("param consumo3 :=\n")
        for (q, r), v in d["consumo3"].items():
            w(f"  [{q},{r}] {_fmt(v)}\n")
        w(";\nparam n3_atual :=\n")
        for (h, r), v in d["n3_atual"].items():
            w(f"  [{h},{r}] {v}\n")
        w(";\nparam n3_max :=\n")
        for (h, r), v in d["n3_max"].items():
            w(f"  [{h},{r}] {v}\n")
        w(";\n\nend;\n")


# ----------------------------------------------------------------------------
# Planilha
# ----------------------------------------------------------------------------

LACUNAS = [
    # (prioridade, item, situacao atual, como refinar). Todas ja tem aproximacao na base: nada bloqueia os cenarios.
    ("Baixa", "Otimalidade da solucao", "Sem Gurobi: HiGHS + busca local no vinculo da APS + limitante por decomposicao "
     "(rodar_cenarios.py). Gap de cada cenario em resultados/gurobi_2026-11-03/resumo_cenarios.csv.",
     "Gurobi (licenca academica gratuita) com o mesmo script, para fechar o gap no artigo."),
    ("Baixa", "UBS tradicionais (eAP)", "Custo adicional de R$ 0,62 mi por eAP-equivalente/ano, medido em 2 unidades "
     "(Tibery e Custodio Pereira).", "Mais UBS tradicionais nos contratos dos setores Sul, Oeste e Central-Norte."),
    ("Baixa", "Distribuicao espacial da populacao 2026", "Crescimento de 7,7% aplicado de forma uniforme aos setores do "
     "Censo 2022.", "Crescimento por bairro (cadastro do IPTU ou ligacoes de agua), se a Prefeitura tiver."),
    ("Baixa", "Formato do artigo", "Padrao SBPO (12 paginas) adotado.", "Confirmar com o professor."),
]

RESOLVIDAS = [
    ("Nivel 3 = hospitais; distancia sem pesos; acesso rural de carro; eSB = eSF", "Decisao do grupo (out/2026)"),
    ("Zona rural 100% a 5 km/25 min; referencia hospitalar unica; urgencia fora", "Decisao do grupo (out/2026)"),
    ("Demanda hospitalar", "Dois cenarios gravados: Caderno 1 (1,00) e observada no SIH (1,14)"),
    ("Parcela do HC-UFU para residentes", "SIH: 75,3% nas internacoes; SIA/TabNet: 72% no ambulatorio"),
    ("Custeio de UBS e policlinica", "Contratos de gestao (388/2023, 16o TA, out/2026): custo fixo por unidade e custo "
     "por eSF calibrados no gasto real de 10 UBSF; policlinica pelo CER"),
    ("Encargos de pessoal", "Planilha das OS: 16,75 x salario mensal (sem INSS patronal)"),
    ("Produtividade do especialista", "Meta contratual da SMS: 336 consultas/mes por 20 h"),
    ("Precos de equipamentos", "PNCP e pregoes: US R$ 178 mil; TC 64 canais R$ 2,88 mi; RM 1,5 T R$ 6,22 mi"),
    ("Tetos da policlinica", "Novo PAC: 25 consultorios, 4 salas de US, 1 TC, 1 RM"),
    ("Populacao do ano-base", "Estimativa IBGE 2026 (768.339 hab.); cobertura de planos recalculada"),
    ("Salarios medicos", "CAGED: R$ 19.178 em 40 h; folha da UBSF Ipanema II implica ~R$ 19,9 mil"),
    ("Custeio hospitalar por leito", "SPDM 2025: despesa real do Hospital Municipal + anexo"),
    ("Imagem e consultas contratadas", "SIA: capacidade existente pela producao SUS de 12 meses, inclusive privados"),
    ("Modalidade das eAP", "CNES (membros das equipes): 31 de 20 h, 18 de 30 h, 22 de 35 h+"),
    ("Numero de ACS", "Prefeitura: ~500 (CNES registra ~210)"),
    ("Locais candidatos", "Projetos aprovados: Policlinica do Jaragua (Novo PAC, R$ 16,9 mi) e UBS Fruta do Conde"),
    ("UBS tradicionais (eAP)", "Contratos out/2026 (Tibery, Custodio Pereira): +R$ 617,8 mil por eAP-eq/ano no custo fixo "
     "das UBS existentes com eAP (aproximacao)"),
    ("Tetos de enfermeiro e tecnico de radiologia na policlinica", "Derivados do programa do Novo PAC: horas de "
     "enfermagem de 38 especialistas e horas para operar 1 TC + 1 RM (aproximacao)"),
    ("Distribuicao espacial da populacao 2026", "Uniforme entre setores (aproximacao: +7,7% em 4 anos; erro pequeno no "
     "numero de equipes)"),
    ("Pontos das faixas do Caderno", "Ponto medio + fila de 5%; o lado alto fica no cenario 'observada' (x1,14)"),
    ("Transito nos tempos de carro", "Nao aplicado: verificado que nenhum limite de tempo fica proximo de ser violado"),
    ("Formato do artigo", "SBPO (aproximacao; confirmar com o professor)"),
    ("Desempenho do solver", "rodar_cenarios.py: busca local no vinculo da APS + limitante valido por decomposicao "
     "(APS e niveis 2-3); Gurobi usado automaticamente se instalado"),
]

VALIDACAO = [
    # (tema, indicador, valor observado, valor no modelo/hipotese anterior, fonte)
    ("Contratos OS", "Gasto de 10 UBSF do Leste (out/2026)", "R$ 30,6 mi/ano", "modelo calibrado: R$ 31,0 mi (+1%); "
     "modelo anterior: R$ 22 mi (-28%)", "Contrato 388/2023, 16o TA"),
    ("Contratos OS", "UBSF com 1 eSF (Morumbi III, IV, V, Ipanema II)", "R$ 1,35-1,81 mi/ano", "modelo: R$ 1,77 mi",
     "Contrato 388/2023, 16o TA"),
    ("Contratos OS", "Encargos e provisoes sobre a folha", "39,6% (sem INSS patronal)", "antes: 35,8% + 13o e ferias = 18,1x",
     "Contrato 388/2023, 16o TA"),
    ("Contratos OS", "Setor Sul 2021: UBSF com 1 eSF", "~R$ 68 mil/mes = R$ 1,13 mi/ano a precos de set/2026 (IPCA x1,38)",
     "Leste 2026: R$ 1,35-1,81 mi (pisos da enfermagem 2023 e do ACS 2022 subiram acima da inflacao)",
     "Contrato 251/2020, 6o aditivo"),
    ("Contratos OS", "Setor Oeste 2022", "R$ 8,98 mi/mes (UAIs R$ 4,14 mi)", "-", "Contrato 178/2022, Anexo V"),
    ("Contratos OS", "Meta do medico especialista", "336 consultas/mes por 20 h (3,9/h contratada)",
     "Portaria 1.101: 4/h (usada antes sobre horas produtivas)", "Contrato 388/2023, Anexo I, Quadro 3"),
    ("Contratos OS", "Enfermeiro da ESF na rede (servidor antigo)", "R$ 10.417 / 200 h", "piso R$ 4.750", "Contrato 388/2023, 16o TA"),
    ("TabNet SIA", "Parcela de residentes no ambulatorio do HC-UFU", "72% (consultas 0,72; US 0,74; TC 0,76)",
     "SIH (internacoes): 75,3%", "SIA por residencia x por local de atendimento"),
    ("IBGE", "Populacao de Uberlandia", "768.339 (estimativa 2026)", "Censo 2022: 713.224", "SIDRA 6579"),
    ("PNCP", "Tomografo 64 canais", "R$ 2.519.000 (SES-PR, 2023); R$ 3,43 mi estimados (MG, 2024)", "R$ 2,5 mi inferido",
     "PNCP"),
    ("SIH", "Internacoes no HC-UFU (12 meses)", "20.220 (75,3% residentes)", "fracao inferida antes: 58%", "SIH RD MG set/25-ago/26"),
    ("SIH", "Internacoes no Hospital Municipal", "15.449 (99,5% residentes)", "100%", "SIH"),
    ("SIH", "Internacoes nas 8 UAIs", "~19.900 (TMP 3,3 dias)", "fora do modelo (urgencia)", "SIH"),
    ("SIH", "Internacoes hospitalares de residentes", "39.950/ano", "Caderno: ver aba Demanda", "SIH"),
    ("SIH", "Cirurgicas / clinicas / obstetricas / pediatricas", "20.449 / 10.066 / 5.521 / 3.623", "Caderno: ver aba Demanda", "SIH"),
    ("SIH", "Leito-dia hospitalar de residentes", "~213 mil", "Caderno: ~187 mil (populacao 2022)", "SIH"),
    ("SIA", "Consultas medicas especializadas SUS", "554.781 (municipal 257 mil; HC 219 mil; privados 77 mil)", "demanda: aba Demanda", "SIA/TabNet ago/25-jul/26"),
    ("SIA", "Ultrassom / TC / RM SUS", "95.105 / 36.114 / 12.967", "demanda: aba Demanda", "SIA/TabNet"),
    ("SPDM", "Despesa Hospital Municipal + anexo", "R$ 269,9 mi/ano (322 leitos SUS)", "modelo antes: ~R$ 160 mi", "SPDM 2025"),
    ("SPDM", "Ocupacao de leitos do Hospital Municipal", "85-88%", "Caderno: 81,5% (fila 5%)", "SPDM Relatorio 2025"),
    ("SPDM", "Saidas hospitalares 2025", "13.626 (HMM) + 1.971 (anexo)", "-", "SPDM Relatorio 2025"),
    ("CAGED", "Medico da ESF", "R$ 18.219 / 38 h", "R$ 15.000 inferido", "CAGED via salario.com.br"),
    ("CAGED", "Enfermeiro / tecnico de enfermagem", "R$ 4.503 / R$ 2.552 (38 h)", "piso R$ 4.750 / R$ 3.325", "CAGED"),
    ("CNES", "eAP por carga do medico", "31 x 20 h; 18 x 30-33 h; 22 x 35 h+", "0,5 eSF cada (inferido)", "CNES equipes"),
    ("Prefeitura", "ACS em atividade", "~500 (mar/2025)", "CNES: ~210", "Portal da Prefeitura"),
    ("Novo PAC", "Policlinica de Uberlandia (Jaragua)", "R$ 16,9 mi; ordem de servico 26/08/2026", "R$ 18 mi inferido", "noticias / Prefeitura"),
    ("OSRM", "Tempo de carro (fluxo livre) nos encaminhamentos da solucao", "nivel 2 -> hospital: ate 20 min; UBS -> "
     "nivel 2 na cidade: mediana 13 min", "limites de 120 e 60 min: transito nao muda a viabilidade", "OSRM + resultados"),
    ("Contratos OS", "UBS tradicionais (Tibery, Custodio Pereira)", "R$ 2,08 mi e R$ 2,71 mi/ano acima do custo de eSF",
     "+R$ 617,8 mil por eAP-eq no custo fixo", "Contrato 388/2023, 16o TA"),
]

PROJETOS = [
    ("Policlinica de Uberlandia", "Jaragua (Oeste)", "Novo PAC; consultas, endoscopia, TC, RM, pequenos procedimentos; "
     "R$ 16,9 mi; ordem de servico 26/08/2026", "candidato CAND_AAE_POLICLINICA_JARAGUA"),
    ("6 UBS Tipo I", "Aclimacao, Aurora, Fruta do Conde/Mansour, Guarani, Jardim Europa, Sao Jose", "SES-MG/Prefeitura 2026",
     "Fruta do Conde = candidato novo; as demais substituem predios de UBS existentes"),
    ("2 UBS Tipo III", "Planalto, Roosevelt", "SES-MG/Prefeitura 2026", "substituem/ampliam UBS existentes"),
    ("3 UBSF Tipo III", "Santa Luzia, Shopping Park, Sao Jorge", "Novo PAC (dez/2025)", "ampliam UBSF existentes"),
    ("UBS Jardim Botanico", "Jardim Botanico", "Novo PAC (jul/2025)", "substitui UBSF existente"),
    ("UPA Oeste", "Monte Hebron", "Novo PAC", "urgencia: fora do modelo"),
]


def escrever_xlsx(d, da, geo, caminho):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    F = "Arial"
    hdr_fill = PatternFill("solid", fgColor="1F4E78")
    hdr_font = Font(name=F, bold=True, color="FFFFFF")
    inp_font = Font(name=F, color="0000FF")
    norm = Font(name=F)
    cls_fill = {"EXERCICIO": "FCE4D6", "DECISAO": "EDE2F6", "NORMATIVO": "DDEBF7", "DADO": "E2EFDA", "INFERIDO": "FFF2CC"}
    wb = Workbook()

    def tabela(ws, df, linha=1, larguras=None, wrap=False):
        for j, c in enumerate(df.columns, 1):
            x = ws.cell(row=linha, column=j, value=str(c))
            x.font, x.fill = hdr_font, hdr_fill
            x.alignment = Alignment(wrap_text=True, vertical="center")
        for i, row in enumerate(df.itertuples(index=False), linha + 1):
            for j, v in enumerate(row, 1):
                if isinstance(v, (np.floating, float)) and np.isnan(v):
                    v = None
                elif isinstance(v, np.integer):
                    v = int(v)
                elif isinstance(v, np.floating):
                    v = float(v)
                x = ws.cell(row=i, column=j, value=v)
                x.font = norm
                if wrap:
                    x.alignment = Alignment(wrap_text=True, vertical="top")
        for j, c in enumerate(df.columns, 1):
            ws.column_dimensions[get_column_letter(j)].width = (larguras or {}).get(c, max(10, min(45, len(str(c)) + 4)))
        ws.freeze_panes = ws.cell(row=linha + 1, column=1)

    # ---- Leia-me
    ws = wb.active
    ws.title = "Leia-me"
    textos = [
        ("Base de dados de Uberlandia (MG) - rede SUS em 3 niveis", True),
        ("Modelo: modelo/modelo_rede_saude_v02.mod  |  Dados (pasta dados/): dados_uberlandia_setores.dat (completo) e "
         "dados_uberlandia_agregado.dat (para GLPK/GUSEK); *_demanda_obs.dat = cenario de demanda hospitalar observada (x1,14)", False),
        ("Gerado por codigo/gerar_base_uberlandia.py (IBGE Censo 2022, CNES, ANS, SIDRA, OSRM/OpenStreetMap).", False),
        ("", False),
        ("Classificacao de cada parametro (aba Parametros):", True),
        ("EXERCICIO - fixado pelo enunciado (limites de acesso, regra 'OU', 3.000 pessoas/eSF, 750/ACS)", False),
        ("DECISAO - escolha do autor (pesos de distancia, acesso rural de carro, eSB = eSF, fator de demanda)", False),
        ("NORMATIVO - lei, portaria ou Caderno 1 de Parametros SUS (Portaria 1.631/2015 -> PRC 1/2017)", False),
        ("DADO - medido em base publica (IBGE, CNES, ANS, OSRM, SIH, SIA, CAGED, SPDM, Novo PAC)", False),
        ("INFERIDO - hipotese de modelagem com o raciocinio registrado; trocar por dado local quando houver", False),
        ("", False),
        ("Numeros de referencia", True),
        (f"Setores com populacao: {len(d['I'])}  |  pontos de demanda na versao agregada: {len(da['I'])}", False),
        (f"Populacao 2026 (Censo 2022 x {P.FATOR_POP}): {sum(d['pop'].values()):,}  |  beneficiarios de planos (ANS {d['ans']['periodo']}): "
         f"{d['ans']['benef']:,}  |  prop_SUS = {d['prop_SUS']}", False),
        (f"J1: {len(d['J1'])} locais de APS ({int(d['j1'].existente.sum())} UBS existentes)  |  J2: {len(d['J2'])}  |  J3: {len(d['J3'])}", False),
        (f"Internacoes SUS esperadas/ano: {sum(d['NI'].values()):,.0f}  |  nascidos vivos {d['nv_ano']}: {d['nv'][d['nv_ano']]:,}", False),
        ("", False),
        ("Como usar", True),
        ("1) GUSEK: abrir modelo/modelo_rede_saude_v02.mod e associar dados/dados_uberlandia_agregado.dat (modo 1, depois modo 2). "
         "Usar limite de tempo e gap (ex.: --tmlim 3600 --mipgap 0.02): o GLPK dificilmente prova o otimo nesta escala.", False),
        ("2) Recomendado: python codigo/rodar_cenarios.py (Gurobi se instalado; senao HiGHS com vinculo guloso). "
         "Gera resultados/<rodada>/resumo_cenarios.csv, os CSV por cenario e os mapas.", False),
        ("3) A aba Anualizacao tem formulas: mudar taxa, vida util ou investimento mostra o efeito no custo anual. "
         "Para levar a mudanca ao .dat, editar codigo/parametros_uberlandia.py e rodar o script de novo.", False),
        ("Celulas em azul = entradas editaveis.", False),
    ]
    for i, (t, b) in enumerate(textos, 1):
        ws.cell(row=i, column=1, value=t).font = Font(name=F, bold=b, size=12 if i == 1 else 10)
    ws.column_dimensions["A"].width = 140

    # ---- Parametros
    ws = wb.create_sheet("Parametros")
    doc = pd.DataFrame(P.DOC)
    doc.columns = ["Grupo", "Parametro", "Valor", "Unidade", "Classificacao", "Fonte", "Raciocinio"]
    tabela(ws, doc, larguras={"Grupo": 12, "Parametro": 42, "Valor": 30, "Unidade": 22, "Classificacao": 14,
                              "Fonte": 55, "Raciocinio": 70}, wrap=True)
    for i, c in enumerate(doc.Classificacao, 2):
        ws.cell(row=i, column=5).fill = PatternFill("solid", fgColor=cls_fill.get(c, "FFFFFF"))
    extra = pd.DataFrame([
        ["Dados", "populacao por setor", "matriz01[i,'POP']", "pessoas", "DADO", "IBGE, Censo 2022, malha de setores com atributos (v0001)", ""],
        ["Dados", "d01, t01", "OSRM perfil a pe", "km, min", "DADO", "OpenStreetMap via OSRM (routing.openstreetmap.de)",
         "Ponto do setor = ponto interno do poligono (representative point)."],
        ["Dados", "d12, t12, d23, t23", "OSRM perfil carro", "km, min", "DADO", "OpenStreetMap via OSRM (router.project-osrm.org)",
         "Velocidade de fluxo livre (sem transito)."],
        ["Dados", "prop_SUS", d["prop_SUS"], "-", "DADO", f"ANS PDA 047 ({d['ans']['periodo']}) / IBGE Censo 2022",
         f"1 - {d['ans']['benef']:,} / {d['idade']['total']:,}"],
        ["Dados", "equipes, ACS, leitos, profissionais", "CNES", "-", "DADO", "cnes.datasus.gov.br (servicos da ficha do estabelecimento)", ""],
        ["Dados", "nascidos vivos", d["nv"][d["nv_ano"]], "por ano", "DADO", f"IBGE, Registro Civil, tabela 2612 ({d['nv_ano']})", ""],
    ], columns=doc.columns)
    base = len(doc) + 3
    for i, row in enumerate(extra.itertuples(index=False), base):
        for j, v in enumerate(row, 1):
            x = ws.cell(row=i, column=j, value=v)
            x.font = norm
            x.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=i, column=5).fill = PatternFill("solid", fgColor=cls_fill["DADO"])

    # ---- Lacunas
    ws = wb.create_sheet("Lacunas")
    tabela(ws, pd.DataFrame(LACUNAS, columns=["Prioridade", "Item", "Aproximacao adotada", "Como refinar"]),
           larguras={"Prioridade": 11, "Item": 38, "Aproximacao adotada": 80, "Como refinar": 70}, wrap=True)
    lin = len(LACUNAS) + 3
    ws.cell(row=lin, column=1, value="Resolvidas (out/2026)").font = Font(name=F, bold=True)
    for k, (item, como) in enumerate(RESOLVIDAS, lin + 1):
        ws.cell(row=k, column=2, value=item).font = norm
        ws.cell(row=k, column=3, value=como).font = norm

    # ---- Validacao com dados locais
    ws = wb.create_sheet("Validacao")
    tabela(ws, pd.DataFrame(VALIDACAO, columns=["Base", "Indicador", "Observado", "Modelo / hipotese anterior", "Fonte"]),
           larguras={"Base": 10, "Indicador": 44, "Observado": 52, "Modelo / hipotese anterior": 44, "Fonte": 30}, wrap=True)

    # ---- Contratos de gestao (calibracao dos custos da APS)
    ws = wb.create_sheet("Contratos_OS")
    linhas = []
    for (k, v), (_, real, mod) in zip(P.UBSF_LESTE_2026.items(), P.CALIB_APS):
        linhas.append(dict(unidade=k, gasto_mensal_out2026=v[0], eSF=v[1], eSB=v[2], ACS=v[3], eMulti=v[4], eAPP_prisional=v[5],
                           despesas_operacionais=v[6], servicos_terceiros=v[7], gasto_anual_real=round(real),
                           custo_anual_modelo=round(mod), erro_pct=round(100 * (mod / real - 1), 1)))
    tabela(ws, pd.DataFrame(linhas), larguras={"unidade": 42})
    n = len(linhas) + 3
    notas = [
        "Fonte: contrato de gestao 388/2023 (Missao Sal da Terra, Setor Leste), 16o termo aditivo, planilha de custos de out/2026 "
        "('gastos totais', ja sem INSS patronal). Equipes: CNES out/2026; ACS: Anexo I do contrato; eAPP conta como meia eSF.",
        f"Custo fixo operacional da UBS = R$ {P.F_UBS:,.0f}/ano (intercepto de despesas operacionais + servicos de terceiros "
        "x eSF, 9 UBSF urbanas).",
        f"custo_ESF = R$ {P.EQUIPES['custo_ESF']:,.0f}/ano: unico parametro ajustado por minimos quadrados para que "
        "F_UBS + custo_ESF x eSF + custo_ESB x eSB + custo_ACS x ACS + custo_EMU x eMulti reproduza o gasto real.",
        f"Equipe minima praticada (medico + enfermeiro + 2 tecnicos + aux. administrativo) = R$ {P.EQUIPE_MIN_ESF:,.0f}; "
        "o restante e apoio, multiprofissional fracionado, tutoria e operacao proporcional.",
        f"Fator de pessoal das OS: {P.FATOR_ANUAL} x salario mensal (encargos e provisoes = "
        f"{100 * sum(P.ENCARGOS_OS.values()) / P.SALARIOS_OS:.1f}% da folha, sem INSS patronal).",
        f"Policlinica: custo fixo operacional do CER (ambulatorio especializado do Leste) = R$ {P.CF2_EXIST:,.0f}/ano.",
        "Fora do ajuste: UBSF Ipanema I (R$ 471 mil/mes com 1 eSF no CNES - provavel rateio de outros servicos), Ipanema III "
        "(sem CNES) e as UBS tradicionais Tibery e Custodio Pereira (R$ 2,0-2,9 mi por eSF-equivalente).",
    ]
    for k, t in enumerate(notas, n):
        ws.cell(row=k, column=1, value=t).font = norm

    # ---- Projetos aprovados
    ws = wb.create_sheet("Projetos_aprovados")
    tabela(ws, pd.DataFrame(PROJETOS, columns=["Projeto", "Local", "Situacao", "Como entra na base"]),
           larguras={"Projeto": 28, "Local": 50, "Situacao": 60, "Como entra na base": 50}, wrap=True)

    # ---- Anualizacao (com formulas)
    ws = wb.create_sheet("Anualizacao")
    ws["A1"], ws["A1"].font = "Anualizacao do investimento (anuidade equivalente)", Font(name=F, bold=True, size=12)
    entradas = [("Taxa de desconto i (a.a.)", P.TSD, "NT SEI 19911/2020/ME - Taxa Social de Desconto"),
                ("Vida util predio n (anos)", P.VIDA_PREDIO, "IN RFB 1.700/2017"),
                ("Vida util equipamento n (anos)", P.VIDA_EQUIP, "IN RFB 1.700/2017"),
                ("Custo fixo operacional de uma UBS (R$/ano)", P.F_UBS, "DADO: contratos de gestao, out/2026"),
                ("Manutencao de equipamento (fracao/ano)", P.MANUT_EQUIP, "INFERIDO")]
    for k, (t, v, f) in enumerate(entradas, 3):
        ws.cell(row=k, column=1, value=t).font = norm
        c = ws.cell(row=k, column=2, value=v); c.font = inp_font
        ws.cell(row=k, column=3, value=f).font = norm
    ws["B3"].number_format = ws["B7"].number_format = "0.0%"
    ws["B6"].number_format = "#,##0"
    ws["A9"], ws["B9"] = "CRF predio = i(1+i)^n / ((1+i)^n - 1)", "=B3*(1+B3)^B4/((1+B3)^B4-1)"
    ws["A10"], ws["B10"] = "CRF equipamento", "=B3*(1+B3)^B5/((1+B3)^B5-1)"
    ws["C9"] = "Parcela anual que, paga por n anos a taxa i, equivale ao investimento."
    for c in ("A9", "A10", "B9", "B10", "C9"):
        ws[c].font = norm
    ws["B9"].number_format = ws["B10"].number_format = "0.00000"
    cab = ["Porte", "Investimento Novo PAC (R$)", "Obra anualizada (R$/ano)", "Custo fixo operacional (R$/ano)",
           "custo_porte (R$/ano)"]
    for j, t in enumerate(cab, 1):
        x = ws.cell(row=12, column=j, value=t); x.font, x.fill = hdr_font, hdr_fill
    for k, p in enumerate(range(1, 6), 13):
        ws.cell(row=k, column=1, value=f"Tipo {p}").font = norm
        c = ws.cell(row=k, column=2, value=P.INV_UBS[p]); c.font = inp_font
        ws.cell(row=k, column=3, value=f"=B{k}*$B$9").font = norm
        ws.cell(row=k, column=4, value="=$B$6").font = norm
        ws.cell(row=k, column=5, value=f"=C{k}+D{k}").font = norm
        for j in range(2, 6):
            ws.cell(row=k, column=j).number_format = "#,##0"
    cab = ["Equipamento", "Investimento (R$)", "Capital anualizado (R$/ano)", "Manutencao (R$/ano)", "salario2 (R$/ano)"]
    for j, t in enumerate(cab, 1):
        x = ws.cell(row=19, column=j, value=t); x.font, x.fill = hdr_font, hdr_fill
    for k, (r, v) in enumerate(P.INV_EQ.items(), 20):
        ws.cell(row=k, column=1, value=r).font = norm
        c = ws.cell(row=k, column=2, value=v); c.font = inp_font
        ws.cell(row=k, column=3, value=f"=B{k}*$B$10").font = norm
        ws.cell(row=k, column=4, value=f"=B{k}*$B$7").font = norm
        ws.cell(row=k, column=5, value=f"=C{k}+D{k}").font = norm
        for j in range(2, 6):
            ws.cell(row=k, column=j).number_format = "#,##0"
    ws["A24"] = ("UBS existente: a obra ja foi paga (custo afundado). custo_fixo1 = custo fixo operacional + "
                 "CRF x (investimento do porte novo - investimento do porte atual).")
    ws["A25"] = (f"Policlinica candidata: obra de R$ 16,9 mi x CRF + custo fixo operacional do CER (R$ {P.CF2_EXIST:,.0f}/ano). "
                 "Hospital candidato: R$ 40 mi x CRF (o custeio vem no custo por leito).")
    ws["A24"].font = ws["A25"].font = norm
    for col, wdt in zip("ABCDE", [44, 26, 28, 26, 22]):
        ws.column_dimensions[col].width = wdt

    # ---- Setores
    st = d["st"].copy()
    st = st.merge(da["st"][["id", "grupo"]], on="id", how="left")
    ws = wb.create_sheet("Setores")
    tabela(ws, st[["id", "CD_SETOR", "pop", "SITUACAO", "NM_DIST", "NM_BAIRRO", "AREA_KM2", "modo_acesso", "lon", "lat",
                   "grupo"]]
           .rename(columns={"id": "id_modelo", "pop": "populacao", "NM_DIST": "distrito", "NM_BAIRRO": "bairro",
                            "SITUACAO": "situacao", "grupo": "ponto_agregado"}))

    # ---- APS
    j1 = d["j1"].copy()
    D01 = geo["D01"]
    w = d["st"]["pop"].values
    j1["pop_a_5km"] = [int((w * (D01[:, k] <= DMAX01)).sum()) for k in range(len(j1))]
    cols = ["id", "nome", "existente", "cnes", "eSF", "eAP", "eAP_eq", "ESF_atual", "porte_min", "eSB", "ACS_cnes", "ACS",
            "eMulti", "pop_a_5km", "lon_f", "lat_f", "coord_fonte", "end", "cep"]
    ws = wb.create_sheet("APS_J1")
    tabela(ws, j1[cols].rename(columns={"lon_f": "lon", "lat_f": "lat", "end": "endereco_cnes",
                                        "pop_a_5km": "populacao_a_ate_5km_a_pe"}),
           larguras={"nome": 46, "coord_fonte": 34, "endereco_cnes": 40, "id": 18})

    # ---- Secundaria e terciaria
    j2 = d["j2"].copy()
    for r in P.R2:
        j2[f"atual_{r}"] = [d["n2_atual"].get((i, r), 0) for i in j2.id]
    j2["custo_fixo2"] = [P.CF2_EXIST if e == 1 else P.CF2_CAND for e in j2.existente]
    j2["MED_ESP_cnes_FTE"] = [round(d["sec_cnes"].get(int(c), 0), 1) if e == 1 else 0 for c, e in zip(j2.cnes.fillna(0), j2.existente)]
    ws = wb.create_sheet("Secundaria_J2")
    tabela(ws, j2[["id", "nome", "existente", "cnes", "custo_fixo2"] + [f"atual_{r}" for r in P.R2] +
                  ["MED_ESP_cnes_FTE", "lon_f", "lat_f", "coord_fonte"]].rename(columns={"lon_f": "lon", "lat_f": "lat"}),
           larguras={"nome": 46, "id": 24, "coord_fonte": 30})
    j3 = d["j3"].copy()
    for r in P.R3:
        j3[f"atual_{r}"] = [d["n3_atual"].get((i, r), 0) for i in j3.id]
    j3["custo_fixo3"] = [d["cf3"][i] for i in j3.id]
    ws = wb.create_sheet("Terciaria_J3")
    tabela(ws, j3[["id", "nome", "existente", "cnes", "custo_fixo3"] + [f"atual_{r}" for r in P.R3] +
                  ["lon_f", "lat_f", "coord_fonte"]].rename(columns={"lon_f": "lon", "lat_f": "lat"}),
           larguras={"nome": 46, "id": 20, "coord_fonte": 30})
    ws = wb.create_sheet("Leitos_CNES")
    tabela(ws, d["mapa_leitos"], larguras={"hospital": 36, "atributo": 22, "leito": 50, "recurso": 18})

    # ---- Demanda
    ws = wb.create_sheet("Demanda")
    ws["A1"], ws["A1"].font = "Demanda SUS esperada (atendimentos/ano)", Font(name=F, bold=True, size=12)
    ws["A2"], ws["B2"] = "Populacao total (estimativa 2026)", d["idade"]["total"]
    ws["A3"], ws["B3"] = "prop_SUS", d["prop_SUS"]
    ws["A4"], ws["B4"] = "Populacao SUS", "=B2*B3"
    for c in ("A2", "A3", "A4", "B4"):
        ws[c].font = norm
    ws["B2"].font = ws["B3"].font = inp_font
    cab = ["Servico S2", "taxa", "escala", "por hab SUS/ano", "Demanda/ano", "Fonte"]
    for j, t in enumerate(cab, 1):
        x = ws.cell(row=6, column=j, value=t); x.font, x.fill = hdr_font, hdr_fill
    fontes2 = {"CONS_ESP": "Caderno 1, Quadro 35", "US": "Caderno 1, 6.4", "TC": "Caderno 1, Quadro 35", "RM": "Caderno 1, 6.7"}
    for k, s in enumerate(P.S2, 7):
        ws.cell(row=k, column=1, value=s).font = norm
        ws.cell(row=k, column=2, value=P.TAXA2[s][0]).font = inp_font
        ws.cell(row=k, column=3, value=P.TAXA2[s][1]).font = inp_font
        ws.cell(row=k, column=4, value=f"=B{k}/C{k}").font = norm
        ws.cell(row=k, column=5, value=f"=D{k}*$B$4").font = norm
        ws.cell(row=k, column=6, value=fontes2[s]).font = norm
        ws.cell(row=k, column=5).number_format = "#,##0"
    cab = ["Servico S3", "Internacoes/ano", "TMP (dias)", "dias de UTI/internacao", "prop23[CONS_ESP,q]", "Composicao"]
    for j, t in enumerate(cab, 1):
        x = ws.cell(row=13, column=j, value=t); x.font, x.fill = hdr_font, hdr_fill
    comp = {"INT_CLIN": "clin 15-59 + clin 60+", "INT_CIR": "cir 15-59 + cir 60+", "INT_OBST": "gestantes SUS x 1,0",
            "INT_PED": "ped clin + ped cir (< 15 anos)", "INT_NEO": "nascidos vivos SUS x TI neo"}
    for k, q in enumerate(P.S3, 14):
        for j, v in enumerate([q, round(d["NI"][q]), round(d["tmp"][q], 3), round(d["uti"][q], 4), d["prop23"][q], comp[q]], 1):
            ws.cell(row=k, column=j, value=v).font = norm
    ws.cell(row=19, column=1, value="Total").font = Font(name=F, bold=True)
    ws.cell(row=19, column=2, value="=SUM(B14:B18)").font = Font(name=F, bold=True)
    ws["A21"] = ("prop23 = (internacoes por habitante SUS) / (consultas especializadas por habitante SUS). Assim o modelo "
                 "gera Dem3 = prop23 x Dem2[CONS_ESP], igual ao numero de internacoes do Caderno.")
    ws["A21"].font = norm
    grp = pd.DataFrame([dict(grupo=k, internacoes=round(v)) for k, v in d["grupos"].items()])
    for j, t in enumerate(["Grupo do Quadro 37", "Internacoes/ano"], 1):
        x = ws.cell(row=23, column=j, value=t); x.font, x.fill = hdr_font, hdr_fill
    for k, row in enumerate(grp.itertuples(index=False), 24):
        ws.cell(row=k, column=1, value=row.grupo).font = norm
        ws.cell(row=k, column=2, value=row.internacoes).font = norm
    for col, wdt in zip("ABCDEF", [30, 18, 14, 22, 20, 34]):
        ws.column_dimensions[col].width = wdt

    # ---- Recursos
    ws = wb.create_sheet("Recursos_N2")
    rec2 = pd.DataFrame([dict(recurso=r, unidade=("exames" if r.startswith("EQ") else "horas"), carga2=P.CARGA2[r],
                              salario2=P.SAL2[r], n2_max_padrao=P.N2_MAX[r],
                              **{f"consumo_{s}": P.CONSUMO2.get((s, r), 0) for s in P.S2}) for r in P.R2])
    tabela(ws, rec2)
    ws = wb.create_sheet("Recursos_N3")
    rec3 = pd.DataFrame([dict(recurso=r, unidade=("leito-dia" if r.startswith("LEITO") else "horas"), carga3=P.CARGA3[r],
                              salario3=P.SAL3[r], n3_max_padrao=P.N3_MAX[r],
                              **{f"consumo_{q}": d["consumo3"].get((q, r), 0) for q in P.S3}) for r in P.R3])
    tabela(ws, rec3)

    # ---- Matrizes
    for nome, M, lin, col in [("d01_km", geo["D01"], list(d["st"].id), list(d["j1"].id)),
                              ("t01_min", geo["T01"], list(d["st"].id), list(d["j1"].id))]:
        ws = wb.create_sheet(nome)
        tabela(ws, pd.DataFrame(np.round(M, 3), columns=col).assign(setor=lin)[["setor"] + col])
        ws.freeze_panes = "B2"
    longo = []
    for i, a in enumerate(d["J1"]):
        for k, b in enumerate(d["J2"]):
            longo.append(dict(origem=a, destino=b, trecho="1-2", km=round(geo["D12"][i, k], 3), min=round(geo["T12"][i, k], 2)))
    for i, a in enumerate(d["J2"]):
        for k, b in enumerate(d["J3"]):
            longo.append(dict(origem=a, destino=b, trecho="2-3", km=round(geo["D23"][i, k], 3), min=round(geo["T23"][i, k], 2)))
    ws = wb.create_sheet("d12_d23")
    tabela(ws, pd.DataFrame(longo), larguras={"origem": 22, "destino": 24})

    wb.calculation.fullCalcOnLoad = True
    wb.save(caminho)


# ============================================================================
# EXECUCAO
# ============================================================================

if __name__ == "__main__":
    geo = montar_geografia()
    d = montar_dados(geo, agregado=False)
    da = montar_dados(geo, agregado=True)
    escrever_dat(d, DADOS / "dados_uberlandia_setores.dat")
    escrever_dat(da, DADOS / "dados_uberlandia_agregado.dat")
    # cenario de demanda hospitalar observada (SIH): so muda prop23
    f_obs = P.CENARIOS_DEMANDA3["observada"]
    escrever_dat(montar_dados(geo, agregado=False, fator_demanda3=f_obs), DADOS / "dados_uberlandia_setores_demanda_obs.dat")
    escrever_dat(montar_dados(geo, agregado=True, fator_demanda3=f_obs), DADOS / "dados_uberlandia_agregado_demanda_obs.dat")
    escrever_xlsx(d, da, geo, DADOS / "base_uberlandia.xlsx")
    print("ok:", len(d["I"]), "setores;", len(da["I"]), "pontos agregados;", len(d["J1"]), "J1;",
          len(d["J2"]), "J2;", len(d["J3"]), "J3")
