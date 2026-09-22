# -*- coding: utf-8 -*-
"""Lo strato che resta AI: il giudizio, e solo quello.

Il modello non riceve coordinate da inventare e non scrive geometria. Riceve la
mappa gia' misurata, il fascicolo e le pagine renderizzate, e risponde due cose:

    def valori(fascicolo): ...     quale dato va su quale ancora
    {"punti_aperti": [...]}        che cosa non si puo' compilare, e perche'

Scrive una *funzione*, non un elenco di valori, ed e' la differenza che tiene in
piedi la tesi: quando Bianca completa un dato mancante si aggiorna il fascicolo
e si riesegue l'artefatto, senza ripagare nessuna chiamata.

Il resto - misurare, scrivere, verificare - non passa mai di qui.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import fitz

# I nomi sono in ordine di precedenza. Quelli di Quadra vengono per primi; gli
# altri esistono perche' una chiave sta quasi sempre gia' in un .env di un altro
# progetto, e copiarla in giro e' il modo migliore per perderne il conto.
NOMI_BASE = ("QUADRA_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE",
             "OPENROUTER_BASE_URL", "DEEPSEEK_BASE_URL", "LLM_BASE_URL",
             "BASE_URL")
NOMI_CHIAVE = ("QUADRA_CHIAVE", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
               "OPENAI_API_KEY", "LLM_API_KEY", "API_KEY")
NOMI_MODELLO = ("QUADRA_MODELLO", "OPENROUTER_MODEL", "DEEPSEEK_MODEL",
                "OPENAI_MODEL", "LLM_MODEL", "MODEL", "MODELLO")

DPI_PAGINA = 110
TENTATIVI_RETE = 3
# Il tetto resta alto anche per le domande corte: deepseek-flash ragiona
# prima di rispondere, e con un tetto basso consuma tutto il budget
# pensando e restituisce zero caratteri. Si accorciano i lotti, non il tetto.
LOTTO_INCERTI = 15
BASE = CHIAVE = MODELLO = ""
DA_DOVE = {}
TETTO_GETTONI = 393216


def _primo(nomi):
    for nome in nomi:
        valore = os.environ.get(nome, "").strip()
        if valore:
            return valore, nome
    return "", ""


def configura(percorso_env=None):
    """Legge la configurazione dall'ambiente e dai file .env.

    QUADRA_ENV puo' puntare a un .env che sta altrove: la chiave resta dov'e'
    gia', non si copia in un secondo posto da tenere aggiornato.
    """
    global BASE, CHIAVE, MODELLO, TETTO_GETTONI, DA_DOVE
    try:
        from dotenv import load_dotenv
    except ImportError:                                    # pragma: no cover
        load_dotenv = None
    if load_dotenv is not None:
        load_dotenv()
        altrove = percorso_env or os.environ.get("QUADRA_ENV", "")
        if altrove and Path(altrove).is_file():
            load_dotenv(altrove, override=False)
            DA_DOVE["file"] = str(altrove)
    base, DA_DOVE["base"] = _primo(NOMI_BASE)
    CHIAVE, DA_DOVE["chiave"] = _primo(NOMI_CHIAVE)
    MODELLO, DA_DOVE["modello"] = _primo(NOMI_MODELLO)
    BASE = base.rstrip("/")
    if BASE.endswith("/chat/completions"):
        BASE = BASE[: -len("/chat/completions")]
    # Con un tetto basso e ragionamento alto il modello consuma tutto il budget
    # pensando e restituisce zero caratteri: il tetto si tiene alto.
    TETTO_GETTONI = int(os.environ.get("QUADRA_TETTO_GETTONI", "393216"))
    return BASE, CHIAVE, MODELLO


configura()


class ModelloAssente(RuntimeError):
    """Manca la configurazione del modello: non si inventa un ripiego."""


class RispostaModelloInvalida(ValueError):
    """Una risposta illeggibile non equivale a nessun campo o nessun errore."""


def _lista_risposta(risposta, campo):
    try:
        voci = json.loads(_blocco(risposta, "json") or risposta)
    except (ValueError, TypeError) as e:
        raise RispostaModelloInvalida("JSON non interpretabile") from e
    if not isinstance(voci, list) or any(
            not isinstance(v, dict) or "posto" not in v or
            not isinstance(v.get(campo), str) for v in voci):
        raise RispostaModelloInvalida("Attesa una lista di posti e " + campo)
    return voci


def disponibile() -> bool:
    return bool(BASE and CHIAVE and MODELLO)


def _chiedi(messaggi: list, temperatura: float = 0.0, tetto: int = None) -> str:
    if not disponibile():
        raise ModelloAssente(
            "Configura QUADRA_BASE_URL, QUADRA_CHIAVE e QUADRA_MODELLO in .env "
            "(endpoint compatibile con /chat/completions).")
    import time as _tempo

    import requests
    tetto = tetto or TETTO_GETTONI
    ultimo = None
    for tentativo in range(TENTATIVI_RETE):
        try:
            risposta = requests.post(
                BASE + "/chat/completions",
                headers={"Authorization": "Bearer " + CHIAVE,
                         "Content-Type": "application/json"},
                json={"model": MODELLO, "messages": messaggi,
                      "max_tokens": tetto, "temperature": temperatura},
                timeout=600)
            risposta.raise_for_status()
            break
        except Exception as guaio:                         # noqa: BLE001
            # su cento chiamate qualcuna cade: non deve buttare via la corsa
            ultimo = guaio
            if tentativo == TENTATIVI_RETE - 1:
                raise
            _tempo.sleep(2 * (tentativo + 1))
    dati = risposta.json()
    scelta = dati["choices"][0]
    if scelta.get("finish_reason") == "length" and not scelta["message"].get("content"):
        raise RuntimeError("il modello ha esaurito il budget pensando e non ha "
                           "restituito niente: alza QUADRA_TETTO_GETTONI")
    return scelta["message"].get("content") or ""


# ------------------------------------------------------------- le immagini

def immagini(pdf, pagine=None, dpi: int = DPI_PAGINA) -> list:
    """Le pagine renderizzate, da rimandare indietro dopo ogni tentativo.

    E' l'unica cosa che permette al modello di accorgersi di aver sbagliato:
    senza il render non ha nessun motivo di sospettare di se'.
    """
    doc = fitz.open(pdf)
    fuori = []
    for numero, pagina in enumerate(doc):
        if pagine is not None and numero not in pagine:
            continue
        dati = pagina.get_pixmap(dpi=dpi).tobytes("png")
        fuori.append("data:image/png;base64," + base64.b64encode(dati).decode("ascii"))
    doc.close()
    return fuori


def _messaggio(testo: str, figure=()) -> dict:
    contenuto = [{"type": "text", "text": testo}]
    for f in figure:
        contenuto.append({"type": "image_url", "image_url": {"url": f}})
    return {"role": "user", "content": contenuto}


def _blocco(testo: str, linguaggio: str):
    trovato = re.findall(r"```%s\s*\n(.*?)```" % linguaggio, testo, re.S)
    return trovato[-1].strip() if trovato else None


# ------------------------------------------------------------- pertinenza

REGOLE = """Due regole che non si violano mai.

