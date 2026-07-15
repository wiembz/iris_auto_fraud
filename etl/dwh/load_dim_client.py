"""
etl/dwh/load_dim_client.py
===========================
Charge staging.stg_clients -> dwh.dim_client.

Grain    : une ligne par client unique (idclt)
Cle metier : idclt = client_key (cnat_norm|numpers_norm)
Cle tech   : client_sk (entier sequentiel genere par le DWH)

Usage :
  python etl/dwh/load_dim_client.py
"""
from __future__ import annotations

import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

TABLE_NAME    = "dim_client"
SOURCE_TABLE  = "staging.stg_clients"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

# ---------------------------------------------------------------------------
# Referentiels gouvernorats
# ---------------------------------------------------------------------------
GOUVERNORATS: frozenset[str] = frozenset({
    "TUNIS", "ARIANA", "BEN AROUS", "MANOUBA", "NABEUL", "ZAGHOUAN",
    "BIZERTE", "BEJA", "JENDOUBA", "KEF", "SILIANA", "SOUSSE",
    "MONASTIR", "MAHDIA", "SFAX", "KAIROUAN", "KASSERINE", "SIDI BOUZID",
    "GABES", "MEDENINE", "TATAOUINE", "GAFSA", "TOZEUR", "KEBILI",
})

# Variantes orthographiques -> gouvernorat canonique
GOUVERNORAT_ALIASES: dict[str, str] = {
    "MANNOUBA":        "MANOUBA",  "LA MANNOUBA":    "MANOUBA",
    "LA MANOUBA":      "MANOUBA",
    "SELIANA":         "SILIANA",  "SILIANE":        "SILIANA",
    "MEDNINE":         "MEDENINE", "MEDNIN":         "MEDENINE",
    "LE KEF":          "KEF",      "EL KEF":         "KEF",
    "B AROUS":         "BEN AROUS","BENAROUS":       "BEN AROUS",
    "BEN ARUS":        "BEN AROUS","BEN AROOUS":     "BEN AROUS",
    "BEN AOUS":        "BEN AROUS",
    "TATAOUIN":        "TATAOUINE","KEROUAN":        "KAIROUAN",
    "KAIROUEN":        "KAIROUAN", "MOUNASTIR":      "MONASTIR",
    "JANDOUBA":        "JENDOUBA", "BIZERT":         "BIZERTE",
    "ZAGHOUANE":       "ZAGHOUAN", "L ARIANA":       "ARIANA",
    "ARIAN":           "ARIANA",   "ARIANA NORD":    "ARIANA",
    "ARIENA":          "ARIANA",   "LA MAHDIA":      "MAHDIA",
    "TUNIS VILLE":     "TUNIS",    "GRAND TUNIS":    "TUNIS",
    "SFEX":            "SFAX",     "KEBILLI":        "KEBILI",
    "GBELLI":          "KEBILI",   "KBILI":          "KEBILI",
    "SIDI BOUSID":     "SIDI BOUZID",
    "BEJE":            "BEJA",     "JERBAR":         "MEDENINE",
    "ZAHROUNI":        "TUNIS",    "LE KRAM":        "TUNIS",
    "KRAM":            "TUNIS",
    "CITE ETTADHAMEN": "TUNIS",    "ETTADHAMEN":     "TUNIS",
    "TUNIS R P":       "TUNIS",    "SIDI HASSINE":   "TUNIS",
    "CITE EL MHIRI":   "SFAX",     "EL MHIRI":       "SFAX",
    "TINIS":           "TUNIS",    "TNUIS":          "TUNIS",
    "MENZAH 1":        "TUNIS",    "MENZAH 2":       "TUNIS",
    "MENZAH 3":        "TUNIS",    "MENZAH 4":       "TUNIS",
    "MENZAH 5":        "TUNIS",    "MENZAH 6":       "TUNIS",
    "MENZAH 7":        "TUNIS",    "MENZAH 8":       "TUNIS",
    "EL MANZAH 1":     "TUNIS",    "EL MANZAH 2":    "TUNIS",
    "EL MANZAH 3":     "TUNIS",    "EL MANZAH 4":    "TUNIS",
    "EL MANZAH 5":     "TUNIS",    "EL MANZAH 6":    "TUNIS",
    "EL MANZAH 7":     "TUNIS",    "EL MANZAH 8":    "TUNIS",
    "EL MENZAH":       "TUNIS",    "EZOUHOUR":       "TUNIS",
    "BEN AROUSS":      "BEN AROUS","BEN AROUSE":     "BEN AROUS",
    "GAFSE":           "GAFSA",    "GASFA":          "GAFSA",
    "TOZUER":          "TOZEUR",   "TOUZEUR":        "TOZEUR",
    "MANOOUBA":        "MANOUBA",  "MANAUBA":        "MANOUBA",
    "SIDI HSSINE":     "TUNIS",    "SIDI HASSENE":   "TUNIS",
    "BEJA NORD":       "BEJA",     "BEJA SUD":       "BEJA",
    "NABEUL NORD":     "NABEUL",   "NABEUL SUD":     "NABEUL",
    "KASSERINE NORD":  "KASSERINE","KASSERINE SUD":  "KASSERINE",
    "SOUSSE NORD":     "SOUSSE",   "SOUSSE SUD":     "SOUSSE",
    "SFAX NORD":       "SFAX",     "SFAX SUD":       "SFAX",
    "GABES NORD":      "GABES",    "GABES SUD":      "GABES",
}

# Codes postaux specifiques (priorite sur les plages)
_CPOST_SPECIFIC: dict[int, str] = {
    # Grande Tunis : Tunis
    2000: "TUNIS",    2001: "TUNIS",    2002: "TUNIS",
    2003: "TUNIS",    2009: "TUNIS",    2012: "TUNIS",
    2015: "TUNIS",    2016: "TUNIS",    2017: "TUNIS",
    2018: "TUNIS",    2026: "TUNIS",    2030: "TUNIS",
    2031: "TUNIS",    2035: "TUNIS",    2046: "TUNIS",
    2051: "TUNIS",    2052: "TUNIS",    2053: "TUNIS",
    2060: "TUNIS",    2062: "TUNIS",    2066: "TUNIS",
    2070: "TUNIS",    2078: "TUNIS",    2092: "TUNIS",
    2094: "TUNIS",    2100: "TUNIS",
    # Grande Tunis : Ariana
    2014: "ARIANA",   2022: "ARIANA",   2023: "ARIANA",
    2036: "ARIANA",   2037: "ARIANA",   2047: "ARIANA",
    2048: "ARIANA",   2056: "ARIANA",   2069: "ARIANA",
    2071: "ARIANA",   2073: "ARIANA",   2080: "ARIANA",
    2082: "ARIANA",   2083: "ARIANA",   2090: "ARIANA",
    # Grande Tunis : Ben Arous
    2024: "BEN AROUS",2033: "BEN AROUS",2034: "BEN AROUS",
    2040: "BEN AROUS",2042: "BEN AROUS",2043: "BEN AROUS",
    2044: "BEN AROUS",2050: "BEN AROUS",2054: "BEN AROUS",
    2063: "BEN AROUS",2064: "BEN AROUS",2065: "BEN AROUS",
    2074: "BEN AROUS",2084: "BEN AROUS",2096: "BEN AROUS",
    2099: "BEN AROUS",
    # Grande Tunis : Manouba
    2010: "MANOUBA",  2011: "MANOUBA",  2013: "MANOUBA",
    2041: "MANOUBA",
    # Nabeul
    2086: "NABEUL",   8000: "NABEUL",   8001: "NABEUL",
    8011: "NABEUL",   8030: "NABEUL",   8050: "NABEUL",
    # Tozeur
    2200: "TOZEUR",   2212: "TOZEUR",   2214: "TOZEUR",
    2223: "TOZEUR",   2243: "TOZEUR",
    # Gafsa
    2113: "GAFSA",    2115: "GAFSA",    2120: "GAFSA",
    2170: "GAFSA",
    # Bizerte
    2141: "BIZERTE",  2142: "BIZERTE",
    # Grande Tunis : Ariana (codes hors liste initiale)
    2032: "ARIANA",   2045: "ARIANA",   2058: "ARIANA",   2081: "ARIANA",
    # Grande Tunis : Ben Arous (codes hors liste initiale)
    2059: "BEN AROUS",2072: "BEN AROUS",2097: "BEN AROUS",2500: "BEN AROUS",
    # Grande Tunis : Tunis (codes hors liste initiale)
    2087: "TUNIS",    2098: "TUNIS",
    # Grande Tunis : Manouba (codes hors liste initiale)
    2067: "MANOUBA",
    # Gafsa (codes hors plage 2113-2170)
    2110: "GAFSA",    2111: "GAFSA",    2121: "GAFSA",    2130: "GAFSA",
    2151: "GAFSA",    2190: "GAFSA",
    # Tozeur (codes hors liste 2200-2243)
    2210: "TOZEUR",   2240: "TOZEUR",   2241: "TOZEUR",
    # Medenine (4100-4199)
    4100: "MEDENINE", 4110: "MEDENINE", 4111: "MEDENINE", 4114: "MEDENINE",
    4115: "MEDENINE", 4120: "MEDENINE", 4121: "MEDENINE", 4126: "MEDENINE",
    4130: "MEDENINE", 4131: "MEDENINE", 4135: "MEDENINE", 4144: "MEDENINE",
    4146: "MEDENINE", 4151: "MEDENINE", 4155: "MEDENINE", 4156: "MEDENINE",
    4160: "MEDENINE", 4164: "MEDENINE", 4165: "MEDENINE", 4170: "MEDENINE",
    4173: "MEDENINE", 4175: "MEDENINE", 4180: "MEDENINE", 4191: "MEDENINE",
    # Kebili (4200-4299)
    4200: "KEBILI",   4210: "KEBILI",   4212: "KEBILI",   4230: "KEBILI",
    4260: "KEBILI",   4264: "KEBILI",   4280: "KEBILI",
    # Jendouba
    8070: "JENDOUBA", 8080: "JENDOUBA", 8100: "JENDOUBA",
    8110: "JENDOUBA", 8130: "JENDOUBA", 8140: "JENDOUBA",
    8160: "JENDOUBA", 8170: "JENDOUBA",
    # Siliana (codes hors plage 6000-6099)
    6110: "SILIANA",  6115: "SILIANA",  6120: "SILIANA",
}

