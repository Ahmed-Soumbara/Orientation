"""Regarde à quoi ressemble VRAIMENT une fiche Parcoursup, pour écrire le connecteur
« critères d'examen des vœux » sur des faits, comme explorer_api.py pour les API.

    python explorer_parcoursup.py              # 3 formations prises dans data/parcoursup.csv
    python explorer_parcoursup.py 10945 35899  # ou des codes g_ta_cod précis

Ce qu'il fait, pour chaque fiche (une requête toutes les 2 secondes, pas plus) :
  1. télécharge la page telle quelle et cherche la rubrique des critères ;
  2. si elle n'y est pas (page remplie par JavaScript), l'ouvre dans un navigateur
     automatisé (Playwright, s'il est installé) et note les appels de données de la page ;
  3. enregistre les pages dans le dossier explore_parcoursup/.

Copie tout ce qui s'affiche et envoie-le (et, si on te le demande, un fichier du dossier).
Contenus Parcoursup : Licence Ouverte Etalab 2.0 sauf mention contraire (conditions d'utilisation du site).
"""
import csv, html, re, sys, time
from pathlib import Path
import requests

UA = {"User-Agent": "OrientationLycee/0.1 (projet etudiant IMT-BS/TSP/ENSIIE, lecture ponctuelle des fiches publiques)"}
FICHE = "https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod={}&typeBac=0&originePc=0"
OUT = Path(__file__).parent / "explore_parcoursup"
CSV = Path(__file__).parent / "data" / "parcoursup.csv"
MOTS = ["critères généraux", "critères d'analyse", "comprendre les critères", "essentiel", "très important",
        "complémentaire", "résultats académiques", "savoir-être", "motivation"]
PAUSE = 2.0


def codes_par_defaut(n=3):
    """Une licence, un BUT et une CPGE si possible, pour voir des fiches différentes."""
    if not CSV.exists():
        return ["10945"]                     # Licence de droit, Université d'Évry (open data 2025)
    with CSV.open(encoding="utf-8-sig") as f:
        first = f.readline(); f.seek(0)
        rows = csv.DictReader(f, delimiter=";" if first.count(";") > first.count(",") else ",")
        vus, out = set(), []
        for r in rows:
            fili, lien = (r.get("fili") or ""), (r.get("lien_form_psup") or "")
            m = re.search(r"g_ta_cod=(\d+)", lien)
            if m and fili not in vus:
                vus.add(fili); out.append(m.group(1))
            if len(out) >= n:
                break
    return out or ["10945"]


def texte(page):
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", page))).strip()


def extrait(t, n=1500):
    low = t.lower()
    pos = [low.find(m) for m in ("comprendre les critères", "critères généraux", "critères d'analyse") if low.find(m) >= 0]
    return t[min(pos): min(pos) + n] if pos else None


def rapport(code, page, t, mode, duree):
    low = t.lower()
    print(f"  mode : {mode} · {len(page):,} caractères · {duree:.1f} s")
    print("  titre :", (re.search(r"(?is)<title>(.*?)</title>", page) or [None, "?"])[1].strip()[:120])
    print("  mots trouvés :", {m: low.count(m) for m in MOTS if m in low} or "aucun")
    ex = extrait(t)
    print("  extrait :", ex if ex else "rubrique des critères introuvable dans cette version de la page")
    return bool(ex)


def brut(code):
    t0 = time.time()
    r = requests.get(FICHE.format(code), headers=UA, timeout=(15, 60))
    print(f"  HTTP {r.status_code} · {r.headers.get('content-type', '')} · adresse finale : {r.url}")
    page = r.text
    (OUT / f"{code}_brut.html").write_text(page, encoding="utf-8")
    scripts = re.findall(r'(?i)<script[^>]+src="([^"]+)"', page)
    appels = sorted(set(re.findall(r'["\'](/[^"\']*(?:api|ajax|json|rest)[^"\']*)["\']', page, flags=re.I)))[:20]
    print(f"  scripts : {len(scripts)} · adresses de données repérées dans le code : {appels or 'aucune'}")
    return rapport(code, page, texte(page), "page brute", time.time() - t0)


def navigateur(code):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright absent : pip install playwright && python -m playwright install chromium"); return
    t0, xhr = time.time(), []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA["User-Agent"])
        pg.on("response", lambda res: xhr.append(f"{res.status} {res.request.resource_type} {res.url[:160]}")
              if res.request.resource_type in ("xhr", "fetch") else None)
        pg.goto(FICHE.format(code), wait_until="networkidle", timeout=60000)
        for lib in ("Comprendre les critères", "Critères"):          # onglet ou accordéon éventuel
            try:
                pg.get_by_text(lib, exact=False).first.click(timeout=2000); pg.wait_for_timeout(1500); break
            except Exception:
                pass
        page = pg.content(); b.close()
    (OUT / f"{code}_rendu.html").write_text(page, encoding="utf-8")
    print("  appels de données de la page :", xhr[:20] or "aucun")
    rapport(code, page, texte(page), "navigateur", time.time() - t0)


def cartographie():
    """Le jeu « cartographie des formations » donne-t-il les fiches de la session en cours ?"""
    base = "https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/datasets/fr-esr-cartographie_formations_parcoursup"
    try:
        meta = requests.get(base, headers=UA, timeout=(15, 60)).json()
        rec = requests.get(base + "/records", params={"limit": 1, "order_by": "annee desc"}, headers=UA, timeout=(15, 60)).json()
        print("\n" + "=" * 70 + "\nCartographie des formations Parcoursup (open data)")
        print("  champs :", [f.get("name") for f in meta.get("fields", [])])
        print("  nb :", rec.get("total_count"), "· exemple :", str((rec.get("results") or [None])[0])[:1200])
    except Exception as e:
        print("  ERREUR cartographie :", repr(e))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for i, code in enumerate(sys.argv[1:] or codes_par_defaut()):
        if i:
            time.sleep(PAUSE)
        print("\n" + "=" * 70 + f"\nFiche g_ta_cod={code}")
        try:
            ok = brut(code)
        except Exception as e:
            print("  ERREUR :", repr(e)); ok = False
        if not ok:
            time.sleep(PAUSE); navigateur(code)
    cartographie()
    print(f"\nPages enregistrées dans {OUT}/")