1. Non compilare dichiarazioni legali che il fascicolo non contiene. Cause di
   esclusione, obblighi sul lavoro, conflitti d'interesse, collegamenti fra
   imprese: sono dichiarazioni sostitutive di atto notorio, e una risposta
   sbagliata e' un reato, non una casella storta. Confronta sempre i dati
   dell'impresa con le soglie citate dal modulo e segnala le contraddizioni
   invece di risolverle da solo.

2. Controlla che il modulo appartenga davvero a questa impresa. Compilare
   benissimo il modulo di un'altra gara e' l'errore peggiore possibile: la
   domanda verrebbe esclusa.

Un dato che non c'e' si lascia mancante. Non si deduce, non si stima, non si
inventa: un campo vuoto e' normale, un campo inventato no."""


def pertinenza(testo_modulo: str, fascicolo: dict, figure=()) -> dict:
    """La sola domanda che vale la pena fare prima di lavorare: se la risposta
    fosse no, tutto il lavoro dopo andrebbe buttato."""
    profilo = fascicolo.get("profilo", {})
    richiesta = """%s

Ecco l'inizio di un modulo che una commercialista vuole compilare per la sua
cliente, e che cosa fa l'impresa.

--- MODULO (testo della prima pagina)
%s

--- IMPRESA
ragione sociale: %s
attivita': %s
qualificazioni: %s

Rispondi con un blocco json e basta:
{"pertinente": true/false,
 "motivo": "una riga",
 "domanda": "la domanda da fare, solo se pertinente e' false, altrimenti null"}

Sii prudente al contrario: se il modulo riguarda un settore diverso da quello
dell'impresa, pertinente e' false. Se invece il dubbio e' solo su un dettaglio,
pertinente resta true e il dettaglio diventa un punto aperto piu' avanti.
""" % (REGOLE, testo_modulo[:6000], profilo.get("ragione_sociale", ""),
       profilo.get("oggetto_sociale", "") or profilo.get("attivita_iscrizione", ""),
       profilo.get("soa_categorie_classifiche", ""))

    risposta = _chiedi([_messaggio(richiesta, figure)])
    grezzo = _blocco(risposta, "json") or risposta
    try:
        return json.loads(grezzo)
    except ValueError:
        return {"pertinente": True, "motivo": "risposta non interpretabile",
                "domanda": None, "grezzo": risposta[:2000]}


