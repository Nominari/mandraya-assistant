# Mandraya Assistant

Gemeinsame Konzeptwerkstatt für ein Fantasy-Erlebnisformat für Menschen und Hunde. Früher Arbeitsstand mit Node-Oberfläche, versionierten Quellen, geschützten Beschlüssen und Änderungsvorschlägen.

## Aktueller Umfang

- Drei verbundene Ansichten: Node-Projektübersicht, Themenstand und großzügige Werkstatt
- Freie Diskussionen ohne verpflichtendes Arbeitsziel; letzter Austausch im Arbeitsbereich, Verlauf in eigener Ansicht
- Mandraya-Grundgerüst und Kampagnen mit Beziehungen
- Texteingang und Dateiarchiv für Uploads; Textextraktion aus TXT, Markdown, CSV, DOCX und PDF
- Quellenversionen, Fassungsvergleich und Änderungsprotokoll
- Einzelne präzise Aussagen beschließen und ausdrücklich wieder öffnen; ältere gesperrte Gesamtfassungen bleiben erhalten
- KI-Überblick auf Anfrage, bei Projektänderungen als veraltet markiert
- Bearbeitbare KI-Zwischenstände: Menschen wählen Arbeitsfassung, Varianten, Aussagen und konkrete offene Fragen
- Fragen mit Ursprung, betroffenem Thema und Diskussion; projektweit sichtbar und zurückstellbar
- Vorschläge annehmen oder ablehnen; Prüfung der zugrunde liegenden Konzeptversion
- Google-Anmeldung mit expliziter E-Mail-Freigabeliste
- Minimaler MCP-Endpunkt: Projektübersicht lesen, Knoten lesen, Vorschlag erstellen

KI-Chat nutzt eine eigene, ausdrücklich freigegebene ChatGPT-Verbindung pro Person. Antworten und Quellenbelege werden gemeinsam gespeichert; die KI besitzt nur lesende Projektwerkzeuge. In der Werkstatt werden Antworten durch einen gesonderten, bearbeitbaren Zwischenstand ausgewertet. Menschen übernehmen nur ausdrücklich ausgewählte Ergebnisse. Alle Auswahlfelder starten unmarkiert. Gesprächsstand und Ansatz zum Fortsetzen können unabhängig von Konzeptänderungen gespeichert werden. Konzept- und Quellenfassungen werden vor Übernahme und Freigabe geprüft. Abgebrochene Antworten sind nicht übernehmbar. **Noch keine automatische Drive-Synchronisation.** Das Repository enthält ausschließlich Anwendungscode und das vorläufige Struktur-Gerüst; keine privaten Quellen, Entscheidungen oder Zugangsdaten. Der MCP-Endpunkt verwendet einen separat konfigurierten Bearer-Token und bietet noch keine OAuth-Discovery.

## Start mit Docker

1. `.env.example` nach `.env` kopieren und die eigenen Werte eintragen. Einen zufälligen `MCP_TOKEN` setzen, wenn MCP verwendet werden soll; andernfalls leer lassen.
2. Google OAuth-Webclient mit `https://DEINE-DOMAIN/auth/callback` als Weiterleitungsadresse konfigurieren.
3. `docker compose up --build -d` ausführen.
4. Einen HTTPS-Reverse-Proxy auf `127.0.0.1:4190` konfigurieren. `BASE_URL` muss exakt der öffentlichen HTTPS-Adresse entsprechen. Sichere Anmelde-Cookies erfordern HTTPS.

Keine öffentliche Freigabeliste wird mitgeliefert: `ALLOWED_EMAILS` muss ausdrücklich gesetzt werden. Daten bleiben im Docker-Volume `assistant-data`. Der Port wird nur an Loopback gebunden; HTTPS und Proxy-Konfiguration liegen beim Betreiber. Uploads sind auf 16 MB pro Datei begrenzt. Gescannten PDFs fehlt ohne OCR möglicherweise der Text; Bilder und DOCX-Kommentare werden nicht ausgewertet.

## ChatGPT-Abo verbinden