# Villes / delegations -> gouvernorat
CITY_TO_GOUVERNORAT: dict[str, str] = {
    # ── Tunis ────────────────────────────────────────────────────────────
    "LA MARSA":          "TUNIS",  "MARSA":             "TUNIS",
    "ELMARSA":           "TUNIS",  "LA MARS":           "TUNIS",
    "LAMARSA":           "TUNIS",
    "OUARDIA":           "TUNIS",  "OUERDIA":           "TUNIS",
    "OUARDIA2":          "TUNIS",  "EL OUARDIA":        "TUNIS",
    "OUERDHA":           "TUNIS",  "WARDIA":            "TUNIS",
    "AEROPORT TUNIS CARTH": "TUNIS","AEROPORT CARTHAGE":"TUNIS",
    "CARTAGHE":          "TUNIS",  "TUNIS CARTH":       "TUNIS",
    "CARTHAGE":          "TUNIS",  "CARTHAGE BYRSA":    "TUNIS",
    "TUNIS CARTHAGE":    "TUNIS",  "LA GOULETTE":       "TUNIS",
    "BARDO":             "TUNIS",  "LE BARDO":          "TUNIS",
    "LEBARDO":           "TUNIS",  "EL MENZAH":         "TUNIS",
    "EL OMRANE":         "TUNIS",  "OMRANE SUPERIEUR":  "TUNIS",
    "ENNASR":            "TUNIS",  "SIJOUMI":           "TUNIS",
    "SEJOUMI":           "TUNIS",  "SEDJOUMI":          "TUNIS",
    "EL KHADRA":         "TUNIS",  "CITE KHADRA":       "TUNIS",
    "KHAZNADAR":         "TUNIS",  "KSAR SAID":         "TUNIS",
    "K SAID":            "TUNIS",  "HRAIRIA":           "TUNIS",
    "EL HRAIRIA":        "TUNIS",  "CITE OLYMPIQUE":    "TUNIS",
    "MONTPLAISIR":       "TUNIS",  "MUTUELLEVILLE":     "TUNIS",
    "EL KABBARIA":       "TUNIS",  "KABARIA":           "TUNIS",
    "CITE IBN KHALDOUN": "TUNIS",  "IBN KHALDOUN":      "TUNIS",
    "EL MANAR":          "TUNIS",  "EL MANAR 1":        "TUNIS",
    "EL MANAR 2":        "TUNIS",  "MANAR 2":           "TUNIS",
    "SIDI BOU SAID":     "TUNIS",  "SIDI BOUSAID":      "TUNIS",
    "GAMMARTH":          "TUNIS",  "GASRINE":           "TUNIS",
    "LE KRAM":           "TUNIS",  "LE KRAM OUEST":     "TUNIS",
    "MELLASSINE":        "TUNIS",  "RAS TABIA":         "TUNIS",
    "LES BERGES DU LAC": "TUNIS",  "LAC 2":             "TUNIS",
    "ZAHROUNI":          "TUNIS",  "EZZAHROUNI":        "TUNIS",
    "CITE EZZOUHOUR":    "TUNIS",  "EZZOUHOUR":         "TUNIS",
    "SIDI HASSINE":      "TUNIS",  "ETTADHAMEN":        "TUNIS",
    "CITE ETTADHAMEN":   "TUNIS",  "AGBA":              "TUNIS",
    "CITE ETTAHRIR":     "TUNIS",  "ETTAHRIR":          "TUNIS",
    "CITE SPORTIVE":     "TUNIS",  "CITE NORMALE":      "TUNIS",
    "TUNIS R P":         "TUNIS",
    # ── Ariana ───────────────────────────────────────────────────────────
    "SOUKRA":            "ARIANA", "LA SOUKRA":         "ARIANA",
    "RAOUED":            "ARIANA", "MNIHLA":            "ARIANA",
    "EL MNIHLA":         "ARIANA", "KALAAT LANDALOUS":  "ARIANA",
    "KALAAT LANDLOUS":   "ARIANA", "SIDI THABET":       "ARIANA",
    "BORJ LOUZIR":       "ARIANA", "BORDJ LOUZIR":      "ARIANA",
    "B LOUZIR":          "ARIANA", "EL AOUINA":         "ARIANA",
    "L AOUINA":          "ARIANA", "LAOUINA":           "ARIANA",
    "AOUINA":            "ARIANA", "LAAOUINA":          "ARIANA",
    "AIN ZAGHOUAN":      "ARIANA", "AIN ZAGHOUANE":     "ARIANA",
    "CITE EL GHAZALA":   "ARIANA", "CITE EL GHAZELA":   "ARIANA",
    "EL GHAZALA":        "ARIANA", "CITE EL INTILAKA":  "ARIANA",
    "LA PETITE ARIANA":  "ARIANA", "CITE ARIANA":       "ARIANA",
    "ARIANA NORD":       "ARIANA", "CHOTRANA":          "ARIANA",
    "CHOUTRANA":         "ARIANA", "CHOTRANA 1":        "ARIANA",
    "CHOTRANA 2":        "ARIANA", "BOUHESINA":         "ARIANA",
    "EL BOUHESINA":      "ARIANA", "BORJ LOUZIR ARIANA":"ARIANA",
    "GHZALA":            "ARIANA",
    # ── Ben Arous ─────────────────────────────────────────────────────────
    "EZZAHRA":           "BEN AROUS","RADES":           "BEN AROUS",
    "ELMOUROUJ":         "BEN AROUS","ELMOUROUJ5":      "BEN AROUS",
    "EL MOUROUJ5":       "BEN AROUS","EL MOUROUJ 5":    "BEN AROUS",
    "NELL MEDINA":       "BEN AROUS","NLLE MEDINA":     "BEN AROUS",
    "RADES PLAGE":       "BEN AROUS","MEGRINE":         "BEN AROUS",
    "MORNAG":            "BEN AROUS","MORNEG":          "BEN AROUS",
    "BOU MHEL":          "BEN AROUS","BOUMHEL":         "BEN AROUS",
    "BOU MHAL":          "BEN AROUS","BOUMHAL":         "BEN AROUS",
    "HAMMAM CHOTT":      "BEN AROUS","FOUCHANA":        "BEN AROUS",
    "FOUCHENA":          "BEN AROUS","MOHAMEDIA":       "BEN AROUS",
    "NAASSEN":           "BEN AROUS","EL MOUROUJ":      "BEN AROUS",
    "EL MOUROUJ 1":      "BEN AROUS","EL MOUROUJ 2":    "BEN AROUS",
    "EL MOUROUJ 3":      "BEN AROUS","EL MOUROUJ 4":    "BEN AROUS",
    "EL MOUROUJ 5":      "BEN AROUS","EL MOUROUJ 6":    "BEN AROUS",
    "MOUROUJ":           "BEN AROUS","MOUROUJ 1":       "BEN AROUS",
    "MOUROUJ 2":         "BEN AROUS","MOUROUJ 3":       "BEN AROUS",
    "MOUROUJ 4":         "BEN AROUS","MOUROUJ 5":       "BEN AROUS",
    "HAMMAM LIF":        "BEN AROUS","BORJ CEDRIA":     "BEN AROUS",
    "SIDI REZIG":        "BEN AROUS","BIR EL BEY":      "BEN AROUS",
    "KHELIDIA":          "BEN AROUS","MORNAGUIA":       "MANOUBA",
    "CEBBALA DU MORNAG": "BEN AROUS","NOUVELLE MEDINA": "BEN AROUS",
    "NELLE MEDINA":      "BEN AROUS",
    # ── Manouba ──────────────────────────────────────────────────────────
    "TEBOURBA":          "MANOUBA", "TBORBA":           "MANOUBA",
    "DJEDEIDA":          "MANOUBA", "JEDAIDA":          "MANOUBA",
    "JDEIDA":            "MANOUBA", "JEDEIDA":          "MANOUBA",
    "EL BATTAN":         "MANOUBA", "OUED ELLIL":       "MANOUBA",
    "DOUAR HICHER":      "MANOUBA", "D HICHER":         "MANOUBA",
    "MHAMDIA":           "MANOUBA", "EL MHAMDIA":       "MANOUBA",
    "DEN DEN":           "MANOUBA", "DENDEN":           "MANOUBA",
    # ── Nabeul ───────────────────────────────────────────────────────────
    "HAMMAMET":          "NABEUL",  "KELIBIA":          "NABEUL",
    "KORBA":             "NABEUL",  "MENZEL TEMIME":    "NABEUL",
    "GROMBALIA":         "NABEUL",  "SOLIMAN":          "NABEUL",
    "MENZEL BOU ZELFA":  "NABEUL",  "MENZEL BOUZELFA":  "NABEUL",
    "BENI KHIAR":        "NABEUL",  "BENI KHALLED":     "NABEUL",
    "DAR CHAABANE":      "NABEUL",  "EL HAOUARIA":      "NABEUL",
    "TAKELSA":           "NABEUL",  "BOU ARGOUB":       "NABEUL",
    "TAZERKA":           "NABEUL",  "TAZARKA":          "NABEUL",
    "DAR CHAABANE EL FEHRI":"NABEUL","DAR CHAABENE EL FEHRI":"NABEUL",
    "BARRAKET ESSAHEL":  "NABEUL",  "EL MIDA":          "NABEUL",
    "BORJ HFAIEDH":      "NABEUL",  "BORJ HAFAIEDH":    "NABEUL",
    "BOUARGOUB":         "NABEUL",
    # ── Zaghouan ─────────────────────────────────────────────────────────
    "EL FAHS":           "ZAGHOUAN","NADHOUR":          "ZAGHOUAN",
    "ZRIBA":             "ZAGHOUAN","ZAGOUAN":          "ZAGHOUAN",
    "ZAGAOUN":           "ZAGHOUAN","ZAHOUANE":         "ZAGHOUAN",
    # ── Bizerte ──────────────────────────────────────────────────────────
    "MENZEL BOURGUIBA":  "BIZERTE", "MANZEL BOURGUIBA": "BIZERTE",
    "MATEUR":            "BIZERTE", "RAS JEBEL":        "BIZERTE",
    "SEJNANE":           "BIZERTE", "GHAR EL MELH":     "BIZERTE",
    "EL ALIA":           "BIZERTE", "MENZEL JEMIL":     "BIZERTE",
    "MENZEL ABDERRAHMANE":"BIZERTE","UTIQUE":            "BIZERTE",
    "UTIQUE NOUVELLE":   "BIZERTE", "BORJ ALI RAES":    "BIZERTE",
    "MENZEL HAYET":      "BIZERTE", "BENZARTE":         "BIZERTE",
    "ZARZOUNA":          "BIZERTE",
    # ── Beja ─────────────────────────────────────────────────────────────
    "TEBOURSOUK":        "BEJA",    "NEFZA":            "BEJA",
    "MEDJEZ EL BAB":     "BEJA",    "AIN TUNGA":        "BEJA",
    # ── Jendouba ─────────────────────────────────────────────────────────
    "AIN DRAHAM":        "JENDOUBA","FERNANA":          "JENDOUBA",
    "TABARKA":           "JENDOUBA","BALTA":            "JENDOUBA",
    "OUED MELIZ":        "JENDOUBA","OUED MLIZ":        "JENDOUBA",
    "BOU SALEM":         "JENDOUBA","BOUSALEM":         "JENDOUBA",
    "GHARDIMAOU":        "JENDOUBA",
    # ── Le Kef ───────────────────────────────────────────────────────────
    "DAHMANI":           "KEF",     "SAKIET SIDI YOUSSEF":"KEF",
    "NEBEUR":            "KEF",
    # ── Siliana ──────────────────────────────────────────────────────────
    "MAKTAR":            "SILIANA", "MAKTHAR":          "SILIANA",
    "ROUHIA":            "SILIANA", "BOU ARADA":        "SILIANA",
    "GAAFOUR":           "SILIANA", "BOUARADA":         "SILIANA",
    "BARGOU":            "SILIANA",
    # ── Sousse ───────────────────────────────────────────────────────────
    "ENFIDHA":           "SOUSSE",  "ENFIDA":           "SOUSSE",
    "MSAKEN":            "SOUSSE",  "M SAKEN":          "SOUSSE",
    "HAMMAM SOUSSE":     "SOUSSE",  "AKOUDA":           "SOUSSE",
    "KALAA KEBIRA":      "SOUSSE",  "KALAA SEGHIRA":    "SOUSSE",
    "KALAA SGHIRA":      "SOUSSE",  "KALAA ESSGHIRA":   "SOUSSE",
    "HERGLA":            "SOUSSE",  "SIDI BOU ALI":     "SOUSSE",
    "KONDAR":            "SOUSSE",  "MENZEL BEL OUAER": "SOUSSE",
    "MENZEL BELOUAER":   "SOUSSE",  "MENZEL DAR BELOUAER":"SOUSSE",
    "SOUSASSI":          "SOUSSE",  "SOUASSI":          "SOUSSE",
    "BOU FICHA":         "SOUSSE",  "BOUFICHA":         "SOUSSE",
    "SIDI HENI":         "SOUSSE",  "SIDI EL HANI":     "SOUSSE",
    "CHAT MERIEM":       "SOUSSE",  "K SGHIRA":         "SOUSSE",
    "SABAGHINE K SEGHIRA":"SOUSSE", "SABAGHINE KALAA SEGHIRA":"SOUSSE",
    # ── Monastir ─────────────────────────────────────────────────────────
    "JEMMAL":            "MONASTIR","JEMMEL":           "MONASTIR",
    "DJEMMAL":           "MONASTIR","KSAR HELLAL":      "MONASTIR",
    "KSAR HALAL":        "MONASTIR","MOKNINE":          "MONASTIR",
    "BEKALTA":           "MONASTIR","TEBOULBA":         "MONASTIR",
    "BEMBLA":            "MONASTIR","OUERDANINE":       "MONASTIR",
    "OUARDANINE":        "MONASTIR","SAHLINE":          "MONASTIR",
    "BENI HASSEN":       "MONASTIR","SIDI ALOUANE":     "MONASTIR",
    "ZERAMDINE":         "MONASTIR","ZAREMDINE":        "MONASTIR",
    "ZERAMINE":          "MONASTIR","MENZEL KAMEL":     "MONASTIR",
    "KSIBET":            "MONASTIR","KSIBET SOUSSE":    "MONASTIR",
    "KSIBET EL MEDIOUNI":"MONASTIR",
    # ── Mahdia ───────────────────────────────────────────────────────────
    "EL JEM":            "MAHDIA",  "KSOUR ESSEF":      "MAHDIA",
    "CHEBBA":            "MAHDIA",  "BOU MERDES":       "MAHDIA",
    "MELLOULECH":        "MAHDIA",  "MEHDIA":           "MAHDIA",
    # ── Sfax ─────────────────────────────────────────────────────────────
    "SAKIET ED DAIER":   "SFAX",    "SAKIET EDDAIER":   "SFAX",
    "SAKIET EL ZITE":    "SFAX",    "SAKIET EZZIT":     "SFAX",
    "SAKIET EL ZIT":     "SFAX",    "AGAREB":           "SFAX",
    "JEBENIANA":         "SFAX",    "EL AMRA":          "SFAX",
    "EL HENCHA":         "SFAX",    "MENZEL CHAKER":    "SFAX",
    "MANZEL CHAKER":     "SFAX",    "GHRAIBA":          "SFAX",
    "SKHIRA":            "SFAX",    "MAHRES":           "SFAX",
    "KERKENNAH":         "SFAX",    "CITE EL MHIRI":    "SFAX",
    "EL MHIRI":          "SFAX",    "GREMDA":           "SFAX",
    "SALTANIA":          "SFAX",    "SALTNIA":          "SFAX",
    # ── Kairouan ─────────────────────────────────────────────────────────
    "HAFFOUZ":           "KAIROUAN","CHEBIKA":          "KAIROUAN",
    "SBIKHA":            "KAIROUAN","EL ALAA":          "KAIROUAN",
    "EL OUESLATIA":      "KAIROUAN","HAJEB EL AYOUN":   "KAIROUAN",
    "NASRALLAH":         "KAIROUAN","BOUHAJLA":         "KAIROUAN",
    "AIN JLOULA":        "KAIROUAN","OUESLATIA":        "KAIROUAN",
    "HAJEB LAYOUN":      "KAIROUAN","KAIROUN":          "KAIROUAN",
    "KAIRAOIN":          "KAIROUAN","CHRARDA":          "KAIROUAN",
    # ── Kasserine ────────────────────────────────────────────────────────
    "SBEITLA":           "KASSERINE","SBIBA":           "KASSERINE",
    "SBEITA":            "KASSERINE","FERIANA":         "KASSERINE",
    "FOUSSANA":          "KASSERINE","THALA":           "KASSERINE",
    "HIDRA":             "KASSERINE","JEDILIANE":       "KASSERINE",
    "KASSERINE VILLE":   "KASSERINE","FOUSANA":         "KASSERINE",
    "GUASSRINE":         "KASSERINE","GUASSERINE":      "KASSERINE",
    "GASSERINE":         "KASSERINE","GASERINE":        "KASSERINE",
    # ── Sidi Bouzid ──────────────────────────────────────────────────────
    "REGUEB":            "SIDI BOUZID","EL MEKNASSI":  "SIDI BOUZID",
    "MEKNASSI":          "SIDI BOUZID","MEKNASSY":     "SIDI BOUZID",
    "JILMA":             "SIDI BOUZID","BIR EL HAFEY": "SIDI BOUZID",
    "SOUK JEDID":        "SIDI BOUZID","MEZZOUNA":     "SIDI BOUZID",
    "SIDI BOUZID VILLE": "SIDI BOUZID",
    # ── Gabes ────────────────────────────────────────────────────────────
    "GHANNOUCHE":        "GABES",   "GHENNOUCH":        "GABES",
    "GHANOUCH":          "GABES",   "MATMATA":          "GABES",
    "MARETH":            "GABES",   "EL METOUIA":       "GABES",
    "NOUVELLE MATMATA":  "GABES",   "BOUCHEMMA":        "GABES",
    "MERETH":            "GABES",
    # ── Medenine ─────────────────────────────────────────────────────────
    "DJERBA":            "MEDENINE","JERBA":            "MEDENINE",
    "BOUGRARA":          "MEDENINE","BOUGHRARA":        "MEDENINE",
    "DJERBA MIDOUN":     "MEDENINE","JERBA MIDOUN":     "MEDENINE",
    "JERBA HOUMT SOUK":  "MEDENINE","JERBA AJIM":       "MEDENINE",
    "MIDOUN":            "MEDENINE","ZARZIS":           "MEDENINE",
    "ZARSIS":            "MEDENINE","BEN GARDANE":      "MEDENINE",
    "BEN GUERDANE":      "MEDENINE","BEN GUERDENE":     "MEDENINE",
    "BENGARDANE":        "MEDENINE","BENGARDENE":       "MEDENINE",
    "BENGERDANE":        "MEDENINE","BENGUERDENE":      "MEDENINE",
    "BENI KHEDACHE":     "MEDENINE","BENI KHADECHE":    "MEDENINE",
    "HOUMT SOUK":        "MEDENINE","HOUMET SOUK":      "MEDENINE",
    "HOUMET ESSOUK":     "MEDENINE","H SOUK":           "MEDENINE",
    "SIDI MAKHLOUF":     "MEDENINE","SIDI MAKLOUF":     "MEDENINE",
    "AJIM":              "MEDENINE","JERBAR":           "MEDENINE",
    # Nouvelles delegations Medenine
    "KOUTINE":           "MEDENINE","METAMEUR":         "MEDENINE",
    "OUM ETTAMR":        "MEDENINE","OUM ETTAMAR":      "MEDENINE",
    "OUM ETTAMRE":       "MEDENINE","ELBAYEZ":          "MEDENINE",
    "ROUISS":            "MEDENINE","GUELLALA":         "MEDENINE",
    "BENI FETAIEL":      "MEDENINE","BENI FTEIEL":      "MEDENINE",
    "BAZIM":             "MEDENINE","EL MAY":           "MEDENINE",
    "ERRAJA":            "MEDENINE","MAHBOUBINE":       "MEDENINE",
    "SOUIHEL":           "MEDENINE","GHIZEN":           "MEDENINE",
    "GRIBIS":            "MEDENINE","EL GREBIS":        "MEDENINE",
    "EL MOUENSA":        "MEDENINE","HASSI AMOR":       "MEDENINE",
    "HESSI AMOR":        "MEDENINE","MELLITA JERBA":    "MEDENINE",
    "MELLITA":           "MEDENINE","KSAR JEDID":       "MEDENINE",
    "BENI MAAGUEL":      "MEDENINE","MEDENINE EL JEDIDA":"MEDENINE",
    "JERBA AEROPORT":    "MEDENINE","BENI KHDECHE":     "MEDENINE",
    # ── Tataouine ────────────────────────────────────────────────────────
    "REMADA":            "TATAOUINE","GHOMRASSEN":      "TATAOUINE",
    "BIR LAHMAR":        "TATAOUINE","SMAR":            "TATAOUINE",
    "TATAOUINE VILLE":   "TATAOUINE",
    # ── Gafsa ────────────────────────────────────────────────────────────
    "METLAOUI":          "GAFSA",   "METLAOUI TUNISIE": "GAFSA",
    "MOULARES":          "GAFSA",   "REDEYEF":          "GAFSA",
    "EL GUETTAR":        "GAFSA",   "SENED":            "GAFSA",
    "EL MDHILLA":        "GAFSA",   "OM LARAYES":       "GAFSA",
    "GAFSA VILLE":       "GAFSA",
    # Nouvelles localites Gafsa
    "MOULARAES":         "GAFSA",   "BOULARES":         "GAFSA",
    "LALA":              "GAFSA",   "KSAR GAFSA":       "GAFSA",
    "GAFSA GARE":        "GAFSA",   "GAFSA AEROPORT":   "GAFSA",
    "RDAIEF":            "GAFSA",
    # ── Tozeur ───────────────────────────────────────────────────────────
    "NEFTA":             "TOZEUR",  "DEGACHE":          "TOZEUR",
    "DEGUECH":           "TOZEUR",  "TAMERZA":          "TOZEUR",
    "HAZOUA":            "TOZEUR",  "TOUZEUR":          "TOZEUR",
    "TOUZEUR AEROPORT":  "TOZEUR",  "HAMMA DE DJERID":  "TOZEUR",
    "TOZEUR VILLE":      "TOZEUR",
    # ── Kebili ───────────────────────────────────────────────────────────
    "DOUZ":              "KEBILI",  "FAOUAR":           "KEBILI",
    "EL GOLAA":          "KEBILI",  "SOUK LAHAD":       "KEBILI",
    "SOUK EL AHED":      "KEBILI",  "JEMNA":            "KEBILI",
    "KEBILI VILLE":      "KEBILI",
    # Nouvelles localites Kebili
    "EL FAOUAR":         "KEBILI",  "ELFAOUAR":         "KEBILI",
    "ELFAWAR":           "KEBILI",  "LFAOUAR":          "KEBILI",
    "RJIM MAATOUG":      "KEBILI",  "RJIIM MAATOUG":    "KEBILI",
    "RJIM MATOUG":       "KEBILI",  "RJIIM MATOUG":     "KEBILI",
    "KEBILI BEYEZ":      "KEBILI",  "TOMBAR":           "KEBILI",
    # ── Ariana (nouvelles) ───────────────────────────────────────────────
    "EL NAHLI":          "ARIANA",  "ENNAHLI":          "ARIANA",
    "BORJ TOUIL":        "ARIANA",  "BORJ ETOUL":       "ARIANA",
    "RIADH EL ANDALOUS": "ARIANA",  "RIADH ANDA":       "ARIANA",
    "NKHILETTE":         "ARIANA",  "AL AOUINA":        "ARIANA",
    "ELAOUINA":          "ARIANA",  "L OUINA":          "ARIANA",
    "SIDI DAOUED":       "ARIANA",  "EL AWINA":         "ARIANA",
    "CITE MONJI SLIM":   "ARIANA",  "CITE MINJI SLIM":  "ARIANA",
    "SIDI TAHABET":      "ARIANA",
    # ── Ben Arous (nouvelles) ────────────────────────────────────────────
    "CITE HELLAL":       "BEN AROUS","CITE HELAL":      "BEN AROUS",
    "CITE HELEL":        "BEN AROUS","CT HELEL":        "BEN AROUS",
    "CTE HLAL":          "BEN AROUS","MOUROIJ":         "BEN AROUS",
    "BIR EL BAY":        "BEN AROUS","H LIF":           "BEN AROUS",
    # ── Manouba (nouvelles) ──────────────────────────────────────────────
    "OUED ELIL":         "MANOUBA", "UED ELLIL":        "MANOUBA",
    "OUEDELLIL":         "MANOUBA", "DAOUAR HICHER":    "MANOUBA",
    # ── Tunis (nouvelles) ────────────────────────────────────────────────
    "EL AGBA":           "TUNIS",   "MANAR2":           "TUNIS",
    "GAMMART":           "TUNIS",
    # ── Monastir (nouvelles) ─────────────────────────────────────────────
    "ZAOUIET SOUSSE":    "MONASTIR",
}

