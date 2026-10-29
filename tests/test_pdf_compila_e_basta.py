"""Compila e basta: i campi che chiederebbero conferma si scrivono e restano segnati. Nessuna rete."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from streamlit.testing.v1 import AppTest

from motore import agente, fascicoli, lavori, mappa, piano_pdf

ROOT = Path(__file__).resolve().parents[1]


class CompilaEBasta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rete = patch.object(agente, '_chiedi', side_effect=AssertionError('Unexpected AI call'))
        self.rete.start()
        self.env = patch.dict(os.environ, {'QUADRA_PDF_CONFERME': 'scrivi'})
        self.env.start()
        self.profilo = dict(profilo=dict(nome='Ada Verdi', autorizzato=True))
        self.source = self.root/'source.pdf'
        with fitz.open() as d:
            p = d.new_page()
            for i, label in enumerate(('Richiedente', 'Esecutore')):
                y = 80+i*45
                p.insert_text((30, y), label)
                p.draw_rect((140, y-15, 360, y+10))
            p.insert_text((60, 180), 'Dichiara di essere autorizzato')
            p.draw_rect((35, 170, 44, 179), width=0.4)
            d.save(self.source)
        self.m = mappa.costruisci(self.source)

    def tearDown(self):
        self.env.stop()
        self.rete.stop()
        self.tmp.cleanup()

    def corri(self, piano_di_prima=None, togli=()):
        testo = [a for a in self.m['ancore'] if a['tipo'] != 'casella']
        casella = next(a for a in self.m['ancore'] if a['tipo'] == 'casella')
        decisioni = {testo[0]['id']: dict(stato='assegna', campo='nome', soggetto='Richiedente', motivo='Fonte'),
                     testo[1]['id']: dict(stato='assegna', campo='nome', soggetto='Esecutore', motivo='Fonte'),
                     casella['id']: dict(stato='assegna', campo='autorizzato', soggetto='Impresa', motivo='Fonte')}

        def rilettura(*args, **kwargs):
            kwargs['avvisi'].append(dict(ancora=testo[1]['id'], pagina=1, motivo='Conferma chi è l’esecutore'))
            return {}
        with patch.object(agente, 'disponibile', return_value=True), \
                patch.object(agente, 'immagini', return_value=[]), \
                patch.object(agente, 'decidi_campi', return_value=decisioni), \
                patch.object(agente, 'rileggi_documento', side_effect=rilettura):
            esito = list(piano_pdf.lavora(ROOT, self.source, self.profilo, self.root/'runs', riusa=False,
                                          pertinenza_confermata=True, piano_di_prima=piano_di_prima,
                                          togli=togli))[-1]
        return esito, testo, casella

    def test_scrive_anche_caselle_e_campi_incerti_e_li_segna(self):
        esito, testo, casella = self.corri()
        v = esito['verdetto']
        self.assertEqual({r['ancora'] for r in v['verificate']}, {testo[0]['id'], testo[1]['id'], casella['id']})
        self.assertEqual({r['ancora'] for r in v['da_controllare']}, {testo[1]['id'], casella['id']})
        self.assertFalse([d for d in v['domande_campi'] if d['ancora'] in (testo[1]['id'], casella['id'])])
        # Rifare la bozza dal piano non cambia niente e non chiama nessun modello.
        di_nuovo = piano_pdf.esegui(self.source, self.m, v['piano'], self.profilo,
                                    lavori.nuova_cartella(self.root/'rifatta'))
        self.assertEqual(len(di_nuovo['verdetto']['verificate']), 3)
        self.assertEqual(len(di_nuovo['verdetto']['da_controllare']), 2)
        # Togliere un campo segnato funziona come per ogni altro.
        tolto, _, _ = self.corri(piano_di_prima=v['piano'], togli=[casella['id']])
        self.assertEqual(len(tolto['verdetto']['verificate']), 2)

    def test_l_app_mostra_i_campi_da_controllare_senza_chiedere(self):
        esito, _, _ = self.corri()
        fascicoli.salva(self.root/'fascicoli'/'sintetico.json', self.profilo)
        with patch.dict(os.environ, {'ACCESSO_LIBERO': '1', 'APP_SCADENZA': 'NESSUNA', 'CLIENTI': '',
                                     'QUADRA_DATI': str(self.root)}):
            app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=30).run()
            for k in ('bozza', 'artefatto', 'verdetto'):
                app.session_state[k] = esito[k]
            app.session_state['modulo'] = str(self.source)
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any('2 campi da controllare' in w.value for w in app.warning))
            self.assertFalse(any('attendono una risposta' in i.value for i in app.info))


if __name__ == '__main__':
    unittest.main()
