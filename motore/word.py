# -*- coding: utf-8 -*-
"""Il percorso Word, tenuto distinto da quello PDF.

Sono due problemi diversi e non vanno mescolati. In un PDF non ci sono campi:
ci sono linee e caratteri, e per scrivere bisogna misurare dove c'e' il buco,
indovinare quanto ci sta e poi riaprire il file e contare i pixel per
verificare. In un Word il testo c'e', si sostituisce, e va a capo da solo.

Quindi qui non serve niente di `geometria`, `classificatore`,
`strumenti_documento` e `controllo`: meta' del motore PDF esiste per risolvere
un problema che nel Word non c'e'.

Si riusa invece tutta la parte di **giudizio**, che e' la stessa: il fascicolo,
l'abbinamento fatto dal modello, il guardiano dei soggetti, la rilettura. Per
questo la resa usa la stessa convenzione dei buchi numerati - «3:36» - e il
modello non si accorge nemmeno di star leggendo un Word invece di un PDF.

Due cose imparate misurando, non supposte:

  * il 77% dei moduli Word pubblicati dai comuni e' `.doc` binario vecchio,
    che `python-docx` non apre. Si converte con LibreOffice, e la conversione
    non perde i campi: provata su 17 documenti su 17;
  * i campi sono di due forme sole - righe di riempimento dentro i paragrafi e
    celle di tabella - contro i sei tipi del PDF.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

# I modi in cui un modulo Word segna un posto da riempire. I puntini e i
# puntini di sospensione non sono un caso raro: nei modelli fatti a mano si
# alternano ai trattini senza logica - e si alternano ANCHE DENTRO LO STESSO
# VUOTO. In "cap ..........  Via" - tre puntini di sospensione seguiti da
# cinque punti - il buco e' uno solo, ma tre espressioni separate lo
# spezzavano in due campi attaccati: il modello ne vedeva due e li riempiva
# tutti e due. Usciva "cap IM 18100", con la provincia nel posto del C.A.P.
# Una castroneria nata dal lettore, non dal modello. Misurata sul corpus:
# 215 campi su 2460 spezzati cosi', in 18 moduli su 48.
#
# Quindi si prende il tratto di riempimento INTERO, quali che siano i segni,
# e si decide dopo se e' abbastanza lungo per essere un campo.
VUOTO = re.compile(r"[_.\u2026\u00b7]{2,}")

# Quanto vale ogni segno. I pesi non sono a caso: tengono in piedi le tre
# soglie di prima - tre trattini bassi, cinque punti, due puntini di
# sospensione - e in piu' le fanno sommare fra segni diversi dello stesso
# tratto, che e' il caso che prima sfuggiva.
PESO = {"_": 2, "\u2026": 3}
SOGLIA = 5


def _e_vuoto(tratto: str) -> bool:
    """Se questo tratto di segni e' un posto da riempire o solo punteggiatura."""
    return sum(PESO.get(c, 1) for c in tratto) >= SOGLIA

# Le caselle da spuntare, quando sono un carattere e non un controllo Word.
CASELLA = re.compile(r"[\u2610\u2611\u2612\u25a1\u25a0\u00a7]")

# Quanto e' larga in caratteri una riga di riempimento: tanti quanti sono i
# segni. In un Word non c'e' geometria, e questa e' la sola misura possibile -
# ma e' anche quella giusta, perche' chi ha fatto il modulo ha messo tanti
# trattini quanto spazio voleva dare.
MINIMA_CAPIENZA = 3

LIBREOFFICE = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
)


class ConversioneAssente(RuntimeError):
    """LibreOffice non c'e': un .doc vecchio non si puo' aprire."""


def _soffice():
    for percorso in LIBREOFFICE:
        if Path(percorso).exists():
            return percorso
    return None


def e_docx(percorso) -> bool:
    return Path(percorso).open("rb").read(4).startswith(b"PK\x03\x04")


_PROFILO = None


def _profilo() -> str:
    """Un'installazione utente di LibreOffice tutta nostra.

    LibreOffice tiene un profilo solo per utente, e chi ha il programma
    aperto ce l'ha occupato: la chiamata headless si attacca a quella
    finestra e torna senza aver convertito niente, lasciando un errore che
    sembra "il file non si apre". Con un profilo separato le due cose non si
    vedono nemmeno - e due conversioni nostre possono andare insieme, che
    serve quando si collauda un corpus intero.

    Uno per processo, non uno per chiamata: crearlo costa qualche secondo e
    poi si riusa.
    """
    global _PROFILO
    if _PROFILO is None:
        nostra = Path(tempfile.gettempdir()) / ("quadra_soffice_%d" % os.getpid())
        nostra.mkdir(parents=True, exist_ok=True)
        _PROFILO = nostra.as_uri()
    return _PROFILO


