"""Exercise existing Streamlit layout with synthetic in-memory profile; no API."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from motore import agente, fascicoli


class WordUiTests(unittest.TestCase):
    def test_existing_tabs_and_failed_compilation_message(self):
        with tempfile.TemporaryDirectory() as directory:
            profile={'prova':True,'profilo':{'ragione_sociale':'Impresa sintetica','pec':'test@example.invalid'}}
            env={'ACCESSO_LIBERO':'1','APP_SCADENZA':'NESSUNA','CLIENTI':'','QUADRA_DATI':directory}
            with patch.dict(os.environ,env), patch.object(fascicoli,'elenco',return_value=[Path(directory)/'sintetico.json']), \
                 patch.object(fascicoli,'carica',return_value=profile), \
                 patch.object(agente,'_chiedi',side_effect=AssertionError('No API')):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
                self.assertFalse(app.exception)
                self.assertEqual([t.label for t in app.tabs],['Compila un PDF','Compila un Word','Anagrafica'])
                self.assertFalse(any(r.key == 'w_partecipazione' for r in app.radio))
                self.assertFalse(any(c.key in {'w_rti','w_avv','w_sub'} for c in app.checkbox))
                self.assertFalse(any('Come partecipa' in m.value for m in app.markdown))
                app.session_state['w_partecipazione'] = 'Partecipa da sola'
                app.run()
                self.assertFalse(app.exception)
                self.assertFalse(any(r.key == 'w_partecipazione' for r in app.radio))
                app.session_state.w_verdetto=dict(verificate=[],non_trovate=[],mancate=[],campi_totali=4,
                                                   contraddizioni=[],avvisi=[],esito='non_compilato')
                app.run()
                self.assertFalse(app.exception)
                self.assertTrue(any('0 campi scritti' in e.value for e in app.error))
                self.assertFalse(any('0 campi scritti' in e.value for e in app.success))


if __name__=='__main__': unittest.main()
