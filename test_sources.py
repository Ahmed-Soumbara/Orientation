"""Tests des connecteurs, sans réseau : chaque parseur reçoit un extrait au format du producteur."""
import io, json, zipfile
import pandas as pd
import sources


def test_commune_key():
    assert sources.commune_key("Paris 14e  Arrondissement") == "paris"
    assert sources.commune_key("Évry-Courcouronnes") == "evry courcouronnes"
    assert sources.commune_key("Lyon 3e Arrondissement") == "lyon"


def test_parse_insersup_keeps_national_diplomes_latest_promo():
    df = pd.DataFrame([
        # national, ensemble, diplômé, dernière promo : gardé
        {"promo": "2022", "type_diplome_long": "Master LMD", "libelle_diplome": "Droit privé", "dom_lib": "Droit",
         "discipli_lib": "Droit", "uo_lib": "National", "genre": "ensemble", "nationalite": "ensemble",
         "obtention_diplome": "diplômé", "regime_inscription": "ensemble",
         "tx_sortants_en_emploi_sal_fr_12": "71,5", "tx_sortants_en_emploi_sal_fr_30": "82", "salaire_q2_12": "1900",
         "salaire_q2_30": "2150", "nb_sortants_12": "1200"},
        # femmes seulement : écarté
        {"promo": "2022", "type_diplome_long": "Master LMD", "libelle_diplome": "Droit privé", "uo_lib": "National",
         "genre": "femme", "nationalite": "ensemble", "obtention_diplome": "diplômé",
         "tx_sortants_en_emploi_sal_fr_12": "70", "tx_sortants_en_emploi_sal_fr_30": "nd", "salaire_q2_12": "nd", "salaire_q2_30": "nd"},
        # promo plus ancienne : écartée
        {"promo": "2021", "type_diplome_long": "Master LMD", "libelle_diplome": "Droit privé", "uo_lib": "National",
         "genre": "ensemble", "nationalite": "ensemble", "obtention_diplome": "diplômé",
         "tx_sortants_en_emploi_sal_fr_12": "60", "tx_sortants_en_emploi_sal_fr_30": "70", "salaire_q2_12": "1800", "salaire_q2_30": "2000"},
    ])
    out = sources.parse_insersup(df)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["taux_emploi_12"] == 71.5 and r["salaire_30"] == 2150 and r["type"] == "Master LMD"


def test_parse_loyers_decimal_comma_and_key():
    df = pd.DataFrame({"INSEE_C": ["91228", "75114"], "LIBGEO": ["Évry-Courcouronnes", "Paris 14e Arrondissement"],
                       "DEP": ["91", "75"], "loypredm2": ["17,4", "30,1"], "nbobs_com": ["120", "900"]})
    out = sources.parse_loyers(df)
    assert list(out["cle"]) == ["evry courcouronnes", "paris"]
    assert out.iloc[0]["loyer_m2"] == 17.4 and out.iloc[1]["dep"] == "75"