# --------------------------------------------------------------- i valori

ISTRUZIONI = """Devi scrivere la funzione valori(fascicolo) per questo modulo.

La geometria e' gia' stata misurata: ogni campo del modulo e' un'ancora con un
identificativo, un tipo e un'etichetta. Tu non scrivi coordinate, non disegni,
non tocchi il documento. Scegli solo quale dato va su quale ancora.

I sei tipi, e che cosa si aspettano come valore:
  celle         una fila di caselle strette, un carattere ciascuna: una stringa
                lunga al massimo quanto le celle (16 celle = 16 caratteri)
  casella       un quadratino: True per barrarlo, oppure lascialo fuori
  riempimento   una riga di puntini o trattini: una stringa breve
  tratto        una riga da scrivere sopra: una stringa breve
  area          un riquadro: una stringa, anche lunga
  widget        un campo modulo: una stringa o True/False

Regole per la funzione:
  - usa solo i dati che trovi nel fascicolo, con le sue chiavi esatte;
  - non importare niente, non aprire file, non usare fitz;
  - se un dato manca, NON lasciare l'ancora fuori: scrivila come
    fascicolo["profilo"].get("chiave_che_servirebbe") o
    scenario.get("chiave_che_servirebbe"), inventando una chiave chiara.
    Oggi vale None e resta un punto aperto; il giorno in cui quel dato entra nel
    fascicolo la stessa funzione lo scrive da sola, senza chiamare di nuovo te.
    E' la ragione per cui stai scrivendo una funzione invece di un elenco;
  - non ripetere nel valore l'etichetta che il modulo ha gia' stampato;
  - non barrare una casella che dichiara qualcosa che il fascicolo non dice.

Rispondi con due blocchi e nient'altro:

```python
def valori(fascicolo):
    ...
    return { "p1.area.057-221": ..., }
```

```json
{"punti_aperti": [{"ancora": "p1.riempimento.090-516",
                   "chiave": "profilo.chiave_che_servirebbe",
                   "motivo": "una riga, in italiano semplice, per chi compila"}],
 "note": "quello che vuoi far sapere, in due righe"}
```

La "chiave" e' dove il dato andra' messo nel fascicolo: deve essere la stessa
che hai usato dentro valori(), scritta con i punti (per esempio
"profilo.orario_inizio" oppure "scenari.narni_suolo.ore_inizio").

Un punto aperto nasce sempre da un'ancora di questo modulo rimasta vuota: se il
modulo non lo chiede, non e' un punto aperto."""


def valori(mappa: dict, fascicolo: dict, riassunto: str, figure=(),
           guai: str = "") -> tuple:
    """Chiede al modello la funzione valori() e i punti aperti."""
    richiesta = "%s\n\n%s\n\n--- CAMPI MISURATI DEL MODULO\n%s\n\n--- FASCICOLO\n%s" % (
        REGOLE, ISTRUZIONI, riassunto,
        json.dumps(fascicolo, ensure_ascii=False, indent=1))
    if guai:
        richiesta += ("\n\n--- IL TENTATIVO PRECEDENTE\nGuarda le pagine qui "
                      "allegate: sono il risultato vero del tuo ultimo tentativo.\n"
                      "Il controllo ha misurato questi problemi:\n%s\n"
                      "Riscrivi valori() tenendone conto." % guai)
    risposta = _chiedi([_messaggio(richiesta, figure)])
    codice = _blocco(risposta, "python")
    if not codice:
        raise RuntimeError("il modello non ha restituito la funzione valori()")
    note_grezze = _blocco(risposta, "json")
    try:
        note = json.loads(note_grezze) if note_grezze else {}
    except ValueError:
        note = {"punti_aperti": [], "note": note_grezze or ""}
    return codice, note


