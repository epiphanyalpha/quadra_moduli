"""Word conversion, public API and conservative text helpers.

Structured reading/writing lives in word_documento; PDF processing is unchanged.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

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
    with Path(percorso).open("rb") as stream:
        return stream.read(4).startswith(b"PK\x03\x04")


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


def _senza_ripetizione(etichetta: str, valore: str) -> str:
    """Reuse only an explicit printed street type, never arbitrary repeated words."""
    match = re.fullmatch(r"\s*(?:in\s+)?(via|viale|piazza|corso|vicolo|largo)\s*[:.]?\s*",
                         etichetta or "", re.I)
    if match:
        prefix = re.match(r"^" + re.escape(match.group(1)) + r"\s+(\S.*)$", valore, re.I)
        if prefix:
            return prefix.group(1)
    return valore


def _senza_eco(prima: str, valore: str) -> str:
    """Compatibility helper: a repetition elsewhere never authorizes data loss."""
    return valore


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



from .word_documento import leggi, rendi, scrivi, verifica