# Compléments DQ issus du contrôle dim_client
CITY_TO_GOUVERNORAT.update({
    # Nabeul
    "DAR CHAABANE EL FEHR":   "NABEUL",   "HAMMAM GHZEZ":          "NABEUL",
    "DAR ALLOUCHE":           "NABEUL",   "SIDI AISSA TAKELSA":    "NABEUL",
    # Tozeur
    "BLED EL HADHAR":         "TOZEUR",   "BLED ELHADHAR":         "TOZEUR",
    "EL HADHAR":              "TOZEUR",   "TAMAGHZA":              "TOZEUR",
    "DEGECH":                 "TOZEUR",   "DEGHACHE":              "TOZEUR",
    "DGECH":                  "TOZEUR",   "DGACHE":                "TOZEUR",
    "EL MAHSSEN DEGACHE":     "TOZEUR",   "ELMAHASSEN":            "TOZEUR",
    "SEDADA":                 "TOZEUR",   "HAMMA":                 "TOZEUR",
    # Kairouan
    "HAFOUZ":                 "KAIROUAN", "HAFUZ":                 "KAIROUAN",
    "ALAA EL KEBIRA":         "KAIROUAN", "SISSEB":                "KAIROUAN",
    "CHERARDA":               "KAIROUAN", "KAIRAOUEN":             "KAIROUAN",
    "KAIRAOIN":               "KAIROUAN", "KAIROUEN":              "KAIROUAN",
    # Manouba
    "OUED ELLIL":             "MANOUBA",  "OUEL ELLIL":            "MANOUBA",
    "OUED ELLILE":            "MANOUBA",  "WED ELIL":              "MANOUBA",
    "OUAD ELLIL":             "MANOUBA",  "OUAD ELIL":             "MANOUBA",
    "OUED ELILIL":            "MANOUBA",  "OUEDE ELILE":           "MANOUBA",
    "OURD ELLIL":             "MANOUBA",  "GOBAA OUED ELLIL":      "MANOUBA",
    "SANHAJA":                "MANOUBA",  "SANHAJA 2":             "MANOUBA",
    "SANHEJA":                "MANOUBA",  "SIDI BENOUR":           "MANOUBA",
    "BEJAOUA 01":             "MANOUBA",  "BEJAOUA 1":             "MANOUBA",
    "BEJAOUA 2":              "MANOUBA",  "BORJ EL AMRI":          "MANOUBA",
    "CHABAOU":                "MANOUBA",  "CHEBAOU":               "MANOUBA",
    "CHEBAO":                 "MANOUBA",  "7NOUV CHEBAOU":         "MANOUBA",
    # Ariana
    "EL GAZELLA":             "ARIANA",   "EL GAZELA":             "ARIANA",
    "CITE EL GAZELLA":        "ARIANA",   "CITE EL GAZELA":        "ARIANA",
    "SOKRA":                  "ARIANA",   "BORDJ TOUIL":           "ARIANA",
    "SIDI THEBET":            "ARIANA",   "SIDITHABET":            "ARIANA",
    "RAOUD":                  "ARIANA",   "JAAFER2":               "ARIANA",
    "JAAFER":                 "ARIANA",   "AIN ZAGHAOUAN":         "ARIANA",
    "ARIANA ECOLE":           "ARIANA",   "ENNASR 1":              "ARIANA",
    "ENNASR 2":               "ARIANA",
    # Tunis
    "ELOUARDIA":              "TUNIS",    "EL OMRAM SUPERIEUR":    "TUNIS",
    "EL OMRAN SUPERIEUR":     "TUNIS",    "CITE ETTAHRIE":         "TUNIS",
    "CITE IBN SINA":          "TUNIS",    "CT INTILAKA":           "TUNIS",
    "CITE INTILAKA":          "TUNIS",    "INTILAKA":              "TUNIS",
    "CITE TATHAMEN":          "TUNIS",    "CITE ETADHAMEN":        "TUNIS",
    "ETTADHAMEN II":          "TUNIS",    "CT TADAMEN":            "TUNIS",
    "CTE TADAMEN":            "TUNIS",    "ELKRAM":                "TUNIS",
    "KRAM OUEST":             "TUNIS",    "SALAMBO":               "TUNIS",
    "SALAMBOU":               "TUNIS",    "CARTHAGE SALAMBOU":     "TUNIS",
    "CARTHAGE BIRSA":         "TUNIS",    "CARTHAGE MED ALI":      "TUNIS",
    "CARTHAGE SALAMBO":       "TUNIS",    "BHAR LAZREG":           "TUNIS",
    "MARSA RIADH":            "TUNIS",    "MARSA ERRIADH":         "TUNIS",
    "MARSSA":                 "TUNIS",    "EL MARSSA":             "TUNIS",
    "EL MARSA":               "TUNIS",    "GAMMARTHE":             "TUNIS",
    "EL MANZAH9":             "TUNIS",    "EL MANZAH 9":           "TUNIS",
    "EL MENZAH 9":            "TUNIS",    "EL MEZAH 6":            "TUNIS",
    "EL MANZEH 6":            "TUNIS",    "EL MENZEH 6":           "TUNIS",
    "EL MENZAH6":             "TUNIS",    "MANZAH 9A":             "TUNIS",
    "MENZEH 5":               "TUNIS",    "MENZAH 6":              "TUNIS",
    "MENZAH 9":               "TUNIS",    "CITE NACER":            "TUNIS",
    "CITE NASSER":            "TUNIS",    "SIDI HASSIN":           "TUNIS",
    "SIDI HCINE":             "TUNIS",
    # Ben Arous
    "HAMMAM PLAGE":           "BEN AROUS","HAMMAM CHATT":          "BEN AROUS",
    "H CHATT":                "BEN AROUS","BIR BEY":               "BEN AROUS",
    "BIR BAY":                "BEN AROUS","BORJ SIDRIA":           "BEN AROUS",
    "BOUKORNINE":             "BEN AROUS","BOUGARNINE":            "BEN AROUS",
    "YASMINETTE":             "BEN AROUS","ELYASMINETTE":          "BEN AROUS",
    "YASMINETTE BEN AROUS":   "BEN AROUS","BENA ROUS":             "BEN AROUS",
    "MOHAMADIA":              "BEN AROUS","MOUROUJ3":              "BEN AROUS",
    "MOUROUJ 3":              "BEN AROUS",
    # Jendouba
    "GHARDIMAO":              "JENDOUBA", "GHAR EDIMA":            "JENDOUBA",
    "TBARKA":                 "JENDOUBA", "BULLARIGIA":            "JENDOUBA",
    "BENI METIR":             "JENDOUBA", "BENI MTIR":             "JENDOUBA",
    "B KHALED":               "JENDOUBA", "OUEDMLIZ":              "JENDOUBA",
    "AIN DRAHEM":             "JENDOUBA",
    # Beja
    "MZEZ EL BAB":            "BEJA",     "MJEZ EL BEB":           "BEJA",
    "MJEZ EL BAB":            "BEJA",     "TOUKEBER":              "BEJA",
    # Gafsa
    "BELKHIR":                "GAFSA",    "ELGUETTAR":             "GAFSA",
    "GTAR GAFSA":             "GAFSA",    "SIDI AICH":             "GAFSA",
    "SIDI AICH GAFSA":        "GAFSA",    "SIDI BOUBAKER":         "GAFSA",
    "SIDI BOUBAKER GAFSA":    "GAFSA",    "MDHILLA":               "GAFSA",
    "METLAOUI GAFSA":         "GAFSA",    "THALJA 2 METLAOUI":     "GAFSA",
    "REDAIEF":                "GAFSA",    "REDAYEF":               "GAFSA",
    "GAFSI":                  "GAFSA",    "ZANOUCH":               "GAFSA",
    # Kasserine
    "GASRINNE":               "KASSERINE","KASSRINE":              "KASSERINE",
    "SBITLA":                 "KASSERINE","JEUDLIENNE":            "KASSERINE",
    "JEDELIENA":              "KASSERINE",
    # Sousse
    "MSEKEN":                 "SOUSSE",   "KAALA KEBIRA":          "SOUSSE",
    # Sfax
    "CHIHIA":                 "SFAX",     "RTE DE TENIOUR CHIHIA": "SFAX",
    "RTE TENIOUR":            "SFAX",     "JEBINIANA":             "SFAX",
    "RTE MHARZA":             "SFAX",
    # Medenine
    "HOUMET TRABELSIA":       "MEDENINE", "BENGARDEN":             "MEDENINE",
    # Gabes
    "EL HAMMA GABES":         "GABES",    "EL HAMMA":              "GABES",
    # Mahdia
    "ELJEM":                  "MAHDIA",
    # Bizerte
    "M HAYET":                "BIZERTE",
})

