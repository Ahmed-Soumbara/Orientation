"""Connecteurs vers les sources publiques qui remplacent les valeurs écrites à la main.

Chaque source a :
  - une fonction fetch_xxx() qui télécharge et enregistre un fichier propre dans data/ ;
  - une fonction parse_xxx() pure (testable sans réseau) ;
  - une entrée dans SOURCES, utilisée par refresh_all() et status().

À lancer par un job (python data.py), jamais à chaque connexion d'un élève.
Si une source échoue, l'application garde ses valeurs de secours et le signale.

Diagnostic :  python sources.py --check   (affiche les colonnes reçues de chaque source,
              pour ajuster les noms de colonnes si un producteur les change)
"""
import io, json, os, re, sys, time, unicodedata, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

def load_env(path: Path = Path(__file__).parent / ".env"):
    """Charge les clés d'accès depuis .env (jamais versionné : voir .gitignore)."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
DATA = Path(os.environ.get("DATA_DIR", "data"))
REF = Path(__file__).parent / "ref"            # fichiers de référence versionnés avec le code

ODS_EXPORT = ("https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/"
              "datasets/{ds}/exports/csv?delimiter=%3B&lang=fr")
DATAGOUV_DATASET = "https://www.data.gouv.fr/api/1/datasets/{ds}/"
GEO_COMMUNES = "https://geo.api.gouv.fr/communes"
# API Apprentissage (La bonne alternance) : clé gratuite, vérifiée le 4/11/2026.
APPRENTISSAGE_URL = os.environ.get(
    "APPRENTISSAGE_URL", "https://api.apprentissage.beta.gouv.fr/api/formation/v1/search")

SURFACE_STUDIO_M2 = 25      # hypothèse de l'application pour un logement étudiant


# ---------------------------------------------------------------- outils
def norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()


def commune_key(name) -> str:
    """Clé de rapprochement d'une commune : « Paris 14e Arrondissement » -> « paris »,
    « Évry-Courcouronnes » -> « evry courcouronnes »."""
    k = norm(name)
    k = re.sub(r"\b\d+(er|e)?\s*arrondissement\b", "", k)
    k = re.sub(r"[^a-z0-9]+", " ", k).strip()
    return k


def num(x):
    if x is None or (isinstance(x, float) and x != x):
        return None
    s = str(x).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if s.lower() in ("", "nd", "ns", "nan", "na"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick(cols, *candidates, contains=None):
    """Première colonne présente parmi les candidates (insensible à la casse)."""
    low = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    if contains:
        for c in cols:
            if all(w in c.lower() for w in contains):
                return c
    return None


def _get(url, **kw):
    import requests              # utilise HTTPS_PROXY / REQUESTS_CA_BUNDLE si définis
    # (connexion, lecture) : un site qui ne répond pas est abandonné vite au lieu de bloquer le script
    headers = {"User-Agent": "OrientationLycee/0.1 (projet etudiant, donnees publiques)", **kw.pop("headers", {})}
    r = requests.get(url, timeout=kw.pop("timeout", (15, 180)), headers=headers, **kw)
    r.raise_for_status()
    return r


def datagouv_resources(ds: str) -> list[dict]:
    """Ressources d'un jeu data.gouv.fr (robuste aux changements d'identifiant de fichier)."""
    js = _get(DATAGOUV_DATASET.format(ds=ds)).json()
    return [{"title": r.get("title") or "", "url": r.get("url") or "", "format": (r.get("format") or "").lower(),
             "last_modified": r.get("last_modified")} for r in js.get("resources", [])]


def read_csv_bytes(content: bytes) -> pd.DataFrame:
    head = content[:4000].decode("utf-8", "ignore")
    sep = ";" if head.count(";") >= head.count(",") else ","
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(content), sep=sep, encoding=enc, low_memory=False, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError("Encodage du fichier non reconnu")


# ---------------------------------------------------------------- 1. InserSup
INSERSUP_DS = "fr-esr-insersup"
INSERSUP_FILE = DATA / "insersup.csv"


def parse_insersup(df: pd.DataFrame) -> pd.DataFrame:
    """Taux d'emploi et salaire médian des diplômés, au niveau national, par diplôme.
    Garde : niveau national, tous genres, toutes nationalités, diplômés, dernière promotion."""
    c = list(df.columns)
    col = lambda *a, **k: pick(c, *a, **k)
    typ, lib = col("type_diplome_long", "type_diplome"), col("libelle_diplome", "diplome")
    dis, dom = col("discipli_lib", "discipline"), col("dom_lib", "domaine")
    if not typ or not lib:
        raise ValueError(f"InserSup : colonnes type/libellé introuvables. Colonnes : {c}")
    d = df.copy()
    for name, value in (("genre", "ensemble"), ("nationalite", "ensemble"), ("obtention_diplome", "diplome")):
        k = col(name)
        if k:
            d = d[d[k].map(norm).str.startswith(value)]
    uo = col("uo_lib", "etablissement")
    if uo:
        nat = d[d[uo].map(norm) == "national"]
        d = nat if len(nat) else d
    reg = col("regime_inscription")
    promo = col("promo", "annee")
    if promo:
        d = d[d[promo] == d[promo].dropna().astype(str).max()]
    out = pd.DataFrame({
        "type": d[typ].fillna(""), "libelle": d[lib].fillna(""),
        "discipline": d[dis].fillna("") if dis else "", "domaine": d[dom].fillna("") if dom else "",
        "regime": d[reg].fillna("ensemble") if reg else "ensemble",
        "promo": d[promo] if promo else "",
        "taux_emploi_12": d[col("tx_sortants_en_emploi_sal_fr_12")].map(num) if col("tx_sortants_en_emploi_sal_fr_12") else None,
        "taux_emploi_30": d[col("tx_sortants_en_emploi_sal_fr_30")].map(num) if col("tx_sortants_en_emploi_sal_fr_30") else None,
        "salaire_12": d[col("salaire_q2_12")].map(num) if col("salaire_q2_12") else None,
        "salaire_30": d[col("salaire_q2_30")].map(num) if col("salaire_q2_30") else None,
        "sortants": d[col("nb_sortants_12", "nb_sortants_30")].map(num) if col("nb_sortants_12", "nb_sortants_30") else None,
    })
    return out.dropna(subset=["taux_emploi_12", "taux_emploi_30", "salaire_12", "salaire_30"], how="all")


# Filtre appliqué par le serveur : seules les moyennes nationales, tous genres et nationalités confondus.
# Les valeurs viennent du jeu réel (uo_lib « National », genre/nationalite « ensemble ») ; si le filtre
# ne renvoie rien (libellés modifiés par le producteur), on retombe sur l'export complet.
INSERSUP_WHERE = 'uo_lib="National" and genre="ensemble" and nationalite="ensemble"'


def fetch_insersup() -> Path:
    out = pd.DataFrame()
    try:
        r = _get(ODS_EXPORT.format(ds=INSERSUP_DS), params={"where": INSERSUP_WHERE})
        out = parse_insersup(read_csv_bytes(r.content))
        print(f"   insersup : export filtré, {len(out)} lignes utiles", flush=True)
    except Exception as e:
        print(f"   insersup : filtre refusé ({type(e).__name__}), export complet…", flush=True)
    if out.empty:
        r = _get(ODS_EXPORT.format(ds=INSERSUP_DS))
        out = parse_insersup(read_csv_bytes(r.content))
    INSERSUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(INSERSUP_FILE, sep=";", index=False)
    return INSERSUP_FILE


# ---------------------------------------------------------------- 2. Carte des loyers
LOYERS_DS = "693aa2feed1bf4da603faa49"     # « Carte des loyers » 2025 (ministère du Logement)
LOYERS_FILE = DATA / "loyers.csv"


def parse_loyers(df: pd.DataFrame) -> pd.DataFrame:
    """Loyer d'annonce prédit par commune, en €/m² (appartements)."""
    c = list(df.columns)
    insee, lib = pick(c, "INSEE_C", "insee", "code_insee"), pick(c, "LIBGEO", "commune", "libelle")
    dep, m2 = pick(c, "DEP", "dep", "departement"), pick(c, "loypredm2", contains=["loy", "m2"])
    if not lib or not m2:
        raise ValueError(f"Carte des loyers : colonnes introuvables. Colonnes : {c}")
    nobs = pick(c, "nbobs_com", "nbobs")
    out = pd.DataFrame({"insee": df[insee] if insee else "", "commune": df[lib],
                        "dep": df[dep].astype(str).str.zfill(2) if dep else "",
                        "loyer_m2": df[m2].map(num), "nb_obs": df[nobs].map(num) if nobs else None})
    out["cle"] = out["commune"].map(commune_key)
    return out.dropna(subset=["loyer_m2"])


