# -*- coding: utf-8 -*-
"""Esegue in un container isolato il programma che l'agente ha scritto.

Il programma arriva da un modello: si esegue in un contenitore Linux senza rete,
con il filesystem in sola lettura e nessuna variabile d'ambiente dell'app, e con
un tempo massimo oltre il quale il contenitore viene fermato a forza.

Se il contenitore non è disponibile la funzione **rifiuta di eseguire**: non
esiste un ripiego meno protetto. Su un server con i documenti di più clienti,
eseguire senza isolamento sarebbe il difetto peggiore del sistema.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

IMMAGINE = "quadra-agente:local"
SECONDI_MAX = 120
USCITA_MAX = 8000


class IsolamentoAssente(RuntimeError):
    """Manca il contenitore: non si esegue nulla."""


def comando_docker() -> str:
    """Dove sta docker.

    Docker Desktop si installa anche per singolo utente, e in quel caso la CLI
    non finisce nel PATH di tutte le shell: cercarla solo nel PATH fa concludere
    che manchi quando invece sta girando.
    """
    scelto = os.environ.get("QUADRA_DOCKER", "")
    if scelto and Path(scelto).is_file():
        return scelto
    trovato = shutil.which("docker")
    if trovato:
        return trovato
    candidati = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Docker/Docker/resources/bin/docker.exe",
        Path(os.environ.get("ProgramW6432", "")) / "Docker/Docker/resources/bin/docker.exe",
        Path("/usr/bin/docker"), Path("/usr/local/bin/docker"),
    ]
    for c in candidati:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return ""


def disponibile() -> bool:
    docker = comando_docker()
    if not docker:
        return False
    try:
        esito = subprocess.run([docker, "image", "inspect", IMMAGINE],
                               capture_output=True, timeout=20)
        return esito.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ambiente_pulito() -> dict[str, str]:
    """Solo il minimo per far girare il client docker: nessuna chiave, nessun proxy."""
    # la cartella di docker va nel PATH anche quando la shell non ce l'ha: il
    # client si appoggia a programmi che stanno li' accanto (le credenziali)
    percorso = os.environ.get("PATH", "")
    docker = comando_docker()
    if docker:
        accanto = str(Path(docker).parent)
        if accanto not in percorso:
            percorso = accanto + os.pathsep + percorso
    return {"PATH": percorso,
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            # il client docker legge la sua configurazione sotto il profilo
            # utente: senza, non trova il demone su Windows
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "HOME": os.environ.get("HOME", ""),
            "NO_PROXY": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": ""}


LIBRERIA = Path(__file__).resolve().parent / "riusare" / "strumenti_documento.py"


def esegui(codice: str, originale: Path, cartella: Path, fascicolo: dict) -> dict:
    """Espone al programma solo l'originale in lettura e una cartella in scrittura.

    La libreria comune si monta in /work accanto al programma invece di
    affidarsi a PYTHONPATH: se un giorno il contenitore partisse con `python -I`
    la variabile verrebbe ignorata e l'import fallirebbe senza dire perche'.
    """
    if not disponibile():
        raise IsolamentoAssente(
            f"Manca il contenitore isolato. Installa Docker con container Linux e "
            f"costruisci l'immagine: docker build -f Dockerfile.agente -t {IMMAGINE} .")

    originale = Path(originale).resolve(strict=True)
    cartella = Path(cartella).resolve()
    uscita = cartella / "uscita"
    uscita.mkdir(parents=True, exist_ok=True)
    for vecchio in uscita.iterdir():
        vecchio.unlink()

    programma = cartella / "programma.py"
    dati = cartella / "fascicolo.json"
    programma.write_text(codice, encoding="utf-8")
    dati.write_text(json.dumps(fascicolo, ensure_ascii=False), encoding="utf-8")

    nome = "quadra-" + uuid.uuid4().hex
    docker = comando_docker()
    comando = [
        docker, "run", "--rm", "--name", nome,
        "--network", "none",                       # nessuna rete
        "--read-only",                             # filesystem non scrivibile
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=768m", "--cpus=2",
        "--user=65534:65534",                      # nobody
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--workdir=/work",
        "--mount", f"type=bind,source={originale},target=/work/originale.pdf,readonly",
        "--mount", f"type=bind,source={programma},target=/work/programma.py,readonly",
        "--mount", f"type=bind,source={LIBRERIA.resolve()},"
                   f"target=/work/strumenti_documento.py,readonly",
        "--mount", f"type=bind,source={dati},target=/work/fascicolo.json,readonly",
        "--mount", f"type=bind,source={uscita},target=/work/uscita",
        IMMAGINE, "python", "/work/programma.py",
    ]

    try:
        esito = subprocess.run(comando, capture_output=True, text=True,
                               timeout=SECONDI_MAX, env=_ambiente_pulito(),
                               encoding="utf-8", errors="replace")
        uscita_std, uscita_err, codice_uscita = esito.stdout, esito.stderr, esito.returncode
    except subprocess.TimeoutExpired:
        # Il timeout del client non garantisce che il contenitore si fermi.
        subprocess.run([docker, "rm", "-f", nome], capture_output=True,
                       timeout=15, env=_ambiente_pulito())
        uscita_std, uscita_err, codice_uscita = "", (
            f"Tempo massimo superato ({SECONDI_MAX}s): contenitore fermato."), None

    bozza = uscita / "bozza.pdf"
    scritture = uscita / "scritture.json"
    return {
        "codice_uscita": codice_uscita,
        "stdout": (uscita_std or "")[-USCITA_MAX:],
        "stderr": (uscita_err or "")[-USCITA_MAX:],
        "uscita": str(uscita),
        "bozza": str(bozza) if bozza.is_file() else None,
        "scritture": str(scritture) if scritture.is_file() else None,
        "riuscita": bozza.is_file() and codice_uscita == 0,
    }