# Pays etrangers : nom_final -> mots_cles
# Domaine pays : TUNISIE | LIBYE | ALGERIE | FRANCE | MAROC | ITALIE |
#   ALLEMAGNE | CANADA | ETATS-UNIS | BELGIQUE | ESPAGNE | SUISSE |
#   QATAR | EMIRATS | ARABIE SAOUDITE | ANGLETERRE | CHINE | UNKNOWN
FOREIGN_COUNTRIES: dict[str, list[str]] = {
    "FRANCE":          ["FRANCE", "LYON", "MARSEILLE", "BORDEAUX"],
    "ALGERIE":         ["ALGERIE", "ALGERIA", "ALGER"],
    "LIBYE":           ["LIBYE", "LYBIE", "LIBY", "LYBIA", "LIBYA", "LIBYAN"],
    "MAROC":           ["MAROC", "MOROCCO"],
    "ITALIE":          ["ITALIE", "ITALY", "ITALIA"],
    "ALLEMAGNE":       ["ALLEMAGNE", "GERMANY", "DEUTSCHLAND"],
    "CANADA":          ["CANADA"],
    "ETATS-UNIS":      ["USA", "ETATS UNIS", "UNITED STATES", "AMERIQUE"],
    "BELGIQUE":        ["BELGIQUE", "BELGIUM"],
    "ESPAGNE":         ["ESPAGNE", "SPAIN"],
    "SUISSE":          ["SUISSE", "SWITZERLAND"],
    "QATAR":           ["QATAR"],
    "EMIRATS":         ["EMIRATS", "DUBAI", "UAE"],
    "ARABIE SAOUDITE": ["ARABIE SAOUDITE", "SAUDI", "RIYAD"],
    "ANGLETERRE":      ["ANGLETERRE", "ENGLAND", "UNITED KINGDOM"],
    "CHINE":           ["CHINE", "CHINA"],
}