def fetch_loyers() -> Path:
    res = [r for r in datagouv_resources(LOYERS_DS) if r["format"] == "csv" or r["url"].endswith(".csv")]
    # le jeu contient plusieurs fichiers (maisons, appartements, T1-T2, T3+) : on préfère les T1-T2
    best = (next((r for r in res if re.search(r"app.?12|t1.?t2", norm(r["url"] + " " + r["title"]))), None)
            or next((r for r in res if "app" in norm(r["url"] + " " + r["title"])), None)
            or (res[0] if res else None))
    if not best:
        raise ValueError("Carte des loyers : aucun fichier CSV trouvé")
    out = parse_loyers(read_csv_bytes(_get(best["url"]).content))
    out.attrs["fichier"] = best["url"]
    LOYERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(LOYERS_FILE, sep=";", index=False)
    return LOYERS_FILE


# ---------------------------------------------------------------- 3. Métiers (Onisep)
METIERS_DS = "ideo-fiches-metiers"
METIERS_FILE = DATA / "metiers.json"


def _text(el) -> str:
    return re.sub(r"\s+", " ", " ".join(t for t in el.itertext() if t.strip())).strip()


def parse_metiers_xml(content: bytes) -> list[dict]:
    """Fiches métiers Idéo (XML, éventuellement dans un ZIP). Les balises sont repérées par
    leur nom (nom/libellé, niveau, formation, secteur, accroche) pour résister aux évolutions."""
    blobs = []
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            blobs = [z.read(n) for n in z.namelist() if n.lower().endswith(".xml")]
    else:
        blobs = [content]
    out = []
    for b in blobs:
        root = ET.fromstring(b)
        for m in root.iter():
            if m.tag.lower() not in ("metier", "fiche_metier", "fiche"):
                continue
            kids = {k.tag.lower(): k for k in m}
            def first(rx):
                for tag, el in kids.items():
                    if re.search(rx, tag):
                        t = _text(el)
                        if t:
                            return t
                return ""
            nom = first(r"^(nom|libelle)(_metier)?$") or first(r"nom_metier|libelle")
            if not nom:
                continue
            out.append({"id": first(r"^(identifiant|id)"), "nom": nom,
                        "niveau": first(r"niveau"), "formations": first(r"formation"),
                        "secteurs": first(r"secteur"), "accroche": first(r"accroche|format_court")[:400],
                        "rome": first(r"rome")})
    if not out:
        raise ValueError("Fiches métiers : aucune fiche reconnue dans le XML")
    return out