ISTRUZIONI_ANAGRAFICA = """Sei un tecnico che prepara la modulistica di un'impresa italiana.

Ricevi dei punti da compilare di un modulo. Di ognuno hai l'etichetta stampata
accanto, la frase in cui si trova e quanto spazio c'e'. Hai anche l'elenco dei
campi dell'anagrafica dell'impresa.

Per ogni punto dici UNA cosa sola: quale campo dell'anagrafica ci va, oppure
niente.

Regole, in ordine di importanza:

1. NON SCRIVI TU I VALORI. Nomini il campo; il valore lo copia il programma dal
   campo che hai nominato. Non trascrivere mai un codice fiscale o una partita
   IVA: in una dichiarazione sostitutiva una trascrizione a memoria e' un reato.

2. NEL DUBBIO, NIENTE. Un campo lasciato vuoto lo vede chi guarda la bozza; un
   dato giusto nel posto sbagliato non lo vede nessuno. Meglio dieci punti
   lasciati a chi compila che uno sbagliato.

3. LEGGI LA FRASE, NON L'ETICHETTA. 'nel sito' dentro 'pubblicato sul sito
   della stazione appaltante' non chiede il nostro sito: chiede quello del
   Comune, e la risposta e' niente. 'White List' dentro una dichiarazione
   sull'infiltrazione mafiosa non chiede la prefettura: e' una dichiarazione.

4. LE DICHIARAZIONI LEGALI NON SI COMPILANO. Cause di esclusione, Legge
   68/1999, conflitti d'interesse, avvalimento, subappalto: sono decisioni di
   chi firma, non dati da travasare. Rispondi niente.

5. DISTINGUI L'IMPRESA DALLA PERSONA. 'codice fiscale' in una riga che parla
   del sottoscritto e' quello del rappresentante; nell'intestazione della ditta
   e' quello dell'impresa. Se la frase non lo dice, rispondi niente.

Rispondi con un solo blocco json, una voce per ogni punto ricevuto:

```json
[{"punto": "p1.area.057-221", "campo": "cognome_rappresentante"},
 {"punto": "p1.riempimento.313-324", "campo": null}]
```"""


ISTRUZIONI_PAGINA = """Sei un tecnico che prepara la modulistica di un'impresa italiana.

Ricevi una pagina di modulo resa come prosa, con i posti da riempire segnati
cosi': «7:21». Il primo numero e' l'indirizzo del posto, il secondo quante
lettere ci entrano. «7:casella» e' un quadratino da barrare.

Hai anche l'elenco dei campi dell'anagrafica dell'impresa.

Per ogni posto **che chiede un dato dell'anagrafica** dici quale campo ci va.
Gli altri li lasci fuori dalla risposta: non sono roba tua.

Regole, in ordine di importanza:

1. NON SCRIVI TU I VALORI. Nomini il campo; il valore lo copia il programma dal
   campo che hai nominato. Non trascrivere mai un codice fiscale o una partita
   IVA: in una dichiarazione sostitutiva una trascrizione a memoria e' un reato.

2. NEL DUBBIO, NIENTE. Un posto lasciato vuoto lo vede chi guarda la bozza; un
   dato giusto nel posto sbagliato non lo vede nessuno. Meglio dieci posti
   lasciati a chi compila che uno sbagliato.

3. LEGGI LA PAGINA, NON LA PAROLA ACCANTO. La stessa parola cambia dato a
   seconda di dove sta: 'via' in una frase che parla di chi risiede e' la via
   di residenza, 'via' sotto 'con sede in' e' quella della sede. 'nel sito'
   dentro 'pubblicato sul sito della stazione appaltante' chiede il sito del
   Comune: la risposta e' nessuno.

4. LE DICHIARAZIONI LEGALI NON SI COMPILANO. Cause di esclusione, Legge
   68/1999, conflitti d'interesse, avvalimento, subappalto: sono decisioni di
   chi firma. Lasciali fuori.

5. LE CASELLE NON SONO ANAGRAFICA. Una casella e' una scelta di chi compila:
   lasciala sempre fuori.

6. LA CAPIENZA E' UN INDIZIO. «:15» dopo 'il' e' una data, «:10» dopo 'Cap' e'
   un CAP, «:16» e' un codice fiscale. Se il dato che avresti in mente non ci
   sta, quasi sempre e' il dato sbagliato.

Rispondi con un solo blocco json, solo i posti che sai riempire:

```json
[{"posto": 2, "campo": "nome_rappresentante"},
 {"posto": 4, "campo": "data_nascita"}]
```"""