def converti(percorso, cartella) -> Path:
    """Un `.doc` vecchio diventa `.docx`. L'originale non si tocca.

    Misurato: 17 conversioni su 17 senza perdere un campo. Non e' un ripiego,
    e' l'unico modo - il formato binario del 1997 non si legge in Python.
    """
    percorso, cartella = Path(percorso), Path(cartella)
    if e_docx(percorso):
        return percorso
    programma = _soffice()
    if not programma:
        raise ConversioneAssente(
            "Questo e' un documento Word vecchio (.doc) e serve LibreOffice "
            "per aprirlo. Installalo, oppure aprilo con Word e salvalo come "
            ".docx.")
    cartella.mkdir(parents=True, exist_ok=True)
    subprocess.run([programma, "-env:UserInstallation=" + _profilo(),
                    "--headless", "--convert-to", "docx",
                    "--outdir", str(cartella), str(percorso)],
                   capture_output=True, timeout=180, check=False)
    fatto = cartella / (percorso.stem + ".docx")
    if not fatto.is_file():
        raise ConversioneAssente("LibreOffice non ha prodotto il .docx da %s"
                                 % percorso.name)
    return fatto


def in_pdf(percorso, cartella) -> Path:
    """La bozza resa in PDF, per poterla guardare com'e' venuta.

    Un elenco di scritture non e' un foglio. Sul PDF si vede dove e' finito
    ogni valore, e a volte e' l'unica cosa che permette di dire se e' nel
    posto giusto: il testo di un modulo puo' uscire a pezzi dalla lettura
    mentre sulla pagina si legge benissimo, e viceversa.

    Non si converte per compilare - sul Word si scrive sul Word, e quella
    resta la regola - si converte solo per guardare. Il file che si consegna
    e' sempre il .docx.
    """
    percorso, cartella = Path(percorso), Path(cartella)
    programma = _soffice()
    if not programma:
        raise ConversioneAssente(
            "Per vedere l'anteprima serve LibreOffice. La bozza Word c'e' "
            "lo stesso e si puo' scaricare: manca solo il modo di mostrarla.")
    cartella.mkdir(parents=True, exist_ok=True)
    fatto = cartella / (percorso.stem + ".pdf")
    # Se la bozza e' piu' nuova del PDF si rifa', altrimenti si riusa: la
    # conversione costa qualche secondo e la pagina si ridisegna spesso.
    if fatto.is_file() and fatto.stat().st_mtime >= percorso.stat().st_mtime:
        return fatto
    subprocess.run([programma, "-env:UserInstallation=" + _profilo(),
                    "--headless", "--convert-to", "pdf",
                    "--outdir", str(cartella), str(percorso)],
                   capture_output=True, timeout=180, check=False)
    if not fatto.is_file():
        raise ConversioneAssente("LibreOffice non ha prodotto il PDF da %s"
                                 % percorso.name)
    return fatto


def _paragrafi(documento):
    """Tutti i paragrafi, del corpo e delle celle, una volta sola.

    Preso dal compilatore gia' esistente: le celle contengono paragrafi, e
    scorrere solo `documento.paragraphs` ne perde meta'.
    """
    # Il dizionario tiene in vita gli elementi, e non e' un dettaglio: se si
    # usasse un set di id(), Python riuserebbe gli identificativi degli oggetti
    # liberati e paragrafi diversi risulterebbero lo stesso. Misurato: una
    # cella di tabella su due spariva, e il campo dentro non veniva mai visto.
    visti = {}
    for p in documento.paragraphs:
        visti[id(p._p)] = p._p
        yield p, None
    for numero, tabella in enumerate(documento.tables):
        for riga in tabella.rows:
            for cella in riga.cells:
                for p in cella.paragraphs:
                    if id(p._p) not in visti:
                        visti[id(p._p)] = p._p
                        yield p, (numero, cella)


def _testo(paragrafo) -> str:
    return "".join(r.text for r in paragrafo.runs)


