# Mandraya Assistant

Gemeinsame Konzeptwerkstatt für ein Fantasy-Erlebnisformat für Menschen und Hunde. Früher Arbeitsstand mit Node-Oberfläche, versionierten Quellen, geschützten Beschlüssen und Änderungsvorschlägen.

## Aktueller Umfang

- Mandraya-Grundgerüst und Kampagnen mit Beziehungen
- Texteingang und Dateiarchiv für Uploads; Textextraktion aus TXT, Markdown, CSV, DOCX und PDF
- Quellenversionen, Fassungsvergleich und Änderungsprotokoll
- Beschlüsse sperren und ausdrücklich wieder öffnen
- Vorschläge annehmen oder ablehnen; Prüfung der zugrunde liegenden Konzeptversion
- Google-Anmeldung mit expliziter E-Mail-Freigabeliste
- Minimaler MCP-Endpunkt: Projektübersicht lesen, Knoten lesen, Vorschlag erstellen

**Noch keine KI-Chat-Anbindung und keine automatische Drive-Synchronisation.** Das Repository enthält ausschließlich Anwendungscode und das vorläufige Struktur-Gerüst; keine privaten Quellen, Entscheidungen oder Zugangsdaten. Der MCP-Endpunkt verwendet einen separat konfigurierten Bearer-Token und bietet noch keine OAuth-Discovery.

## Start mit Docker

1. `.env.example` nach `.env` kopieren und die eigenen Werte eintragen. Einen zufälligen `MCP_TOKEN` setzen, wenn MCP verwendet werden soll; andernfalls leer lassen.
2. Google OAuth-Webclient mit `https://DEINE-DOMAIN/auth/callback` als Weiterleitungsadresse konfigurieren.
3. `docker compose up --build -d` ausführen.
4. Einen HTTPS-Reverse-Proxy auf `127.0.0.1:4190` konfigurieren. `BASE_URL` muss exakt der öffentlichen HTTPS-Adresse entsprechen. Sichere Anmelde-Cookies erfordern HTTPS.

Keine öffentliche Freigabeliste wird mitgeliefert: `ALLOWED_EMAILS` muss ausdrücklich gesetzt werden. Daten bleiben im Docker-Volume `assistant-data`. Der Port wird nur an Loopback gebunden; HTTPS und Proxy-Konfiguration liegen beim Betreiber. Uploads sind auf 16 MB pro Datei begrenzt. Gescannten PDFs fehlt ohne OCR möglicherweise der Text; Bilder und DOCX-Kommentare werden nicht ausgewertet.

## Tests

Mit Python 3.12: `python -m pip install -r app/requirements.txt`, danach `cd app` und `python -m unittest discover -s tests -v`. Tests arbeiten in einem temporären Datenverzeichnis.

## Sicherung

`docker compose exec assistant python backup.py` erzeugt eine SQLite-Sicherung und ein Archiv der hochgeladenen Dateien im Datenvolume unter `backups/`. Regelmäßige und externe Sicherungen müssen zusätzlich eingerichtet werden.

## Quellenimport

`app/import_sources.py` verarbeitet eine JSON-Liste mit `id`, `title`, `content` und optional `url`, `path`, `kind`, `coverage`, `modified`, `nodes`. Gleiche Quellen-ID und gleicher Texthash erzeugen keine doppelte Version. Quelldateien und Importdaten gehören nicht ins Repository.

## Lizenz

MIT, siehe LICENSE. Die Lizenz gilt für den Anwendungscode. Sie räumt keine Rechte an externen Quellen oder der Marke Mandraya ein.