def abbina_pagina(testo_pagina: str, indirizzi: dict, chiavi_anagrafica,
                  immagine=None, scartate=None, decisioni=None) -> dict:
    """Legge una pagina intera e dice quali posti sa riempire.

    Una pagina alla volta, come farebbe chiunque: le sezioni, le intestazioni e
    l'ordine delle frasi sono l'informazione che distingue 'via' di residenza da
    'via' della sede, e mandando le righe staccate quell'informazione sparisce.

    Se si passa una lista `scartate`, le proposte fuori dal contratto - un
    posto che non esiste, una chiave che non e' nell'anagrafica - ci finiscono
    dentro invece di far fallire tutto. Senza, una sola riga sbagliata butta
    via l'intero modulo: e' successo su `02_tricase_pitturazione_immobili`, e
    quel modulo non ha prodotto niente. Una proposta fuori contratto non si
    puo' scrivere comunque - non c'e' nessun posto dove metterla - quindi
    scartarla non fa perdere niente, mentre fermarsi fa perdere tutto il
    resto. Il valore predefinito resta la severita' di prima, cosi' chi non
    ha chiesto niente non si ritrova un comportamento diverso.
    """
    richiesta = "%s\n\n--- CAMPI DELL'ANAGRAFICA\n%s\n\n--- LA PAGINA\n%s" % (
        ISTRUZIONI_PAGINA, "\n".join(sorted(chiavi_anagrafica)), testo_pagina)
    if decisioni is not None:
        richiesta += """\nCONTRATTO WORD: restituisci UNA voce per OGNI posto,
con campo e motivo. Per un posto da lasciare vuoto usa campo="" e spiega il
motivo. Lo stesso dato va ripetuto in tutti i campi che lo richiedono per lo
stesso soggetto: non omettere una ragione sociale o P.IVA perche compare gia.
Non confondere ripetizione con cambio di soggetto. Denominazione e ragione
sociale possono essere sinonimi nello stesso campo. Sottoscritto senza
distinzione nome/cognome richiede il nome completo, non solo il cognome.
Nello schema nome_rappresentante indica il nome completo; la chiave
nome_rappresentante_solo indica il solo nome proprio. Una frase come
'nat [posto] a [posto] il [posto]' contiene una desinenza grammaticale,
poi luogo e data: non mettere il luogo nel posto della desinenza, e non
inventare una richiesta di provincia dove non e indicata. Se manca una
chiave adatta alla desinenza, lasciala vuota. 'Corrente in', riferito a
un'impresa, chiede la sua sede: non e automaticamente un dato della gara.
Gli spazi candidati possono essere impaginazione: non inserirvi una carica
nel mezzo di una frase stampata. Se un campo richiede solo una parte di un
dato aggregato non assegnare l'intero aggregato. Alternative gia soddisfatte
dal dato stampato restano vuote. Queste istruzioni sostituiscono la richiesta
precedente di elencare solo i posti riempiti. Nessun limite di capienza Word.
"""
    risposta = _chiedi([_messaggio(richiesta, [immagine] if immagine else ())])
    deciso = {}
    for voce in _lista_risposta(risposta, "campo"):
        campo, posto = voce["campo"], str(voce["posto"])
        if decisioni is not None and posto in indirizzi:
            decisioni[indirizzi[posto]] = {"campo": campo, "motivo": str(voce.get("motivo") or "Motivo non restituito")[:500]}
            if not campo:
                continue
        if campo not in chiavi_anagrafica or posto not in indirizzi:
            if scartate is None:
                raise RispostaModelloInvalida("Posto o chiave fuori dal contratto")
            scartate.append({"posto": posto, "campo": campo,
                             "perche": "posto o chiave fuori dal contratto"})
            continue
        aid = indirizzi[posto]
        if aid in deciso and deciso[aid] != campo:
            if scartate is None:
                raise RispostaModelloInvalida(
                    "Assegnazioni contraddittorie allo stesso posto")
            # due chiavi diverse sullo stesso posto: non si sceglie a caso,
            # si lascia vuoto e si toglie anche la prima
            scartate.append({"posto": posto, "campo": campo,
                             "perche": "due chiavi diverse sullo stesso posto"})
            deciso.pop(aid, None)
            continue
        deciso[aid] = campo
    return deciso