def _etichetta(prima: str) -> str:
    """Quel che sta scritto subito a sinistra del buco.

    Si taglia al buco precedente: senza il taglio l'etichetta si allunga
    lungo tutta la riga e finisce per contenere i campi di prima, che e' lo
    stesso difetto gia' corretto sul percorso PDF.
    """
    pezzo = prima
    for trovato in VUOTO.finditer(prima):
        if _e_vuoto(trovato.group()):
            pezzo = prima[trovato.end():]
    pezzo = re.sub(r"\s+", " ", pezzo).strip(" :.-\u2013")
    return pezzo[-60:]


PAROLA = re.compile(r"[^\W\d_]+", re.UNICODE)
MINIMA_PAROLA = 3


def _senza_ripetizione(etichetta: str, valore: str) -> str:
    """Toglie dal valore la parola che il modulo ha gia' stampato.

    Sul foglio c'e' scritto "Via ..........." e nell'anagrafica l'indirizzo e'
    "Via delle Fornaci": scrivendolo intero si legge "Via Via delle Fornaci".
    Non e' un dato sbagliato, e' una parola di troppo - ma a chi legge sembra
    un errore, e la bozza va rifatta lo stesso.

    Misurato sul corpus, 654 scritture: la parola si ripete 20 volte (3,1%) e
    tutte e venti sono "Via". La regola resta generale perche' cosi' non c'e'
    un elenco di casi da tenere aggiornato, ma e' tenuta stretta: si toglie
    UNA parola, l'ULTIMA dell'etichetta, lunga almeno tre lettere, e solo se
    il valore non si riduce a quella.

    ALLARGARLA E' TENTANTE E FA DANNO. Resta fuori questa, che si legge male:

        Camera di Commercio ... di [Camera di Commercio Riviere di Liguria]

    e per prenderla bisognerebbe cercare la frase in tutta l'etichetta invece
    che in fondo. Misurato su tutte le 654 scritture: quella regola scatta 35
    volte, ne sistema due, e in cambio produce

        [rivamare]@pec.example.invalid -> "@pec.example.invalid"

    perche' "rivamare" compare gia' prima nella riga; svuota "Legale
    rappresentante" dove l'etichetta lo dice per esteso; e riduce "Societa' a
    responsabilita' limitata" a "a responsabilita' limitata". Due sistemate,
    una castroneria nuova e due peggioramenti: il conto non torna.

    Quel caso e' piuttosto un dato del fascicolo scritto per esteso dove il
    modulo chiede solo il nome: si risolve nell'anagrafica, non qui.
    """
    parole_etichetta = PAROLA.findall(etichetta or "")
    parole_valore = PAROLA.findall(valore or "")
    if not parole_etichetta or len(parole_valore) < 2:
        return valore
    ripetuta = parole_etichetta[-1]
    if len(ripetuta) < MINIMA_PAROLA or ripetuta.lower() != parole_valore[0].lower():
        return valore
    return re.sub(r"^\s*%s\b[\s,]*" % re.escape(parole_valore[0]), "", valore, count=1)


# La capienza di un campo modulo, quando il modulo non la dichiara. Non c'e'
# niente da misurare - non ha larghezza, e' un contenitore - e sessanta
# caratteri e' quanto tiene una riga di modulo.
CAPIENZA_MODULO = 60


def _ha_campo_modulo(parte) -> bool:
    """Se qui dentro c'e' un campo modulo di Word, a qualsiasi profondita'."""
    from docx.oxml.ns import qn
    return bool(parte._element.findall(".//" + qn("w:textInput")))


