"""Moteur de positionnement : situe un élève par rapport aux admis d'une formation.

Ce moteur ne calcule PAS une probabilité d'admission individuelle : les données
Parcoursup sont agrégées (pas de dossiers individuels). Il renvoie des statistiques
vérifiables, une zone, un niveau de confiance et les limites.
"""
from dataclasses import dataclass, field, asdict

MENTIONS = ["sans", "ab", "b", "tb"]          # tb = très bien et félicitations
RANK = {m: i for i, m in enumerate(MENTIONS)}
LABELS = {"sans": "sans mention", "ab": "assez bien", "b": "bien", "tb": "très bien"}

# Seuils à calibrer sur les vraies données (placeholders).
CORE_SHARE = 0.50      # ton niveau >= celui de 50 % des admis -> cœur
EDGE_SHARE = 0.15      # >= 15 % des admis -> marge, sinon en dessous
RATE_VERY_SELECTIVE = 0.15
RATE_SELECTIVE = 0.50
MIN_ADMITS_HIGH, MIN_ADMITS_MEDIUM = 60, 20

LIMITS = ("Appréciations des professeurs, lettre de motivation, lycée d'origine "
          "et critères propres à chaque commission.")


def mention_from_average(avg: float) -> str:
    """Mention probable au bac (seuils de la spec)."""
    if avg < 12:
        return "sans"
    if avg < 14:
        return "ab"
    if avg < 16:
        return "b"
    return "tb"


@dataclass
class FormationStats:
    """Effectifs agrégés d'une formation (ou d'un groupe d'établissements)."""
    name: str
    session: int
    voe_tot: int = 0                 # candidats
    acc_tot: int = 0                 # admis (ont accepté la proposition)
    capa_fin: int = 0                # places
    admits_by_mention: dict = field(default_factory=dict)   # {"sans":n,"ab":n,"b":n,"tb":n}
    source: str = "Open data Parcoursup"

    @property
    def n_known(self) -> int:
        return sum(self.admits_by_mention.get(m, 0) for m in MENTIONS)

    @property
    def admission_rate(self):
        """Admis / candidats. Approximation du taux d'accès, PAS le taux officiel."""
        return self.acc_tot / self.voe_tot if self.voe_tot else None

    @property
    def pressure(self):
        """Candidats par place."""
        return self.voe_tot / self.capa_fin if self.capa_fin else None

    def share_at_or_below(self, mention: str):
        """Part des admis dont la mention est inférieure ou égale à celle de l'élève.
        Élevée = l'élève est au moins aussi bon que la plupart des admis."""
        if not self.n_known:
            return None
        at_or_below = sum(self.admits_by_mention.get(m, 0)
                          for m in MENTIONS if RANK[m] <= RANK[mention])
        return at_or_below / self.n_known


def selectivity(f: FormationStats) -> str:
    r = f.admission_rate
    if r is None:
        return "inconnue"
    if r < RATE_VERY_SELECTIVE:
        return "très sélective"
    if r < RATE_SELECTIVE:
        return "sélective"
    return "accessible"


def confidence(f: FormationStats, current_session: int) -> tuple[str, list[str]]:
    reasons, level = [], 2          # 2 = élevé, 1 = moyen, 0 = faible
    if f.n_known < MIN_ADMITS_MEDIUM:
        level = 0
        reasons.append(f"seulement {f.n_known} admis avec mention connue")
    elif f.n_known < MIN_ADMITS_HIGH:
        level = min(level, 1)
        reasons.append(f"{f.n_known} admis seulement")
    if f.session < current_session - 1:
        level = max(level - 1, 0)
        reasons.append(f"données de la session {f.session}")
    if f.n_known < 0.8 * f.acc_tot:
        level = max(level - 1, 0)
        reasons.append("mention inconnue pour une part des admis")
    return ["faible", "moyen", "élevé"][level], reasons


@dataclass
class Position:
    zone: str                  # core | edge | below | unknown
    message: str
    confidence: str
    confidence_reasons: list
    selectivity: str
    student_mention: str
    share_at_or_below: float | None
    admission_rate: float | None
    n_admits: int
    source: str
    limits: str = LIMITS

    def to_dict(self):
        return asdict(self)


MESSAGES = {
    "core": "Ton niveau correspond à celui de la plupart des admis de l'an dernier.",
    "edge": "Une partie des admis avait ton profil, mais la plupart avaient une mention plus élevée.",
    "below": "Peu d'admis avaient ta mention probable : voici ce qui ferait la différence.",
    "unknown": "Les données publiques sont insuffisantes pour te situer sur cette formation.",
}


def position(avg: float, f: FormationStats, current_session: int) -> Position:
    mention = mention_from_average(avg)
    share = f.share_at_or_below(mention)
    if share is None:
        zone = "unknown"
    elif share >= CORE_SHARE:
        zone = "core"
    elif share >= EDGE_SHARE:
        zone = "edge"
    else:
        zone = "below"
    conf, reasons = confidence(f, current_session)
    return Position(
        zone=zone, message=MESSAGES[zone], confidence=conf, confidence_reasons=reasons,
        selectivity=selectivity(f), student_mention=LABELS[mention],
        share_at_or_below=None if share is None else round(share, 3),
        admission_rate=None if f.admission_rate is None else round(f.admission_rate, 3),
        n_admits=f.acc_tot, source=f"{f.source}, session {f.session}, {f.acc_tot} admis")