def fetch_metiers() -> Path:
    res = datagouv_resources(METIERS_DS)
    best = next((r for r in res if r["format"] in ("zip", "xml") or re.search(r"\.(zip|xml)$", r["url"])), None)
    if not best:
        raise ValueError("Fiches métiers : aucun fichier ZIP ou XML trouvé")
    import requests
    try:
        content = _get(best["url"]).content
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            raise PermissionError(
                "Refus du serveur Onisep (le portail open data de l'Onisep est en maintenance depuis fin octobre "
                "2026). Les fiches précédemment récupérées restent utilisées ; relancer quand le portail rouvre.") from None
        raise
    rows = parse_metiers_xml(content)
    METIERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METIERS_FILE.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return METIERS_FILE


# ---------------------------------------------------------------- 4. Apprentissage (API Apprentissage)
# Vérifié le 4/11/2026 : GET /api/formation/v1/search avec « Authorization: Bearer <clé> » répond
# {"data": [ {identifiant, statut, formateur:{organisme:{etablissement:{adresse:{commune, departement}}}},
# ...} ]}. Clé gratuite : compte sur api.apprentissage.beta.gouv.fr (variable APPRENTISSAGE_TOKEN).
APPR_FILE = DATA / "apprentissage.csv"


def _dig(obj, *path):
    for k in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def _find_intitule(f: dict) -> str:
    """Intitulé de la formation : on cherche d'abord les chemins attendus, puis toute clé « intitule »."""
    for path in (("certification", "valeur", "intitule", "cfd", "long"), ("certification", "valeur", "intitule", "rncp"),
                 ("certification", "intitule", "cfd", "long"), ("certification", "intitule", "rncp"),
                 ("intitule", "long"), ("intitule",)):
        v = _dig(f, *path)
        if isinstance(v, str) and v.strip():
            return v
    stack = [f]
    while stack:                                     # premier texte trouvé sous une clé « intitule »
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if "intitule" in k and isinstance(v, str) and v.strip():
                    return v
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
    return ""


