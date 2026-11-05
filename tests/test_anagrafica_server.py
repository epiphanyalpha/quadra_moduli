"""L'anagrafica riservata del server torna da sola dopo ogni riavvio. Nessuna rete."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from motore import fascicoli

ROOT = Path(__file__).resolve().parents[1]
ANAGRAFICA = {"profilo": {"ragione_sociale": "Impresa Alfa", "conto_dedicato_iban": "IT60 X054 2811 1010 0000 0123 456"}}


class AnagraficaServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.segreto = self.root / "segreti" / "anagrafica.json"
        self.segreto.parent.mkdir()
        self.segreto.write_text(json.dumps(ANAGRAFICA), encoding="utf-8")
        env = patch.dict(os.environ, {"QUADRA_ANAGRAFICA": str(self.segreto)})
        env.start()
        self.addCleanup(env.stop)
        self.dati = self.root / "dati"

    def test_torna_dopo_il_riavvio_con_i_dati_del_conto(self):
        percorso = fascicoli.semina(self.dati)
        self.assertEqual(fascicoli.elenco(self.dati), [percorso])
        self.assertEqual(fascicoli.carica(percorso)["profilo"]["conto_dedicato_iban"],
                         ANAGRAFICA["profilo"]["conto_dedicato_iban"])

    def test_non_sovrascrive_le_correzioni_fatte_nell_app(self):
        percorso = fascicoli.semina(self.dati)
        corretta = fascicoli.carica(percorso)
        corretta["profilo"]["ragione_sociale"] = "Corretta"
        fascicoli.salva(percorso, corretta)
        self.assertIsNone(fascicoli.semina(self.dati))
        self.assertEqual(fascicoli.carica(percorso)["profilo"]["ragione_sociale"], "Corretta")

    def test_senza_file_o_con_file_rotto_si_torna_a_chiederla(self):
        self.segreto.write_text("non e' json", encoding="utf-8")
        self.assertIsNone(fascicoli.semina(self.dati))
        self.segreto.unlink()
        self.assertIsNone(fascicoli.semina(self.dati))
        self.assertEqual(fascicoli.elenco(self.dati), [])

    def test_l_app_parte_senza_chiedere_l_anagrafica(self):
        with patch.dict(os.environ, {"ACCESSO_LIBERO": "1", "APP_SCADENZA": "NESSUNA", "CLIENTI": "",
                                     "QUADRA_DATI": str(self.dati)}):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertNotIn("Manca l'anagrafica dell'impresa", [t.value for t in app.title])


if __name__ == "__main__":
    unittest.main()
