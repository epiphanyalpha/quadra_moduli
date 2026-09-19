# -*- coding: utf-8 -*-
"""Il codice di accesso: chi entra, e fino a quando.

Un'app che sta su un server e non chiede niente e' aperta a chiunque
indovini l'indirizzo. E' gia' successo: una prova per questo stesso cliente
e' rimasta in rete quattro giorni senza lucchetto, col nome dell'impresa in
cima alla pagina.

Due cose soltanto, tenute separate apposta:

  CLIENTI       chi puo' entrare  -> "codice:Nome, codice:Nome"
  APP_SCADENZA  fino a quando     -> "2026-10-31", oppure "NESSUNA"

La scadenza serve a una prova che dura un mese: si imposta il giorno in cui
finisce e non ci si deve ricordare di spegnerla. Senza, la prova diventa
un servizio acceso per sempre che nessuno guarda piu'.

La regola che conta e' l'ultima: **senza codici, in produzione l'app si
chiude.** In locale resta aperta, perche' li' il lucchetto sarebbe solo una
seccatura. Il verso e' quello giusto: una dimenticanza fa restare fuori
tutti, non entrare tutti.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import streamlit as st

CLIENTI_SU_FILE = Path(__file__).resolve().parent.parent / "clienti.json"


def aperta_senza_codice() -> bool:
    """Se e' lecito lavorare senza lucchetto: solo dove lo si dichiara.

    PRIMA QUI SI INDOVINAVA, E HA SBAGLIATO. La regola era "se vedo le
    variabili che mette Render, allora sono in produzione e senza codici mi
    chiudo". Su Render con Docker quelle variabili non sono arrivate, l'app
    si e' creduta sul computer di casa e **si e' aperta a chiunque**. Non
    era teoria: e' successo, sul servizio vero, con il nome del cliente in
    cima alla pagina.

    Il difetto non era la lista di variabili sbagliata - era il verso. Una
    regola che deve indovinare dove si trova, quando indovina male sbaglia
    dalla parte di lasciare entrare tutti.

    Adesso non indovina: **chiuso, a meno che qualcuno non dica il
    contrario.** ACCESSO_LIBERO=1 si mette nel .env locale, che non entra
    nel repository e non arriva su nessun server. Se un giorno lo si
    dimentica, l'errore e' restare chiusi fuori dal proprio computer: fa
    perdere un minuto, si vede subito, non fa danno a nessuno.
    """
    return os.getenv("ACCESSO_LIBERO", "").strip() in ("1", "si", "true", "vero")


def codici() -> dict:
    """{codice: nome di chi lo usa}, dalle variabili d'ambiente o da un file.

    Dall'ambiente perche' cosi' un accesso si da' e si toglie dal pannello di
    Render, senza toccare il codice e senza un rilascio. Il file serve solo
    a chi prova in locale, e non entra nel repository.
    """
    fuori = {}
    if CLIENTI_SU_FILE.is_file():
        try:
            fuori.update(json.loads(CLIENTI_SU_FILE.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            pass
    for pezzo in os.getenv("CLIENTI", "").split(","):
        # Il nome dopo i due punti e' comodo ma non obbligatorio. Scritto
        # obbligatorio era una trappola: chi imposta la variabile scrive la
        # parola d'accesso e basta, l'app non trova nessun codice valido e
        # si chiude dicendo "accesso non configurato" - cioe' sembra rotta
        # proprio a chi l'ha appena configurata.
        codice, _, nome = pezzo.partition(":")
        if codice.strip():
            fuori[codice.strip()] = nome.strip() or "Ospite"
    return fuori


def _scaduta():
    """La data di fine, se c'e' ed e' passata."""
    detto = os.getenv("APP_SCADENZA", "").strip()
    if not detto or detto.upper() == "NESSUNA":
        return None
    try:
        fine = date.fromisoformat(detto)
    except ValueError:
        return None
    return fine if date.today() > fine else None


def porta(marchio: str = "") -> str:
    """Ferma la pagina finche' non si entra. Torna il nome di chi e' entrato.

    Si chiama subito dopo `set_page_config` e prima di disegnare qualsiasi
    cosa: quello che sta sopra la porta lo vede anche chi non ha il codice.
    """
    fine = _scaduta()
    if fine is not None:
        st.error("Questa prova e' finita il %s. Se serve ancora, scrivici."
                 % fine.strftime("%d/%m/%Y"))
        st.stop()

    ammessi = codici()
    if not ammessi:
        if aperta_senza_codice():
            return ""                  # dichiarato aperto: solo in locale
        st.error("**Accesso non configurato: l'app resta chiusa.**\n\n"
                 "Manca la variabile `CLIENTI` con la parola d'accesso. "
                 "Si mette nel pannello del servizio, sezione Environment, "
                 "e poi il servizio va riavviato perche' la legga.")
        st.stop()

    if st.session_state.get("chi_entra"):
        return st.session_state["chi_entra"]

    sinistra, centro, destra = st.columns([1, 2, 1])
    with centro:
        if marchio:
            st.markdown(marchio, unsafe_allow_html=True)
        detto = st.text_input("Codice di accesso", type="password",
                              placeholder="il codice che ti abbiamo dato")
    if detto and detto in ammessi:
        st.session_state["chi_entra"] = ammessi[detto]
        st.rerun()
    elif detto:
        # Non si dice se il codice e' inesistente o scaduto: a chi prova a
        # indovinare, ogni differenza e' un indizio.
        with centro:
            st.error("Codice non valido.")
    st.stop()