def parse_apprentissage(records: list[dict]) -> pd.DataFrame:
    """Structure vérifiée sur la vraie réponse : lieu.adresse (lieu réel de la formation),
    certification.valeur.intitule.cfd.long, certification.valeur.domaines.rome.rncp[].code (métiers visés)."""
    rows = []
    for f in records:
        lieu = f.get("lieu") or {}
        etab = _dig(f, "formateur", "organisme", "etablissement") or {}
        adr = lieu.get("adresse") or etab.get("adresse") or {}
        geo = (lieu.get("geolocalisation") or etab.get("geopoint") or {}).get("coordinates") or [None, None]
        cert = _dig(f, "certification", "valeur") or {}
        romes = [r.get("code") for r in (_dig(cert, "domaines", "rome", "rncp") or []) if r.get("code")]
        rows.append({"intitule": _find_intitule(f),
                     "commune": _dig(adr, "commune", "nom") or "", "insee": _dig(adr, "commune", "code_insee") or "",
                     "dep": _dig(adr, "departement", "code_insee") or "",
                     "uai": lieu.get("uai") or _dig(f, "formateur", "organisme", "identifiant", "uai") or "",
                     "organisme": etab.get("enseigne") or _dig(f, "formateur", "organisme", "unite_legale", "raison_sociale") or "",
                     "rome": "|".join(dict.fromkeys(romes)),
                     "niveau": _dig(cert, "intitule", "niveau", "cfd", "europeen") or _dig(cert, "intitule", "niveau", "rncp", "europeen") or "",
                     "duree": _dig(f, "modalite", "duree_indicative") or "",
                     "cycle": _dig(f, "modalite", "annee_cycle") or "",      # année du cursus où commence l'apprentissage
                     "lon": geo[0], "lat": geo[1]})
    out = pd.DataFrame(rows)
    if out.empty or not out["intitule"].astype(bool).any():
        raise ValueError("Apprentissage : aucun intitulé de formation trouvé dans la réponse")
    out["cle"] = out["intitule"].map(norm)
    return out


def fetch_apprentissage(page_size: int = 1000, budget_s: int = 300) -> Path:
    import requests
    token = os.environ.get("APPRENTISSAGE_TOKEN")
    if not token:
        raise PermissionError("APPRENTISSAGE_TOKEN absent : clé gratuite sur api.apprentissage.beta.gouv.fr")
    h = {"Authorization": f"Bearer {token}"}
    rows, page, t0, seen = [], 0, time.time(), set()
    while time.time() - t0 < budget_s:
        try:
            js = _get(APPRENTISSAGE_URL, params={"page_index": page, "page_size": page_size}, headers=h, timeout=(15, 90)).json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                raise PermissionError("Clé refusée par l'API Apprentissage : vérifier APPRENTISSAGE_TOKEN") from None
            raise
        items = js.get("data", []) if isinstance(js, dict) else js
        ids = {json.dumps(_dig(i, "identifiant"), sort_keys=True) for i in items}
        if not items or ids <= seen:                 # page vide ou déjà vue : fin
            break
        seen |= ids
        rows += items
        print(f"   apprentissage : {len(rows)} formations", flush=True)
        pag = js.get("paginate") or js.get("pagination") or {} if isinstance(js, dict) else {}
        total = pag.get("page_count") or pag.get("nombre_de_page")
        if len(items) < page_size or (total is not None and page + 1 >= int(total)):
            break
        page += 1
    out = parse_apprentissage(rows)
    APPR_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(APPR_FILE, sep=";", index=False)
    return APPR_FILE


# ---------------------------------------------------------------- 4 bis. InserJeunes (voie pro, BTS en lycée, CFA)
# Vérifié le 4/11/2026 : data.education.gouv.fr, jeu fr-en-inserjeunes-lycee_pro-examen, champs
# annee, uai, libelle, region, examen, taux_poursuite_etudes, taux_emploi_6/12/18/24_mois. Sans clé.
INSERJEUNES_DS = "fr-en-inserjeunes-lycee_pro-examen"
INSERJEUNES_FILE = DATA / "inserjeunes.csv"
EDU_EXPORT = ("https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/{ds}/exports/csv"
              "?delimiter=%3B&lang=fr")