# Localites etrangeres connues -> (pays, localite_canonique)
# Detectees en priorite sur le simple mot-cle pays (donnent aussi la localite)
FOREIGN_CITY_MAP: dict[str, tuple[str, str]] = {
    # Libye
    "TRIPOLI":          ("LIBYE",      "TRIPOLI"),
    "TRIPOLI LIBYA":    ("LIBYE",      "TRIPOLI"),
    "TRIPOLI LIBYE":    ("LIBYE",      "TRIPOLI"),
    "TRABLES":          ("LIBYE",      "TRIPOLI"),
    "TRABLESS":         ("LIBYE",      "TRIPOLI"),
    "TRABESS":          ("LIBYE",      "TRIPOLI"),
    "TRABLESSE":        ("LIBYE",      "TRIPOLI"),
    "TRABLESSE LIBYE":  ("LIBYE",      "TRIPOLI"),
    "BENGHAZI":         ("LIBYE",      "BENGHAZI"),
    "BENIGHAZI":        ("LIBYE",      "BENGHAZI"),
    "MISURATA":         ("LIBYE",      "MISURATA"),
    "MISRATA":          ("LIBYE",      "MISURATA"),
    # Angleterre
    "LONDON":           ("ANGLETERRE", "LONDON"),
    # France
    "PARIS":            ("FRANCE",     "PARIS"),
    # Chine
    "LIAONING":         ("CHINE",      "LIAONING"),
    # Maroc
    "CASABLANCA":       ("MAROC",      "CASABLANCA"),
}

# Compléments DQ : localités UNKNOWN + variantes orthographiques supplémentaires
CITY_TO_GOUVERNORAT.update({
    # Tunis
    "KRAM GHARBI":            "TUNIS",    "OMRANE SUP":             "TUNIS",
    "EZAHROUNI":              "TUNIS",    "INTILAK":                "TUNIS",
    "SIDI HASSIN":            "TUNIS",    "SIDI HCINE":             "TUNIS",
    "EL MENZAH 5":            "TUNIS",    "EL MENZEH 5":            "TUNIS",
    "MENZEH 5":               "TUNIS",    "EL MENZAH 7":            "TUNIS",
    "MENZEH 06":              "TUNIS",    "SIDI DAOUD":             "TUNIS",
    "SIDI DAOUED":            "TUNIS",    "KAZNADAR":               "TUNIS",
    "LA LMARSA":              "TUNIS",    "RIADH LA MARSA":         "TUNIS",
    "CARTHAGE SALAMBOO":      "TUNIS",    "CARTHAGR BYRSA":         "TUNIS",
    # Ariana
    "CITE ENNASER":           "ARIANA",   "CITE ENNASSER":          "ARIANA",
    "CTE ENNARS2":            "ARIANA",   "MENZAH 6 ARIANA":        "ARIANA",
    # Ben Arous
    "MORNAGUE":               "BEN AROUS",
    # Manouba
    "MANOUBA.":               "MANOUBA",  "OUED ELLI":              "MANOUBA",
    "OUED ELILI":             "MANOUBA",  "OUEDE ELLIL":            "MANOUBA",
    "WEDRAN NORT":            "MANOUBA",  "SANHAJA OUED ELLIL":     "MANOUBA",
    "CHEBBAOU":               "MANOUBA",  "CHABBAOU":               "MANOUBA",
    "OUED ELLIL CHEBBAOU":    "MANOUBA",  "SIDI BENNOUR":           "MANOUBA",
    "SIDI BEN NOUR":          "MANOUBA",  "EL BASSATINE":           "MANOUBA",
    "SAYDA MANOUBIA":         "MANOUBA",  "CITE EL JINENE":         "MANOUBA",
    "CITE EL WARD":           "MANOUBA",  "EL WARD1":               "MANOUBA",
    "ANBAR":                  "MANOUBA",  "NEJET":                  "MANOUBA",
    "CITE NAJET":             "MANOUBA",  "CITE ENNAJET JEDAYDA":   "MANOUBA",
    "JEDAYDA":                "MANOUBA",
    # Nabeul
    "CORNICHE HAMMAMET":      "NABEUL",   "HAMMAM GHEZEZ":          "NABEUL",
    "ELMIDA":                 "NABEUL",   "FONDOUK JEDID":          "NABEUL",
    "FONDOUK JEDIDI":         "NABEUL",   "ASMAR FONDOUK JEDIDI":   "NABEUL",
    "KHANGUET HOJJAJ":        "NABEUL",
    # Sousse
    "AV BOURGUIBA ENFIDHA":   "SOUSSE",
    # Monastir
    "BELLI":                  "MONASTIR", "BEELI":                  "MONASTIR",
    "BELLI VILLAGE":          "MONASTIR", "MHEDHBA BELLI":          "MONASTIR",
    "M HEDHBA":               "MONASTIR", "MHEDHBA":                "MONASTIR",
    # Mahdia
    "KSOUR ESSAF":            "MAHDIA",
    # Sfax
    "SAKIET ED DAYER":        "SFAX",     "SAKIET EDDAYER":         "SFAX",
    "SAKIET EDDAYER 3011":    "SFAX",     "RTE LAFRANE":            "SFAX",
    "RTE DE LAFRANE":         "SFAX",     "RTE DE LAFRANE KM 6.5":  "SFAX",
    "RTE LAFRANE KM 7":       "SFAX",     "RTE EL AIN":             "SFAX",
    "RTE EL AIN KM 2":        "SFAX",     "RTE DE TENIOUR":         "SFAX",
    "COMPUS SPORTIVES CSS":   "SFAX",     "MAJIDA BOULILA":         "SFAX",
    # Kairouan
    "HAJEB ELAYOUN":          "KAIROUAN", "AIN JALOULA":            "KAIROUAN",
    "NAHALLA AIN JALOULA":    "KAIROUAN", "RACCADA":                "KAIROUAN",
    # Sidi Bouzid
    "SIDI BOUZD":             "SIDI BOUZID","CITE NOUR SERS":       "SIDI BOUZID",
    "SERS":                   "SIDI BOUZID","FRAYOU HECHRIA":        "SIDI BOUZID",
    # Gafsa
    "NEFFTA":                 "TOZEUR",
    # Jendouba
    "GHAR DIMA":              "JENDOUBA",
})

# Variantes localités étrangères vues dans le DQ
FOREIGN_CITY_MAP.update({
    "TRIPOLIE":               ("LIBYE", "TRIPOLI"),
    "LYBIA TRABLES":          ("LIBYE", "TRIPOLI"),
    "TRABLES LIBYA":          ("LIBYE", "TRIPOLI"),
    "TRABLESS LIBYA":         ("LIBYE", "TRIPOLI"),
    "TRABESS LIBYA":          ("LIBYE", "TRIPOLI"),
    "TRABLESSE LIBYA":        ("LIBYE", "TRIPOLI"),
})