def _campi_modulo(paragrafo) -> list:
    """I campi modulo veri di Word: [(inizio, fine, "modulo", capienza)].

    Un modulo fatto bene non usa i puntini: usa i campi FORMTEXT, che in Word
    si compilano cliccandoci dentro. Noi non li vedevamo, e i moduli fatti
    bene erano quelli che ci riuscivano peggio. Misurato sul corpus: 11
    documenti su 48 li usano, e in tre sono l'UNICO modo di riempirli - 261,
    99 e 72 campi. Quei tre scrivevano zero campi su zero, e un quarto non
    produceva nemmeno la bozza.

    Nel testo il campo compare come il suo risultato: cinque spazi EN
    (\\u2002) messi li' da Word. Quindi e' un intervallo di caratteri come un
    altro, e si riempie con la stessa sostituzione dei puntini - non serve
    una seconda strada per scrivere.
    """
    from docx.oxml.ns import qn

    fuori, dentro, inizio, posizione = [], False, 0, 0
    for run in paragrafo.runs:
        elemento = run._element
        segni = [c.get(qn("w:fldCharType")) for c in elemento.findall(qn("w:fldChar"))]
        if "begin" in segni:
            # solo i campi di testo: le caselle FORMCHECKBOX non hanno
            # risultato, non occupano posto nel testo, e vanno spuntate
            # cambiando l'XML invece che scrivendoci dentro
            dentro = bool(elemento.findall(".//" + qn("w:textInput")))
            inizio = None
        elif "separate" in segni and dentro:
            inizio = posizione
        elif "end" in segni and dentro:
            if inizio is not None and posizione > inizio:
                fuori.append((inizio, posizione, "modulo", CAPIENZA_MODULO))
            dentro = False
        posizione += len(run.text)
    return fuori


def leggi(percorso, cartella_lavoro=None) -> dict:
    """Il modulo Word tradotto in campi, come `mappa.costruisci` per il PDF.

    Torna {"documento", "ancore", "rese"} con la stessa forma della mappa PDF,
    cosi' quello che viene dopo - modello, guardiano, artefatto - non cambia.
    """
    import docx

    percorso = Path(percorso)
    usabile = converti(percorso, cartella_lavoro or percorso.parent / "convertiti")
    documento = docx.Document(io.BytesIO(usabile.read_bytes()))

    ancore, righe = [], []
    for indice, (paragrafo, dove) in enumerate(_paragrafi(documento)):
        testo = _testo(paragrafo)
        if not testo.strip() and not _ha_campo_modulo(paragrafo):
            # Un paragrafo che sembra vuoto puo' essere un campo modulo e
            # basta: il suo risultato sono cinque spazi, e `strip()` li
            # toglie tutti. Saltandolo si perdeva il campo.
            continue
        # I buchi di tutte e due le specie, messi in fila per posizione. In
        # fila e non in due giri perche' l'etichetta di ognuno e' quello che
        # sta fra la fine del buco prima e l'inizio suo: separandoli,
        # l'etichetta di un campo modulo si allungherebbe sopra un campo a
        # puntini, e viceversa.
        buchi = [(m.start(), m.end(), "riempimento", m.end() - m.start())
                 for m in VUOTO.finditer(testo)
                 if m.end() - m.start() >= MINIMA_CAPIENZA and _e_vuoto(m.group())]
        buchi += _campi_modulo(paragrafo)
        buchi.sort()

        pezzi, ultimo = [], 0
        for inizio, fine, specie, quanti in buchi:
            identificativo = "p%04d.%s.%03d" % (indice, specie, inizio)
            ancore.append({
                "id": identificativo,
                "tipo": specie,
                "paragrafo": indice,
                "inizio": inizio,
                "fine": fine,
                "capienza": quanti,
                "etichetta": _etichetta(testo[ultimo:inizio]),
                "tabella": dove[0] if dove else None,
            })
            pezzi.append((ultimo, inizio, identificativo, quanti))
            ultimo = fine
        for trovato in CASELLA.finditer(testo):
            identificativo = "p%04d.casella.%03d" % (indice, trovato.start())
            ancore.append({
                "id": identificativo,
                "tipo": "casella",
                "paragrafo": indice,
                "inizio": trovato.start(),
                "fine": trovato.end(),
                "capienza": 1,
                "etichetta": _etichetta(testo[:trovato.start()]),
                "tabella": dove[0] if dove else None,
            })
        righe.append((indice, testo))

    ancore.extend(_celle_vuote(documento, len(righe), righe))

    return {"documento": percorso.name,
            "formato": "word",
            "convertito_da": None if usabile == percorso else percorso.name,
            "ancore": ancore,
            "righe": righe}