def parse_inserjeunes(df: pd.DataFrame) -> pd.DataFrame:
    """Dernier millésime disponible par lycée et par diplôme (CAP, bac pro, BTS…)."""
    need = {"annee", "uai", "examen", "taux_emploi_6_mois", "taux_emploi_12_mois"}
    if not need <= set(df.columns):
        raise ValueError(f"InserJeunes : colonnes manquantes {sorted(need - set(df.columns))}")
    d = df.copy()
    d["annee"] = d["annee"].astype(str)
    d = d.sort_values("annee").groupby(["uai", "examen"], as_index=False).tail(1)
    keep = ["uai", "libelle", "region", "examen", "annee", "taux_poursuite_etudes",
            "taux_emploi_6_mois", "taux_emploi_12_mois", "taux_emploi_24_mois"]
    out = d[[c for c in keep if c in d]].copy()
    for c in ("taux_poursuite_etudes", "taux_emploi_6_mois", "taux_emploi_12_mois", "taux_emploi_24_mois"):
        if c in out:
            out[c] = out[c].map(num)
    return out


def fetch_inserjeunes() -> Path:
    out = parse_inserjeunes(read_csv_bytes(_get(EDU_EXPORT.format(ds=INSERJEUNES_DS)).content))
    INSERJEUNES_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(INSERJEUNES_FILE, sep=";", index=False)
    return INSERJEUNES_FILE


# ---------------------------------------------------------------- 4 ter. Métiers ROME (France Travail)
# Vérifié le 4/11/2026 : jeton client_credentials (scope api_rome-metiersv1 nomenclatureRome), puis
# GET /partenaire/rome-metiers/v1/metiers/metier -> [{"code": "N2215", "libelle": "..."}].
# Clés gratuites : application sur francetravail.io (FT_CLIENT_ID, FT_CLIENT_SECRET). 1 appel par seconde.
FT_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
FT_METIERS_URL = "https://api.francetravail.io/partenaire/rome-metiers/v1/metiers/metier"
ROME_FILE = DATA / "metiers_rome.json"


def ft_token(scope: str = "api_rome-metiersv1 nomenclatureRome") -> str:
    import requests
    cid, sec = os.environ.get("FT_CLIENT_ID"), os.environ.get("FT_CLIENT_SECRET")
    if not cid or not sec:
        raise PermissionError("FT_CLIENT_ID / FT_CLIENT_SECRET absents : application gratuite sur francetravail.io")
    r = requests.post(FT_TOKEN_URL, params={"realm": "/partenaire"}, timeout=(15, 60),
                      data={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec, "scope": scope})
    r.raise_for_status()
    return r.json()["access_token"]


def parse_rome(items: list) -> list[dict]:
    out = [{"code": i.get("code"), "libelle": i.get("libelle")} for i in items if i.get("code") and i.get("libelle")]
    if not out:
        raise ValueError("Métiers ROME : réponse vide")
    return sorted(out, key=lambda m: norm(m["libelle"]))


def fetch_rome() -> Path:
    items = _get(FT_METIERS_URL, headers={"Authorization": f"Bearer {ft_token()}", "Accept": "application/json"}).json()
    ROME_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROME_FILE.write_text(json.dumps(parse_rome(items), ensure_ascii=False), encoding="utf-8")
    return ROME_FILE


# ---------------------------------------------------------------- 5. Communes (appel direct)
def search_communes(q: str, limit: int = 8) -> list[dict]:
    """API Découpage administratif (geo.api.gouv.fr) : sans clé, appelée à la demande."""
    js = _get(GEO_COMMUNES, params={"nom": q, "fields": "nom,code,codeDepartement,centre,population",
                                   "boost": "population", "limit": limit}, timeout=10).json()
    out = []
    for c in js:
        lon, lat = (c.get("centre") or {}).get("coordinates", [None, None])
        out.append({"nom": c.get("nom"), "insee": c.get("code"), "dep": c.get("codeDepartement"),
                    "lat": lat, "lon": lon, "population": c.get("population")})
    return out


# ---------------------------------------------------------------- 5 bis. Critères d'examen des vœux (fiches Parcoursup)
# Ils ne sont pas dans l'open data (méthodologie 2025) mais sur la fiche publique de chaque formation.
# Contenus Parcoursup : Licence Ouverte Etalab 2.0 sauf mention contraire (conditions d'utilisation du site).
# Lecture à la demande, une fiche à la fois, puis mise en cache : jamais tout le catalogue d'un coup.
FICHE_URL = "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={}&typeBac=0&originePc=0"
CRITERES_DIR = DATA / "criteres"
NIVEAUX = {"complémentaire": 1, "important": 2, "très important": 3, "essentiel": 4}


