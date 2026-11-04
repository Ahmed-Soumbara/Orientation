"""Interroge chaque API candidate et affiche ce qu'elle renvoie VRAIMENT
(statut HTTP, champs, un exemple). Sert à écrire les connecteurs sur des faits, pas sur des suppositions.

    python explorer_api.py              # toutes les sources
    python explorer_api.py inserjeunes  # une seule

Clés d'accès (gratuites, à créer une fois) : à mettre dans l'environnement, jamais dans le code.
    export APPRENTISSAGE_TOKEN=...                 # compte sur api.apprentissage.beta.gouv.fr
    export FT_CLIENT_ID=...  FT_CLIENT_SECRET=...   # application sur francetravail.io
Copie tout ce qui s'affiche et envoie-le.
"""
import json, os, sys
import requests

try:
    from sources import load_env
    load_env()                                     # lit les clés dans .env si présent
except Exception:
    pass

UA = {"User-Agent": "OrientationLycee/0.1 (projet etudiant, donnees publiques)"}
ODS = {
    "education": "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets",
    "esr": "https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/datasets",
}


def show(title, r=None, err=None, body=None):
    print("\n" + "=" * 70 + f"\n{title}")
    if err:
        print("  ERREUR :", err); return
    print("  HTTP", r.status_code, r.headers.get("content-type", ""))
    if body is not None:
        print("  " + json.dumps(body, ensure_ascii=False)[:1500])


def get(url, **kw):
    return requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=(15, 60), **kw)


def ods_dataset(base, ds):
    """Schéma et un exemple d'un jeu Opendatasoft (même plateforme que Parcoursup)."""
    try:
        r = get(f"{base}/{ds}")
        meta = r.json() if r.ok else r.text[:300]
        fields = [f.get("name") for f in meta.get("fields", [])] if isinstance(meta, dict) else meta
        r2 = get(f"{base}/{ds}/records", params={"limit": 1})
        show(f"{ds}", r2, body={"champs": fields, "nb": r2.json().get("total_count") if r2.ok else None,
                                "exemple": (r2.json().get("results") or [None])[0] if r2.ok else r2.text[:300]})
    except Exception as e:
        show(ds, err=repr(e))


def ods_search(base, q):
    try:
        r = get(base, params={"where": f'search("{q}")', "limit": 20, "select": "dataset_id"})
        show(f"Jeux contenant « {q} » sur {base.split('/')[2]}", r,
             body=[d.get("dataset_id") for d in r.json().get("results", [])] if r.ok else r.text[:300])
    except Exception as e:
        show(q, err=repr(e))


def inserjeunes():
    ods_search(ODS["education"], "inserjeunes")
    for ds in ("fr-en-inserjeunes-lycee_pro", "fr-en-inserjeunes-lycee_pro-examen", "fr-en-inserjeunes-cfa"):
        ods_dataset(ODS["education"], ds)


def insersup():
    ods_dataset(ODS["esr"], "fr-esr-insersup")


def onisep():
    for url in ("https://api.opendata.onisep.fr/api/1.0/dataset/5fa5949243f97/search?size=1",
                "https://opendata.onisep.fr/3-api.htm"):
        try:
            r = get(url)
            show(f"Onisep {url}", r, body=r.text[:400])
        except Exception as e:
            show(url, err=repr(e))


def apprentissage():
    tok = os.environ.get("APPRENTISSAGE_TOKEN")
    if not tok:
        show("API Apprentissage", err="APPRENTISSAGE_TOKEN absent : crée un compte sur api.apprentissage.beta.gouv.fr"); return
    h = {"Authorization": f"Bearer {tok}"}
    for path in ("/api/doc/openapi.json", "/api/openapi.json", "/api/formation/v1/search?page_size=1",
                 "/api/certification/v1?identifiant.rncp=RNCP35185"):
        try:
            r = get("https://api.apprentissage.beta.gouv.fr" + path, headers=h)
            body = r.json() if "json" in r.headers.get("content-type", "") else r.text[:300]
            if isinstance(body, dict) and "paths" in body:      # documentation OpenAPI : on liste les routes
                body = {"routes": sorted(body["paths"])[:80]}
            if isinstance(body, dict) and body.get("data"):      # structure complète d'une formation
                def tree(o, p=""):
                    if isinstance(o, dict):
                        return [x for k, v in o.items() for x in tree(v, f"{p}.{k}" if p else k)]
                    if isinstance(o, list) and o:
                        return tree(o[0], p + "[0]")
                    return [f"{p} = {str(o)[:60]}"]
                print("\n".join("    " + l for l in tree(body["data"][0])))
                body = {k: v for k, v in body.items() if k != "data"}
            show(f"API Apprentissage {path}", r, body=body)
        except Exception as e:
            show(path, err=repr(e))


def france_travail():
    cid, sec = os.environ.get("FT_CLIENT_ID"), os.environ.get("FT_CLIENT_SECRET")
    if not cid or not sec:
        show("France Travail", err="FT_CLIENT_ID / FT_CLIENT_SECRET absents : crée une application sur francetravail.io"); return
    try:
        r = requests.post("https://entreprise.francetravail.fr/connexion/oauth2/access_token",
                          params={"realm": "/partenaire"}, headers=UA, timeout=(15, 60),
                          data={"grant_type": "client_credentials", "client_id": cid, "client_secret": sec,
                                "scope": "api_rome-metiersv1 nomenclatureRome"})
        show("France Travail : jeton", r, body={k: (v if k != "access_token" else "…") for k, v in r.json().items()} if r.ok else r.text[:300])
        if r.ok:
            t = r.json()["access_token"]
            r2 = get("https://api.francetravail.io/partenaire/rome-metiers/v1/metiers/metier",
                     headers={"Authorization": f"Bearer {t}", "Accept": "application/json"})
            js = r2.json() if r2.ok else r2.text[:300]
            show("France Travail : métiers ROME", r2, body=js[:2] if isinstance(js, list) else js)
    except Exception as e:
        show("France Travail", err=repr(e))


SOURCES = {"inserjeunes": inserjeunes, "insersup": insersup, "onisep": onisep,
           "apprentissage": apprentissage, "france_travail": france_travail}

if __name__ == "__main__":
    for name in (sys.argv[1:] or SOURCES):
        SOURCES[name]()