def _celle_vuote(documento, da_indice: int, righe: list) -> list:
    """Le celle vuote di una tabella: sono campi anche loro.

    Un modulo su quattro non usa i trattini: mette una tabella con l'etichetta
    a sinistra e la cella accanto vuota. Misurato su un modulo di Galatina che
    non abbinava niente - diciotto caselle riconosciute e zero campi di testo,
    mentre la domanda vera stava tutta in tabelle.

    Le due disposizioni non si equivalgono e la differenza e' quella che conta:

      etichetta | (vuota)         -> il campo e' dell'impresa
      Ragione sociale | C.F.      -> intestazione di un ELENCO, e sotto ci
      (vuota) | (vuota)              vanno altri soggetti, non noi

    Nel secondo caso si segna `elenco`, cosi' chi decide sa che quelle righe
    parlano di qualcun altro - subappaltatori, consorziate - invece di
    scoprirlo dopo aver scritto.
    """
    fuori = []
    indice = da_indice
    for numero, tabella in enumerate(documento.tables):
        if not tabella.rows:
            continue
        intestazione = [c.text.strip() for c in tabella.rows[0].cells]
        # un elenco: la prima riga ha titoli e sotto ci sono piu' righe vuote
        vuote_sotto = sum(1 for r in tabella.rows[1:]
                          if not any(c.text.strip() for c in r.cells))
        elenco = (all(intestazione) and len(intestazione) > 1 and vuote_sotto >= 2)
        for riga_n, riga in enumerate(tabella.rows):
            celle = riga.cells
            for colonna, cella in enumerate(celle):
                if cella.text.strip():
                    continue
                if _ha_campo_modulo(cella):
                    # La cella sembra vuota perche' il campo modulo che c'e'
                    # dentro mostra cinque spazi. Il campo e' un dato esatto e
                    # questa e' un'euristica: vince il campo, e ci si scrive
                    # dentro invece che accanto. Senza questo lo stesso posto
                    # risulta due volte - misurato, 162 celle su un modulo del
                    # Demanio - e chi decide potrebbe riempirle tutte e due.
                    continue
                sinistra = celle[colonna - 1].text.strip() if colonna else ""
                sopra = intestazione[colonna] if (riga_n and colonna < len(intestazione)) else ""
                etichetta = sinistra or sopra
                if not etichetta:
                    continue
                indice += 1
                identificativo = "t%02d.cella.%02d-%02d" % (numero, riga_n, colonna)
                fuori.append({
                    "id": identificativo, "tipo": "cella",
                    "paragrafo": None, "tabella": numero,
                    "riga": riga_n, "colonna": colonna,
                    "inizio": 0, "fine": 0,
                    "capienza": 60,
                    "etichetta": re.sub(r"\s+", " ", etichetta)[:60],
                    "elenco": bool(elenco and riga_n > 0),
                })
                righe.append((None, "%s: «CELLA:%s»"
                              % (etichetta, identificativo)))
    return fuori


def _sostituisci(paragrafo, inizio: int, fine: int, valore: str) -> bool:
    """Mette il valore al posto del riempitivo, dentro i frammenti di Word.

    Word spezza una frase in piu' frammenti secondo la formattazione, e un
    `____` puo' attraversarne tre. Riscrivere il paragrafo intero perderebbe
    grassetti e corsivi dell'etichetta, quindi si tocca solo il testo dei
    frammenti coinvolti.

    Adattato dal compilatore gia' esistente, che questa parte la faceva bene.
    """
    frammenti = list(paragrafo.runs)
    if not frammenti:
        return False
    intero = "".join(f.text for f in frammenti)
    valore = str(valore)
    # Nei modelli i trattini sono spesso incollati alle parole vicine
    # ("___a___(Prov.)"): senza lo spazio il valore si attacca all'etichetta.
    if inizio > 0 and not intero[inizio - 1].isspace() and not valore.startswith(" "):
        valore = " " + valore
    if fine < len(intero) and not intero[fine].isspace() and not valore.endswith(" "):
        valore = valore + " "

    posizioni, scorre = [], 0
    for i, f in enumerate(frammenti):
        posizioni.append((i, scorre, scorre + len(f.text)))
        scorre += len(f.text)
    coinvolti = [p for p in posizioni if p[2] > inizio and p[1] < fine]
    if not coinvolti:
        return False
    primo, inizio_primo, _ = coinvolti[0]
    ultimo, inizio_ultimo, _ = coinvolti[-1]
    prima = frammenti[primo].text[:max(0, inizio - inizio_primo)]
    dopo = frammenti[ultimo].text[max(0, fine - inizio_ultimo):]
    if primo == ultimo:
        frammenti[primo].text = prima + valore + dopo
    else:
        frammenti[primo].text = prima + valore
        for i in range(primo + 1, ultimo):
            frammenti[i].text = ""
        frammenti[ultimo].text = dopo
    return True