def test_parse_metiers_xml_in_zip():
    xml = """<metiers><metier><identifiant>MET.7</identifiant><nom_metier>Avocat / Avocate</nom_metier>
      <accroche_metier>Conseiller et défendre.</accroche_metier><niveau_acces_min><libelle>Bac + 5</libelle></niveau_acces_min>
      <formations_min_requise><formation_min_requise><libelle>Master de droit</libelle></formation_min_requise></formations_min_requise>
      <secteurs_activite><secteur_activite><libelle>Droit</libelle></secteur_activite></secteurs_activite></metier>
      <metier><identifiant>MET.8</identifiant><nom_metier>Infirmier / Infirmière</nom_metier><niveau_acces_min><libelle>Bac + 3</libelle></niveau_acces_min></metier></metiers>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fiches.xml", xml)
    rows = sources.parse_metiers_xml(buf.getvalue())
    assert [r["nom"] for r in rows] == ["Avocat / Avocate", "Infirmier / Infirmière"]
    assert rows[0]["niveau"] == "Bac + 5" and "Master de droit" in rows[0]["formations"]


def test_parse_apprentissage_real_shape():
    # Extrait de la vraie réponse de /api/formation/v1/search (4/11/2026), intitulé ajouté sous « certification ».
    f = {"identifiant": {"cle_ministere_educatif": "X"},
         "certification": {"valeur": {"intitule": {"cfd": {"long": "BTS NEGOCIATION ET DIGITALISATION DE LA RELATION CLIENT"}}}},
         "formateur": {"organisme": {"identifiant": {"uai": "0410018X"}, "etablissement": {"enseigne": "LEGTA DE VENDOME",
            "adresse": {"commune": {"nom": "Areines", "code_insee": "41003"}, "departement": {"code_insee": "41"}},
            "geopoint": {"coordinates": [1.09, 47.79]}}}}}
    out = sources.parse_apprentissage([f])
    r = out.iloc[0]
    assert r["dep"] == "41" and r["uai"] == "0410018X" and r["lat"] == 47.79
    assert r["cle"].startswith("bts negociation")


def test_parse_apprentissage_finds_intitule_anywhere():
    out = sources.parse_apprentissage([{"autre": {"bloc": [{"intitule_long": "BUT INFORMATIQUE"}]}}])
    assert out.iloc[0]["intitule"] == "BUT INFORMATIQUE"


def test_parse_inserjeunes_keeps_latest_year():
    df = pd.DataFrame([
        {"annee": "cumul 2020-2021", "uai": "0351878B", "libelle": "Lycée Coetlogon", "region": "BRETAGNE", "examen": "BTS",
         "taux_poursuite_etudes": "40", "taux_emploi_6_mois": "50", "taux_emploi_12_mois": "60", "taux_emploi_24_mois": "70"},
        {"annee": "cumul 2021-2022", "uai": "0351878B", "libelle": "Lycée Coetlogon", "region": "BRETAGNE", "examen": "BTS",
         "taux_poursuite_etudes": "38", "taux_emploi_6_mois": "52", "taux_emploi_12_mois": "63", "taux_emploi_24_mois": "71"},
        {"annee": "cumul 2021-2022", "uai": "0351878B", "libelle": "Lycée Coetlogon", "region": "BRETAGNE", "examen": "BAC PRO",
         "taux_poursuite_etudes": "57", "taux_emploi_6_mois": "41", "taux_emploi_12_mois": "53", "taux_emploi_24_mois": "55"}])
    out = sources.parse_inserjeunes(df)
    bts = out[out["examen"] == "BTS"].iloc[0]
    assert len(out) == 2 and bts["annee"] == "cumul 2021-2022" and bts["taux_emploi_12_mois"] == 63


def test_load_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('# clés\nAPPRENTISSAGE_TOKEN="abc"\n', encoding="utf-8")
    monkeypatch.delenv("APPRENTISSAGE_TOKEN", raising=False)
    sources.load_env(tmp_path / ".env")
    import os
    assert os.environ["APPRENTISSAGE_TOKEN"] == "abc"


def test_reference_files_are_valid():
    b = sources.load_baremes()
    assert b["droits"]["licence"] == 178 and "0bis" in b["bourses"]["montants"]
    assert not hasattr(sources, "load_frais")  # frais des écoles privées retirés (v13)


def test_refresh_all_reports_failures_without_crashing(monkeypatch):
    def boom():
        raise ConnectionError("hors ligne")
    monkeypatch.setitem(sources.SOURCES["loyers"], "fetch", boom)
    r = sources.refresh_all(["loyers"])
    assert r["loyers"]["ok"] is False and "hors ligne" in r["loyers"]["erreur"]


def test_api_sources_endpoints(tmp_path, monkeypatch):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(sources, "LOYERS_FILE", tmp_path / "loyers.csv")
    monkeypatch.setattr(sources, "METIERS_FILE", tmp_path / "metiers.json")
    c = TestClient(api.app)
    assert c.get("/api/loyers").json() == {}
    sources.parse_loyers(pd.DataFrame({"LIBGEO": ["Évry-Courcouronnes"], "DEP": ["91"], "loypredm2": ["17,4"]})) \
        .to_csv(tmp_path / "loyers.csv", sep=";", index=False)
    assert c.get("/api/loyers").json() == {"91|evry courcouronnes": 17.4}
    (tmp_path / "metiers.json").write_text(json.dumps([{"nom": "Avocat / Avocate"}, {"nom": "Infirmier"}]), encoding="utf-8")
    assert [m["nom"] for m in c.get("/api/metiers", params={"q": "avoc"}).json()] == ["Avocat / Avocate"]
    assert c.get("/api/baremes").json()["droits"]["licence"] == 178
    assert {s["id"] for s in c.get("/api/sources").json()} >= {"insersup", "loyers", "metiers", "communes", "baremes"}



def test_insersup_falls_back_to_full_export_when_filter_is_empty(monkeypatch, tmp_path):
    calls = []
    full = ("promo;type_diplome_long;libelle_diplome;uo_lib;genre;nationalite;obtention_diplome;"
            "tx_sortants_en_emploi_sal_fr_12;tx_sortants_en_emploi_sal_fr_30;salaire_q2_12;salaire_q2_30\n"
            "2022;Master LMD;Droit;National;ensemble;ensemble;diplômé;71;82;1900;2150\n").encode()
    empty = full.split(b"\n")[0] + b"\n"
    class R:
        def __init__(self, c): self.content = c
    def fake_get(url, **kw):
        calls.append(kw.get("params"))
        return R(empty if kw.get("params") else full)
    monkeypatch.setattr(sources, "_get", fake_get)
    monkeypatch.setattr(sources, "INSERSUP_FILE", tmp_path / "insersup.csv")
    sources.fetch_insersup()
    assert calls[0] == {"where": sources.INSERSUP_WHERE} and calls[1] is None
    assert len(pd.read_csv(tmp_path / "insersup.csv", sep=";")) == 1


def test_parse_apprentissage_uses_real_place_and_rome():
    f = {"certification": {"valeur": {"intitule": {"cfd": {"long": "JARDINIER DE GOLF (CSA)"}, "niveau": {"cfd": {"europeen": "3"}}},
                                      "domaines": {"rome": {"rncp": [{"code": "A1203"}, {"code": "A1203"}]}}}},
         "formateur": {"organisme": {"etablissement": {"adresse": {"commune": {"nom": "Areines"}, "departement": {"code_insee": "41"}}}}},
         "lieu": {"adresse": {"commune": {"nom": "Blois", "code_insee": "41018"}, "departement": {"code_insee": "41"}},
                  "geolocalisation": {"coordinates": [1.33, 47.59]}, "uai": "0410018X"},
         "modalite": {"duree_indicative": 1}}
    r = sources.parse_apprentissage([f]).iloc[0]
    assert r["commune"] == "Blois" and r["rome"] == "A1203" and r["niveau"] == "3" and r["lat"] == 47.59


def test_parse_rome_and_api_metiers_fallback(tmp_path, monkeypatch):
    rows = sources.parse_rome([{"code": "A1203", "libelle": "Jardinier / Jardinière"}, {"code": "", "libelle": "x"}])
    assert rows == [{"code": "A1203", "libelle": "Jardinier / Jardinière"}]
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(sources, "METIERS_FILE", tmp_path / "absent.json")
    monkeypatch.setattr(sources, "ROME_FILE", tmp_path / "rome.json")
    monkeypatch.setattr(sources, "APPR_FILE", tmp_path / "appr.csv")
    (tmp_path / "rome.json").write_text(json.dumps(rows), encoding="utf-8")
    pd.DataFrame([{"intitule": "JARDINIER DE GOLF (CSA)", "rome": "A1203|A1204"}]).to_csv(tmp_path / "appr.csv", sep=";", index=False)
    m = TestClient(api.app).get("/api/metiers", params={"q": "jardin"}).json()
    assert m[0]["rome"] == "A1203" and m[0]["nb_apprentissage"] == 1 and "JARDINIER DE GOLF" in m[0]["formations"]


def test_api_apprentissage_aggregates_rome_and_cycle(tmp_path, monkeypatch):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(sources, "APPR_FILE", tmp_path / "appr.csv")
    pd.DataFrame([{"cle": "but informatique", "intitule": "BUT INFORMATIQUE", "rome": "M1805|M1810", "cycle": "2"},
                  {"cle": "but informatique", "intitule": "BUT INFORMATIQUE", "rome": "M1805", "cycle": "2"}]
                 ).to_csv(tmp_path / "appr.csv", sep=";", index=False)
    r = TestClient(api.app).get("/api/apprentissage").json()["but informatique"]
    assert r["n"] == 2 and r["rome"]["M1805"] == 2 and r["cycle"] == {"2": 2}


def test_every_passerelle_cites_a_source():
    """Chaque passerelle du site renvoie à un texte (règle v13 : sinon elle est retirée)."""
    import re
    from pathlib import Path
    html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    edges = re.findall(r'\["(\w+)","(\w+)","passerelle","[^"]*"(,\[[^\]]+\])?\]', html)
    assert edges and all(src for *_, src in edges), [e for e in edges if not e[2]]
    keys = set(re.findall(r"^ (\w+):\{l:", html.split("const PSRC={")[1].split("};")[0], flags=re.M))
    cited = {k for *_, src in edges for k in re.findall(r'"(\w+)"', src)}
    assert cited <= keys
    assert "PLAFOND" not in html and "parTrim" not in html      # plus d'objectif de note par trimestre


def test_parse_fiche_criteres_sur_vraie_fiche():
    """Fiche réelle : licence de droit d'Évry (g_ta_cod 10945), relevée le 4/11/2026."""
    from pathlib import Path
    page = (Path(__file__).parent / "fixtures" / "fiche_10945.html").read_text(encoding="utf-8")
    d = sources.parse_fiche_criteres(page)
    assert d["grille"] == [{"categorie": "Résultats scolaires", "poids": 40}, {"categorie": "Méthodes de travail", "poids": 20},
                           {"categorie": "Savoir-être", "poids": 20}, {"categorie": "Motivation", "poids": 20}]
    assert len(d["criteres"]) == 4
    c = d["criteres"][0]
    assert c["critere"].startswith("Notes des matières littéraires") and c["niveau"] == 3 and c["poids_categorie"] == 40
    assert "moyenne de la classe" in c["elements"]
    assert [x["importance"] for x in d["criteres"][1:]] == ["Important"] * 3
    assert d["session"] == 2026 and d["cordees"] and d["conseils"].startswith("Il est nécessaire")


def test_criteres_lit_le_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "CRITERES_DIR", tmp_path)
    (tmp_path / "123.json").write_text('{"g_ta_cod": "123", "grille": []}', encoding="utf-8")
    monkeypatch.setattr(sources, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pas de réseau")))
    assert sources.criteres("123")["g_ta_cod"] == "123"


def test_programmes_sources_et_copie_du_site():
    """Chaque chapitre vient d'un texte cité ; le site embarque la même version que ref/programmes.json."""
    import json, re
    from pathlib import Path
    p = sources.load_programmes()
    for mat in p["matieres"].values():
        for niv in mat["niveaux"].values():
            assert niv["etiquettes"] == [] or niv["source"] in p["sources"]
            assert niv["etiquettes"] or niv.get("a_completer")      # vide = dit pourquoi
    for e in p["epreuves"]:
        assert all(k in p["sources"] for k in e["sources"])
    html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    emb = re.search(r"let PROGRAMMES=(\{.*?\});\n", html).group(1).replace("<\\/", "</")
    assert json.loads(emb) == p