# Mots-cles personne morale
_MORALE_KEYWORDS_RE = re.compile(
    r"\b(?:SOCIETE|STE|SARL|SUARL|ENTREPRISE|ETABLISSEMENT|"
    r"ORGANISME|BANQUE|ASSURANCE|ADMINISTRATION|MINISTERE|"
    r"MUNICIPALITE|COMMUNE|ASSOCIATION)\b"
    r"|\bSA\b|S\.A\.?"
)

# Mots de voirie : filtre faux-etrangers (RUE D ALGERIE, AV ESPAGNE…)
_STREET_RE = re.compile(
    r"\b(?:RUE|R|AV|AVE|AVENUE|IMPASSE|IMP|BD|BLVD|BOULEVARD|"
    r"CHEMIN|ROUTE|RTE|PASSAGE|ALLEE|PLACE|SQUARE|LOTISSEMENT|LOT|"
    r"IMMEUBLE|IMM|BATIMENT|BAT|VILLA|CITE|CTE|RESIDENCE|RES|"
    r"ZI|ZA|QUARTIER|ZONE|CAFE|RESTAURANT|LIBRAIRIE|LIBRERIE|"
    r"ECOLE|LYCEE|COLLEGE|LOCAL|MAGASIN|BOULANGERIE)\b"
)

# Pre-compiled combined patterns — built once at module load.
# Sorting longest-first ensures "BEN AROUS" is tried before "AROUS" in alternation.
_GOUVERNORATS_RE = re.compile(
    r"\b(" + "|".join(re.escape(g) for g in sorted(GOUVERNORATS, key=len, reverse=True)) + r")\b"
)
_ALIASES_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in sorted(GOUVERNORAT_ALIASES, key=len, reverse=True)) + r")\b"
)
_CITIES_LONG_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(c)
        for c in sorted((k for k in CITY_TO_GOUVERNORAT if len(k) >= 5), key=len, reverse=True)
    ) + r")\b"
)
_FOREIGN_CITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in sorted(FOREIGN_CITY_MAP, key=len, reverse=True)) + r")\b"
)
_FOREIGN_KW_MAP: dict[str, str] = {
    kw: country
    for country, keywords in FOREIGN_COUNTRIES.items()
    for kw in keywords
}
_FOREIGN_COUNTRY_RE = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in sorted(_FOREIGN_KW_MAP, key=len, reverse=True)) + r")\b"
)


