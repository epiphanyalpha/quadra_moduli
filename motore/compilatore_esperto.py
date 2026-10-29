# -*- coding: utf-8 -*-
"""Decidere che cosa scrivere in un Word come lo deciderebbe una persona esperta.

Il percorso di prima chiedeva al modello di abbinare ogni posto a un NOME di
voce dell'anagrafica, senza fargli vedere i valori, e poteva scrivere solo un
valore cosi' com'era. Una persona invece guarda il modulo, guarda i dati e
scrive la frase che serve: "Imperia (IM)", "nata a Imperia il 06/03/1971,
c.f. ...". Qui si fa lo stesso, con tre regole prese dalla letteratura sulla
compilazione automatica dei moduli (FormGym 2025, FormFactory 2025, CRITIC):

1. Il "dove" lo decide il codice, il "cosa" il modello. I posti li trova il
   lettore Word, che sa scrivere senza rompere il documento; il modello indica
   solo il posto per numero, o un paragrafo per le righe senza spazio segnato
   ("Banca", "IBAN"), che il codice controlla prima di accettare.
2. Ogni valore porta le sue fonti, e il codice verifica che ogni parola venga
   davvero da quelle voci dell'anagrafica e che il formato torni con
   l'etichetta (codice fiscale, IBAN, CAP, PEC...). Il modello puo' comporre e
   formattare, non inventare.
3. Si corregge con riscontri esterni, pochi giri e poi ci si ferma: dopo la
   scrittura il modello rilegge il modulo COMPILATO, insieme alle segnalazioni
   dei controlli, e propone solo correzioni, che passano dagli stessi
   controlli. Al massimo due giri.

In piu', una memoria per modulo: quando chi compila toglie o corregge un
campo, la scelta resta legata all'impronta di quel modulo e la volta dopo il
modello la riceve come indicazione. Le stazioni appaltanti riusano gli stessi
modelli: e' cosi' che un modulo gia' visto esce giusto.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from motore import agente, word

MODELLO_PREDEFINITO = "anthropic/claude-sonnet-5.5"
GIRI_REVISIONE = 2
MAX_AGGIUNTE = 12

# Parole di raccordo che una persona aggiunge componendo un dato: non sono
# dati, quindi non serve che vengano dall'anagrafica.
RACCORDO = set("""a al alla allo ai agli alle il lo la i gli le di del dello della
dei degli delle da dal dalla e ed in nel nella con presso per n nr num numero
via viale piazza piazzale corso vicolo largo localita loc c f cf cod codice
fiscale p iva piva partita nato nata nati residente residenti sede legale
operativa prov provincia cap tel telefono cell cellulare fax email mail pec
iban banca filiale agenzia conto corrente snc civico frazione fraz comune
qualita quale sig sigra dott ing geom arch rag
gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre
novembre dicembre""".split())


# ----------------------------------------------------------------- utilita'

def _norm(testo) -> str:
    testo = unicodedata.normalize("NFKD", str(testo or ""))
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    return testo.lower()


def _parole(testo):
    return re.findall(r"[a-z0-9]+", _norm(testo))


def impronta_modulo(mappa) -> str:
    """La stessa forma di modulo da' la stessa impronta, a prescindere dal file."""
    righe = [re.sub(r"\s+", " ", b["testo"]).strip() for b in mappa["inventario"]["blocchi"]]
    return hashlib.sha256("\n".join(r for r in righe if r).encode("utf-8")).hexdigest()[:24]


def configurazione():
    """Indirizzo, chiave e modello per il giudizio; None se non c'e' una chiave."""
    cw = agente.config_word()
    base, chiave = (cw[0], cw[1]) if cw else (agente.BASE, agente.CHIAVE)
    modello = os.environ.get("QUADRA_ESPERTO_MODELLO", "").strip() or MODELLO_PREDEFINITO
    if not (base and chiave):
        return None
    return base, chiave, modello


def attivo() -> bool:
    return (os.environ.get("QUADRA_WORD_MODO", "classico").strip().lower() == "esperto"
            and configurazione() is not None)


# ------------------------------------------------------------ il modello

class RispostaNonValida(ValueError):
    pass


