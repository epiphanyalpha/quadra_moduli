"""Un modulo con una firma digitale si compila in coda: i byte firmati restano identici. Nessuna rete."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from motore import agente, lavori, mappa, piano_pdf
from riusare.strumenti_documento import firmato

ROOT = Path(__file__).resolve().parents[1]


class ModuloFirmato(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rete = patch.object(agente, '_chiedi', side_effect=AssertionError('Unexpected AI call'))
        self.rete.start()
        self.profilo = dict(profilo=dict(nome='Ada Verdi'))
        self.source = self.root/'firmato.pdf'
        with fitz.open() as d:
            p = d.new_page()
            p.insert_text((30, 80), 'Richiedente')
            p.draw_rect((140, 65, 360, 90))
            firma = d.get_new_xref()
            d.update_object(firma, '<< /Type /Sig /ByteRange [0 10 20 30] >>')
            d.xref_set_key(d.pdf_catalog(), 'FirmaDiProva', '%d 0 R' % firma)
            d.save(self.source)
        self.assertTrue(firmato(self.source))

    def tearDown(self):
        self.rete.stop()
        self.tmp.cleanup()

    def test_si_compila_in_coda_senza_toccare_i_byte_firmati(self):
        aid = mappa.costruisci(self.source)['ancore'][0]['id']
        with patch.object(agente, 'disponibile', return_value=True), \
                patch.object(agente, 'immagini', return_value=[]), \
                patch.object(agente, 'decidi_campi', return_value={aid: dict(
                    stato='assegna', campo='nome', soggetto='Richiedente', motivo='Fonte')}), \
                patch.object(agente, 'rileggi_documento', return_value={}):
            passi = list(piano_pdf.lavora(ROOT, self.source, self.profilo, self.root/'runs',
                                          pertinenza_confermata=True))
        esito = passi[-1]
        self.assertNotIn('rifiuto', [p['passo'] for p in passi])
        self.assertTrue(esito['verdetto']['firma_preesistente'])
        self.assertEqual([r['valore'] for r in esito['verdetto']['verificate']], ['Ada Verdi'])
        originale = self.source.read_bytes()
        bozza = Path(esito['bozza']).read_bytes()
        self.assertEqual(bozza[:len(originale)], originale)
        self.assertGreater(len(bozza), len(originale))
        with fitz.open(esito['bozza']) as d:
            self.assertIn('Ada Verdi', d[0].get_text())


if __name__ == '__main__':
    unittest.main()