Diese quelloffene Anwendung implementiert den offiziellen [Sign-in-with-ChatGPT-Fluss für OSS](https://developers.openai.com/siwc/token-sharing-open-source/sign-in). Die Verfügbarkeit der Abo-Nutzung hängt von der Freigabe durch OpenAI und dem angemeldeten Konto ab; ohne erfolgreiche Anmeldung wird keine KI simuliert. Es gibt keinen automatischen Wechsel auf kostenpflichtige API-Schlüssel.

Auf dem eigenen Computer die Python-Abhängigkeiten installieren und aus dem Repository starten:

```sh
python tools/connect_chatgpt.py --ssh BENUTZER@SERVER --owner DEINE_GOOGLE_ANMELDEADRESSE --key PFAD_ZUM_SSH_SCHLUESSEL
```

Der Helfer erwartet einen Container namens `mandraya-assistant`; bei einer Compose-Installation seinen tatsächlichen Namen entsprechend anpassen. Er öffnet die offizielle Anmeldung, verwendet einen temporären Loopback-Callback und überträgt die Verbindung über SSH auf den Server. Die Zustimmung erfolgt persönlich im Browser. Google-Anmeldung und ChatGPT-Konto sind getrennt. Jede Person richtet ihre eigene Verbindung ein. Die lokale Registrierung liegt geschützt unter `~/.config/mandraya-assistant/chatgpt/`; Tokens werden dort nicht gespeichert.

Der Server schützt Tokens durch Dateirechte und Verschlüsselung im Datenvolume. Der daneben gespeicherte Schlüssel schützt nicht vor einem kompromittierten Server. Betrieb mit genau einem Anwendungsprozess; Token-Erneuerung wird pro Konto serialisiert. Die Oberfläche bietet Trennung und versucht dabei den OpenAI-Widerruf; falls dieser nicht bestätigt wird, in den ChatGPT-Einstellungen ebenfalls widerrufen. Relevante Projekttexte gehen für Antworten an OpenAI. Frühere ChatGPT-Gespräche werden nicht importiert. Modelle stammen aus der jeweiligen Kontofreigabe.

## Tests

Mit Python 3.12: `python -m pip install -r app/requirements.txt`, danach `cd app` und `python -m unittest discover -s tests -v`. Tests arbeiten in einem temporären Datenverzeichnis.

## Sicherung

`docker compose exec assistant python backup.py` erzeugt eine SQLite-Sicherung und ein Archiv der hochgeladenen Dateien im Datenvolume unter `backups/`. Regelmäßige und externe Sicherungen müssen zusätzlich eingerichtet werden. ChatGPT-Zugangsdaten und Verschlüsselungsschlüssel sind nicht im regulären Backup enthalten; nach Verlust der Zugangsdaten die Konten erneut verbinden. Chatverläufe liegen in SQLite und sind enthalten.

## Workflow und Grenzen

Die Oberfläche zeigt gespeicherte Quellen und Aussagen, keine zugesicherte Vollständigkeit. KI-Ergebnisse sind Entwürfe. Neue Fragen aus KI-Analysen entstehen erst nach menschlicher Bestätigung. Die projektweite Fragenübersicht wird im sichtbaren Browser alle 30 Sekunden aktualisiert; es gibt keine permanente Hintergrundanalyse. Der letzte Austausch steht im Arbeitsbereich. Der bisherige Verlauf lädt zunächst die jüngsten 60 gespeicherten Nachrichten je Diskussion; ältere Nachrichten lassen sich schrittweise nachladen. Der KI-Kontext ist begrenzt und berücksichtigt den geprüften Zwischenstand; eine vollständige Analyse aller früheren Dialoge wird nicht zugesichert. Unfertige Eingaben und bearbeitete Übernahmeformulare werden personenbezogen im Browser zwischengespeichert; erst bestätigte Übernahmen werden gemeinsam gespeichert und protokolliert. Bei Datenbankänderungen sichert `backup.py` die bisherige Datenbank. Nach Schemaerweiterungen erfordert ein Rollback auf ältere Software gegebenenfalls Wiederherstellung dieser Sicherung.

## Quellenimport

`app/import_sources.py` verarbeitet eine JSON-Liste mit `id`, `title`, `content` und optional `url`, `path`, `kind`, `coverage`, `modified`, `nodes`. Gleiche Quellen-ID und gleicher Texthash erzeugen keine doppelte Version. Quelldateien und Importdaten gehören nicht ins Repository.

## Lizenz

MIT, siehe LICENSE. Die Lizenz gilt für den Anwendungscode. Sie räumt keine Rechte an externen Quellen oder der Marke Mandraya ein.
