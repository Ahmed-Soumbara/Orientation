"""Arbre Domaine > Parcours > Formation > Établissement, et suggestions de parcours."""
import pandas as pd
from engine import FormationStats, position
from data import slug

# Parcoursup n'a pas de notion de « domaine » : classement par mots-clés (à affiner avec l'Onisep).
DOMAINS = {
    "Commerce et gestion": ["commerc", "gestion", "management", "marketing", "vente", "comptab", "ecg", "ecs", "ect", "économie"],
    "Ingénierie et numérique": ["ingénieur", "ingenieur", "informatique", "numérique", "génie", "mpsi", "pcsi", "mp2i", "ptsi", "électronique", "mécanique"],
    "Santé et social": ["santé", "sante", "infirm", "pass", "las", "kiné", "paramédical", "social", "médecine"],
    "Droit et sciences politiques": ["droit", "politique", "iep", "sciences po"],
    "Lettres, langues et arts": ["lettres", "langue", "arts", "design", "histoire", "philosophie", "communication", "hypokhâgne", "khâgne"],
    "Sciences": ["physique", "chimie", "biologie", "mathématiques", "svt", "sciences"],
}
DOMAIN_NAMES = list(DOMAINS) + ["Autres"]


def domain_of(row) -> str:
    text = f"{row.get('form', '')} {row.get('detail', '')} {row.get('fili', '')}".lower()
    for name, keys in DOMAINS.items():
        if any(k in text for k in keys):
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


def stats_of(g: pd.DataFrame, name: str) -> FormationStats:
    return FormationStats(
        name=name, session=int(g["session"].max()),
        voe_tot=int(g["voe_tot"].sum()), acc_tot=int(g["acc_tot"].sum()),
        capa_fin=int(g["capa_fin"].sum()) if "capa_fin" in g else 0,
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
    agg = (d.groupby(["domain", "form", "detail"])
             .agg(session=("session", "max"), voe_tot=("voe_tot", "sum"), acc_tot=("acc_tot", "sum"),
                  capa_fin=("capa_fin", "sum"), m_sans=("m_sans", "sum"), m_ab=("m_ab", "sum"),
                  m_b=("m_b", "sum"), m_tb=("m_tb", "sum"), n_schools=("uai", "nunique"))
             .reset_index())
    out = {"sure": [], "edge": [], "below": []}
    for r in agg.itertuples(index=False):
        if r.acc_tot < min_admits:
            continue
        s = FormationStats(name=r.detail, session=int(r.session), voe_tot=int(r.voe_tot),
                           acc_tot=int(r.acc_tot), capa_fin=int(r.capa_fin),
                           admits_by_mention={"sans": int(r.m_sans), "ab": int(r.m_ab),
                                              "b": int(r.m_b), "tb": int(r.m_tb)})
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
