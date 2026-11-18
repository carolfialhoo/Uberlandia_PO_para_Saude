# -*- coding: utf-8 -*-
"""
Monta o mapa interativo (mapa/mapa_rede_sus.html), um arquivo unico que abre em qualquer navegador.

Entradas (nesta pasta):
  mapa_modelo.html        pagina com os marcadores /*LEAFLET_CSS*/ e /*DADOS_JSON*/
  leaflet-1.9.4.min.css   estilo do Leaflet (copiado de cdnjs; vai embutido na pagina)
  dados_mapa.json         gerado por codigo/analise_cenarios.py
O script do Leaflet 1.9.4 e carregado do cdnjs quando a pagina abre (precisa de internet).

Uso: python mapa/montar_mapa.py
"""
import re
from pathlib import Path

AQUI = Path(__file__).resolve().parent
modelo = (AQUI / "mapa_modelo.html").read_text(encoding="utf-8")
css = (AQUI / "leaflet-1.9.4.min.css").read_text(encoding="utf-8")
# o CSS do Leaflet aponta para imagens de icones que a pagina nao usa: troca as url(...) por none
css = re.sub(r"url\([^)]*\)", "none", css)
# "</" dentro do JSON fecharia a tag <script>; "<\/" e o mesmo texto para o JSON.parse
dados = (AQUI / "dados_mapa.json").read_text(encoding="utf-8").replace("</", r"<\/")
html = modelo.replace("/*LEAFLET_CSS*/", css).replace("/*DADOS_JSON*/", dados)
(AQUI / "mapa_rede_sus.html").write_text(html, encoding="utf-8")
print(f"mapa_rede_sus.html: {len(html) / 1e6:.2f} MB")
