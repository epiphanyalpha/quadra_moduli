# L'app come gira su un server. Sul computer di chi sviluppa non serve:
# li' Python e LibreOffice ci sono gia'.
#
# Due cose valgono la pena di essere spiegate, perche' sono le uniche due
# che fanno la differenza fra un'immagine che funziona e una che no.
#
# LIBREOFFICE. Il percorso Word ne ha bisogno per due lavori distinti: aprire
# i .doc del 1997 - che sono il 77% dei moduli pubblicati dai comuni, e che
# nessuna libreria Python legge - e rendere in PDF la bozza per mostrarla.
# Si installa `libreoffice-writer` e non `libreoffice`: l'intera suite porta
# dentro Calc, Impress e mezzo Java per un lavoro che tocca solo i documenti
# di testo.
#
# I CARATTERI. Senza, LibreOffice converte lo stesso ma sostituisce i font
# mancanti, e l'anteprima mostra una pagina che non e' quella che Bianca
# stampera'. Costano pochi megabyte e tolgono una classe intera di "sul mio
# computer si vedeva diverso".
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-core \
        fonts-dejavu-core \
        fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Le dipendenze prima del codice: cosi' una modifica all'app non rifa'
# l'installazione dei pacchetti a ogni rilascio.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Docker non c'e', dentro un contenitore: il percorso PDF lo sa e lo dice.
# Il percorso Word non lo usa mai, ed e' quello che si consegna.
EXPOSE 8501

# `$PORT` la decide Render. In locale, se non c'e', vale 8501.
CMD streamlit run app.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
