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


# Le site (static/index.html) est servi à la racine, après les routes /api.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="site")