ISTRUZIONI_RILETTURA = """Sei un tecnico che controlla la modulistica di un'impresa italiana
prima di consegnarla.

Ricevi il testo della pagina con le assegnazioni proposte: dove c'era uno spazio da
riempire adesso trovi «7=[ valore ]», e dove e' rimasto vuoto trovi «7=___».
L'immagine allegata e' il modulo ORIGINALE: serve per leggere soggetti,
intestazioni e tabelle. I valori proposti sono nel testo, non nell'immagine.

Il tuo compito e' uno solo: **dire quali valori non rispondono al campo e al
soggetto a cui il campo si riferisce.**

Non devi proporre il valore giusto, non devi riempire i vuoti, non devi
giudicare se il modulo e' completo. Devi solo segnalare quello che, letto
nella frase, e' assurdo.

Esempi di cose da segnalare:
  'in qualità di [ mario@posta.it ]'   un indirizzo dove va una carica
  'per la seguente attività [ 41.00.00; 42.91.00; 49.41.00 ]' un elenco dove
      il modulo chiede una cosa sola
  'COGNOME [ Rossi ] COGNOME [ Rossi ] COGNOME [ Rossi ]' la stessa persona
      in righe che sono per persone diverse

Un valore plausibile puo' comunque essere sbagliato: controlla sempre il
soggetto e il significato richiesto. L'attivita' dell'impresa non e' l'oggetto
della gara; la sede dell'impresa non e' la residenza del rappresentante.
Se il contesto non permette di confermare l'associazione, segnala il dubbio:
il campo resta vuoto, senza inventare dati o chiedere nuove risposte.

Rispondi con un solo blocco json. Se e' tutto sensato, lista vuota.

```json
[{"posto": 9, "perche": "un indirizzo e-mail dove il modulo chiede la carica"}]
```"""


def rileggi_pagina(testo_compilato: str, indirizzi: dict, immagine=None) -> dict:
    """Guarda la pagina gia' compilata e dice che cosa non ha senso.

    E' una domanda diversa da quella che ha prodotto i valori - non 'cosa va
    qui' ma 'questo ha senso qui' - e il valore e' davanti agli occhi invece
    che da scegliere. E' la stessa ragione per cui un refuso si vede meglio
    rileggendo che scrivendo.

    Serve anche a misurare: gli errori di senso oggi li conto a mano su qualche
    decina di scritture, e cosi' non si distingue il 3% dal 2%.
    """
    richiesta = "%s\n\n--- LA PAGINA COMPILATA\n%s" % (ISTRUZIONI_RILETTURA,
                                                       testo_compilato)
    risposta = _chiedi([_messaggio(richiesta, [immagine] if immagine else ())])
    bocciati = {}
    for voce in _lista_risposta(risposta, "perche"):
        posto = str(voce["posto"])
        if posto not in indirizzi:
            raise RispostaModelloInvalida("Posto di rilettura sconosciuto")
        bocciati[indirizzi[posto]] = voce["perche"][:240]
    return bocciati


def con_i_valori(testo_pagina: str, indirizzi: dict, scelte: dict,
                 anagrafe=None) -> str:
    """La resa della pagina con dentro i valori scelti, pronta da rileggere."""
    def sostituisci(trovato):
        numero = trovato.group(1)
        ancora = indirizzi.get(numero)
        chiave = scelte.get(ancora) if ancora else None
        if not chiave:
            return "«%s=___»" % numero
        valore = anagrafe.valore(chiave) if anagrafe else chiave
        return "«%s=[ %s ]» (chiave JSON: %s)" % (numero, str(valore), chiave)
    return re.sub(r"«(\d+):[^»]*»", sostituisci, testo_pagina)


