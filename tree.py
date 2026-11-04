"""Arbre Domaine > Parcours > Formation > Établissement, et suggestions de parcours."""
import pandas as pd
from engine import FormationStats, position
from data import slug

# Parcoursup n'a pas de notion de « domaine » : classement par expressions régulières
# (à remplacer par la nomenclature Onisep). On cherche des MOTS entiers et non des
# morceaux de mots : « las » trouvait « classe », « ect » trouvait « secteur ».
# L'ordre compte : la première règle qui correspond l'emporte.
import re, unicodedata

DOMAINS = {
    "Santé et social": r"\bpass\b|licence_las|\bsante\b|sanitaire|medecine|infirm|kine|pharma|maieut|orthophon|\bifsi\b|psychomot|ergotherap|secteur social|\bd\.e\b",
    "Droit et sciences politiques": r"\bdroit\b|sciences politiques|\bsciences po\b|\biep\b|juridique",
    "Ingénierie et numérique": r"ingenieur|informatique|numerique|\bgenie\b|\b(mpsi|pcsi|mp2i|ptsi|tsi)\b|electronique|mecanique|\bsio\b",
    "Commerce et gestion": r"commerc|gestion|management|marketing|\bvente\b|comptab|\b(ecg|ect)\b|econom|\bdcg\b|negociation",
    "Lettres, langues et arts": r"lettres|langue|\barts?\b|design|dn made|histoire|philosophie|communication|hypokhagne|khagne",
    "Sciences": r"physique|chimie|biologie|mathematique|\bsvt\b|sciences",
}
_RX = {name: re.compile(rx) for name, rx in DOMAINS.items()}
DOMAIN_NAMES = list(DOMAINS) + ["Autres"]


def _norm(s) -> str:
    return unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()


def domain_of(row) -> str:
    text = _norm(f"{row.get('fili', '')} {row.get('form', '')} {row.get('detail', '')}")
    for name, rx in _RX.items():
        if rx.search(text):
            return name
    return "Autres"


def add_domains(df: pd.DataFrame) -> pd.DataFrame:
    """À appeler une fois au chargement des données."""
    df = df.copy()
    if "detail" not in df:
        df["detail"] = df["form"]
    df["detail"] = df["detail"].where(df["detail"] != "", df["form"])
    if "capa_fin" not in df:
        df["capa_fin"] = 0
    df["domain"] = df.apply(domain_of, axis=1)
    return df


def prepare(df, academie=None, query=None, domain=None, min_admits=1) -> pd.DataFrame:
    d = df if "domain" in df else add_domains(df)
    d = d[d["acc_tot"] >= min_admits]
    if academie and "academie" in d:
        d = d[d["academie"].str.lower() == academie.lower()]
    if domain:
        d = d[d["domain"] == domain]
    if query:
        q = query.lower()
        d = d[d["form"].str.lower().str.contains(q, regex=False)
              | d["detail"].str.lower().str.contains(q, regex=False)
              | d["school"].str.lower().str.contains(q, regex=False)]
    return d.copy()


def taux_of(g: pd.DataFrame):
    """Taux d'accès d'un groupe : moyenne des taux officiels pondérée par le nombre de candidats."""
    if "taux" not in g:
        return None
    ok = g[g["taux"].notna() & (g["voe_tot"] > 0)]
    return float((ok["taux"] * ok["voe_tot"]).sum() / ok["voe_tot"].sum()) if len(ok) else None


def stats_of(g: pd.DataFrame, name: str) -> FormationStats:
    return FormationStats(
        name=name, session=int(g["session"].max()),
        voe_tot=int(g["voe_tot"].sum()), acc_tot=int(g["acc_tot"].sum()),
        capa_fin=int(g["capa_fin"].sum()) if "capa_fin" in g else 0,
        neobac=int(g["neobac"].sum()) if "neobac" in g else 0,
        taux_acces=taux_of(g),
        admits_by_mention={"sans": int(g["m_sans"].sum()), "ab": int(g["m_ab"].sum()),
                           "b": int(g["m_b"].sum()), "tb": int(g["m_tb"].sum())})