# ---------------------------------------------------------------------------
# Helpers texte
# ---------------------------------------------------------------------------
def _normalize_text(raw) -> str | None:
    if pd.isna(raw):
        return None
    s = str(raw).strip()
    if not s or s.upper() in ("NAN", "NONE", "NULL", "0"):
        return None
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = re.sub(r"['''\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s else None


def _norm_to_gouvernorat(norm) -> str | None:
    if not isinstance(norm, str) or not norm:
        return None
    if norm in GOUVERNORATS:
        return norm
    return GOUVERNORAT_ALIASES.get(norm)


def _norm_to_city(norm) -> str | None:
    if not isinstance(norm, str) or not norm:
        return None
    return CITY_TO_GOUVERNORAT.get(norm)


def _detect_foreign_naive(norm) -> str | None:
    """Detection naive sans filtre voirie (pour calcul des evites)."""
    if not isinstance(norm, str) or not norm:
        return None
    m = _FOREIGN_COUNTRY_RE.search(norm)
    return _FOREIGN_KW_MAP[m.group(1)] if m else None


def _detect_foreign_country(norm) -> str | None:
    """Detecte un pays etranger avec filtre voirie."""
    if not isinstance(norm, str) or not norm:
        return None
    has_street = bool(_STREET_RE.search(norm))
    for match in _FOREIGN_COUNTRY_RE.finditer(norm):
        if not has_street:
            return _FOREIGN_KW_MAP[match.group(1)]
        prefix = norm[max(0, match.start() - 50):match.start()]
        if not _STREET_RE.search(prefix):
            return _FOREIGN_KW_MAP[match.group(1)]
    return None


def _detect_foreign_city(norm) -> tuple[str, str] | None:
    """
    Detecte une localite etrangere connue avec filtre voirie.
    Retourne (pays, localite_canonique) ou None.
    Prioritaire sur _detect_foreign_country (donne aussi la localite).
    """
    if not isinstance(norm, str) or not norm:
        return None
    has_street = bool(_STREET_RE.search(norm))
    for match in _FOREIGN_CITY_RE.finditer(norm):
        if not has_street:
            return FOREIGN_CITY_MAP[match.group(1)]
        prefix = norm[max(0, match.start() - 50):match.start()]
        if not _STREET_RE.search(prefix):
            return FOREIGN_CITY_MAP[match.group(1)]
    return None


def _infer_gouvernor_from_cpost(cpost_raw) -> str | None:
    try:
        cp = int(str(cpost_raw).strip().split(".")[0])
    except (ValueError, TypeError, AttributeError):
        return None
    if cp <= 0:
        return None
    if cp in _CPOST_SPECIFIC:
        return _CPOST_SPECIFIC[cp]
    if 1000 <= cp < 1100: return "TUNIS"
    if 1100 <= cp < 1200: return "ZAGHOUAN"
    if 1200 <= cp < 1300: return "KASSERINE"
    if 3000 <= cp < 3100: return "SFAX"
    if 3100 <= cp < 3200: return "KAIROUAN"
    if 3200 <= cp < 3400: return "SFAX"
    if 4000 <= cp < 4100: return "SOUSSE"
    if 4100 <= cp < 4200: return "MEDENINE"
    if 4200 <= cp < 4300: return "KEBILI"
    if 5000 <= cp < 5100: return "MONASTIR"
    if 5100 <= cp < 5400: return "MAHDIA"
    if 6000 <= cp < 6100: return "SILIANA"
    if 6100 <= cp < 6500: return "GABES"
    if 6500 <= cp < 6800: return "MEDENINE"
    if 6800 <= cp < 7000: return "TATAOUINE"
    if 7000 <= cp < 7100: return "BIZERTE"
    if 7100 <= cp < 7200: return "KEF"
    if 7200 <= cp < 7600: return "BEJA"
    if 7600 <= cp < 7800: return "JENDOUBA"
    if 8000 <= cp < 8100: return "NABEUL"
    if 9000 <= cp < 9100: return "BEJA"
    if 9100 <= cp < 9300: return "SIDI BOUZID"
    if 9400 <= cp < 9600: return "GAFSA"
    if 9600 <= cp < 9700: return "TOZEUR"
    if 9700 <= cp < 9900: return "KEBILI"
    return None


def _search_text_for_gouvernorat(norm) -> str | None:
    """Substring search dans un texte normalise (pour adr1)."""
    if not isinstance(norm, str) or not norm:
        return None
    m = _GOUVERNORATS_RE.search(norm)
    if m:
        return m.group(1)
    m = _ALIASES_RE.search(norm)
    if m:
        return GOUVERNORAT_ALIASES[m.group(1)]
    m = _CITIES_LONG_RE.search(norm)
    if m:
        return CITY_TO_GOUVERNORAT[m.group(1)]
    return None


_VALID_TN_CPOST_RE = re.compile(r"\b([1-9][0-9]{3})\b")


def _extract_cpost_from_text(text: str | None) -> str | None:
    """Extrait un code postal tunisien à 4 chiffres depuis un texte (adr1/cite)."""
    if not isinstance(text, str) or not text:
        return None
    for m in _VALID_TN_CPOST_RE.finditer(text):
        cp = int(m.group(1))
        if 1000 <= cp <= 9999:
            return m.group(1)
    return None


def _find_tunisian_locality(norm: str | None) -> str | None:
    """
    Retourne le nom canonique de la localité tunisienne trouvée dans norm
    (clé de CITY_TO_GOUVERNORAT), ou None.
    Priorité : correspondance exacte > sous-chaîne via regex pré-compilée.
    """
    if not isinstance(norm, str) or not norm:
        return None
    if norm in CITY_TO_GOUVERNORAT:
        return norm
    m = _CITIES_LONG_RE.search(norm)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Resolution geographique centrale
#
# Domaine gouvernor : 24 gouvernorats TN | HORS_TUNISIE | UNKNOWN
# Jamais de nom de pays dans gouvernor.
#
# Priorite :
#   1. Gouvernorat TN explicite (col gouvernor, cite, adr1)
#   2. Localite TN connue (cite puis adr1)
#   3. Localite etrangere connue  <-- bat le cpost
#   4. Code postal TN fiable
#   5. Mot-cle pays etranger avec filtre voirie
#   6. UNKNOWN
# ---------------------------------------------------------------------------
def _resolve_geography(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, dict]:
    """Retourne (gouvernor, pays, localite, stats)."""
    idx = df.index

    def _nc(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series(None, index=idx, dtype=object)
        return df[col].map(_normalize_text)

    cite_norm = _nc("cite")
    adr1_norm = _nc("adr1")

    # Localités TN canoniques détectées (pour localite_out)
    loc_tn_from_cite = cite_norm.map(_find_tunisian_locality)
    loc_tn_from_adr1 = adr1_norm.map(_find_tunisian_locality)
    loc_tn_detected  = loc_tn_from_cite.combine_first(loc_tn_from_adr1)

    # ── Signal TN : colonne gouvernor ─────────────────────────────────────
    tn_from_gov  = pd.Series(None, index=idx, dtype=object)
    gov_col_norm = pd.Series(None, index=idx, dtype=object)
    for col in ("gouvernor_enriched", "gouvernor_original", "gouvernor"):
        if col in df.columns:
            normed = df[col].map(_normalize_text)
            gov_col_norm = gov_col_norm.combine_first(normed)
            candidate = (normed.map(_norm_to_gouvernorat)
                               .combine_first(normed.map(_norm_to_city)))
            tn_from_gov = tn_from_gov.combine_first(candidate)

    # ── Signal TN : cite ──────────────────────────────────────────────────
    tn_from_cite = (cite_norm.map(_norm_to_gouvernorat)
                             .combine_first(cite_norm.map(_norm_to_city)))

    # ── Signal TN : adr1 (substring) ─────────────────────────────────────
    tn_from_adr1 = adr1_norm.map(_search_text_for_gouvernorat)

    # ── Signal TN : cpost ─────────────────────────────────────────────────
    cpost_raw    = df["cpost"] if "cpost" in df.columns else pd.Series(None, index=idx)
    tn_from_cpost = cpost_raw.map(_infer_gouvernor_from_cpost)

    # ── Signal etranger : localite connue (bat le cpost) ──────────────────
    fc_cite     = cite_norm.map(_detect_foreign_city)
    fc_adr1     = adr1_norm.map(_detect_foreign_city)
    foreign_city = fc_cite.combine_first(fc_adr1)
    fc_pays      = foreign_city.map(lambda x: x[0] if isinstance(x, tuple) else None)
    fc_localite  = foreign_city.map(lambda x: x[1] if isinstance(x, tuple) else None)

    # ── Signal etranger : mot-cle pays avec filtre voirie ─────────────────
    fk_cite    = cite_norm.map(_detect_foreign_country)
    fk_adr1    = adr1_norm.map(_detect_foreign_country)
    fk_gov     = gov_col_norm.map(_detect_foreign_country)
    foreign_kw = fk_cite.combine_first(fk_adr1).combine_first(fk_gov)

    # ── Masks de decision (mutuellement exclusifs) ────────────────────────
    tn_explicit = (tn_from_gov.combine_first(tn_from_cite)
                              .combine_first(tn_from_adr1))
    m_tn_exp = tn_explicit.notna()
    m_fc     = ~m_tn_exp & fc_pays.notna()
    m_cpost  = ~m_tn_exp & ~m_fc & tn_from_cpost.notna()
    m_fk     = ~m_tn_exp & ~m_fc & ~m_cpost & foreign_kw.notna()

    # ── Construction des series resultat ──────────────────────────────────
    gov_out  = pd.Series("UNKNOWN", index=idx, dtype=object)
    pays_out = pd.Series("UNKNOWN", index=idx, dtype=object)
    loc_out  = pd.Series("UNKNOWN", index=idx, dtype=object)

    if "cite" in df.columns:
        cite_clean = (df["cite"].astype(str).str.strip().str.upper()
                      .where(df["cite"].notna()))
        cite_clean = cite_clean.where(
            cite_clean.notna() & (cite_clean != "NAN") & (cite_clean.str.len() > 0)
        )
    else:
        cite_clean = pd.Series(None, index=idx, dtype=object)

    # 1. TN explicite (gouvernorat ou localite TN dans gouvernor/cite/adr1)
    gov_out[m_tn_exp]  = tn_explicit[m_tn_exp]
    pays_out[m_tn_exp] = "TUNISIE"
    loc_out[m_tn_exp]  = loc_tn_detected[m_tn_exp].combine_first(cite_clean[m_tn_exp]).fillna("UNKNOWN")

    # 2. Localite etrangere connue (bat cpost)
    gov_out[m_fc]  = "HORS_TUNISIE"
    pays_out[m_fc] = fc_pays[m_fc]
    loc_out[m_fc]  = fc_localite[m_fc].fillna("UNKNOWN")

    # 3. Code postal TN fiable
    gov_out[m_cpost]  = tn_from_cpost[m_cpost]
    pays_out[m_cpost] = "TUNISIE"
    loc_out[m_cpost]  = loc_tn_detected[m_cpost].combine_first(cite_clean[m_cpost]).fillna("UNKNOWN")

    # 4. Mot-cle pays etranger
    gov_out[m_fk]  = "HORS_TUNISIE"
    pays_out[m_fk] = foreign_kw[m_fk]
    loc_out[m_fk]  = "UNKNOWN"

    # ── Statistiques ──────────────────────────────────────────────────────
    from_gov_m  = m_tn_exp & tn_from_gov.notna()
    from_cite_m = m_tn_exp & tn_from_gov.isna() & tn_from_cite.notna()
    from_adr1_m = m_tn_exp & tn_from_gov.isna() & tn_from_cite.isna() & tn_from_adr1.notna()

    naive_cite  = cite_norm.map(_detect_foreign_naive)
    naive_adr1  = adr1_norm.map(_detect_foreign_naive)
    had_foreign = (fc_pays.notna() | fk_cite.notna() | fk_adr1.notna()
                   | naive_cite.notna() | naive_adr1.notna())
    n_avoided_tn     = int((m_tn_exp & had_foreign).sum())
    n_avoided_street = int(
        ((naive_cite.notna() & fk_cite.isna() & fc_cite.isna()) |
         (naive_adr1.notna() & fk_adr1.isna() & fc_adr1.isna())).sum()
    )

    # Top 30 valeurs UNKNOWN
    still_unknown = gov_out == "UNKNOWN"
    unresolved_samples: list[str] = []
    if still_unknown.any():
        candidates: list[tuple[int, str]] = []
        for col in ("gouvernor", "cite"):
            if col in df.columns:
                top = (
                    df.loc[still_unknown, col]
                    .dropna().astype(str).str.strip().str.upper()
                    .replace("", pd.NA).dropna()
                    .value_counts().head(15)
                )
                for val, cnt in top.items():
                    candidates.append((int(cnt), f"[{col}] {val}"))
        candidates.sort(reverse=True)
        unresolved_samples = [v for _, v in candidates[:30]]

    # Top pays etrangers et localites etrangeres
    mask_hors    = gov_out == "HORS_TUNISIE"
    top_pays_etr: dict = {}
    top_loc_etr:  dict = {}
    if mask_hors.any():
        top_pays_etr = pays_out[mask_hors].value_counts().head(20).to_dict()
        locs = loc_out[mask_hors & (loc_out != "UNKNOWN")]
        if len(locs):
            top_loc_etr = locs.value_counts().head(20).to_dict()

    stats = {
        "from_gov":                int(from_gov_m.sum()),
        "from_cite":               int(from_cite_m.sum()),
        "from_adr1":               int(from_adr1_m.sum()),
        "from_cpost":              int(m_cpost.sum()),
        "n_avoided_false_foreign": n_avoided_tn + n_avoided_street,
        "unresolved_samples":      unresolved_samples,
        "top_pays_etranger":       top_pays_etr,
        "top_localite_etranger":   top_loc_etr,
    }

    return gov_out, pays_out, loc_out, stats


# ---------------------------------------------------------------------------
# Autres helpers
# ---------------------------------------------------------------------------
def _first_col(df: pd.DataFrame, candidates: list[str]) -> pd.Series | None:
    for col in candidates:
        if col in df.columns:
            return df[col]
    return None


def _clean_text_col(series: pd.Series) -> pd.Series:
    result = series.astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    return result.where((result.str.len() > 0) & (result != "nan"))


def _build_idclt(df: pd.DataFrame) -> pd.Series:
    """
    Construit la clé client utilisée pour les jointures DWH.

    dim_contrat.idclt = numpers seul (ex: 1813284).
    dim_client.idclt doit être identique pour que la jointure fonctionne.
    L'ancienne clé CL|1813284 n'est pas utilisée comme clé de jointure.
    """
    _blanks = {"NAN", "NONE", "NULL", "0", "0.0"}

    # Priorité 1 : numpers_norm
    for col in ("numpers_norm", "numpers"):
        if col in df.columns:
            s = df[col].astype(str).str.strip()
            s = s.where(s.notna() & (s.str.len() > 0) & (~s.str.upper().isin(_blanks)))
            return s.str.replace(r"\.0$", "", regex=True)

    # Fallback : client_key de type CL|1813284 — on retire le préfixe
    if "client_key" in df.columns:
        s = df["client_key"].astype(str).str.strip()
        s = s.str.replace(r"^[A-Z]+\|", "", regex=True)
        return s.where(s.notna() & (s.str.len() > 0) & (~s.str.upper().isin(_blanks)))

    return pd.Series(pd.NA, index=df.index, dtype=object)


def _build_date_naissance(df: pd.DataFrame) -> pd.Series:
    raw = _first_col(df, ["date_naissance", "datnais", "datenais", "date_nais", "date_naiss"])
    if raw is None:
        return pd.Series(pd.NaT, index=df.index)
    parsed = pd.to_datetime(raw, errors="coerce", dayfirst=True)
    cutoff_min = pd.Timestamp(TODAY.year - 110, TODAY.month, TODAY.day)
    cutoff_max = pd.Timestamp(TODAY)
    return parsed.where(parsed >= cutoff_min).where(parsed <= cutoff_max)


def _build_sexe(df: pd.DataFrame) -> pd.Series:
    raw = _first_col(df, ["sexe", "sex", "gender"])
    if raw is None:
        return pd.Series("UNKNOWN", index=df.index)
    normed = raw.astype(str).str.strip().str.upper()
    result = pd.Series("UNKNOWN", index=df.index, dtype=object)
    result[normed.isin(["M", "MASCULIN", "MALE"])]  = "M"
    result[normed.isin(["F", "FEMININ", "FEMALE"])] = "F"
    return result


def _build_nombre_enfant(df: pd.DataFrame) -> pd.Series:
    raw = _first_col(df, ["nbenfant", "nb_enfant", "nb_enfants", "nombre_enfant", "nbrenf"])
    if raw is None:
        return pd.Series(pd.NA, index=df.index, dtype="Int64")
    num = pd.to_numeric(raw, errors="coerce")
    return num.where(num >= 0).where(num <= 20).astype("Int64")


def determiner_nature_client(df: pd.DataFrame) -> tuple[pd.Series, dict]:
    result = pd.Series("PERSONNE_PHYSIQUE", index=df.index, dtype=object)

    def _blank(col: str, blanks: set[str]) -> pd.Series:
        if col not in df.columns:
            return pd.Series(True, index=df.index)
        return df[col].astype(str).str.strip().str.upper().isin(blanks)

    blank_vals = {"X", "UNKNOWN", "NAN", "NONE", ""}
    sexe_blank = _blank("sexe", blank_vals)
    sit_blank  = _blank("situation_familiale", blank_vals)
    dob_null   = df["date_naissance"].isna() if "date_naissance" in df.columns else pd.Series(True, index=df.index)
    enf_null   = (df["nombre_enfant"].isna() | (df["nombre_enfant"] == 0)) if "nombre_enfant" in df.columns else pd.Series(True, index=df.index)

    mask_rule2 = sexe_blank & dob_null & enf_null & sit_blank
    result[mask_rule2] = "PERSONNE_MORALE"

    raw_label  = _first_col(df, ["client_nature_label", "nature_label"])
    mask_rule1 = pd.Series(False, index=df.index)
    if raw_label is not None:
        normed = raw_label.map(_normalize_text).fillna("")
        mask_rule1 = normed.str.contains(_MORALE_KEYWORDS_RE, na=False)
        result[mask_rule1] = "PERSONNE_MORALE"

    stats = {
        "n_personne_physique": int((result == "PERSONNE_PHYSIQUE").sum()),
        "n_personne_morale":   int((result == "PERSONNE_MORALE").sum()),
        "n_morale_rule1":      int(mask_rule1.sum()),
        "n_morale_rule2":      int(mask_rule2.sum()),
    }
    return result, stats


def _build_situation_familiale(df: pd.DataFrame) -> pd.Series:
    raw = _first_col(df, ["situation_familiale", "sitfam", "etat_civil", "situafami"])
    if raw is None:
        return pd.Series("UNKNOWN", index=df.index)
    normed = raw.astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True)
    return normed.where(
        (normed.str.len() > 0) & (normed != "NAN") & (normed != "NONE"),
        other="UNKNOWN",
    )


# ---------------------------------------------------------------------------
# Transformation principale
# ---------------------------------------------------------------------------
def transform_dim_client(df_raw: pd.DataFrame, logger) -> tuple[pd.DataFrame, dict]:
    n_raw = len(df_raw)
    logger.info(f"  Lignes lues depuis {SOURCE_TABLE} : {n_raw}")

    df = df_raw.copy()

    # 1. Cle client
    df["idclt"] = _build_idclt(df)
    n_null_key = int(df["idclt"].isna().sum())
    if n_null_key:
        logger.warning(f"  {n_null_key} lignes sans idclt supprimees")
        df = df[df["idclt"].notna()].copy()

    # 2. Deduplication
    n_before = len(df)
    df["_completeness"] = df.notna().sum(axis=1)
    df = (
        df.sort_values(["idclt", "_completeness"], ascending=[True, False])
        .drop_duplicates(subset=["idclt"], keep="first")
        .drop(columns=["_completeness"])
        .reset_index(drop=True)
    )
    n_dupes = n_before - len(df)
    if n_dupes:
        logger.info(f"  Doublons supprimes : {n_dupes}")

    # 3. Identite
    if "typeid" not in df.columns:
        df["typeid"] = None
    # Staging stocke la pièce d'identité sous "id" — renommée "id_piece" dans le DWH
    if "id" in df.columns:
        df["id_piece"] = df["id"]
    elif "id_piece" not in df.columns:
        df["id_piece"] = None

    # 4. Adresse
    for col in ("adr1", "cite"):
        if col in df.columns:
            df[col] = _clean_text_col(df[col])
        else:
            df[col] = None

    if "cpost" in df.columns:
        cleaned = _clean_text_col(df["cpost"])
        df["cpost"] = cleaned.where(~cleaned.isin({"0", "0.0", "-", "."}))
    else:
        df["cpost"] = None

    # Compléter cpost depuis adr1/cite si vide (vectorisé)
    combined_addr = df["adr1"].fillna("") + " " + df["cite"].fillna("")
    cpost_from_text = combined_addr.str.extract(r"\b([1-9][0-9]{3})\b", expand=False)
    df["cpost"] = df["cpost"].fillna(cpost_from_text)

    # Si cite est vide, enrichir depuis adr1 quand une localité TN y est détectée
    adr1_norm_tmp = df["adr1"].map(_normalize_text)
    loc_from_adr1 = adr1_norm_tmp.map(_find_tunisian_locality)
    cite_norm_tmp = df["cite"].map(_normalize_text)
    cite_missing  = cite_norm_tmp.isna() | cite_norm_tmp.isin({"", "-", ".", "UNKNOWN"})
    df.loc[cite_missing & loc_from_adr1.notna(), "cite"] = \
        loc_from_adr1[cite_missing & loc_from_adr1.notna()]

    # 5. Geographie : gouvernor + pays + localite
    df["gouvernor"], df["pays"], df["localite"], geo_stats = _resolve_geography(df)

    # 6. Date de naissance
    df["date_naissance"] = _build_date_naissance(df)

    # 7. Sexe
    df["sexe"] = _build_sexe(df)

    # 8. Nombre d'enfants
    df["nombre_enfant"] = _build_nombre_enfant(df)

    # 9. Situation familiale
    df["situation_familiale"] = _build_situation_familiale(df)

    # 10. Nature client
    df["nature_client"], nc_stats = determiner_nature_client(df)

    # 11. Colonnes techniques
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"]    = TODAY

    # 12. Cle substitut DWH
    df = df.reset_index(drop=True)
    df.insert(0, "client_sk", range(1, len(df) + 1))

    # 13. Selection colonnes finales
    final_cols = [
        "client_sk", "idclt", "typeid", "id_piece",
        "nature_client",
        "adr1", "cpost", "cite", "gouvernor", "pays", "localite",
        "date_naissance", "sexe", "nombre_enfant", "situation_familiale",
        "source_system", "created_at",
    ]
    for col in final_cols:
        if col not in df.columns:
            df[col] = None

    # 14. Ligne technique UNKNOWN (client_sk = 0)
    # fact_sinistre et fact_contrat référencent client_sk = 0 quand le client
    # source est introuvable. Cette ligne doit toujours exister dans dim_client.
    unknown_row = pd.DataFrame([{
        "client_sk":           0,
        "idclt":               "UNKNOWN",
        "typeid":              None,
        "id_piece":            None,
        "nature_client":       "UNKNOWN",
        "adr1":                None,
        "cpost":               None,
        "cite":                None,
        "gouvernor":           "UNKNOWN",
        "pays":                "UNKNOWN",
        "localite":            "UNKNOWN",
        "date_naissance":      pd.NaT,
        "sexe":                "UNKNOWN",
        "nombre_enfant":       None,
        "situation_familiale": None,
        "source_system":       "TECHNICAL",
        "created_at":          TODAY,
    }])
    df = pd.concat([unknown_row[final_cols], df[final_cols]], ignore_index=True)
    df["client_sk"] = df["client_sk"].astype("int64")

    n_tn      = int((df["pays"] == "TUNISIE").sum())
    n_hors    = int((df["gouvernor"] == "HORS_TUNISIE").sum())
    n_unk_gov = int((df["gouvernor"] == "UNKNOWN").sum())
    n_etr_pays = int(((df["pays"] != "TUNISIE") & (df["pays"] != "UNKNOWN")).sum())
    n_loc_unk = int((df["localite"] == "UNKNOWN").sum())

    metrics = {
        "n_raw":                 n_raw,
        "n_null_key":            n_null_key,
        "n_dupes":               n_dupes,
        "n_loaded":              len(df),
        "n_personne_physique":   nc_stats["n_personne_physique"],
        "n_personne_morale":     nc_stats["n_personne_morale"],
        "n_morale_rule1":        nc_stats["n_morale_rule1"],
        "n_morale_rule2":        nc_stats["n_morale_rule2"],
        "n_gov_tunisie":         n_tn,
        "n_gov_hors_tunisie":    n_hors,
        "n_gov_unknown":         n_unk_gov,
        "n_pays_etranger":       n_etr_pays,
        "n_loc_unknown":         n_loc_unk,
        "gov_from_gov":          geo_stats["from_gov"],
        "gov_from_cite":         geo_stats["from_cite"],
        "gov_from_adr1":         geo_stats["from_adr1"],
        "gov_from_cpost":        geo_stats["from_cpost"],
        "n_avoided_false_foreign": geo_stats["n_avoided_false_foreign"],
        "gov_unresolved":        geo_stats["unresolved_samples"],
        "top_pays_etranger":     geo_stats["top_pays_etranger"],
        "top_localite_etranger": geo_stats["top_localite_etranger"],
        "n_sexe_unknown":        int((df["sexe"] == "UNKNOWN").sum()),
        "n_dob_null":            int(df["date_naissance"].isna().sum()),
        "n_enf_null":            int(df["nombre_enfant"].isna().sum()),
    }

    return df[final_cols], metrics


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
def load_dim_client(run_id: str, engine, logger) -> dict:
    logger.info(f"[READ] {SOURCE_TABLE}")
    df_raw = pd.read_sql(f"SELECT * FROM {SOURCE_TABLE}", engine)

    df_final, metrics = transform_dim_client(df_raw, logger)

    _, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)
    metrics["elapsed"] = elapsed

    return metrics