def abbina_documento(rese, chiavi_anagrafica, immagini=None,
                     paralleli: int = 4, errori=None) -> dict:
    """Tutte le pagine di un modulo, chieste insieme.

    Ogni pagina e' una domanda indipendente: il modello non ha bisogno di aver
    visto la pagina 3 per leggere la 4. Chiederle una alla volta fa aspettare
    un minuto per pagina senza nessun guadagno, e su un modulo da diciassette
    pagine sono venti minuti buttati.
    """
    from concurrent.futures import ThreadPoolExecutor

    deciso = {}
    if not rese:
        return deciso
    with ThreadPoolExecutor(max_workers=max(1, paralleli)) as squadra:
        lavori = [squadra.submit(abbina_pagina, p["testo"], p["indirizzi"],
                                 chiavi_anagrafica,
                                 (immagini or {}).get(p["pagina"]))
                  for p in rese]
        for p, lavoro in zip(rese, lavori):
            try:
                deciso.update(lavoro.result())
            except Exception as e:                         # noqa: BLE001
                if errori is None:
                    raise
                errori.append({"fase": "abbinamento", "pagina": p["pagina"],
                               "errore": type(e).__name__})
    return deciso


def abbina_anagrafica(incerti, chiavi_anagrafica, lotto: int = LOTTO_INCERTI) -> dict:
    """Chiede al modello che cosa va nei punti che il codice non sa decidere.

    Il deterministico ha gia' chiuso i casi facili. Qui arrivano solo i punti
    dove serve leggere la frase: l'etichetta ambigua, il frammento di
    dichiarazione, il buco senza etichetta. E' il lavoro che nessuna tabella
    puo' fare, ed e' l'unico per cui si paga.
    """
    deciso = {}
    for inizio in range(0, len(incerti), lotto):
        pezzo = incerti[inizio:inizio + lotto]
        elenco = []
        for a in pezzo:
            elenco.append({"punto": a.id, "tipo": a.tipo,
                           "etichetta": (a.etichetta or "")[:60],
                           "frase": (a.contesto or "")[:180],
                           "spazio_caratteri": max(1, int(a.riquadro.width / 4.2))})
        richiesta = "%s\n\n--- CAMPI DELL'ANAGRAFICA\n%s\n\n--- PUNTI DA DECIDERE\n%s" % (
            ISTRUZIONI_ANAGRAFICA, "\n".join(sorted(chiavi_anagrafica)),
            json.dumps(elenco, ensure_ascii=False, indent=1))
        risposta = _chiedi([_messaggio(richiesta)])
        grezzo = _blocco(risposta, "json") or risposta
        try:
            for voce in json.loads(grezzo):
                campo = voce.get("campo")
                if campo and campo in chiavi_anagrafica:
                    deciso[voce["punto"]] = campo
        except ValueError:
            continue
    return deciso


def testo_prima_pagina(pdf, quante: int = 2) -> str:
    doc = fitz.open(pdf)
    pezzi = [doc[i].get_text("text") for i in range(min(quante, doc.page_count))]
    doc.close()
    return "\n".join(pezzi)


# ------------------------------------------------------------ diagnostica

def modelli_disponibili(filtro: str = "") -> list:
    """Chiede all'endpoint quali modelli offre.

    Il nome esatto di un modello cambia da fornitore a fornitore e non si
    indovina: si chiede. Serve a riempire QUADRA_MODELLO senza tentativi.
    """
    if not (BASE and CHIAVE):
        raise ModelloAssente("Servono almeno QUADRA_BASE_URL e QUADRA_CHIAVE.")
    import requests
    risposta = requests.get(BASE + "/models",
                            headers={"Authorization": "Bearer " + CHIAVE},
                            timeout=60)
    risposta.raise_for_status()
    nomi = [m.get("id", "") for m in risposta.json().get("data", [])]
    filtro = filtro.lower()
    return sorted(n for n in nomi if filtro in n.lower())