SPUNTA = "☒"          # la casella con la crocetta


def scrivi(percorso, mappa: dict, valori: dict, uscita) -> dict:
    """Riempie il documento e torna il resoconto di quello che ha scritto.

    I campi dello stesso paragrafo si riempiono **da destra a sinistra**:
    scrivendo da sinistra, il primo valore sposta tutto quello che segue e le
    posizioni misurate durante la lettura non valgono piu'.
    """
    import docx

    percorso, uscita = Path(percorso), Path(uscita)
    usabile = converti(percorso, uscita.parent / "convertiti")
    documento = docx.Document(io.BytesIO(usabile.read_bytes()))
    paragrafi = [p for p, _ in _paragrafi(documento)]
    per_id = {a["id"]: a for a in mappa["ancore"]}

    da_fare = []
    for identificativo, valore in valori.items():
        a = per_id.get(identificativo)
        if a is None:
            raise ValueError("Valore su un campo che non esiste: %s" % identificativo)
        if valore is None or valore is False or str(valore).strip() == "":
            continue
        da_fare.append((a, valore))
    # Le celle non stanno in un paragrafo del corpo e hanno `paragrafo` a None:
    # ordinarle insieme agli altri fa confrontare None con un numero. Vanno in
    # fondo, e fra loro l'ordine non conta perche' ognuna sta per conto suo.
    da_fare.sort(key=lambda x: (x[0]["paragrafo"] is None,
                                x[0]["paragrafo"] if x[0]["paragrafo"] is not None else 0,
                                -x[0]["inizio"]))

    scritture, mancate = [], []
    for a, valore in da_fare:
        testo = SPUNTA if a["tipo"] == "casella" else str(valore).strip()
        if a["tipo"] in ("riempimento", "modulo"):
            # Solo qui: in un riempimento e in un campo modulo l'etichetta sta
            # sulla stessa riga, subito prima del buco, e la ripetizione si
            # legge. In una cella di tabella l'intestazione sta altrove e
            # togliere la parola lascerebbe la cella monca.
            testo = _senza_ripetizione(a.get("etichetta", ""), testo)
        if a["tipo"] == "cella":
            cella = documento.tables[a["tabella"]].rows[a["riga"]].cells[a["colonna"]]
            if cella.text.strip():
                mancate.append({"ancora": a["id"], "valore": testo,
                                "motivo": "la cella non e' piu' vuota"})
                continue
            cella.paragraphs[0].add_run(testo)
            scritture.append({"ancora": a["id"], "tipo": "cella",
                              "etichetta": a["etichetta"], "valore": testo,
                              "paragrafo": None, "tabella": a["tabella"],
                              "riga": a["riga"], "colonna": a["colonna"]})
            continue
        paragrafo = paragrafi[a["paragrafo"]]
        if a["tipo"] != "casella" and len(testo) > a["capienza"] * 4:
            # In Word il testo va a capo e non sborda: il limite non e' lo
            # spazio, e' la credibilita'. Un valore quattro volte piu' lungo
            # del posto che gli hanno dato quasi sempre e' il campo sbagliato.
            mancate.append({"ancora": a["id"], "valore": testo,
                            "motivo": "lungo %d su un posto da %d: non e' quello"
                                      % (len(testo), a["capienza"])})
            continue
        if _sostituisci(paragrafo, a["inizio"], a["fine"], testo):
            scritture.append({"ancora": a["id"], "tipo": a["tipo"],
                              "etichetta": a["etichetta"], "valore": testo,
                              "paragrafo": a["paragrafo"]})
        else:
            mancate.append({"ancora": a["id"], "valore": testo,
                            "motivo": "il paragrafo non ha frammenti di testo"})

    uscita.parent.mkdir(parents=True, exist_ok=True)
    documento.save(str(uscita))
    return {"bozza": str(uscita), "scritture": scritture, "mancate": mancate}


PRIMA_DEL_VALORE = 100
DOPO_IL_VALORE = 60