def node(id_, type_, label, g, avg, current_session, children=None):
    s = stats_of(g, label)
    n = {"id": id_, "type": type_, "label": label, "n_children": len(children or []),
         "stats": {"voe_tot": s.voe_tot, "acc_tot": s.acc_tot, "capa_fin": s.capa_fin,
                   "admission_rate": None if s.admission_rate is None else round(s.admission_rate, 3),
                   "mentions": s.admits_by_mention}}
    if type_ in ("parcours", "formation", "etablissement") and avg is not None:
        n["position"] = position(avg, s, current_session).to_dict()
    if children is not None:
        n["children"] = children
    return n


def build_tree(df: pd.DataFrame, avg: float | None = None, academie: str | None = None,
               query: str | None = None, max_depth: int = 4, min_admits: int = 1,
               limit_formations: int | None = 50, max_schools: int | None = 5,
               domain: str | None = None) -> dict:
    """Arbre (tronqué à max_depth, limité aux N formations les plus peuplées).

    avg      : moyenne de l'élève (ajoute la zone sur chaque nœud) ; None = arbre neutre.
    academie : ne garde que les établissements de cette académie.
    domain   : ne garde qu'un domaine.
    query    : filtre texte sur formation et établissement.
    """
    d = prepare(df, academie, query, domain, min_admits)
    cs = int(df["session"].max())
    if limit_formations and len(d):
        top = d.groupby("detail")["acc_tot"].sum().nlargest(limit_formations).index
        d = d[d["detail"].isin(top)]

    keys = ["domain", "form", "detail", "school"]
    types = ["domaine", "parcours", "formation", "etablissement"]

    def build(group, level, path):
        if level >= len(keys) or level >= max_depth:
            return None
        out = []
        for value, g in group.groupby(keys[level], sort=True):
            label = value or "(non renseigné)"
            id_ = f"{path}/{slug(label)}" if path else slug(label)
            if types[level] == "etablissement":
                id_ = f"{path}/{g.iloc[0]['uai']}"
            out.append(node(id_, types[level], label, g, avg, cs, build(g, level + 1, id_)))
        out = sorted(out, key=lambda n: -n["stats"]["acc_tot"])
        if types[level] == "etablissement" and max_schools:
            out = out[:max_schools]
        return out

    root_kids = build(d, 0, "")
    return {"id": "root", "type": "racine", "label": "Après le bac",
            "n_children": len(root_kids or []), "children": root_kids or []}


def suggest(df: pd.DataFrame, avg: float, academie: str | None = None,
            domain: str | None = None, per_group: int = 6, min_admits: int = 20) -> dict:
    """Formations classées en 3 groupes selon la zone de l'élève :
    sure (cœur, confiance suffisante), edge (à la marge), below (ambitieuses)."""
    d = prepare(df, academie, None, domain, 1)
    cs = int(df["session"].max())
    out = {"sure": [], "edge": [], "below": []}
    for (dom, form, detail), g in d.groupby(["domain", "form", "detail"]):
        if g["acc_tot"].sum() < min_admits:
            continue
        s = stats_of(g, detail)
        r = type("R", (), {"detail": detail, "form": form, "domain": dom, "n_schools": g["uai"].nunique()})
        p = position(avg, s, cs)
        item = {"label": r.detail, "parcours": r.form, "domain": r.domain,
                "n_schools": int(r.n_schools), "acc_tot": s.acc_tot, "position": p.to_dict()}
        if p.zone == "core" and p.confidence != "faible":
            out["sure"].append(item)
        elif p.zone == "edge":
            out["edge"].append(item)
        elif p.zone == "below":
            out["below"].append(item)
    for k in out:
        out[k] = sorted(out[k], key=lambda i: -i["acc_tot"])[:per_group]
    return out