def stato() -> str:
    """Dice che cosa ha trovato e da quale variabile, mai il valore della chiave."""
    righe = []
    if DA_DOVE.get("file"):
        righe.append("letto anche da: %s" % DA_DOVE["file"])
    righe.append("endpoint: %s   [%s]" % (BASE or "(non trovato)",
                                          DA_DOVE.get("base") or "-"))
    righe.append("chiave:   %s   [%s]"
                 % ("trovata (%d caratteri)" % len(CHIAVE) if CHIAVE
                    else "(non trovata)", DA_DOVE.get("chiave") or "-"))
    righe.append("modello:  %s   [%s]" % (MODELLO or "(non trovato)",
                                          DA_DOVE.get("modello") or "-"))
    righe.append("tetto:    %d gettoni" % TETTO_GETTONI)
    if not (BASE and CHIAVE and MODELLO):
        righe.append("")
        righe.append("Manca qualcosa. Nel .env di Quadra basta una riga come:")
        righe.append("    QUADRA_ENV=percorso\\del\\.env\\che\\hai\\gia")
        righe.append("piu' QUADRA_MODELLO, se quel file non lo contiene.")
    return "\n".join(righe)


def nomi_nel_file(percorso=None) -> list:
    """I nomi delle variabili definite in un .env, senza i valori.

    Serve a capire come si chiama l'endpoint in un file che non e' nostro. Il
    valore si mostra solo se e' un indirizzo http, che non e' un segreto: una
    chiave non si stampa mai, nemmeno per diagnosi.
    """
    percorso = percorso or DA_DOVE.get("file") or os.environ.get("QUADRA_ENV", "")
    if not percorso or not Path(percorso).is_file():
        return []
    from dotenv import dotenv_values
    fuori = []
    for nome, valore in dotenv_values(percorso).items():
        valore = (valore or "").strip()
        if valore.lower().startswith(("http://", "https://")):
            fuori.append("%s = %s" % (nome, valore))
        else:
            fuori.append("%s = <non e' un indirizzo: %d caratteri>"
                         % (nome, len(valore)))
    return fuori


if __name__ == "__main__":
    import sys as _sys
    print(stato())
    if "--nomi" in _sys.argv:
        print("\nvariabili definite nel file puntato da QUADRA_ENV:")
        for riga in nomi_nel_file():
            print("  " + riga)
        raise SystemExit(0)
    if BASE and CHIAVE:
        filtro = _sys.argv[1] if len(_sys.argv) > 1 else ""
        print("\nmodelli offerti dall'endpoint%s:"
              % (" che contengono %r" % filtro if filtro else ""))
        try:
            for nome in modelli_disponibili(filtro):
                print("  " + nome)
        except Exception as guaio:                         # noqa: BLE001
            print("  non sono riuscito a chiederglielo: %s" % guaio)


def rileggi_documento(rese, scelte: dict, anagrafe, immagini=None,
                      paralleli: int = 4, errori=None) -> dict:
    """Rilegge tutte le pagine compilate e restituisce i valori da togliere.

    Gira **prima** di scrivere: un valore bocciato non deve arrivare sul foglio.
    Una casella vuota Bianca la riempie, un'assurdita' le fa buttare la bozza.
    """
    from concurrent.futures import ThreadPoolExecutor

    bocciati = {}
    if not rese or not scelte:
        return bocciati
    with ThreadPoolExecutor(max_workers=max(1, paralleli)) as squadra:
        lavori = []
        for p in rese:
            testo = con_i_valori(p["testo"], p["indirizzi"], scelte, anagrafe)
            if "=[ " not in testo:
                continue          # su questa pagina non abbiamo scritto niente
            lavori.append((p, squadra.submit(rileggi_pagina, testo, p["indirizzi"],
                                             (immagini or {}).get(p["pagina"]))))
        for p, lavoro in lavori:
            try:
                bocciati.update(lavoro.result())
            except Exception as e:                         # noqa: BLE001
                if errori is None:
                    raise
                errori.append({"fase": "rilettura", "pagina": p["pagina"],
                               "errore": type(e).__name__})
                for aid in p["indirizzi"].values():
                    if aid in scelte:
                        bocciati[aid] = "rilettura non disponibile: assegnazione sospesa"
    return bocciati


def immagini_per_pagina(pdf, pagine, dpi: int = DPI_PAGINA) -> dict:
    """Le pagine che servono, renderizzate, indicizzate per numero di pagina."""
    doc = fitz.open(pdf)
    fuori = {}
    for numero in pagine:
        if 1 <= numero <= doc.page_count:
            dati = doc[numero - 1].get_pixmap(dpi=dpi).tobytes("png")
            fuori[numero] = ("data:image/png;base64,"
                             + base64.b64encode(dati).decode("ascii"))
    doc.close()
    return fuori
