"""API + site : sert l'arbre, les suggestions et le positionnement depuis les données en cache.

Lancer :  pip install fastapi uvicorn pandas pyarrow requests
          uvicorn api:app --reload      puis ouvrir http://127.0.0.1:8000/
Rafraîchir les données :  python data.py   (cron : 1 fois par mois, voire par session)
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import data
from engine import position
from tree import DOMAIN_NAMES, add_domains, build_tree, stats_of, suggest

STATE = {}


def load_state(force: bool = False):
    df = add_domains(data.load(force=force))        # domaines calculés 1 seule fois
    STATE["df"] = df
    STATE["session"] = int(df["session"].max())
    STATE["academies"] = (sorted(a for a in df["academie"].dropna().unique() if a)
                          if "academie" in df else [])


@asynccontextmanager
async def lifespan(app):
    load_state()                                     # lu 1 fois au démarrage, en mémoire
    yield


app = FastAPI(title="Cap Sup API", lifespan=lifespan)


class Student(BaseModel):
    avg: float = Field(ge=0, le=20)
    academie: str | None = None


@app.get("/api/meta")
def meta():
    """Listes pour le formulaire (académies, domaines) et session des données."""
    return {"session": STATE["session"], "academies": STATE["academies"], "domains": DOMAIN_NAMES}


@app.get("/api/suggest")
def api_suggest(avg: float = Query(ge=0, le=20), academie: str | None = None,
                domain: str | None = None, n: int = Query(6, ge=1, le=20)):
    """Formations suggérées : sûres, à la marge, ambitieuses."""
    return suggest(STATE["df"], avg, academie=academie, domain=domain, per_group=n)


@app.get("/api/tree")
def tree(avg: float | None = Query(None, ge=0, le=20), academie: str | None = None,
         domain: str | None = None, q: str | None = None, depth: int = Query(4, ge=1, le=4),
         limit: int = Query(50, ge=1, le=500), schools: int = Query(5, ge=1, le=50)):
    """Arbre Domaine > Parcours > Formation > Établissement, avec la zone si avg est fourni."""
    return build_tree(STATE["df"], avg=avg, academie=academie, domain=domain, query=q,
                      max_depth=depth, limit_formations=limit, max_schools=schools)


@app.post("/api/position/{fid:path}")
def formation_position(fid: str, student: Student):
    """Positionnement d'un élève sur UN établissement (fid = uai|formation)."""
    g = STATE["df"][STATE["df"]["fid"] == fid]
    if g.empty:
        raise HTTPException(404, "Formation inconnue")
    return position(student.avg, stats_of(g, g.iloc[0]["school"]), STATE["session"]).to_dict()


@app.post("/api/refresh")
def refresh():
    """À protéger (clé d'admin) en production."""
    load_state(force=True)
    return {"rows": len(STATE["df"]), "session": STATE["session"]}


@app.get("/api/raw.csv")
def raw_csv():
    """Fichier Parcoursup brut (mis en cache par data.py) : le site le lit avec son propre moteur."""
    raw = data.CACHE.with_suffix(".csv")
    if not raw.exists():
        raise HTTPException(404, "Données non téléchargées : lancer python data.py")
    return FileResponse(raw, media_type="text/csv; charset=utf-8")


@app.get("/api/specialites.json")
def specialites():
    """Admis par formation et doublette de spécialités ; liste vide si le jeu n'est pas encore téléchargé."""
    import pandas as pd
    if not data.SPE_CACHE.exists():
        return []
    return pd.read_csv(data.SPE_CACHE, sep=";").fillna(0).to_dict(orient="records")


# ---------------------------------------------------------------- sources complémentaires
import json as _json
import sources


def _csv_records(path):
    import pandas as pd
    if not path.exists():
        return []
    return _json.loads(pd.read_csv(path, sep=";", dtype=str).fillna("").to_json(orient="records"))


@app.get("/api/sources")
def api_sources():
    """État de chaque source : disponible ou non, nombre de lignes, date de mise à jour."""
    return sources.status()


@app.get("/api/insertion")
def api_insertion():
    """Taux d'emploi et salaires médians des diplômés (InserSup), niveau national."""
    return _csv_records(sources.INSERSUP_FILE)


@app.get("/api/loyers")
def api_loyers():
    """Loyer au m² par commune : {"dep|cle commune": loyer}. Vide si la carte n'est pas chargée."""
    import pandas as pd
    if not sources.LOYERS_FILE.exists():
        return {}
    df = pd.read_csv(sources.LOYERS_FILE, sep=";", dtype={"dep": str})
    return {f"{d}|{k}": round(float(v), 2) for d, k, v in zip(df["dep"], df["cle"], df["loyer_m2"])}