def _clean(fragment: str) -> str:
    import html as _html
    t = re.sub(r"(?s)<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def parse_fiche_criteres(page: str) -> dict:
    """Extrait de la fiche : grille (poids de chaque catégorie), critères détaillés avec
    leur degré d'importance (1 à 4), conseils aux candidats. Structure vérifiée sur la fiche
    10945 (licence de droit, Évry) téléchargée par explorer_parcoursup.py le 4/11/2026."""
    out = {"grille": [], "criteres": [], "conseils": None, "session": None, "cordees": False}
    m = re.search(r'(?s)<table id="table-analyse-cddt[^"]*".*?</table>', page)
    if m:
        for lab, val in re.findall(r'(?s)<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', m.group(0)):
            lab, pct = _clean(lab), num(_clean(val).replace("%", ""))
            if lab.lower() != "au total" and pct is not None:
                out["grille"].append({"categorie": lab, "poids": pct})
    for table in re.findall(r'(?s)<table class="table-forme-notation-cgev[^"]*".*?</table>', page):
        cap = _clean((re.search(r"(?s)<caption[^>]*>(.*?)</caption>", table) or [None, ""])[1])
        poids = num((re.search(r"(\d+(?:[.,]\d+)?)\s*%", cap) or [None, None])[1])
        body = (re.search(r"(?s)<tbody>(.*?)</tbody>", table) or [None, ""])[1]
        for row in re.findall(r"(?s)<tr>(.*?)</tr>", body):
            th = re.search(r"(?s)<th[^>]*>(.*?)</th>", row)
            tds = re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)
            lvl = _clean((re.search(r'(?s)class="psup-rating-text">(.*?)<', row) or [None, ""])[1])
            if th:
                out["criteres"].append({"categorie": cap, "poids_categorie": poids, "critere": _clean(th.group(1)),
                                        "elements": _clean(tds[0]) if tds else "", "importance": lvl,
                                        "niveau": NIVEAUX.get(lvl.lower())})
    c = re.search(r'(?s)Conseils aux candidats</h4>\s*<div[^>]*>(.*?)</div>', page)
    if c:
        out["conseils"] = _clean(c.group(1))
    sess = re.search(r"candidatures en [a-zéû-]+ (\d{4})", page)
    out["session"] = int(sess.group(1)) if sess else None
    out["cordees"] = "cordées de la réussite dans l'analyse" in page
    return out


def criteres(g_ta_cod: str, refresh: bool = False) -> dict:
    """Critères d'une formation : depuis le cache, sinon lecture de la fiche (environ 1 s)."""
    code = re.sub(r"\D", "", str(g_ta_cod))
    if not code:
        raise ValueError("g_ta_cod invalide")
    f = CRITERES_DIR / f"{code}.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text(encoding="utf-8"))
    url = FICHE_URL.format(code)
    d = parse_fiche_criteres(_get(url, timeout=(10, 30)).text)
    d.update({"g_ta_cod": code, "url": url, "date_releve": time.strftime("%Y-%m-%d"),
              "licence": "Licence Ouverte Etalab 2.0 (Parcoursup)"})
    CRITERES_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def criteres_batch(codes, pause: float = 1.0, budget_s: float | None = None) -> dict:
    """Lecture d'un lot de fiches (par ex. tout le catalogue, une nuit par an).
    Reprend là où il s'était arrêté : les fiches déjà en cache sont sautées."""
    t0, done, fails = time.time(), 0, []
    todo = [c for c in dict.fromkeys(str(c) for c in codes) if not (CRITERES_DIR / f"{c}.json").exists()]
    for i, c in enumerate(todo, 1):
        if budget_s and time.time() - t0 > budget_s:
            print(f"  budget de {budget_s:.0f} s atteint : relance la commande pour continuer"); break
        try:
            criteres(c); done += 1
        except Exception as e:
            fails.append((c, repr(e)[:120]))
        if i % 50 == 0:
            print(f"  {i}/{len(todo)} fiches, {time.time() - t0:.0f} s", flush=True)
        time.sleep(pause)
    return {"lues": done, "deja_en_cache": len(set(map(str, codes))) - len(todo), "echecs": fails[:20]}


