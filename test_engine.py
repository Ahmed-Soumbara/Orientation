import pandas as pd
from data import normalize
from engine import FormationStats, position, mention_from_average
from tree import build_tree


def fake_raw():
    rows = [
        # session, uai, école, formation, détail, fili, voe, capa, acc, sans, ab, b, tb
        (2025, "U1", "IUT A", "BUT - Services", "BUT Techniques de commercialisation", "BUT", 1200, 100, 100, 30, 45, 20, 5),
        (2025, "U2", "IUT B", "BUT - Services", "BUT Techniques de commercialisation", "BUT", 900, 80, 80, 20, 35, 20, 5),
        (2025, "U3", "Lycée H4", "Classe préparatoire économique", "CPGE ECG", "CPGE", 3000, 40, 40, 0, 2, 10, 28),
        (2025, "U4", "Petit lycée", "Classe préparatoire économique", "CPGE ECG", "CPGE", 100, 10, 8, 0, 1, 2, 3),
    ]
    cols = ["session", "cod_uai", "g_ea_lib_vx", "form_lib_voe_acc", "fil_lib_voe_acc", "fili",
            "voe_tot", "capa_fin", "acc_tot", "acc_sansmention", "acc_ab", "acc_b", "acc_tb"]
    df = pd.DataFrame(rows, columns=cols)
    df["acad_mies"] = "Paris"
    return df


def test_mentions():
    assert [mention_from_average(x) for x in (10, 12.5, 15, 17)] == ["sans", "ab", "b", "tb"]


def test_zones_match_spec_persona():
    # Inès : moyenne 12,5 -> BUT TC dans le cœur, prépa ECG en dessous.
    df = normalize(fake_raw())
    t = build_tree(df, avg=12.5)
    by_label = {}
    def walk(n):
        by_label[n["label"]] = n
        for c in n.get("children", []):
            walk(c)
    walk(t)
    assert by_label["BUT Techniques de commercialisation"]["position"]["zone"] == "core"
    assert by_label["CPGE ECG"]["position"]["zone"] == "below"


def test_confidence_drops_with_few_admits():
    f = FormationStats("x", 2025, voe_tot=50, acc_tot=8, admits_by_mention={"ab": 8})
    assert position(12.5, f, 2025).confidence == "faible"


def test_no_data_is_unknown():
    f = FormationStats("x", 2025, voe_tot=0, acc_tot=0)
    assert position(15, f, 2025).zone == "unknown"


def test_limit_formations_and_schools():
    df = normalize(fake_raw())
    t = build_tree(df, avg=12.5, limit_formations=1, max_schools=1)
    forms, schools = [], []
    def walk(n):
        if n["type"] == "formation": forms.append(n)
        if n["type"] == "etablissement": schools.append(n)
        for c in n.get("children", []): walk(c)
    walk(t)
    assert len(forms) == 1
    assert len(schools) == 1


def test_suggest_groups():
    from tree import suggest
    df = normalize(fake_raw())
    r = suggest(df, 12.5, min_admits=1)
    assert [i["label"] for i in r["sure"]] == ["BUT Techniques de commercialisation"]
    assert [i["label"] for i in r["below"]] == ["CPGE ECG"]


def test_api_endpoints():
    import api
    from fastapi.testclient import TestClient
    from tree import add_domains
    api.STATE["df"] = add_domains(normalize(fake_raw()))
    api.STATE.update(session=2025, academies=["Paris"])
    c = TestClient(api.app)
    assert c.get("/api/meta").json()["academies"] == ["Paris"]
    t = c.get("/api/tree", params={"avg": 12.5, "q": "cpge (ecg)"}).json()
    assert t["children"] == []                    # recherche avec parenthèses : pas d'erreur regex
    t = c.get("/api/tree", params={"avg": 12.5, "q": "cpge"}).json()
    assert t["children"][0]["children"][0]["position"]["zone"] == "below"
    s = c.get("/api/suggest", params={"avg": 12.5, "n": 3}).json()
    assert set(s) == {"sure", "edge", "below"}
    assert c.get("/").status_code == 200           # le site est servi à la racine


def test_raw_csv_and_site(tmp_path, monkeypatch):
    import api, data
    from fastapi.testclient import TestClient
    monkeypatch.setattr(data, "CACHE", tmp_path / "p.parquet")
    c = TestClient(api.app)
    assert c.get("/api/raw.csv").status_code == 404
    (tmp_path / "p.csv").write_text("session;lib_for_voe_ins;taux_acces_ens\n2025;BUT GEA;40\n", encoding="utf-8")
    r = c.get("/api/raw.csv")
    assert r.status_code == 200 and "BUT GEA" in r.text
    assert "loadServer" in c.get("/").text
