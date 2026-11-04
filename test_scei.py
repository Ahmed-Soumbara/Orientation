"""Tests sans réseau du connecteur SCEI (écoles après une prépa)."""
from pathlib import Path
import scei

PAGE = (Path(__file__).parent / "fixtures" / "scei_exemple.html").read_text(encoding="utf-8")


def test_parse_ecoles_et_filieres():
    rows = scei.parse_scei(PAGE, "https://www.scei-concours.fr/stat2025/cmt_mp.html")
    ecoles = [r for r in rows if r["niveau"] == "ecole"]
    fil = [r for r in rows if r["niveau"] == "filiere"]
    assert [r["ecole"] for r in ecoles] == ["Télécom SudParis", "Ecole fictive de test"]   # « Totaux » sauté
    tsp = ecoles[0]
    assert tsp["filiere"] == "MP" and tsp["annee"] == 2025
    assert tsp["inscrits"] == 5509 and tsp["entres"] == 82 and tsp["places"] == 90
    assert tsp["admissibles"] is None                      # case vide : pas de zéro inventé
    assert tsp["concours"] == "Concours Mines-Télécom"     # ligne de concours dans le tableau
    assert [r["filiere"] for r in fil] == ["MP"]            # « Inter-Filière » sauté
    assert fil[0]["places"] == 3100                         # pas la colonne « Places/Insc. »


def test_load_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(scei, "SCEI_FILE", tmp_path / "scei.csv")
    assert scei.load_scei() == []


def test_api_scei(tmp_path, monkeypatch):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(scei, "SCEI_FILE", tmp_path / "scei.csv")
    c = TestClient(api.app)
    assert c.get("/api/scei").json() == []


def test_recule_d_un_an_si_session_absente(tmp_path, monkeypatch):
    monkeypatch.setattr(scei, "SCEI_FILE", tmp_path / "scei.csv")
    monkeypatch.setattr(scei, "DATA", tmp_path)
    vues = []
    def pages(a, **kw):
        vues.append(a)
        return [] if a == 2026 else [(f"https://www.scei-concours.fr/stat{a}/x.html", PAGE)]
    monkeypatch.setattr(scei, "pages_stat", pages)
    scei.fetch_scei(2026)
    assert vues == [2026, 2025] and len(scei.load_scei()) == 3


GENERALE = """<html><head><style>body,div,table { font-family:"Liberation Sans" }</style></head><body><table>
<tr><td colspan="5">Tous Concours confondus :</td><td></td></tr>
<tr><td>2025</td><td></td><td></td></tr>
<tr><td></td><td>Inscrits</td><td>Admissibles</td><td>Classés</td><td>Propositions</td><td>Entrés</td><td>Places</td><td>Remplissage</td><td>Places/Insc.</td></tr>
<tr><td>MP</td><td>8495</td><td>7074</td><td>6500</td><td>6062</td><td>4198</td><td>4699</td><td>89%</td><td>55%</td></tr>
<tr><td>Inter-Filière (MP,PC,PSI)</td><td></td><td></td><td></td><td></td><td></td><td>1643</td><td></td><td></td></tr>
<tr><td>2024</td><td></td><td></td></tr>
<tr><td></td><td>Inscrits</td><td>Admissibles</td><td>Classés</td><td>Propositions</td><td>Entrés</td><td>Places</td><td>Remplissage</td><td>Places/Insc.</td></tr>
<tr><td>MP</td><td>8300</td><td>7000</td><td>6400</td><td>6000</td><td>4100</td><td>4600</td><td>89%</td><td>55%</td></tr>
<tr><td>Totaux</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td></td><td></td></tr>
</table></body></html>"""


def test_page_generale_annees_en_lignes():
    rows = scei.parse_scei(GENERALE, "https://www.scei-concours.fr/stat2025/stat_generale_2025.html")
    assert [(r["annee"], r["niveau"], r["filiere"], r["places"]) for r in rows] == [(2025, "filiere", "MP", 4699), (2024, "filiere", "MP", 4600)]
    assert "font-family" not in rows[0]["contexte"]          # le CSS n'est pas pris pour du texte