def _intorno(paragrafo: str, valore: str) -> str:
    """La frase intorno al valore, non l'inizio del paragrafo.

    Serve a giudicare se un dato giusto sta nel posto di un altro, e per
    giudicarlo bisogna vedere che cosa c'e' scritto SUBITO PRIMA. Tagliando
    il paragrafo ai primi 150 caratteri, i valori che cadono piu' in la'
    restavano fuori dalla riga e non si potevano controllare affatto:
    misurate 94 scritture su 654, il 14%, invisibili alla rilettura. E il
    numero che ne usciva - "22 da guardare su 654" - era calcolato
    sull'86%, senza che niente lo dicesse.
    """
    pulito = re.sub(r"\s+", " ", paragrafo).strip()
    dove = pulito.find(valore.strip())
    if dove < 0:
        return pulito[:PRIMA_DEL_VALORE + DOPO_IL_VALORE]
    inizio = max(0, dove - PRIMA_DEL_VALORE)
    fine = dove + len(valore.strip()) + DOPO_IL_VALORE
    return ("..." if inizio else "") + pulito[inizio:fine]


def verifica(uscita, resoconto: dict) -> dict:
    """Riapre la bozza e controlla che ogni valore ci sia davvero.

    Come per il PDF: non ci si fida di quello che il programma dichiara di
    aver fatto, si riapre il documento e si guarda. Qui pero' basta rileggere
    il testo, perche' non c'e' inchiostro da misurare.
    """
    import docx

    documento = docx.Document(str(uscita))
    paragrafi = [_testo(p) for p, _ in _paragrafi(documento)]
    verificate, non_trovate = [], []
    for s in resoconto["scritture"]:
        if s["tipo"] == "cella":
            cella = documento.tables[s["tabella"]].rows[s["riga"]].cells[s["colonna"]]
            if s["valore"] in cella.text:
                verificate.append(dict(s, riga="%s: %s"
                                       % (s["etichetta"],
                                          _intorno(cella.text, s["valore"]))))
            else:
                non_trovate.append(dict(s, motivo="la cella e' rimasta vuota"))
            continue
        dentro = paragrafi[s["paragrafo"]] if s["paragrafo"] < len(paragrafi) else ""
        if s["valore"] in dentro:
            verificate.append(dict(s, riga=_intorno(dentro, s["valore"])))
        else:
            non_trovate.append(dict(s, motivo="scritto ma non risulta nel documento"))
    return {"verificate": verificate, "non_trovate": non_trovate,
            "mancate": resoconto.get("mancate", [])}


def rendi(mappa: dict) -> tuple:
    """Il documento come prosa con i buchi numerati, come per il PDF.

    Stessa convenzione - «numero:capienza» - perche' la domanda che si fa al
    modello dev'essere la stessa: cambiando il modo di chiedere cambierebbero
    le risposte, e tutte le misure fatte sul PDF non varrebbero piu' niente.
    """
    per_paragrafo = {}
    for a in mappa["ancore"]:
        per_paragrafo.setdefault(a["paragrafo"], []).append(a)

    per_id = {a["id"]: a for a in mappa["ancore"]}
    numerate, indirizzi, fuori = [], {}, []
    numero = 0
    for indice, testo in mappa["righe"]:
        if indice is None:
            # una cella di tabella: il segnaposto porta gia' il suo
            # identificativo, qui diventa un buco numerato come gli altri
            trovato = re.search(r"«CELLA:([^»]+)»", testo)
            if not trovato:
                continue
            a = per_id.get(trovato.group(1))
            if a is None:
                continue
            numero += 1
            indirizzi[str(numero)] = a["id"]
            numerate.append((numero, a))
            segno = "«%d:%d»" % (numero, a["capienza"])
            if a.get("elenco"):
                segno += " (riga di un elenco di altri soggetti)"
            fuori.append(testo[:trovato.start()].strip() + " " + segno)
            continue
        dentro = sorted(per_paragrafo.get(indice, []), key=lambda a: a["inizio"])
        if not dentro:
            pulita = re.sub(r"\s+", " ", testo).strip()
            if pulita:
                fuori.append(pulita)
            continue
        pezzi, ultimo = [], 0
        for a in dentro:
            numero += 1
            indirizzi[str(numero)] = a["id"]
            numerate.append((numero, a))
            pezzi.append(testo[ultimo:a["inizio"]])
            pezzi.append("\u00ab%d:%s\u00bb"
                         % (numero, "casella" if a["tipo"] == "casella"
                            else a["capienza"]))
            ultimo = a["fine"]
        pezzi.append(testo[ultimo:])
        fuori.append(re.sub(r"\s+", " ", "".join(pezzi)).strip())
    return "\n".join(fuori), indirizzi
