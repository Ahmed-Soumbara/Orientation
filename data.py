"""Télécharge le jeu Parcoursup, le met en cache et le normalise.

À lancer par un job (cron / planificateur), JAMAIS à chaque connexion d'un utilisateur.
"""
import os, re, time
from pathlib import Path
import pandas as pd

# Endpoint d'export standard Opendatasoft (à vérifier au premier lancement).
URL = ("https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/"
       "datasets/fr-esr-parcoursup/exports/csv?delimiter=%3B&lang=fr")
CACHE = Path(os.environ.get("PSUP_CACHE", "data/parcoursup.parquet"))
MAX_AGE_DAYS = 30

# nom logique -> noms possibles dans le fichier (les colonnes changent selon les sessions)
COLS = {
    "session": ["session"],
    "uai": ["cod_uai"],
    "school": ["g_ea_lib_vx"],
    "dept": ["dep_lib"],
    "academie": ["acad_mies", "academie"],
    "region": ["region_etab_aff"],
    "city": ["ville_etab"],
    "fili": ["fili"],
    "form": ["form_lib_voe_acc"],
    "detail": ["fil_lib_voe_acc", "detail_forma"],
    "voe_tot": ["voe_tot"],
    "capa_fin": ["capa_fin"],
    "acc_tot": ["acc_tot"],
    "m_sans": ["acc_sansmention"],
    "m_ab": ["acc_ab"],
    "m_b": ["acc_b"],
    "m_tb": ["acc_tb"],
    "m_tbf": ["acc_tbf"],
    "link": ["lien_form_sup", "lien_form_psup"],
}
REQUIRED = ["session", "uai", "school", "form", "voe_tot", "acc_tot",
            "m_sans", "m_ab", "m_b", "m_tb"]


def download(dest: Path = CACHE, url: str = URL) -> Path:
    import requests   # utilise HTTPS_PROXY / REQUESTS_CA_BUNDLE si définis
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_suffix(".csv")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(raw, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    normalize(pd.read_csv(raw, sep=";", low_memory=False)).to_parquet(dest)
    return dest


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower() for c in df.columns]
    out, missing = {}, []
    for logical, options in COLS.items():
        hit = next((c for c in options if c in df.columns), None)
        if hit is None:
            if logical in REQUIRED:
                missing.append(options)
            continue
        out[logical] = df[hit]
    if missing:
        raise ValueError(f"Colonnes introuvables : {missing}. "
                         f"Colonnes du fichier : {sorted(df.columns)}")
    res = pd.DataFrame(out)
    for c in ["session", "voe_tot", "capa_fin", "acc_tot",
              "m_sans", "m_ab", "m_b", "m_tb", "m_tbf"]:
        if c in res:
            res[c] = pd.to_numeric(res[c], errors="coerce").fillna(0).astype(int)
    if "m_tbf" not in res:
        res["m_tbf"] = 0
    res["m_tb"] = res["m_tb"] + res["m_tbf"]          # TB + félicitations
    for c in ["form", "detail", "fili", "school"]:
        if c in res:
            res[c] = res[c].fillna("").astype(str).str.strip()
    res["fid"] = res["uai"].astype(str) + "|" + res.get("detail", res["form"]).map(slug)
    return res


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def load(force: bool = False) -> pd.DataFrame:
    stale = (not CACHE.exists()
             or time.time() - CACHE.stat().st_mtime > MAX_AGE_DAYS * 86400)
    if force or stale:
        download()
    return pd.read_parquet(CACHE)


if __name__ == "__main__":
    df = load(force=True)
    print(len(df), "formations,", df["session"].max(), "= dernière session")
