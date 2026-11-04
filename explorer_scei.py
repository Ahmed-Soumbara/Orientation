"""Regarde à quoi ressemblent VRAIMENT les pages de statistiques du SCEI, pour régler scei.py
sur des faits (comme explorer_parcoursup.py pour les fiches Parcoursup).

    python explorer_scei.py           # année 2025
    python explorer_scei.py 2024

Ce qu'il fait (une requête par seconde au plus) :
  1. part de la page générale de l'année et du portail des statistiques, suit les liens « stat » du site ;
  2. enregistre chaque page dans le dossier explore_scei/ ;
  3. affiche, pour chaque page, ses tableaux (les 3 premières lignes) et ce que scei.py en comprend ;
  4. cherche Télécom SudParis dans les lignes reconnues.

Copie tout ce qui s'affiche et envoie-le.
"""
import re, sys
from pathlib import Path
import scei

OUT = Path(__file__).parent / "explore_scei"


def main(annee: int):
    OUT.mkdir(exist_ok=True)
    pages = scei.pages_stat(annee, log=print)
    print(f"\n{len(pages)} pages lues\n")
    toutes = []
    for i, (u, page) in enumerate(pages):
        nom = re.sub(r"[^A-Za-z0-9]+", "_", u.split("scei-concours.fr/")[-1])[:80] or f"page{i}"
        (OUT / f"{i:02d}_{nom}.html").write_text(page, encoding="utf-8")
        p = scei.lire_page(page)
        lignes = scei.parse_scei(page, u, annee)
        toutes += lignes
        print(f"== {u}\n   titre : {p.title.strip()[:100]!r}\n   {len(p.tables)} tableaux, {len(lignes)} lignes reconnues")
        liens = sorted(set(p.links))
        print(f"   {len(liens)} liens :")
        for l in liens[:80]:
            print("      ", l)
        for t in p.tables[:4]:
            print(f"   avant le tableau : {t['avant'][:120]!r}")
            for r in t["rows"][:3]:
                print("     ", r[:10])
        if lignes:
            print("   exemple reconnu :", {k: v for k, v in lignes[0].items() if k not in ("contexte", "url")})
        print()
    if any("iframe" in pg.lower() or "<script" in pg.lower() for _, pg in pages):
        print("Remarque : une page contient des scripts ou un cadre (iframe) : les liens peuvent être ajoutés par JavaScript.")
    ecoles = [r for r in toutes if r["niveau"] == "ecole"]
    print(f"TOTAL : {len(toutes)} lignes, dont {len(ecoles)} par école, "
          f"{len({r['ecole'] for r in ecoles})} écoles, filières : {sorted({r['filiere'] for r in toutes if r['filiere']})}")
    tsp = [r for r in ecoles if re.search(r"sud ?paris", scei.norm(r["ecole"]))]
    print(f"Télécom SudParis : {len(tsp)} lignes")
    for r in tsp:
        print("  ", {k: v for k, v in r.items() if k not in ("contexte", "url")})


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2025)