_ROME_CACHE = {}


def _metiers_rome():
    """Métiers ROME + formations en apprentissage qui y mènent (lien officiel par code ROME)."""
    import pandas as pd
    key = (sources.ROME_FILE.stat().st_mtime if sources.ROME_FILE.exists() else 0,
           sources.APPR_FILE.stat().st_mtime if sources.APPR_FILE.exists() else 0)
    if _ROME_CACHE.get("key") == key:
        return _ROME_CACHE["rows"]
    rome = _json.loads(sources.ROME_FILE.read_text(encoding="utf-8")) if sources.ROME_FILE.exists() else []
    forms = {}
    if sources.APPR_FILE.exists():
        df = pd.read_csv(sources.APPR_FILE, sep=";", dtype=str).fillna("")
        if "rome" in df:
            df = df[df["rome"] != ""].assign(rome=df["rome"].str.split("|")).explode("rome")
            for code, g in df.groupby("rome"):
                top = g["intitule"].value_counts().head(6)
                forms[code] = {"formations": [f"{t} ({n})" for t, n in top.items()], "nb": int(len(g))}
    rows = [{"id": m["code"], "nom": m["libelle"], "rome": m["code"], "niveau": "",
             "formations": " · ".join(forms.get(m["code"], {}).get("formations", [])),
             "nb_apprentissage": forms.get(m["code"], {}).get("nb", 0), "source": "rome"} for m in rome]
    _ROME_CACHE.update(key=key, rows=rows)
    return rows


@app.get("/api/metiers")
def api_metiers(q: str | None = None, n: int = Query(20, ge=1, le=20000)):
    """Fiches métiers : Onisep si disponible, sinon référentiel ROME de France Travail."""
    if sources.METIERS_FILE.exists():
        rows = _json.loads(sources.METIERS_FILE.read_text(encoding="utf-8"))
    else:
        rows = _metiers_rome()
    if q:
        k = sources.norm(q)
        rows = [r for r in rows if k in sources.norm(r["nom"])]
    return rows[:n]


@app.get("/api/apprentissage")
def api_apprentissage():
    """Nombre de formations en apprentissage par intitulé normalisé."""
    import pandas as pd
    if not sources.APPR_FILE.exists():
        return {}
    df = pd.read_csv(sources.APPR_FILE, sep=";", dtype=str).fillna("")
    out = {}
    for cle, g in df.groupby("cle"):                  # par intitulé : nombre, codes ROME visés, année de début
        rome = g["rome"].str.split("|").explode() if "rome" in g else pd.Series(dtype=str)
        cyc = g["cycle"] if "cycle" in g else pd.Series(dtype=str)
        out[cle] = {"n": int(len(g)), "rome": rome[rome != ""].value_counts().head(8).to_dict(),
                    "cycle": cyc[cyc != ""].value_counts().to_dict()}
    return out


@app.get("/api/inserjeunes")
def api_inserjeunes():
    """Insertion des sortants de BTS par lycée (InserJeunes) : {uai: {...}}."""
    import pandas as pd
    if not sources.INSERJEUNES_FILE.exists():
        return {}
    df = pd.read_csv(sources.INSERJEUNES_FILE, sep=";", dtype={"uai": str})
    df = df[df["examen"].astype(str).str.upper().str.contains("BTS")]
    return _json.loads(df.set_index("uai").to_json(orient="index"))


@app.get("/api/communes")
def api_communes(q: str = Query(min_length=2)):
    """Recherche de commune (geo.api.gouv.fr), pour calculer la distance domicile-formation."""
    try:
        return sources.search_communes(q)
    except Exception:
        return []


@app.get("/api/criteres/{g_ta_cod}")
def api_criteres(g_ta_cod: str):
    """Critères d'examen des vœux d'une formation, lus sur sa fiche Parcoursup puis mis en cache."""
    try:
        return sources.criteres(g_ta_cod)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Fiche Parcoursup indisponible : {e!r}"[:300])


@app.get("/api/programmes")
def api_programmes():
    """Chapitres et épreuves anticipées transcrits des textes officiels (ref/programmes.json)."""
    return sources.load_programmes()


@app.get("/api/baremes")
def api_baremes():
    """Barèmes officiels de l'année (fichier de référence ref/baremes.json)."""
    return sources.load_baremes()




# Le site (static/index.html) est servi à la racine, après les routes /api.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="site")