def _chiedi(testo: str, config, tetto: int = 16000) -> tuple:
    """Una domanda, una risposta JSON e quanto e' costata (in dollari, se noto)."""
    import requests
    base, chiave, modello = config
    corpo = {"model": modello, "max_tokens": tetto,
             "messages": [{"role": "user", "content": testo}]}
    if "openrouter.ai" in base:
        corpo["usage"] = {"include": True}
        sforzo = os.environ.get("QUADRA_ESPERTO_SFORZO", "").strip()
        if sforzo:
            corpo["reasoning"] = {"effort": sforzo}
    ultimo = None
    for tentativo in range(3):
        try:
            r = requests.post(base.rstrip("/") + "/chat/completions",
                              headers={"Authorization": "Bearer " + chiave,
                                       "Content-Type": "application/json"},
                              json=corpo, timeout=(15, float(os.getenv("QUADRA_TIMEOUT_ESPERTO", "240"))))
            if r.status_code in (400, 401, 402, 403, 404):
                r.raise_for_status()
            r.raise_for_status()
            dati = r.json()
            break
        except requests.RequestException as guaio:
            ultimo = guaio
            stato = getattr(getattr(guaio, "response", None), "status_code", None)
            if tentativo == 2 or stato in (400, 401, 402, 403, 404):
                raise
    costo = float((dati.get("usage") or {}).get("cost") or 0.0)
    try:
        contenuto = dati["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RispostaNonValida("Risposta del servizio incompleta") from exc
    return _json(contenuto), costo


def _json(testo: str) -> dict:
    blocco = agente._blocco(testo, "json") or testo
    try:
        dati = json.loads(blocco)
    except ValueError:
        trovato = re.search(r"\{.*\}", testo, re.S)
        if not trovato:
            raise RispostaNonValida("JSON assente")
        try:
            dati = json.loads(trovato.group(0))
        except ValueError as exc:
            raise RispostaNonValida("JSON non interpretabile") from exc
    if not isinstance(dati, dict):
        raise RispostaNonValida("Atteso un oggetto JSON")
    return dati


# ------------------------------------------------------ come si presenta

def rendi(mappa, scritti=None):
    """Il modulo come testo, con §N davanti a ogni paragrafo e i posti numerati.

    Con `scritti` ({ancora: valore}) mostra il modulo COMPILATO: i valori fra
    ⟦k: valore⟧ e i posti vuoti come «k». E' quello che si fa rileggere.
    """
    scritti = scritti or {}
    gruppi = defaultdict(list)
    for a in mappa["ancore"]:
        if a.get("scrivibile", True):
            gruppi[a["paragrafo"]].append(a)
    indirizzi, righe, parte_prima = {}, [], None
    blocchi = mappa["inventario"]["blocchi"]
    for indice, testo in mappa["righe"]:
        parte = blocchi[indice]["parte"]
        if parte != parte_prima:
            righe.append("[Parte del documento: %s]" % parte)
            parte_prima = parte
        pezzi, ultimo = [], 0
        for a in sorted(gruppi[indice], key=lambda x: (x["inizio"], x["id"])):
            numero = str(len(indirizzi) + 1)
            indirizzi[numero] = a["id"]
            if a["tabella"] is not None and not pezzi:
                pezzi.append("[Tabella; riga %s; colonna %s] " % (a["riga"], a["colonna"]))
            pezzi.append(testo[ultimo:a["inizio"]])
            if a.get("contesto_cella"):
                pezzi.append("[cella accanto: %s] " % a["contesto_cella"])
            etichette = " / ".join(dict.fromkeys(v for v in (a.get("etichette_sdt") or {}).values() if v))
            if etichette:
                pezzi.append("[controllo Word: %s] " % etichette)
            if a["id"] in scritti:
                pezzi.append("⟦%s: %s⟧" % (numero, scritti[a["id"]]))
            else:
                pezzi.append("«%s%s»" % (numero, ":casella" if a["tipo"] == "casella" else ""))
            if a.get("elenco"):
                pezzi.append(" (riga di un elenco di altri soggetti)")
            ultimo = a["fine"]
        pezzi.append(testo[ultimo:])
        resa = re.sub(r"\s+", " ", "".join(pezzi)).strip()
        if resa:
            righe.append("§%d %s" % (indice, resa))
    return "\n".join(righe), indirizzi


def _anagrafica(profilo: dict) -> str:
    righe = []
    for chiave in sorted(profilo):
        valore = profilo[chiave]
        if isinstance(valore, (str, int, float)) and str(valore).strip():
            righe.append("%s: %s" % (chiave, str(valore).strip()))
    return "\n".join(righe)


ISTRUZIONI = """Sei un impiegato esperto di gare d'appalto e pratiche amministrative.
Compili il modulo qui sotto per l'impresa descritta nell'ANAGRAFICA, come lo
compileresti a mano.

Il modulo e' in testo: ogni riga comincia con §N (numero del paragrafo). I
posti da compilare sono segnati «k» (testo) o «k:casella».

COMPITO: per ogni posto che chiede un dato che l'anagrafica contiene, scrivi
il testo esatto da inserire in quel posto.

REGOLE
1. Usa solo dati dell'anagrafica. Puoi comporre e formattare come farebbe una
   persona ("Imperia (IM)", "nata a Imperia il 06/03/1971, c.f. ..."), ma ogni
   parola deve venire dall'anagrafica. In "fonti" metti le chiavi usate.
2. Il valore completa la frase stampata: non ripetere parole gia' stampate
   subito prima o dopo il posto. Se il modulo stampa "Via ____ n. ____",
   nel primo posto va la sola strada e nel secondo il civico.
3. Capisci di chi parla ogni frase: l'impresa, il sottoscritto/legale
   rappresentante, oppure altri soggetti (soci, direttori tecnici, ausiliarie,
   mandanti, subappaltatori, progettisti, proprietari, terzi). Compila un dato
   di una persona solo se l'anagrafica contiene proprio quella persona in quel
   ruolo.
4. Lascia vuoto (cioe' non elencare): dati della singola gara o pratica (CIG,
   CUP, lotto, importi, ribassi, date, oggetto dell'appalto), luogo e data della
   firma, caselle, scelte fra dichiarazioni alternative, campi riservati a
   imprese straniere, a raggruppamenti o consorzi se l'impresa non lo e', e
   qualunque cosa su cui non sei sicuro.
5. Righe che chiedono chiaramente un dato ma non hanno un posto segnato (per
   esempio, sotto "gli estremi del conto corrente sono:", righe che contengono
   solo "Banca", "Filiale", "IBAN"): mettile in "aggiunte" con il numero del
   paragrafo. Il valore sara' scritto in fondo a quella riga. Solo per righe
   brevi che sono un'etichetta di un dato, mai per titoli o frasi.
6. Parole stampate tronche, da completare col genere ("sottoscritt", "nat",
   "residente"): se dopo la parola c'e' UN SOLO posto, quel posto serve al dato
   (il nome, il luogo): scrivi la desinenza attaccata al dato, per esempio
   "a Carla Ferrante" dopo "sottoscritt". Se ci sono due posti, il primo
   breve e' la desinenza e il secondo il dato. Il dato principale non deve
   mai sparire per far posto alla desinenza.
7. Rileggi ogni frase con i valori dentro: deve suonare come la scriverebbe
   un impiegato. Ogni posto con un dato dell'impresa o del rappresentante che
   l'anagrafica contiene (anche una sigla di provincia fra parentesi, un
   civico, un CAP) va compilato.

Rispondi SOLO con un oggetto JSON, senza altro testo:
{"campi": [{"posto": "k", "valore": "...", "fonti": ["chiave", ...]}],
 "aggiunte": [{"paragrafo": N, "valore": "...", "fonti": ["chiave", ...]}]}
I posti che lasci vuoti non vanno elencati."""


REVISIONE = """Sei il revisore. Qui sotto c'e' lo stesso modulo GIA' COMPILATO: i valori
scritti sono fra ⟦k: valore⟧, i posti rimasti vuoti sono «k». Ti do anche
l'ANAGRAFICA e le SEGNALAZIONI dei controlli automatici.

Correggi solo errori certi:
- un valore nel posto sbagliato o riferito al soggetto sbagliato;
- parole ripetute rispetto al testo stampato ("via Via ...", "Camera di
  Commercio di Camera di Commercio ...");
- un dato che l'anagrafica ha e che un posto vuoto chiede in modo chiaro
  (anche una sigla di provincia fra parentesi, un civico, un CAP);
- una frase che, letta per intero, non si capisce o ha perso il dato
  principale (per esempio "il sottoscritto" senza il nome: la desinenza va
  attaccata al nome, non al suo posto);
- un valore scritto dove le regole dicono di lasciare vuoto (dati della gara,
  firma, alternative, soggetti che l'anagrafica non ha).
Le stesse regole della compilazione valgono qui: solo dati dell'anagrafica,
con le loro fonti.

Rispondi SOLO con JSON:
{"correzioni": [{"posto": "k", "valore": "nuovo testo oppure stringa vuota per togliere",
                 "fonti": ["chiave", ...], "motivo": "..."}],
 "aggiunte": [{"paragrafo": N, "valore": "...", "fonti": ["chiave", ...]}]}
Se e' tutto giusto: {"correzioni": [], "aggiunte": []}."""


# ---------------------------------------------------------------- controlli

def controlla_provenienza(valore: str, fonti, profilo: dict):
    """None se ogni parola del valore viene dalle fonti; altrimenti il motivo."""
    if not isinstance(fonti, list) or not fonti:
        return "senza fonti"
    sorgenti = []
    for f in fonti:
        dato = profilo.get(str(f))
        if dato is None or not str(dato).strip():
            return "fonte inesistente o vuota: %s" % f
        sorgenti.append(str(dato))
    parole_fonti = set()
    for s in sorgenti:
        parole_fonti.update(_parole(s))
    compatto = "".join(_parole(" ".join(sorgenti)))
    for p in _parole(valore):
        if p in parole_fonti or p in RACCORDO:
            continue
        if len(p) >= 3 and p in compatto:
            continue
        return "la parola '%s' non viene dall'anagrafica" % p
    return None


def _iban_valido(compatto: str) -> bool:
    s = compatto.upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    numero = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(numero) % 97 == 1


def controlla_formato(etichetta: str, valore: str):
    """None se il formato torna con l'etichetta che precede il posto."""
    # "C.A.P." e "P. IVA" diventano "cap" e "p iva": le sigle puntate si ricompongono.
    sigle = re.sub(r"\b([A-Za-z])\.\s?(?=[A-Za-z]\.)", r"\1", etichetta)
    coda = " ".join(_parole(sigle)[-3:])
    compatto = re.sub(r"[\s.\-/]", "", valore)
    def finisce(*voci):
        return any(coda == v or coda.endswith(" " + v) for v in voci)
    if finisce("cap") and not re.fullmatch(r"\d{5}", compatto):
        return "un CAP vuole 5 cifre"
    if finisce("iban") and not _iban_valido(compatto):
        return "IBAN non valido"
    if finisce("pec", "email", "e mail", "mail") and "@" not in valore:
        return "manca la chiocciola di un indirizzo email"
    if finisce("c f", "cf", "codice fiscale", "cod fiscale") and not (
            re.fullmatch(r"[A-Za-z0-9]{16}", compatto) or re.fullmatch(r"\d{11}", compatto)):
        return "un codice fiscale ha 16 caratteri (o 11 cifre per un'impresa)"
    if finisce("p iva", "partita iva", "piva") and not re.fullmatch(r"(IT)?\d{11}", compatto, re.I):
        return "una partita IVA ha 11 cifre"
    if finisce("tel", "telefono", "cell", "cellulare", "fax") and (
            re.search(r"[A-Za-z]", valore) or len(re.sub(r"\D", "", valore)) < 6):
        return "un telefono e' fatto di cifre"
    if re.fullmatch(r"[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}", compatto) and not _iban_valido(compatto):
        return "sembra un IBAN ma la cifra di controllo non torna"
    return None


# ---------------------------------------------- righe senza spazio segnato

def aggiungi_posto(mappa, paragrafo: int):
    """Un posto alla fine di una riga-etichetta senza spazio segnato.

    Il modello indica il paragrafo, il codice decide se e' accettabile: riga
    breve, non vuota, senza altri posti. Torna l'id del posto o un motivo.
    """
    blocchi = mappa["inventario"]["blocchi"]
    if not isinstance(paragrafo, int) or not 0 <= paragrafo < len(blocchi):
        return None, "paragrafo inesistente"
    b = blocchi[paragrafo]
    testo = b["testo"]
    if not testo.strip() or len(testo.strip()) > 60:
        return None, "non e' una riga-etichetta breve"
    if any(a["paragrafo"] == paragrafo for a in mappa["ancore"]):
        return None, "la riga ha gia' un posto"
    rif = b["id"] + "_agg01"
    punto = dict(riferimento=rif, tipo="inserimento_testo", parte=b["parte"],
                 percorso=b["percorso"], paragrafo=b["id"], percorso_paragrafo=b["percorso"],
                 testo_originale=testo, posizione_cella=None, scrivibile=True,
                 motivo_tecnico="", inizio=len(testo), fine=len(testo), originale="",
                 candidato=True, etichetta_implicita=True)
    mappa["inventario"]["punti"].append(punto)
    mappa["ancore"].append(dict(
        id=rif, tipo="riempimento", paragrafo=paragrafo, inizio=len(testo), fine=len(testo),
        capienza=1, etichetta=re.sub(r"\s+", " ", testo).strip(" :.-–")[-100:],
        etichette_sdt={}, tabella=None, riga=None, colonna=None, elenco=False,
        contesto_cella="", parte=b["parte"], scrivibile=True, motivo="", candidato=True,
        tipo_word="inserimento_testo", etichetta_implicita=True, aggiunto=True))
    return rif, None


def ricrea_aggiunte(mappa, scelte: dict):
    """Rifacendo la bozza, i posti aggiunti vanno ricreati prima di riusarli."""
    per_id = {b["id"]: i for i, b in enumerate(mappa["inventario"]["blocchi"])}
    for aid in scelte:
        if aid.endswith("_agg01") and aid[:-6] in per_id:
            if not any(a["id"] == aid for a in mappa["ancore"]):
                aggiungi_posto(mappa, per_id[aid[:-6]])


def valori_da_scelte(scelte: dict, profilo: dict) -> dict:
    """Le scelte possono essere un valore composto {valore, fonti} o una chiave."""
    valori = {}
    for aid, s in scelte.items():
        if isinstance(s, dict) and str(s.get("valore", "")).strip():
            valori[aid] = str(s["valore"]).strip()
        elif isinstance(s, str) and str(profilo.get(s, "")).strip():
            valori[aid] = str(profilo[s]).strip()
    return valori


# --------------------------------------------------------------- memoria

def _file_memoria(cartella_memoria, impronta):
    return Path(cartella_memoria) / ("%s.json" % impronta)


def leggi_memoria(cartella_memoria, impronta) -> dict:
    try:
        return json.loads(_file_memoria(cartella_memoria, impronta).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def ricorda(cartella_memoria, impronta, etichette: dict, tolti=(), confermati=None):
    """Tiene le scelte di chi compila: cosa ha tolto e cosa ha confermato."""
    if not cartella_memoria:
        return
    memoria = leggi_memoria(cartella_memoria, impronta)
    for aid in tolti:
        memoria.setdefault("tolti", {})[aid] = etichette.get(aid, "")
        memoria.get("confermati", {}).pop(aid, None)
    for aid, valore in (confermati or {}).items():
        if aid not in tolti:
            memoria.setdefault("confermati", {})[aid] = [etichette.get(aid, ""), valore]
    try:
        from motore.lavori import salva_json
        salva_json(_file_memoria(cartella_memoria, impronta), memoria)
    except OSError:
        pass


def _indicazioni(memoria: dict, indirizzi: dict) -> str:
    numero = {v: k for k, v in indirizzi.items()}
    righe = []
    for aid, etichetta in (memoria.get("tolti") or {}).items():
        if aid in numero:
            righe.append("- posto %s (%s): chi compila l'ha tolto, lascialo vuoto" % (numero[aid], etichetta))
    for aid, (etichetta, valore) in (memoria.get("confermati") or {}).items():
        if aid in numero:
            righe.append("- posto %s (%s): chi compila ha confermato \"%s\"" % (numero[aid], etichetta, valore))
    if not righe:
        return ""
    return ("\n\nMEMORIA DI QUESTO MODULO (correzioni di chi lo ha gia' compilato, "
            "da rispettare):\n" + "\n".join(righe))


# ------------------------------------------------------------- il lavoro

# Sezioni che una regola chiara esclude per un'impresa italiana: le istruzioni
# lo dicono al modello, ma sui 20 moduli di gara del 29/10 le ha compilate due
# volte su due. Una regola certa si mette nel codice, non si chiede.
ESCLUSE = re.compile(r"transfrontalier|non stabilit\w* in italia")


def sezione_esclusa(testo_riga: str):
    if ESCLUSE.search(_norm(testo_riga)):
        return "sezione riservata agli operatori economici transfrontalieri"
    return None


def _testo_prima(mappa, ancora) -> str:
    """Il testo STAMPATO subito prima del posto: e' quello che legge chi compila.

    Non l'etichetta interna dei controlli Word, che a volte e' sbagliata: in
    un modulo vero il controllo della provincia si chiama "N° CF/P. IVA", e
    fidandosi di quel nome si scartava una sigla di provincia giusta.
    """
    riga = dict(mappa["righe"]).get(ancora["paragrafo"], "")
    return riga[:ancora["inizio"]][-60:] or ancora.get("etichetta", "")


def _accetta(voci, indirizzi, by_id, profilo, mappa, scelte, scarti, chiave_valore="valore"):
    """Passa ogni proposta dai controlli; aggiorna `scelte` con quelle buone."""
    for voce in voci or []:
        if not isinstance(voce, dict):
            continue
        posto = str(voce.get("posto", "")).strip()
        aid = indirizzi.get(posto)
        valore = str(voce.get(chiave_valore, "") or "").strip()
        if aid is None:
            scarti.append(dict(posto=posto, valore=valore, motivo="posto inesistente"))
            continue
        if by_id[aid]["tipo"] == "casella":
            scarti.append(dict(posto=posto, valore=valore, motivo="caselle lasciate a chi compila"))
            continue
        if not valore:
            scelte.pop(aid, None)
            continue
        motivo = (sezione_esclusa(dict(mappa["righe"]).get(by_id[aid]["paragrafo"], "")) or
                  controlla_provenienza(valore, voce.get("fonti"), profilo) or
                  controlla_formato(_testo_prima(mappa, by_id[aid]), valore))
        if motivo:
            scarti.append(dict(posto=posto, ancora=aid, valore=valore, motivo=motivo))
            continue
        scelte[aid] = {"valore": valore, "fonti": [str(f) for f in voce["fonti"]],
                       "motivo": str(voce.get("motivo", ""))[:300]}


def _accetta_aggiunte(voci, mappa, profilo, scelte, scarti):
    for voce in (voci or [])[:MAX_AGGIUNTE]:
        if not isinstance(voce, dict):
            continue
        valore = str(voce.get("valore", "") or "").strip()
        try:
            paragrafo = int(voce.get("paragrafo"))
        except (TypeError, ValueError):
            scarti.append(dict(paragrafo=voce.get("paragrafo"), valore=valore, motivo="paragrafo non valido"))
            continue
        if not valore:
            continue
        etichetta = mappa["inventario"]["blocchi"][paragrafo]["testo"] if 0 <= paragrafo < len(mappa["inventario"]["blocchi"]) else ""
        motivo = (controlla_provenienza(valore, voce.get("fonti"), profilo) or
                  controlla_formato(etichetta, valore))
        if motivo:
            scarti.append(dict(paragrafo=paragrafo, valore=valore, motivo=motivo))
            continue
        aid, motivo = aggiungi_posto(mappa, paragrafo)
        if motivo:
            scarti.append(dict(paragrafo=paragrafo, valore=valore, motivo=motivo))
            continue
        scelte[aid] = {"valore": valore, "fonti": [str(f) for f in voce["fonti"]],
                       "motivo": "riga senza spazio segnato"}


def segnalazioni(mappa, scritti: dict) -> list:
    """Controlli deterministici sul modulo compilato, da passare al revisore."""
    fuori = []
    righe = dict(mappa["righe"])
    by_id = {a["id"]: a for a in mappa["ancore"]}
    for aid, valore in scritti.items():
        a = by_id.get(aid)
        if not a:
            continue
        prima = _parole(righe.get(a["paragrafo"], "")[:a["inizio"]])[-4:]
        primo = _parole(valore)[:4]
        for n in range(min(len(prima), len(primo)), 0, -1):
            if prima[-n:] == primo[:n]:
                fuori.append("«%s»: il valore ripete '%s' gia' stampato prima del posto"
                             % (valore, " ".join(primo[:n])))
                break
    conteggio = defaultdict(list)
    for aid, valore in scritti.items():
        a = by_id.get(aid)
        if a:
            conteggio[(a["paragrafo"], valore)].append(aid)
    for (paragrafo, valore), aids in conteggio.items():
        if len(aids) > 1:
            fuori.append("lo stesso valore «%s» e' scritto in %d posti della stessa riga" % (valore, len(aids)))
    return fuori


def decidi(mappa, fascicolo: dict, documento, cartella_lavoro, cartella_memoria=None):
    """Generatore: emette i passi per l'app, alla fine restituisce l'esito.

    L'esito e' {scelte, valori, scarti, costo, giri, guasti}: `scelte` va
    rimandata indietro per rifare la bozza senza richiamare il modello.
    """
    config = configurazione()
    profilo = fascicolo.get("profilo", {})
    impronta = impronta_modulo(mappa)
    memoria = leggi_memoria(cartella_memoria, impronta) if cartella_memoria else {}
    testo, indirizzi = rendi(mappa)
    by_id = {a["id"]: a for a in mappa["ancore"]}
    scelte, scarti, guasti, costo = {}, [], [], 0.0
    domanda = "%s\n\n--- ANAGRAFICA\n%s%s\n\n--- IL MODULO\n%s" % (
        ISTRUZIONI, _anagrafica(profilo), _indicazioni(memoria, indirizzi), testo)

    yield {"passo": "valori", "tentativo": 1,
           "testo": "Leggo il modulo e decido che cosa scrivere in ogni campo."}
    risposta = None
    for tentativo in range(2):
        try:
            risposta, c = _chiedi(domanda, config)
            costo += c
            break
        except RispostaNonValida as storto:
            guasti.append(dict(fase="proposta", errore=str(storto)))
    if risposta is None:
        return dict(scelte={}, valori={}, scarti=scarti, costo=costo, giri=0,
                    guasti=guasti, impronta=impronta)
    _accetta(risposta.get("campi"), indirizzi, by_id, profilo, mappa, scelte, scarti)
    _accetta_aggiunte(risposta.get("aggiunte"), mappa, profilo, scelte, scarti)

    giri = 0
    for giro in range(1, GIRI_REVISIONE + 1):
        valori = valori_da_scelte(scelte, profilo)
        prova = Path(cartella_lavoro) / ("prova_%d.docx" % giro)
        resoconto = word.scrivi(documento, mappa, valori, prova)
        scritti = {s["ancora"]: s["valore"] for s in resoconto["scritture"]}
        for m in resoconto["mancate"]:
            scelte.pop(m["ancora"], None)
            scarti.append(dict(ancora=m["ancora"], valore=m["valore"], motivo=m["motivo"]))
        yield {"passo": "correzione",
               "testo": "Rileggo il modulo compilato (giro %d di %d)." % (giro, GIRI_REVISIONE)}
        compilato, indirizzi = rendi(mappa, scritti)
        by_id = {a["id"]: a for a in mappa["ancore"]}
        avvisi = segnalazioni(mappa, scritti)
        domanda_r = "%s\n\n--- SEGNALAZIONI\n%s\n\n--- ANAGRAFICA\n%s%s\n\n--- IL MODULO COMPILATO\n%s" % (
            REVISIONE, "\n".join(avvisi) or "nessuna", _anagrafica(profilo),
            _indicazioni(memoria, indirizzi), compilato)
        try:
            revisione, c = _chiedi(domanda_r, config)
            costo += c
        except RispostaNonValida as storto:
            guasti.append(dict(fase="revisione", errore=str(storto)))
            break
        giri = giro
        prima = json.dumps(scelte, sort_keys=True, ensure_ascii=False)
        _accetta(revisione.get("correzioni"), indirizzi, by_id, profilo, mappa, scelte, scarti)
        _accetta_aggiunte(revisione.get("aggiunte"), mappa, profilo, scelte, scarti)
        if json.dumps(scelte, sort_keys=True, ensure_ascii=False) == prima:
            break
        yield {"passo": "correzione", "testo": "Ho corretto qualcosa: riscrivo e ricontrollo."}

    return dict(scelte=scelte, valori=valori_da_scelte(scelte, profilo), scarti=scarti,
                costo=round(costo, 5), giri=giri, guasti=guasti, impronta=impronta)
