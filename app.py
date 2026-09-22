# -*- coding: utf-8 -*-
"""La chat: Bianca trascina un modulo, ne riesce una bozza.

Quello che si vede qui e' quasi tutto racconto di cose gia' decise altrove. Le
scelte di questa pagina sono quattro:

  * la bozza si guarda, non si scarica e basta. Le pagine renderizzate stanno
    sotto il verdetto, perche' i dati mancanti si riempiono guardando il foglio;
  * i punti aperti si rispondono qui e finiscono nel fascicolo, non nel
    programma. Poi si riesegue: zero chiamate al modello;
  * l'avviso sui soggetti sta SOPRA la bozza. Il verdetto verde dice il vero -
    ogni scrittura sta dentro il suo campo - ma non dice se quel campo era di
    questa impresa, e li' il motore sbaglia;
  * l'anagrafica si modifica qui dentro. Un dato che manca e' una casella vuota
    su ogni modulo futuro: e' il posto dove il lavoro di Bianca si accumula
    invece di ripetersi.

    streamlit run app.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import fitz
import streamlit as st

import esecuzione
from motore import (accesso, agente, compilatore, controllo, fascicoli,
                    lavorazione, lavorazione_word, scheda, soggetti, word)

RADICE = Path(__file__).resolve().parent

# Dove stanno le cose che si scrivono lavorando - l'anagrafica dell'impresa
# e le bozze - separate da dove sta il programma. Sul computer di chi
# sviluppa coincidono e non cambia niente. Su un server no: il programma sta
# dentro l'immagine e riparte uguale a ogni rilascio, mentre questi devono
# sopravvivere, e stanno su un disco che si monta in un punto solo.
DATI = Path(os.environ.get("QUADRA_DATI") or RADICE)
LAVORO = DATI / "esiti" / "chat"
LAVORO_WORD = DATI / "esiti" / "chat_word"
(DATI / "fascicoli").mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Quadra - compila moduli", layout="wide")


def _stato(chiave, iniziale):
    if chiave not in st.session_state:
        st.session_state[chiave] = iniziale
    return st.session_state[chiave]


LOGO = RADICE / "risorse" / "quadra-logo.svg"
CLIENTE = "per Luigi Badessi S.r.l."


@st.cache_data(show_spinner=False)
def _marchio() -> str:
    """Il logo Quadra e il nome di chi lo usa, in cima alla spalla.

    L'SVG si mette dentro la pagina invece di caricarlo come immagine per
    una ragione sola: cosi' la scritta puo' prendere `currentColor` e
    seguire il tema. Con un file a colori fissi il lettering nero sparisce
    sul tema scuro e quello bianco sparisce sul chiaro, e non si sa quale
    dei due avra' chi usera' l'app.
    """
    if not LOGO.is_file():
        return "### Quadra\n%s" % CLIENTE
    disegno = LOGO.read_text(encoding="utf-8")
    disegno = disegno.replace('fill="#111111"', 'fill="currentColor"')
    disegno = disegno.replace('<svg ', '<svg style="width:100%;height:auto" ', 1)
    return ('<div style="margin:.2rem 0 1rem">%s'
            '<div style="opacity:.65;font-size:.82rem;margin-top:-.4rem">%s</div>'
            '</div>' % (disegno, CLIENTE))


# La porta sta qui, prima di qualunque cosa venga disegnata: quello che sta
# sopra lo vede anche chi non ha il codice. In locale non chiede niente.
CHI_ENTRA = accesso.porta(_marchio())


ROSSO = (0.82, 0.08, 0.08)
ALTEZZA_TARGA = 6.4          # la targhetta col numero, in punti tipografici
DPI_ANTEPRIMA = 135          # a 110 i numeri sparivano


def _pagine_segnate(bozza, artefatto, verificate):
    """Le pagine della bozza con ogni scrittura cerchiata e numerata.

    Su certi moduli il testo esce a pezzi - due colonne affiancate che la resa
    mescola lettera per lettera - e la frase nel riquadro diventa illeggibile.
    Li' l'unica cosa che permette di giudicare e' vedere DOVE e' finito il
    valore sul foglio. I numeri sono quelli delle righe del riquadro, cosi' si
    passa dall'uno all'altro.
    """
    ancore = {}
    if artefatto:
        percorso = Path(artefatto) / "mappa.json"
        if percorso.is_file():
            ancore = {a["id"]: a["rect"]
                      for a in json.loads(percorso.read_text(encoding="utf-8"))["ancore"]}
    doc = fitz.open(bozza)
    per_pagina = {}
    for numero, r in enumerate(verificate, 1):
        rect = ancore.get(r["ancora"])
        if rect:
            per_pagina.setdefault(int(r["pagina"]) - 1, []).append((numero, rect))
    fuori = []
    for indice, pagina in enumerate(doc):
        segni = per_pagina.get(indice, [])
        for numero, rect in segni:
            r = fitz.Rect(rect)
            pagina.draw_rect(r, color=ROSSO, width=1.1)
            # Il numero va letto a schermo, dentro una pagina rimpicciolita:
            # scritto e basta spariva. Qui e' bianco su una targhetta piena,
            # che si vede anche sopra i puntini prestampati.
            larga = 7.5 + 3.6 * (len(str(numero)) - 1)
            base = max(ALTEZZA_TARGA, r.y0)
            targa = fitz.Rect(r.x0, base - ALTEZZA_TARGA, r.x0 + larga, base)
            pagina.draw_rect(targa, color=ROSSO, fill=ROSSO, width=0)
            pagina.insert_text((targa.x0 + 1.4, targa.y1 - 1.8), str(numero),
                               fontsize=6.4, color=(1, 1, 1))
        # Quali numeri stanno su questa pagina: con cinquanta righe in tabella,
        # sapere che la pagina 5 sono le righe dalla 28 alla 38 evita di
        # scorrerle tutte per trovare quella che si e' vista cerchiata.
        numeri = sorted(n for n, _ in segni)
        quali = ""
        if numeri:
            quali = (" — righe %d-%d" % (numeri[0], numeri[-1])
                     if numeri[-1] - numeri[0] + 1 == len(numeri)
                     else " — righe " + ", ".join(str(n) for n in numeri))
        fuori.append((indice + 1, pagina.get_pixmap(dpi=DPI_ANTEPRIMA).tobytes("png"), quali))
    doc.close()
    return fuori


@st.cache_data(show_spinner=False)
def _ritagli(bozza: str, artefatto: str, ancore_scritte: tuple, quando: float):
    """Un ritaglio di foglio per ogni scrittura: la riga com'e' venuta.

    Meglio del numero sul margine. Il numero obbliga a cercare il riquadro
    sulla pagina rimpicciolita e poi a tornare in tabella; il ritaglio mette
    sotto gli occhi la riga vera - etichetta stampata a sinistra, valore
    dentro, campi vicini - che e' l'unica cosa che permette di dire se il dato
    e' nel posto di un altro.

    `quando` non si usa: sta nella firma perche' la cache si rifaccia quando
    la bozza cambia.
    """
    rettangoli = {}
    percorso = Path(artefatto) / "mappa.json" if artefatto else None
    if percorso and percorso.is_file():
        rettangoli = {a["id"]: a["rect"]
                      for a in json.loads(percorso.read_text(encoding="utf-8"))["ancore"]}
    doc = fitz.open(bozza)
    fuori = {}
    for identificativo, pagina_uno, tipo in ancore_scritte:
        rect = rettangoli.get(identificativo)
        if not rect:
            continue
        pagina = doc[int(pagina_uno) - 1]
        r = fitz.Rect(rect)
        # Una casella spuntata non si giudica dalla riga: quello che dice che
        # cosa si e' scelto sta SOPRA, nell'intestazione della colonna - "da 16
        # a 50 lavoratori", "societa' a responsabilita' limitata". Un campo di
        # testo invece ha l'etichetta a sinistra, e li' basta poco spazio.
        sopra = 30 if tipo == "casella" else 9
        taglio = fitz.Rect(max(0, pagina.rect.x0 + 8), max(0, r.y0 - sopra),
                           min(pagina.rect.x1 - 8, pagina.rect.x1), r.y1 + 7)
        # Annotazione e non disegno: si toglie dopo. Disegnando, i ritagli
        # successivi della stessa pagina si porterebbero dietro i riquadri di
        # quelli prima, e si vedrebbero tre cornici rosse su una riga sola.
        segno = pagina.add_rect_annot(r)
        segno.set_colors(stroke=ROSSO)
        segno.set_border(width=1.1)
        segno.update()
        fuori[identificativo] = pagina.get_pixmap(dpi=125, clip=taglio).tobytes("png")
        pagina.delete_annot(segno)
    doc.close()
    return fuori


INTORNO_RITAGLIO = 9         # quanto foglio sopra la riga, nel ritaglio
# Quanto testo si legge intorno a una ricorrenza per capire se e' quella
# giusta. Due punti bastano per una riga sola, ma un paragrafo lungo sul
# foglio va a capo tre volte e la frase registrata sta su piu' righe: con
# una finestra stretta non si riconosce. Misurato su sei moduli, 138
# scritture: +-2 ne colloca 124, +-14 ne colloca 127, +-26 ne colloca 129.
ALTEZZA_CONTESTO = 26
SOMIGLIANZA_MINIMA = 0.35    # sotto, non e' la riga che cercavamo


def _dove_sul_foglio(documento, scritture):
    """Per ogni scrittura, il rettangolo sul foglio dove il valore e' finito.

    In un Word non c'e' geometria - non si misura niente, si sostituisce del
    testo - quindi il posto sulla pagina si trova cercando il valore nel PDF.
    Il problema e' che lo stesso valore c'e' piu' volte: "Imperia" compare
    sei volte su un modulo, fra comune di nascita, residenza e sede.

    Si sceglie con la frase: di ogni ricorrenza si legge il testo intorno e
    si tiene quella che somiglia di piu' alla riga che il controllo ha
    registrato per quella scrittura. Se nessuna somiglia abbastanza non si
    cerchia niente: un riquadro sul campo sbagliato e' peggio di nessun
    riquadro, perche' fa buttare via una bozza giusta.
    """
    from difflib import SequenceMatcher

    def pulita(testo):
        return re.sub(r"\s+", " ", (testo or "")).strip().lower()

    fuori = {}
    for s in scritture:
        valore = str(s["valore"]).strip()
        atteso = pulita(s.get("riga"))
        if not valore:
            continue
        def quanto(intorno):
            """Quanta parte della frase piu' corta si ritrova nell'altra.

            Non il rapporto di somiglianza secco: quello penalizza le righe
            brevi, dove il contesto e' poco e la frase registrata e' lunga.
            Cosi' una riga corta e giusta non viene scartata.
            """
            if not intorno or not atteso:
                return 0.0
            uguale = SequenceMatcher(None, intorno, atteso).find_longest_match(
                0, len(intorno), 0, len(atteso))
            return uguale.size / min(len(intorno), len(atteso))

        migliore, punteggio_migliore = None, 0.0
        for numero_pagina, pagina in enumerate(documento):
            for r in pagina.search_for(valore):
                largo = fitz.Rect(pagina.rect.x0, r.y0 - ALTEZZA_CONTESTO,
                                  pagina.rect.x1, r.y1 + ALTEZZA_CONTESTO)
                punteggio = quanto(pulita(pagina.get_textbox(largo)))
                if punteggio > punteggio_migliore:
                    migliore, punteggio_migliore = (numero_pagina, r), punteggio
        if migliore and punteggio_migliore >= SOMIGLIANZA_MINIMA:
            fuori[s["ancora"]] = migliore
    return fuori


@st.cache_data(show_spinner=False)
def _anteprima_word(bozza: str, scritture: tuple, quando: float):
    """Le pagine della bozza Word, con ogni scrittura cerchiata e numerata.

    Stessa cosa che si vede sul percorso PDF, e per la stessa ragione: un
    elenco di righe non e' un foglio, e la domanda "e' nel posto giusto" si
    risponde guardando il posto.

    `quando` non si usa: sta nella firma perche' la cache si rifaccia quando
    la bozza cambia.
    """
    voci = [{"ancora": a, "valore": v, "riga": r} for a, v, r in scritture]
    foglio = word.in_pdf(Path(bozza), Path(bozza).parent / "anteprima")
    documento = fitz.open(str(foglio))
    posti = _dove_sul_foglio(documento, voci)

    ritagli, per_pagina = {}, {}
    for numero, s in enumerate(voci, 1):
        trovato = posti.get(s["ancora"])
        if not trovato:
            continue
        indice, r = trovato
        pagina = documento[indice]
        per_pagina.setdefault(indice, []).append((numero, r))
        taglio = fitz.Rect(pagina.rect.x0 + 8, max(0, r.y0 - INTORNO_RITAGLIO),
                           pagina.rect.x1 - 8, r.y1 + 7)
        # Annotazione e non disegno, come sul PDF: disegnando, i ritagli dopo
        # si porterebbero dietro i riquadri di quelli prima.
        segno = pagina.add_rect_annot(r)
        segno.set_colors(stroke=ROSSO)
        segno.set_border(width=1.1)
        segno.update()
        ritagli[s["ancora"]] = pagina.get_pixmap(dpi=125, clip=taglio).tobytes("png")
        pagina.delete_annot(segno)

    pagine = []
    for indice, pagina in enumerate(documento):
        segni = per_pagina.get(indice, [])
        for numero, r in segni:
            pagina.draw_rect(r, color=ROSSO, width=1.1)
            larga = 7.5 + 3.6 * (len(str(numero)) - 1)
            base = max(ALTEZZA_TARGA, r.y0)
            targa = fitz.Rect(r.x0, base - ALTEZZA_TARGA, r.x0 + larga, base)
            pagina.draw_rect(targa, color=ROSSO, fill=ROSSO, width=0)
            pagina.insert_text((targa.x0 + 1.4, targa.y1 - 1.8), str(numero),
                               fontsize=6.4, color=(1, 1, 1))
        numeri = sorted(n for n, _ in segni)
        quali = ""
        if numeri:
            quali = (" — righe %d-%d" % (numeri[0], numeri[-1])
                     if numeri[-1] - numeri[0] + 1 == len(numeri)
                     else " — righe " + ", ".join(str(n) for n in numeri))
        pagine.append((indice + 1,
                       pagina.get_pixmap(dpi=DPI_ANTEPRIMA).tobytes("png"), quali))
    documento.close()
    return pagine, ritagli


def _striscia(arrivato: int) -> str:
    """Le cinque fasi in fila, con il segno di dove siamo.

    Serve perche' la compilazione dura minuti e quasi tutto il tempo se ne va
    in due fasi sole - decidere e verificare. Senza la striscia, chi guarda
    vede una pagina ferma e non sa se sta lavorando o se si e' piantata.
    """
    pezzi = []
    for numero, (_, etichetta) in enumerate(lavorazione.FASI, 1):
        if numero < arrivato:
            pezzi.append("~~%s~~" % etichetta)      # fatta
        elif numero == arrivato:
            pezzi.append("**%s**" % etichetta)      # in corso
        else:
            pezzi.append(etichetta)                 # ancora da fare
    return "  ·  ".join(pezzi)


_stato("passi", [])
_stato("verdetto", None)
_stato("bozza", None)
_stato("domanda", None)
_stato("avvisi", [])
_stato("rifiuto", None)
_stato("artefatto", None)
_stato("w_verdetto", None)
_stato("w_bozza", None)
_stato("w_domanda", None)
_stato("w_rifiuto", None)
_stato("w_modulo", None)


# --------------------------------------------------------------- la spalla

# Il primo avvio su un server nuovo: il disco e' vuoto e l'anagrafica non
# c'e' ancora. Prima l'app si fermava con "Nessun fascicolo in fascicoli/",
# che e' il nome di una cartella e non dice a chi legge che cosa fare. Il
# fascicolo dell'impresa non viaggia dentro l'immagine - sono dati di
# persone vere, e un'immagine finisce in posti che non si controllano -
# quindi il primo giorno si carica, e questa e' la pagina che lo chiede.
if not fascicoli.elenco(DATI):
    st.markdown(_marchio(), unsafe_allow_html=True)
    st.title("Manca l'anagrafica dell'impresa")
    st.write("Prima di compilare un modulo devo sapere chi e' l'impresa: "
             "ragione sociale, sede, partita IVA, posizioni INPS e INAIL. "
             "Si carica una volta sola e resta.")
    arrivato = st.file_uploader("Trascina qui il file dell'anagrafica (.json)",
                                type="json", key="prima_anagrafica")
    if arrivato is not None:
        try:
            dati = json.loads(arrivato.getvalue().decode("utf-8"))
            nuovo, resoconto = fascicoli.importa(dati)
        except (ValueError, UnicodeDecodeError) as guaio:
            st.error("Non riesco a leggerlo: %s" % guaio)
        else:
            st.info(fascicoli.racconta_importazione(resoconto))
            if st.button("Salva questa anagrafica", type="primary"):
                (DATI / "fascicoli").mkdir(parents=True, exist_ok=True)
                fascicoli.salva(DATI / "fascicoli" / Path(arrivato.name).name,
                                nuovo)
                st.rerun()
    st.stop()

with st.sidebar:
    st.markdown(_marchio(), unsafe_allow_html=True)
    elenco = fascicoli.elenco(DATI)
    # Con un fascicolo solo non c'e' niente da scegliere, e la tendina non
    # fa che chiedere di decidere una cosa gia' decisa. In produzione c'e'
    # quello dell'impresa e basta: si vede il nome e via.
    if len(elenco) == 1:
        scelto = elenco[0]
    else:
        # I fascicoli veri per primi: il predefinito dev'essere quello con
        # cui si lavora, non il primo in ordine alfabetico, che qui sarebbe
        # l'ombra.
        ordinati = sorted(elenco,
                          key=lambda p: fascicoli.e_di_prova(fascicoli.carica(p)))
        scelto = st.selectbox(
            "Fascicolo", ordinati,
            format_func=lambda p: p.name + (
                "  —  DATI FINTI"
                if fascicoli.e_di_prova(fascicoli.carica(p)) else ""))
    fascicolo = fascicoli.carica(scelto)
    profilo = fascicolo.get("profilo", {})
    st.caption(profilo.get("ragione_sociale", ""))
    # Detto qui e detto forte: una bozza compilata con dati inventati sembra
    # in tutto una bozza buona, e l'unico momento in cui ci si puo'
    # accorgere e' prima di cominciare.
    if fascicoli.e_di_prova(fascicolo):
        st.error("**Dati finti.** Questo fascicolo serve alle prove: le "
                 "bozze che escono non si consegnano a nessuno.")

    # Sul piano gratuito non c'e' un disco: quello che si scrive vive finche'
    # il server resta acceso. Dirlo e' meno della meta' del lavoro - l'altra
    # meta' e' rendere indolore rimetterlo, e per questo c'e' il bottone.
    # Scoprirlo da soli, con l'anagrafica sparita e un modulo da consegnare,
    # sarebbe il modo peggiore.
    if os.environ.get("DATI_VOLATILI"):
        with st.expander("L'anagrafica va tenuta al sicuro"):
            st.caption("Questo server non ha una memoria permanente: se si "
                       "riavvia, l'anagrafica va ricaricata. Tienine una "
                       "copia sul tuo computer e rimetterla sarà questione "
                       "di secondi.")
            st.download_button(
                "Scarica l'anagrafica",
                json.dumps(fascicolo, ensure_ascii=False, indent=1)
                    .encode("utf-8"),
                file_name=Path(scelto).name, mime="application/json")
    vuoti = scheda.mancanti(profilo)
    st.caption("%d dati in anagrafica%s"
               % (len(profilo), ", %d da riempire" % len(vuoti) if vuoti else ""))

    st.divider()
    # Si dice che cosa si puo' fare, non come e' fatto sotto. "Contenitore
    # isolato pronto" e "Modello: deepseek-flash" erano due cose vere e due
    # cose inutili per chi compila: non puo' deciderne nessuna delle due, e
    # leggerle la mette davanti all'impianto invece che al suo lavoro. Dei
    # guai invece va detto tutto, perche' cambiano quello che puo' fare.
    if agente.disponibile():
        st.success("Pronta: posso compilare Word e PDF.")
    else:
        st.error("Manca la chiave del servizio che legge i moduli: posso solo "
                 "rifare i PDF gia' compilati una volta. Chiedi a chi "
                 "l'ha installata.")

    # Qui c'era il conto dei moduli PDF gia' compilati, con l'elenco delle
    # cartelle: "prova_gratis_sassari_894b5399". Nomi interni, con l'impronta
    # attaccata, che non si riconoscono e su cui non si fa niente - il modulo
    # si carica, non si sceglie da quella lista. Era un quadrante per chi ha
    # scritto il programma, in una pagina che non e' sua.


pagina_moduli, pagina_word, pagina_anagrafica = st.tabs(
    ["Compila un PDF", "Compila un Word", "Anagrafica"])


# ------------------------------------------------------------- la lavagna

with pagina_moduli:
    st.title("Compila un modulo")
    caricato = st.file_uploader("Trascina qui il PDF del modulo", type="pdf")

    def _compila(modulo: Path, confermata: bool = False):
        st.session_state.passi, st.session_state.verdetto = [], None
        st.session_state.bozza, st.session_state.domanda = None, None
        st.session_state.avvisi, st.session_state.rifiuto = [], None
        barra = st.empty()
        racconto = st.container()
        try:
            for passo in lavorazione.lavora(RADICE, modulo, fascicolo, LAVORO,
                                            pertinenza_confermata=confermata):
                st.session_state.passi.append(passo)
                _, arrivato = lavorazione.fase(passo)
                if arrivato:
                    with barra.container():
                        st.progress(arrivato / len(lavorazione.FASI))
                        st.caption(_striscia(arrivato))
                with racconto:
                    # Del verdetto si racconta solo il titolo: l'elenco per
                    # esteso sta nel riquadro sotto, e stamparlo due volte
                    # significa scorrere due muri di testo identici per
                    # arrivare alla bozza.
                    st.write(passo["testo"].split("\n")[0]
                             if passo["passo"] == "verdetto" else passo["testo"])
                if passo.get("verdetto"):
                    st.session_state.verdetto = passo["verdetto"]
                    st.session_state.bozza = passo.get("bozza")
                    st.session_state.avvisi = passo.get("avvisi") or []
                if passo.get("artefatto"):
                    st.session_state.artefatto = passo["artefatto"]
                if passo["passo"] == "domanda_bloccante":
                    st.session_state.domanda = passo["domanda"]
                if passo["passo"] == "rifiuto":
                    st.session_state.rifiuto = passo["testo"]
        except esecuzione.IsolamentoAssente as fermata:
            st.error(str(fermata))
        except agente.ModelloAssente as fermata:
            st.error(str(fermata))

    if caricato is not None and st.button("Compila", type="primary"):
        LAVORO.mkdir(parents=True, exist_ok=True)
        modulo = LAVORO / caricato.name
        modulo.write_bytes(caricato.getbuffer())
        st.session_state.modulo = str(modulo)
        _compila(modulo)

    if st.session_state.rifiuto:
        st.error(st.session_state.rifiuto)

    # La domanda sulla pertinenza e' l'unica che ferma il lavoro, e finora non
    # si poteva rispondere: il motore la faceva, la pagina la mostrava, e li'
    # finiva. Chi conosce la gara sa la risposta meglio del modello, e deve
    # poterla dare senza ricaricare niente.
    if st.session_state.domanda:
        st.warning("Prima di andare avanti: %s" % st.session_state.domanda)
        si, no = st.columns(2)
        if si.button("Sì, è di questa impresa: vai avanti"):
            _compila(Path(st.session_state.modulo), confermata=True)
        if no.button("No, era il modulo sbagliato"):
            st.session_state.domanda = None
            st.session_state.passi = []
            st.info("Lasciato stare. Non ho scritto niente.")

    # Sta sopra il verdetto apposta. Il verdetto dice che ogni scrittura e'
    # finita dentro il suo campo, ed e' vero; non dice se il campo era di
    # questa impresa. Su un fascicolo di gara quella differenza vale una
    # dichiarazione falsa, e se l'avviso stesse in fondo lo leggerebbe solo
    # chi gia' sospetta.
    if st.session_state.avvisi:
        pagine = sorted({a["pagina"] for a in st.session_state.avvisi})
        st.error("**Da controllare a mano prima di consegnare: pagina %s.** "
                 "Qui il modulo parla di un soggetto diverso dall'impresa, "
                 "oppure la sezione vale solo in certi casi. E' il punto in "
                 "cui questo strumento sbaglia piu' spesso."
                 % ", ".join(str(p) for p in pagine))
        for a in st.session_state.avvisi:
            st.caption("pagina %d — %s — %d campi scritti — «%s»"
                       % (a["pagina"], a["motivo"], len(a["ancore"]), a["riga"]))

    verdetto = st.session_state.verdetto
    if verdetto:
        st.divider()
        testa = {controllo.COMPLETO: st.success,
                 controllo.MANCANO_DATI: st.info,
                 controllo.NON_RIUSCITO: st.warning,
                 controllo.ERRORI_NON_SEGNALATI: st.error}[verdetto["stato"]]
        testa(controllo.racconta(verdetto).split("\n")[0])

        sinistra, destra = st.columns([2, 3])

        with sinistra:
            st.subheader("Verdetto")
            st.text(controllo.racconta(verdetto))

            aperti = verdetto["punti_aperti"]
            if aperti:
                # Due gruppi con due destini diversi: quelli che hanno un posto
                # nel fascicolo si rispondono qui e restano buoni per i moduli
                # futuri; gli altri si scrivono a mano sulla bozza. Prima erano
                # mescolati, e su un modulo di quattro pagine diventavano
                # quarantotto caselle di cui tre quarti inutili.
                # Un punto aperto entra nel fascicolo solo se chiede un dato
                # dell'anagrafica **che gia' esiste**. Il modello puo' nominare
                # una chiave, non inventarne una: lasciandogliele creare, il
                # fascicolo si riempie di `profilo.referente` e
                # `profilo.firma_legale_rappresentante`, e il modulo dopo le
                # reinventa con un altro nome che non combacia con niente.
                # Tutto il resto -- i dati di QUESTA pratica -- si scrive a
                # mano sulla bozza, guardando la pagina.
                def _in_anagrafica(p):
                    chiave = p.get("chiave") or ""
                    if not chiave.startswith("profilo."):
                        return False
                    return chiave.split(".", 1)[1] in profilo

                salvabili = [p for p in aperti if _in_anagrafica(p)]
                a_mano = [p for p in aperti if not _in_anagrafica(p)]

                # Il titolo diceva "Da completare: 12" su un modulo venuto
                # bene: tre campi d'anagrafica scritti giusti, e dodici buchi
                # che sono marca da bollo, timbro e firma. Contarli insieme fa
                # sembrare un fallimento quello che e' il risultato atteso.
                if salvabili:
                    st.subheader("Mancano %d dati dell'impresa" % len(salvabili))
                else:
                    st.subheader("L'anagrafica è a posto")
                    st.caption("Tutto quello che il fascicolo sa su questa "
                               "impresa è finito sulla bozza. Il resto del "
                               "modulo riguarda questa pratica e lo compili tu.")

                con_nome = [p for p in a_mano if (p["etichetta"] or "").strip()]
                muti = len(a_mano) - len(con_nome)
                if con_nome:
                    with st.expander("I %d campi che restano a te" % len(a_mano)):
                        st.dataframe(
                            [{"pagina": p["pagina"], "campo": p["etichetta"]}
                             for p in con_nome],
                            use_container_width=True, hide_index=True)
                        if muti:
                            st.caption("Altri %d non hanno un'etichetta: si "
                                       "vedono solo guardando la bozza." % muti)

                if salvabili:
                    with st.expander("Riempi i %d dati d'anagrafica che mancano"
                                     % len(salvabili)):
                        st.caption("Sono dati dell'impresa che il fascicolo non "
                                   "ha ancora. Rispondendo qui restano buoni "
                                   "per tutti i moduli futuri, e questo si rifa' "
                                   "senza nuove chiamate al modello.")
                        with st.form("punti"):
                            risposte = {}
                            for p in salvabili:
                                etichetta = "%s (pagina %d)" % (
                                    p["etichetta"] or p["ancora"], p["pagina"])
                                # La chiave e' obbligatoria: su un modulo le
                                # etichette si ripetono - tre "metri", tre
                                # "altro" - e senza chiave Streamlit si ferma
                                # con un errore invece di disegnare la pagina.
                                risposte[p["ancora"]] = st.text_input(
                                    etichetta, key="aperto_" + p["ancora"],
                                    help=p.get("motivo"))
                            if st.form_submit_button("Salva nel fascicolo e rifai"):
                                aggiornati = 0
                                for p in salvabili:
                                    valore = (risposte.get(p["ancora"]) or "").strip()
                                    if not valore:
                                        continue
                                    fascicoli.imposta(fascicolo, p["chiave"], valore)
                                    aggiornati += 1
                                if aggiornati:
                                    fascicoli.salva(scelto, fascicolo)
                                    st.success("%d dati salvati. Premi Compila: "
                                               "riusa il programma gia' fatto, "
                                               "senza spendere." % aggiornati)
                                else:
                                    st.caption("Non hai scritto niente.")

        with destra:
            st.subheader("La bozza")
            if st.session_state.bozza:
                percorso = Path(st.session_state.bozza)
                st.download_button("Scarica la bozza", percorso.read_bytes(),
                                   file_name="bozza_" + Path(st.session_state.get(
                                       "modulo", "modulo.pdf")).name,
                                   mime="application/pdf")
                st.caption("I riquadri rossi sono le scritture, numerati come "
                           "nel riquadro «Rivedi e togli quello che non va».")
                for numero, immagine, quali in _pagine_segnate(
                        percorso, st.session_state.artefatto,
                        verdetto["verificate"]):
                    st.image(immagine, use_container_width=True,
                             caption="pagina %d%s" % (numero, quali))

        # Togliere un campo sbagliato invece di buttare la bozza. Finora una
        # castroneria costava tutto il modulo: cinquanta campi giusti persi per
        # uno storto. Qui si toglie quello, il programma si riesegue con la
        # stessa geometria e nessuna chiamata al modello, e quello che resta e'
        # gia' verificato.
        with st.expander("Rivedi e togli quello che non va"):
            st.caption("Leggi la colonna «come si legge sul modulo»: è la frase "
                       "del foglio col valore dentro. Spunta «togli» su quello "
                       "che non ti convince e rifai la bozza: non costa niente.")
            ritagli = _ritagli(
                str(st.session_state.bozza), str(st.session_state.artefatto or ""),
                tuple((r["ancora"], r["pagina"], r["tipo"])
                      for r in verdetto["verificate"]),
                Path(st.session_state.bozza).stat().st_mtime)

            da_togliere = []
            pagina_mostrata = None
            for numero, r in enumerate(verdetto["verificate"], 1):
                if r["pagina"] != pagina_mostrata:
                    pagina_mostrata = r["pagina"]
                    st.markdown("**pagina %s**" % pagina_mostrata)
                sinistra_r, destra_r = st.columns([1, 11])
                with sinistra_r:
                    if st.checkbox("%d" % numero, key="togli_" + r["ancora"]):
                        da_togliere.append(r["ancora"])
                with destra_r:
                    immagine = ritagli.get(r["ancora"])
                    if immagine:
                        st.image(immagine, use_container_width=True)
                    else:
                        st.caption(r.get("riga") or r["etichetta"] or r["ancora"])
            if st.button("Rifai la bozza senza i %d campi spuntati" % len(da_togliere),
                         disabled=not da_togliere or not st.session_state.artefatto):
                cartella = Path(st.session_state.artefatto)
                codice = (cartella / "programma.py").read_text(encoding="utf-8")
                mappa_art = json.loads((cartella / "mappa.json").read_text(encoding="utf-8"))
                note_art = json.loads((cartella / "note.json").read_text(encoding="utf-8"))
                originale = Path(st.session_state.modulo)
                esito = esecuzione.esegui_al_meglio(compilatore.senza(codice, da_togliere),
                                          originale, LAVORO, fascicolo)
                if not esito["riuscita"]:
                    st.error("Non sono riuscito a rifarla: %s"
                             % (esito["stderr"] or esito["stdout"])[:300])
                else:
                    scritture = json.loads(
                        Path(esito["scritture"]).read_text(encoding="utf-8"))
                    nuovo = controllo.controlla(originale, esito["bozza"],
                                                mappa_art, scritture, note_art)
                    nuovo["soggetti_da_controllare"] = soggetti.avvertimenti(
                        mappa_art, [r["ancora"] for r in nuovo["verificate"]])
                    st.session_state.verdetto = nuovo
                    st.session_state.bozza = esito["bozza"]
                    st.session_state.avvisi = nuovo["soggetti_da_controllare"]
                    st.success("Rifatta senza %d campi. Scaricala qui accanto."
                               % len(da_togliere))
                    st.rerun()


# ----------------------------------------------------------- l'anagrafica

# ----------------------------------------------------------------- il Word

with pagina_word:
    st.title("Compila un Word")
    st.caption("Accetta anche i `.doc` vecchi: li converte da solo. È un "
               "percorso separato da quello PDF — in un Word il testo c'è e "
               "si sostituisce, non c'è niente da misurare.")

    caricato_w = st.file_uploader("Trascina qui il modulo Word",
                                  type=["docx", "doc"], key="carica_word")

    # Misurato su 48 bandi e 4553 campi: questa domanda da sola decide 1152
    # campi, il 25,3%. Se l'impresa si presenta da sola, un quarto del modulo
    # si spegne prima di chiedere al modello - meno spesa e meno occasioni di
    # sbagliare. E' la cosa che migliora di piu' il risultato, e costa un clic.
    st.markdown("**Come partecipa l'impresa a questa gara?**")
    # A scelta multipla e non singola: si puo' partecipare in raggruppamento
    # E subappaltare, e con la scelta singola chi lo fa si vedeva spegnere
    # sezioni che invece lo riguardano.
    # Tre risposte esplicite e non una casella che ne apre altre: "da sola" e
    # "non lo so" sono risposte OPPOSTE - la prima spegne un quarto del
    # modulo, la seconda non spegne niente - e con la casella "lo so gia'"
    # si assomigliavano, perche' spuntata-e-basta e non-spuntata si vedono
    # quasi uguali.
    DA_SOLA = "Partecipa da sola"
    INSIEME = "Partecipa insieme ad altri, o subappalta"
    NON_SO = "Non lo so ancora"
    risposta = st.radio("scelta della partecipazione",
                        [DA_SOLA, INSIEME, NON_SO], key="w_partecipazione",
                        label_visibility="collapsed",
                        help="È la risposta che conta di più: su 48 bandi "
                             "decide 1152 campi su 4553, il 25%.")
    if risposta == NON_SO:
        condizioni_w = None
        st.caption("Senza risposta decide il modello, sezione per sezione, ed "
                   "è lì che sbaglia più spesso. Se lo sai, dimmelo.")
    else:
        scelte = set()
        if risposta == INSIEME:
            c1, c2, c3 = st.columns(3)
            if c1.checkbox("In raggruppamento o consorzio", key="w_rti"):
                scelte.add("raggruppamento")
            if c2.checkbox("Con avvalimento", key="w_avv"):
                scelte.add("avvalimento")
            if c3.checkbox("Con subappalto", key="w_sub"):
                scelte.add("subappalto")
        condizioni_w = scelte
        if risposta == INSIEME and not scelte:
            st.caption("Spunta quali: finché non lo fai è come dire che "
                       "partecipa da sola.")
        elif not scelte:
            st.caption("**Partecipa da sola.** Le sezioni su raggruppamenti, "
                       "avvalimento e subappalto resteranno vuote: su un bando "
                       "tipico è circa un quarto dei campi.")
        else:
            st.caption("Restano attive: %s. Le altre sezioni condizionali "
                       "resteranno vuote." % ", ".join(sorted(scelte)))

    def _compila_word(documento: Path, confermata: bool = False, togli=(),
                      condizioni=None, scelte_di_prima=None):
        st.session_state.w_verdetto = None
        st.session_state.w_bozza = None
        st.session_state.w_domanda = None
        st.session_state.w_rifiuto = None
        barra = st.empty()
        racconto = st.container()
        try:
            for passo in lavorazione_word.lavora(RADICE, documento, fascicolo,
                                                 LAVORO_WORD,
                                                 pertinenza_confermata=confermata,
                                                 togli=togli,
                                                 condizioni=condizioni,
                                                 scelte_di_prima=scelte_di_prima):
                _, arrivato = lavorazione.fase(passo)
                if arrivato:
                    with barra.container():
                        st.progress(arrivato / len(lavorazione.FASI))
                        st.caption(_striscia(arrivato))
                with racconto:
                    st.write(passo["testo"].split("\n")[0]
                             if passo["passo"] == "verdetto" else passo["testo"])
                if passo.get("verdetto"):
                    st.session_state.w_verdetto = passo["verdetto"]
                    st.session_state.w_bozza = passo.get("bozza")
                if passo["passo"] == "domanda_bloccante":
                    st.session_state.w_domanda = passo["domanda"]
                if passo["passo"] == "rifiuto":
                    st.session_state.w_rifiuto = passo["testo"]
        except agente.ModelloAssente as fermata:
            st.error(str(fermata))
        except Exception as fermata:
            st.session_state.w_verdetto = None
            st.session_state.w_bozza = None
            st.error("Compilazione Word interrotta (%s). Nessuna bozza verificata disponibile: riprova."
                     % type(fermata).__name__)

    if caricato_w is not None and st.button("Compila il Word", type="primary"):
        LAVORO_WORD.mkdir(parents=True, exist_ok=True)
        modulo_w = LAVORO_WORD / caricato_w.name
        modulo_w.write_bytes(caricato_w.getbuffer())
        st.session_state.w_modulo = str(modulo_w)
        _compila_word(modulo_w, condizioni=condizioni_w)

    if st.session_state.w_rifiuto:
        st.error(st.session_state.w_rifiuto)

    if st.session_state.w_domanda:
        st.warning("Prima di andare avanti: %s" % st.session_state.w_domanda)
        si_w, no_w = st.columns(2)
        if si_w.button("Sì, è di questa impresa: vai avanti", key="si_word"):
            _compila_word(Path(st.session_state.w_modulo), confermata=True,
                          condizioni=condizioni_w)
        if no_w.button("No, era il modulo sbagliato", key="no_word"):
            st.session_state.w_domanda = None
            st.info("Lasciato stare. Non ho scritto niente.")

    vw = st.session_state.w_verdetto
    if vw:
        st.divider()
        # Le contraddizioni stanno in cima e sono rosse: due dichiarazioni
        # alternative compilate insieme dicono cose incompatibili, e a
        # differenza di una casella vuota non si vedono scorrendo il foglio.
        if vw["contraddizioni"]:
            st.error("**%d dichiarazioni alternative risultano compilate più "
                     "di una volta.** Dicono cose incompatibili: vanne tolta "
                     "una." % len(vw["contraddizioni"]))
            for c in vw["contraddizioni"]:
                st.caption("· %s" % c["riga"])
                st.caption("· %s" % c["altra"])
        if vw["avvisi"]:
            st.warning("**Da controllare a mano:** qui il modulo parla di un "
                       "soggetto diverso dall'impresa, oppure la sezione vale "
                       "solo in certi casi.")
            for a in vw["avvisi"]:
                st.caption("%s — %d campi — «%s»"
                           % (a["motivo"], len(a["ancore"]), a["riga"]))

        messaggio_w = lavorazione_word.racconta(vw)
        if vw.get("esito") == "non_compilato":
            st.error(messaggio_w)
        elif vw.get("esito") == "da_verificare":
            st.warning(messaggio_w)
        else:
            st.success(messaggio_w)

        if st.session_state.w_bozza:
            st.download_button("Scarica la bozza Word",
                               Path(st.session_state.w_bozza).read_bytes(),
                               file_name="bozza_" + Path(
                                   st.session_state.get("w_modulo", "modulo.docx")).name,
                               mime="application/vnd.openxmlformats-"
                                    "officedocument.wordprocessingml.document")

        # L'anteprima del foglio, come sul PDF. Costa una conversione con
        # LibreOffice e qualche secondo: se non c'e', si va avanti col testo,
        # che e' comunque quello che serve per giudicare.
        pagine_w, ritagli_w = [], {}
        if st.session_state.w_bozza:
            try:
                pagine_w, ritagli_w = _anteprima_word(
                    st.session_state.w_bozza,
                    tuple((r["ancora"], r["valore"], r.get("riga", ""))
                          for r in vw["verificate"]),
                    Path(st.session_state.w_bozza).stat().st_mtime)
            except Exception as guaio:                     # noqa: BLE001
                st.caption("Non riesco a mostrarti il foglio (%s). "
                           "La bozza c'è lo stesso: qui sotto trovi le righe."
                           % str(guaio)[:80])

        if pagine_w:
            with st.expander("Guarda le pagine (%d)" % len(pagine_w)):
                for numero, immagine, quali in pagine_w:
                    st.caption("Pagina %d%s" % (numero, quali))
                    st.image(immagine, use_container_width=True)

        with st.expander("Rivedi e togli quello che non va (%d scritture)"
                         % len(vw["verificate"])):
            st.caption("Per ogni riga: il valore, la frase del documento, e il "
                       "ritaglio del foglio com'è venuto. Spunta quelle "
                       "sbagliate e rifai la bozza.")
            togliere_w = []
            for numero, r in enumerate(vw["verificate"], 1):
                sx, dx = st.columns([1, 11])
                with sx:
                    if st.checkbox("%d" % numero, key="w_togli_" + r["ancora"]):
                        togliere_w.append(r["ancora"])
                with dx:
                    st.markdown("**%s** — %s" % (r["valore"], r.get("riga", "")))
                    if ritagli_w.get(r["ancora"]):
                        st.image(ritagli_w[r["ancora"]])
            if st.button("Rifai la bozza senza i %d campi spuntati"
                         % len(togliere_w), disabled=not togliere_w,
                         key="rifai_word"):
                # Si rimanda indietro la decisione gia' presa: il modello non
                # viene richiamato, quindi gli altri campi restano quelli che
                # hai appena guardato. Richiamandolo era libero di rispondere
                # diverso, e togliendo un campo se ne muovevano altri.
                _compila_word(Path(st.session_state.w_modulo),
                              confermata=True, togli=togliere_w,
                              condizioni=condizioni_w,
                              scelte_di_prima=vw.get("scelte"))
                st.rerun()

        if vw["mancate"]:
            with st.expander("%d valori non scritti: motivi"
                             % len(vw["mancate"])):
                for m in vw["mancate"]:
                    st.caption("%s — %s" % (m["valore"][:60], m["motivo"]))


with pagina_anagrafica:
    st.title("Anagrafica")
    st.caption("I dati dell'impresa, una volta sola. Ogni dato che manca qui "
               "e' una casella vuota su ogni modulo futuro.")

    with st.expander("Importa un'anagrafica da un file"):
        st.caption("Un JSON esportato da un'altra parte. La sezione dei dati "
                   "puo' chiamarsi profilo, profilo_app, anagrafica o dati: "
                   "la riconosco e la rinomino come serve al compilatore.")
        arrivato = st.file_uploader("Trascina qui il JSON", type="json",
                                    key="json_anagrafica")
        if arrivato is not None:
            try:
                dati = json.loads(arrivato.getvalue().decode("utf-8"))
                nuovo, resoconto = fascicoli.importa(dati)
            except (ValueError, UnicodeDecodeError) as guaio:
                st.error("Non riesco a leggerlo: %s" % guaio)
            else:
                st.info(fascicoli.racconta_importazione(resoconto))
                nome = st.text_input("Salvalo come", value=arrivato.name,
                                     key="nome_anagrafica")
                if st.button("Salva questa anagrafica", type="primary"):
                    destinazione = DATI / "fascicoli" / Path(nome).name
                    if not destinazione.suffix:
                        destinazione = destinazione.with_suffix(".json")
                    fascicoli.salva(destinazione, nuovo)
                    st.success("Salvata in %s. Scegliela nella colonna a "
                               "sinistra per usarla." % destinazione.name)

    st.divider()

    if not profilo:
        st.warning("Questo fascicolo non ha una sezione «profilo»: importane "
                   "uno qui sopra.")
    else:
        cerca = st.text_input("Cerca un dato",
                              placeholder="per esempio: pec, sede, SOA")
        if vuoti:
            st.info("Da riempire: %s" % ", ".join(scheda.etichetta(k) for k in vuoti))

        def _combacia(chiave: str) -> bool:
            if not cerca.strip():
                return True
            aghi = cerca.lower().split()
            dove = (chiave + " " + scheda.etichetta(chiave) + " "
                    + str(profilo.get(chiave) or "")).lower()
            return all(a in dove for a in aghi)

        gruppi = scheda.raggruppa(profilo.keys())
        with st.form("anagrafica"):
            modifiche = {}
            mostrati = 0
            for titolo, chiavi in gruppi.items():
                visibili = [c for c in chiavi if _combacia(c)]
                if not visibili:
                    continue
                st.subheader(titolo)
                for chiave in visibili:
                    valore = str(profilo.get(chiave) or "")
                    # I testi lunghi - oggetto sociale, elenco soci - in una
                    # riga sola non si leggono e non si correggono.
                    disegna = st.text_area if len(valore) > 70 else st.text_input
                    modifiche[chiave] = disegna(scheda.etichetta(chiave),
                                                value=valore,
                                                key="ana_" + chiave,
                                                help=chiave)
                    mostrati += 1
            if not mostrati:
                st.caption("Nessun dato corrisponde a «%s»." % cerca)
            if st.form_submit_button("Salva l'anagrafica", type="primary"):
                cambiati = [k for k, v in modifiche.items()
                            if v != str(profilo.get(k) or "")]
                for chiave in cambiati:
                    fascicoli.imposta(fascicolo, "profilo." + chiave,
                                      modifiche[chiave])
                if cambiati:
                    fascicoli.salva(scelto, fascicolo)
                    st.success("Salvati %d dati: %s."
                               % (len(cambiati),
                                  ", ".join(scheda.etichetta(k) for k in cambiati)))
                else:
                    st.caption("Nessun dato cambiato.")

        with st.expander("Aggiungi un dato che non c'e'"):
            st.caption("Il nome serve al compilatore per riconoscerlo: tutto "
                       "minuscolo, parole unite da trattino basso. Per esempio "
                       "`numero_verde` o `referente_tecnico`.")
            with st.form("nuovo_dato"):
                nome_nuovo = st.text_input("Nome del dato")
                valore_nuovo = st.text_input("Valore")
                if st.form_submit_button("Aggiungi"):
                    pulito = nome_nuovo.strip().lower().replace(" ", "_")
                    if not pulito:
                        st.error("Serve un nome.")
                    elif pulito in profilo:
                        st.error("«%s» c'e' gia': lo trovi qui sopra come «%s»."
                                 % (pulito, scheda.etichetta(pulito)))
                    else:
                        fascicoli.imposta(fascicolo, "profilo." + pulito,
                                          valore_nuovo.strip())
                        fascicoli.salva(scelto, fascicolo)
                        st.success("Aggiunto «%s»." % scheda.etichetta(pulito))
