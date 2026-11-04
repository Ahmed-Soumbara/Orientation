"""Écoles d'ingénieurs après une prépa : statistiques publiées par le SCEI.

Parcoursup s'arrête à l'entrée dans le supérieur. Les écoles qui recrutent après deux ans de CPGE
(concours Mines-Ponts, Centrale-Supélec, CCINP, Mines-Télécom, e3a-Polytech…) passent par le SCEI,
qui publie chaque année des statistiques sur scei-concours.fr. Ce n'est pas de l'open data :
des pages HTML (exportées depuis un tableur), lues ici comme les fiches Parcoursup.

Vérifié le 4/11/2026 : https://www.scei-concours.fr/stat2025/stat_generale_2025.html contient un
tableau par année (2015 à 2025), une ligne par filière (MP, MPI, PC, PSI, PT, TSI, BCPST, TB, TPC),
colonnes Inscrits, Admissibles, Classés, Propositions, Entrés, Places, Remplissage, Places/Insc.
Le portail statistiques.html renvoie, par un script, vers stat2025/stat_sommaire_2025.html :
c'est le point de départ vers le détail par concours et par école (python explorer_scei.py pour le vérifier).

    python scei.py              # télécharge et écrit data/scei.csv
    python scei.py --annee 2025

Module autonome (pas d'import de sources.py) pour éviter un import circulaire :
sources.py l'enregistre dans SOURCES.
"""
import csv, html, os, re, sys, time, unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

DATA = Path(os.environ.get("DATA_DIR", "data"))
SCEI_FILE = DATA / "scei.csv"
BASE = "https://www.scei-concours.fr/"
HUB = BASE + "statistiques.html"
GENERALE = BASE + "stat{a}/stat_generale_{a}.html"
# Sommaire de l'année : le portail statistiques.html y renvoie par un script (vu le 4/11/2026)
SOMMAIRE = BASE + "stat{a}/stat_sommaire_{a}.html"
UA = {"User-Agent": "OrientationLycee/0.1 (projet etudiant IMT-BS/TSP/ENSIIE, lecture ponctuelle des statistiques publiques)"}
PAUSE = 1.0
MAX_PAGES = 120

FILIERES = ["MPI", "MP", "PC", "PSI", "PT", "TSI", "BCPST", "TB", "TPC", "ATS"]
RX_FIL = re.compile(r"(?<![A-Za-z])(" + "|".join(FILIERES) + r")(?![A-Za-z])")
# Noms de colonnes possibles -> nom propre. Si le SCEI en change un, ajouter la variante ici.
COLS = {
    "inscrits": ["inscrits", "inscrit", "nb inscrits"],
    "admissibles": ["admissibles", "admissible"],
    "classes": ["classes", "classe", "nb classes"],
    "propositions": ["propositions", "proposition", "appeles"],
    "entres": ["entres", "integres", "entree", "entres/integres"],
    "places": ["places", "nb places", "places offertes"],
    "rang_median": ["rang median", "rang moyen", "median"],
    "rang_dernier": ["rang du dernier", "rang dernier", "dernier appele", "rang du dernier appele", "rang du dernier entre"],
}
COL_ECOLE = ["ecole", "ecoles", "etablissement", "nom de l'ecole", "ecole / concours", "intitule"]
SAUTER = re.compile(r"^(totaux?|total|ensemble|inter[- ]?filieres?|tous concours)")


def norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()


def num(x):
    s = re.sub(r"[\s  %]", "", str(x or "")).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


class _Pages(HTMLParser):
    """Tableaux d'une page (cellules fusionnées répétées), titre, liens, et le texte qui précède
    chaque tableau (le nom du concours ou de la filière y est souvent écrit)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.links, self.title, self.texte = [], [], "", []
        self._t = self._r = self._c = None
        self._span = 1
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "table":
            self._t = {"rows": [], "avant": " | ".join(t for t in self.texte[-3:] if t)}
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c, self._span = [], max(1, int(a.get("colspan", "1") or 1) if str(a.get("colspan", "1")).isdigit() else 1)
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._c is not None:
            v = re.sub(r"\s+", " ", "".join(self._c)).strip()
            self._r.extend([v] * self._span)
            self._c = None
        elif tag == "tr" and self._r is not None:
            if any(self._r):
                self._t["rows"].append(self._r)
            self._r = None
        elif tag == "table" and self._t is not None:
            self.tables.append(self._t)
            self._t = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, d):
        if self._skip:
            return
        if self._c is not None:
            self._c.append(d)
        elif self._in_title:
            self.title += d
        elif self._t is None and d.strip():
            self.texte.append(re.sub(r"\s+", " ", d).strip())


def lire_page(page: str) -> _Pages:
    p = _Pages()
    p.feed(page)
    return p


def _colonne(h):
    """Nom exact d'abord ; le début du nom seulement pour les intitulés longs (« Rang du dernier appelé MP »).
    « Places/Insc. » n'est donc pas pris pour « Places »."""
    n = norm(h).rstrip(" .")
    for k, vs in COLS.items():
        if n in vs:
            return k
    for k, vs in COLS.items():
        if any(" " in v and n.startswith(v) for v in vs):
            return k
    return None