# ---------------------------------------------------------------------------
# Point d'entree
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_dim_client")
    engine = dwh_utils.build_engine(logger)
    dwh_utils.create_dwh_schema(engine, logger)

    m = load_dim_client(run_id, engine, logger)

    logger.info("=" * 60)
    logger.info("dwh.dim_client loaded successfully")
    logger.info(f"  lignes staging lues    : {m['n_raw']}")
    logger.info(f"  clients charges (DWH)  : {m['n_loaded']}")
    logger.info(f"  doublons supprimes     : {m['n_dupes']}")
    logger.info("  -- nature client --")
    logger.info(f"  PERSONNE_PHYSIQUE      : {m['n_personne_physique']}")
    logger.info(f"  PERSONNE_MORALE        : {m['n_personne_morale']}")
    logger.info(f"    dont nature source   : {m['n_morale_rule1']}")
    logger.info(f"    dont absence info    : {m['n_morale_rule2']}")
    logger.info("  -- geographie --")
    logger.info(f"  pays = TUNISIE         : {m['n_gov_tunisie']}")
    logger.info(f"  pays etranger          : {m['n_pays_etranger']}")
    logger.info(f"  pays = UNKNOWN         : {m['n_gov_unknown']}")
    logger.info(f"  gouvernor = HORS_TUNISIE: {m['n_gov_hors_tunisie']}")
    logger.info(f"  gouvernor = UNKNOWN    : {m['n_gov_unknown']}")
    logger.info(f"  localite = UNKNOWN     : {m['n_loc_unknown']}")
    logger.info(f"  depuis col gouvernor   : {m['gov_from_gov']}")
    logger.info(f"  depuis cite            : {m['gov_from_cite']}")
    logger.info(f"  depuis adr1            : {m['gov_from_adr1']}")
    logger.info(f"  depuis cpost           : {m['gov_from_cpost']}")
    logger.info(f"  faux etrangers evites  : {m['n_avoided_false_foreign']}")
    if m["top_pays_etranger"]:
        logger.info("  -- top pays etrangers --")
        for p, cnt in m["top_pays_etranger"].items():
            logger.info(f"    {p:<20} : {cnt}")
    if m["top_localite_etranger"]:
        logger.info("  -- top localites etrangeres --")
        for loc, cnt in m["top_localite_etranger"].items():
            logger.info(f"    {loc:<20} : {cnt}")
    if m["gov_unresolved"]:
        logger.info("  -- top 30 valeurs UNKNOWN --")
        for s in m["gov_unresolved"]:
            logger.info(f"    {s}")
    logger.info("  -- autres --")
    logger.info(f"  sexe UNKNOWN           : {m['n_sexe_unknown']}")
    logger.info(f"  date_naissance NULL    : {m['n_dob_null']}")
    logger.info(f"  nombre_enfant NULL     : {m['n_enf_null']}")
    logger.info(f"  duree                  : {m['elapsed']:.1f}s")
    logger.info("=" * 60)