def verifier_criteres(n: int = 30, pause: float = 1.0) -> dict:
    """Contrôle du décodage sur un échantillon de toutes les filières (BUT, BTS, CPGE, licences, écoles…).
    Une fiche sans critères est enregistrée dans explore_parcoursup/ pour qu'on adapte le décodage."""
    df = pd.read_csv(DATA / "parcoursup.csv", sep=None, engine="python", dtype=str,
                     usecols=["fili", "lib_for_voe_ins", "lien_form_psup"]).dropna(subset=["lien_form_psup"])
    df["code"] = df["lien_form_psup"].str.extract(r"g_ta_cod=(\d+)")[0]
    par_fili = max(1, n // max(1, df["fili"].nunique()))
    ech = df.sample(frac=1, random_state=1).groupby("fili").head(par_fili).head(n)
    out_dir = Path(__file__).parent / "explore_parcoursup"
    lignes, ok = [], 0
    for _, r in ech.iterrows():
        try:
            page = _get(FICHE_URL.format(r.code), timeout=(10, 30)).text
            d = parse_fiche_criteres(page)
            bon = bool(d["criteres"]) and bool(d["grille"])
            if not bon:
                out_dir.mkdir(exist_ok=True)
                (out_dir / f"{r.code}_sans_criteres.html").write_text(page, encoding="utf-8")
            ok += bon
            lignes.append(f"{'OK ' if bon else 'NON'} {r.fili:<28.28} {r.code:>6}  grille {len(d['grille'])}  "
                          f"critères {len(d['criteres']):>2}  session {d['session']}  {str(r.lib_for_voe_ins)[:40]}")
        except Exception as e:
            lignes.append(f"ERR {r.fili:<28.28} {r.code:>6}  {e!r}"[:140])
        print(lignes[-1], flush=True)
        time.sleep(pause)
    print(f"\n{ok}/{len(ech)} fiches décodées avec leur grille et leurs critères.")
    return {"ok": ok, "total": len(ech)}


# ---------------------------------------------------------------- 6. Fichiers de référence
BAREMES_FILE = REF / "baremes.json"


PROGRAMMES_FILE = REF / "programmes.json"


def load_programmes() -> dict:
    """Chapitres (ou types d'exercice) par matière et par niveau, transcrits des textes officiels."""
    return json.loads(PROGRAMMES_FILE.read_text(encoding="utf-8")) if PROGRAMMES_FILE.exists() else {}


def load_baremes() -> dict:
    return json.loads(BAREMES_FILE.read_text(encoding="utf-8")) if BAREMES_FILE.exists() else {}


# ---------------------------------------------------------------- registre
SOURCES = {
    "insersup": {"label": "Insertion des diplômés (InserSup)", "producteur": "Ministère de l'Enseignement supérieur",
                 "acces": "API open data", "fetch": fetch_insersup, "file": INSERSUP_FILE,
                 "remplace": "Débouchés et salaires écrits par l'équipe"},
    "loyers": {"label": "Carte des loyers 2025", "producteur": "Ministère du Logement (data.gouv.fr)",
               "acces": "API data.gouv.fr", "fetch": fetch_loyers, "file": LOYERS_FILE,
               "remplace": "Loyer moyen national ou parisien fixe"},
    "metiers": {"label": "Fiches métiers Idéo", "producteur": "Onisep (portail en maintenance depuis fin octobre 2026)",
                "acces": "API data.gouv.fr", "fetch": fetch_metiers, "file": METIERS_FILE,
                "remplace": "Liste de 17 métiers d'exemple"},
    "apprentissage": {"label": "Formations en apprentissage (API Apprentissage)", "producteur": "Mission interministérielle apprentissage",
                      "acces": "API, clé gratuite", "fetch": fetch_apprentissage, "file": APPR_FILE,
                      "remplace": "Années d'alternance estimées par voie"},
    "metiers_rome": {"label": "Métiers ROME 4.0 (France Travail)", "producteur": "France Travail",
                     "acces": "API, clé gratuite", "fetch": fetch_rome, "file": ROME_FILE,
                     "remplace": "Liste de 17 métiers d'exemple (relais de l'Onisep en maintenance)"},
    "inserjeunes": {"label": "Insertion après la voie pro et les BTS (InserJeunes)", "producteur": "Ministère de l'Éducation nationale (DEPP)",
                    "acces": "API open data", "fetch": fetch_inserjeunes, "file": INSERJEUNES_FILE,
                    "remplace": "Aucune donnée d'insertion pour les BTS"},
}
LIVE = {"criteres": {"label": "Critères d'examen des vœux", "producteur": "Fiches Parcoursup (Licence Ouverte Etalab 2.0)",
                     "acces": "Lecture de la fiche à la demande, mise en cache", "remplace": "Matières clés déduites par l'équipe"},
        "communes": {"label": "Communes et coordonnées", "producteur": "API Découpage administratif (geo.api.gouv.fr)",
                     "acces": "API appelée à la demande", "remplace": "Rapprochement par région"}}
REFERENCE = {
    "baremes": {"label": "Barèmes officiels (droits, bourses, apprentis, coût de la vie)", "file": BAREMES_FILE,
                "acces": "Fichier de référence, mis à jour chaque rentrée", "remplace": "Valeurs codées dans le site"},
    "programmes": {"label": "Programmes officiels (chapitres, épreuves anticipées)", "file": PROGRAMMES_FILE,
                   "acces": "Fichier de référence, transcrit du Bulletin officiel", "remplace": "Rien : nouvelle fonction"},
}


def refresh_all(names=None) -> dict:
    report = {}
    for name, s in SOURCES.items():
        if names and name not in names:
            continue
        t = time.time()
        print(f"-> {s['label']}…", flush=True)
        try:
            path = s["fetch"]()
            report[name] = {"ok": True, "fichier": str(path), "secondes": round(time.time() - t, 1)}
        except Exception as e:                              # la source reste en secours
            report[name] = {"ok": False, "erreur": f"{type(e).__name__}: {e}"[:300]}
        r = report[name]
        print(f"   {'OK' if r['ok'] else 'ÉCHEC'} en {round(time.time() - t)} s : {r.get('fichier') or r.get('erreur')}", flush=True)
    return report


def _rows(path: Path):
    if not path.exists():
        return None
    if path.suffix == ".json":
        return len(json.loads(path.read_text(encoding="utf-8")))
    return max(sum(1 for _ in open(path, encoding="utf-8")) - 1, 0)


def status() -> list[dict]:
    out = []
    for name, s in SOURCES.items():
        p = s["file"]
        out.append({"id": name, "label": s["label"], "producteur": s["producteur"], "acces": s["acces"],
                    "remplace": s["remplace"], "disponible": p.exists(), "lignes": _rows(p),
                    "mise_a_jour": time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime)) if p.exists() else None})
    for name, s in LIVE.items():
        out.append({"id": name, **s, "disponible": True, "lignes": None, "mise_a_jour": "à la demande"})
    for name, s in REFERENCE.items():
        p = s["file"]
        out.append({"id": name, "label": s["label"], "producteur": "Équipe (sources citées dans le fichier)",
                    "acces": s["acces"], "remplace": s["remplace"], "disponible": p.exists(),
                    "lignes": _rows(p) if p.suffix == ".csv" else None,
                    "mise_a_jour": time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime)) if p.exists() else None})
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["criteres"]:
        # python sources.py criteres 10945 35899      -> ces formations
        # python sources.py criteres --tout --budget 3600   -> tout le catalogue, par tranches d'une heure
        args = sys.argv[2:]
        budget = float(args[args.index("--budget") + 1]) if "--budget" in args else None
        if "--verifier" in args:              # python sources.py criteres --verifier 30
            i = args.index("--verifier")
            verifier_criteres(int(args[i + 1]) if len(args) > i + 1 and args[i + 1].isdigit() else 30)
            sys.exit(0)
        if "--tout" in args:
            df = pd.read_csv(DATA / "parcoursup.csv", sep=None, engine="python", dtype=str, usecols=["lien_form_psup"])
            codes = df["lien_form_psup"].str.extract(r"g_ta_cod=(\d+)")[0].dropna().tolist()
        else:
            codes = [a for a in args if a.isdigit()]
        print(json.dumps(criteres_batch(codes, budget_s=budget), ensure_ascii=False, indent=2))
    elif "--check" in sys.argv:
        for name, s in SOURCES.items():
            p = s["file"]
            if not p.exists():
                print(f"{name:14} absent"); continue
            if p.suffix == ".json":
                rows = json.loads(p.read_text(encoding="utf-8"))
                print(f"{name:14} {len(rows)} fiches, exemple : {rows[0] if rows else '-'}")
            else:
                df = pd.read_csv(p, sep=";", nrows=3)
                print(f"{name:14} {_rows(p)} lignes, colonnes : {list(df.columns)}")
                if len(df):
                    print(" " * 15 + "exemple :", df.iloc[0].to_dict())
    else:
        print(json.dumps(refresh_all(sys.argv[1:] or None), ensure_ascii=False, indent=2))