def parse_scei(page: str, url: str = "", annee: int | None = None) -> list[dict]:
    """Toutes les lignes utiles d'une page de statistiques SCEI.
    niveau = « ecole » (une école, une filière) ou « filiere » (toutes écoles confondues)."""
    p = lire_page(page)
    m = re.search(r"(20\d\d)", url) or re.search(r"(20\d\d)", p.title)
    annee_page = annee or (int(m.group(1)) if m else None)
    out = []
    for t in p.tables:
        contexte = " | ".join(x for x in (p.title.strip(), t["avant"]) if x)
        m_an = re.findall(r"(20\d\d)", t["avant"])
        an = int(m_an[-1]) if m_an else annee_page
        # La filière vient d'abord de l'adresse (stat2025/mp.html), le texte de la page pouvant en citer d'autres
        fil_ctx = RX_FIL.search(url.rsplit("/", 1)[-1].upper()) or RX_FIL.search(p.title) or RX_FIL.search(t["avant"])
        cols, lab, concours = None, 0, ""
        for r in t["rows"]:
            pleines = [x for x in r if x.strip()]
            # Ligne d'année (« 2025 ») : les lignes suivantes appartiennent à cette session
            if pleines and all(re.fullmatch(r"20\d\d", x.strip()) for x in pleines):
                an = int(pleines[0]); continue
            # Ligne de concours (« Banque ECOLE POLYTECHNIQUE - interENS ») : même texte sur toute la ligne, sans chiffre
            if pleines and len(set(pleines)) == 1 and num(pleines[0]) is None and _colonne(pleines[0]) is None:
                concours = pleines[0].strip(); continue
            # Ligne d'en-tête : au moins deux noms de colonnes connus (elle peut se répéter à chaque année)
            if len({_colonne(x) for x in r} - {None}) >= 2:
                cols, pris = {}, set()
                for j, h in enumerate(r):          # une colonne par nom : la première rencontrée
                    k = _colonne(h)
                    if k and k not in pris:
                        cols[j] = k; pris.add(k)
                lab = next((j for j, h in enumerate(r) if norm(h) in COL_ECOLE), 0)
                continue
            if cols is None:
                continue
            nom = (r[lab] if lab < len(r) else "").strip()
            if not nom or SAUTER.match(norm(nom)):
                continue
            vals = {k: num(r[j]) for j, k in cols.items() if j < len(r)}
            if not any(v is not None for v in vals.values()):
                continue
            est_fil = nom.upper() in FILIERES
            out.append({"annee": an, "niveau": "filiere" if est_fil else "ecole",
                        "filiere": nom.upper() if est_fil else (fil_ctx.group(1) if fil_ctx else ""),
                        "ecole": "" if est_fil else nom, "concours": concours, "contexte": contexte[:200], "url": url,
                        **{k: vals.get(k) for k in COLS}})
    return out


def _get(url):
    import requests
    r = requests.get(url, headers=UA, timeout=(15, 60))
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def pages_stat(annee: int, pause: float = PAUSE, max_pages: int = MAX_PAGES, log=print):
    """Pages de statistiques de l'année : la page générale, le portail, puis les liens qui en partent
    (même site, adresse contenant « stat »). Une requête par seconde au plus."""
    vues, file, out = set(), [SOMMAIRE.format(a=annee), GENERALE.format(a=annee), HUB], []
    while file and len(out) < max_pages:
        u = file.pop(0)
        if u in vues:
            continue
        vues.add(u)
        try:
            page = _get(u)
        except Exception as e:
            log(f"   {u} : {type(e).__name__} {e}"[:200])
            continue
        out.append((u, page))
        # Liens HTML, plus les adresses écrites dans les scripts (le menu du portail est construit en JavaScript)
        dans_scripts = re.findall(r"""[\w./-]*stat20\d\d/[\w./-]+\.(?:html?|php)""", page)
        for href in lire_page(page).links + dans_scripts:
            v = urljoin(u, href).split("#")[0]
            if urlparse(v).netloc.endswith("scei-concours.fr") and "stat" in v.lower() and v not in vues \
                    and re.search(r"\.(html?|php)$", v) and (str(annee) in v or u == HUB):
                file.append(v)
        time.sleep(pause)
    return out


def fetch_scei(annee: int | None = None) -> Path:
    """Dernière session publiée. Les statistiques d'une session ne sont pas toujours en ligne
    (le 4/11/2026, stat2026 répondait 401) : on recule d'un an tant qu'aucun tableau n'est trouvé."""
    debut = annee or int(os.environ.get("SCEI_ANNEE", time.localtime().tm_year))
    rows, essais = [], []
    for a in range(debut, debut - 3, -1):
        for u, page in pages_stat(a):
            rows += parse_scei(page, u, a)
        essais.append(a)
        if rows:
            break
    if not rows:
        raise RuntimeError(f"Aucun tableau reconnu pour {essais}. Lancer python explorer_scei.py et ajuster COLS.")
    DATA.mkdir(parents=True, exist_ok=True)
    champs = ["annee", "niveau", "filiere", "ecole", "concours", *COLS, "contexte", "url"]
    with SCEI_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in champs})
    return SCEI_FILE


def load_scei() -> list[dict]:
    """Lignes de data/scei.csv, nombres convertis, vides -> None. Liste vide si le fichier manque.
    Le contexte (texte de la page) n'est pas renvoyé au site : seul le concours sert."""
    if not SCEI_FILE.exists():
        return []
    with SCEI_FILE.open(encoding="utf-8") as f:
        out = []
        for r in csv.DictReader(f, delimiter=";"):
            for k in ("annee", *COLS):
                r[k] = num(r.get(k))
            r["annee"] = int(r["annee"]) if r["annee"] else None
            out.append({k: (v if v != "" else None) for k, v in r.items() if k != "contexte"})
    return out


if __name__ == "__main__":
    a = int(sys.argv[sys.argv.index("--annee") + 1]) if "--annee" in sys.argv else None
    p = fetch_scei(a)
    rows = load_scei()
    print(f"{p} : {len(rows)} lignes, dont {sum(1 for r in rows if r['niveau'] == 'ecole')} par école")
