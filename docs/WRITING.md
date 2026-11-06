# Schreiben und Kampagnengedächtnis einrichten

Version 2.2.0 ergänzt sechs Werkzeuge zu den bisherigen vier Lesewerkzeugen. `create_note`, `update_note`, `patch_note`, `move_note` und `restore_note` ändern Markdown. `list_note_versions` zeigt gesicherte Fassungen an. `read_note` liefert zusätzlich eine SHA-256-Dateirevision und die Gesamtzahl der Zeilen. Vorhandene Leser können die bisherigen Felder weiterverwenden.

## Update in Dockge

1. Vorher einen geschützten Snapshot der Vaults und der App-Daten erstellen. Für eine Rückkehr die bisherigen App- und Gateway-Image-Digests notieren.
2. Beide neuen, erfolgreich geprüften Images ziehen und den bestehenden Stack deployen. Die bisherigen Zugangsdaten und OAuth-URLs weiterverwenden.
3. Die Verwaltung öffnen. Oben muss **Version 2.2.1** stehen. In jeder Freigabe den Haken **Schreiben erlauben** setzen. Ohne Haken bleibt der Vault lesend.
4. Für den ganzen ausgewählten Vault genügt der Haken. Unter **Optional auf Unterordner begrenzen** bei Bedarf einen relativen Projektordner eintragen, beispielsweise `Projekte/Kampagne`. Ein Eintrag pro Zeile, ohne führenden oder abschließenden Schrägstrich. Ein leeres Feld oder `/` erlaubt bei gesetztem Haken den ganzen Vault. Nach einer Rechteänderung die gespeicherte Konfiguration anwenden. Dafür werden vorhandene Images verwendet, ein lokaler Neubau ist nicht erforderlich.
5. Speichern und den kopierbaren Befehl **Gespeicherte Konfiguration anwenden** im Stack-Verzeichnis ausführen. Dadurch werden Mount und Schreibordner des betreffenden Workers aktualisiert. Das ursprüngliche Vault-Verzeichnis muss bereits existieren. Unterordner für neue Notizen kann das Werkzeug selbst anlegen.
6. TrueNAS-ACLs müssen dem Worker-UID/GID das Anlegen, Ersetzen und Verschieben von Dateien sowie das Anlegen von `.mcp-history` erlauben. Der Standard ist UID/GID 568. Keine pauschale `chmod 777`-Änderung verwenden.
7. In ChatGPT die Werkzeuge des bestehenden Plugins aktualisieren. Falls dort weiter nur vier Werkzeuge erscheinen, die Verbindung neu laden beziehungsweise erneut verbinden. Der MCP-Endpunkt bleibt `/mcp`.
8. Eine kleine Testnotiz im erlaubten Projektordner erstellen, lesen, ändern und eine frühere Fassung wiederherstellen. Einen nicht freigegebenen Pfad als Negativtest verwenden. Erst dann produktive Protokolle bearbeiten.

Bei GitHub-Owner-OAuth gelten die aktuell konfigurierten Schreibordner. Für die ältere Header-Bridge benötigt ein neu erstellter Client-Token zusätzlich die ausgewählten Schreibfreigaben im Abschnitt **Client-Zugriff begrenzen**. Bestehende Tokens bekommen durch das Update keine Schreibrechte. Eine spätere Erweiterung der Freigabe erweitert die Schreibrechte alter Tokens ebenfalls nicht.

## Gemeinsames Arbeiten

Vor einer Änderung `read_note` aufrufen und dessen `revision` als `expected_revision` übergeben. Für vollständige Ersetzungen alle Seiten lesen und sicherstellen, dass die Revision währenddessen gleich bleibt. Bei langen Notizen kann `patch_note` genau einen vorhandenen Textabschnitt ersetzen. Bei einem Konflikt erneut lesen und die eigenen Änderungen mit dem Nutzerstand zusammenführen.

Eine wiederholte Erstellung mit identischem Inhalt ist sicher. Eine vorhandene andere Datei führt zum Konflikt. `update_note` kann nach einer verlorenen Antwort mit demselben Zielinhalt wiederholt werden. Bei Verschiebungen nach einer Unterbrechung beide Pfade prüfen. Das Verschieben schreibt Backlinks nicht automatisch um. Betroffene Links zuerst suchen und anschließend gezielt bearbeiten. Als Archivierung einen sichtbaren Archiv-Unterordner verwenden.

Die Dateirevision erkennt Änderungen auch dann, wenn mehrere MCP-Sitzungen arbeiten. Obsidian und andere Editoren teilen den MCP-Lock nicht. Für dieselbe Notiz gleichzeitiges Bearbeiten in Obsidian und MCP vermeiden. Mehrere Notizen bilden keine gemeinsame Transaktion. Nach jedem bestätigten Schritt kann der Assistent den Fortschritt im Projektgedächtnis festhalten und nach einem Fehler fortsetzen.

## Gedächtnis und Referenzen

Im Gedächtnis einen Einstieg, bestätigten Kampagnenstand, Chronologie, Figurenwissen, offene Fäden, Protokolllücken und Quellenregister pflegen. Importierte Compendien, veröffentlichte Abenteuer, Vorbereitung und tatsächlich gespielte Ereignisse als unterschiedliche Quellenarten kennzeichnen. Eine Sitzungsnummer aus einem fremden Beispielprotokoll belegt kein Ereignis der eigenen Runde.

Regeln nach Edition und Quellversion ablegen, etwa SRD 5.1 für 2014 und SRD 5.2.1 für 2024. Regelantworten zuerst im passenden lokalen Bestand prüfen. Bei fehlendem oder unklarem Inhalt eine aktuelle Primärquelle nachschlagen und die geprüfte Antwort mit Datum, Quelle, Edition und möglichen Hausregeln ablegen. Die tatsächlich verwendete Edition und Hausregeln vom Dungeon Master bestätigen lassen.

## Wiederherstellung und Grenzen

Vorherige Inhalte liegen als nach Pfad und Inhalt gehashte Fassungen im versteckten Vault-Ordner `.mcp-history`. `list_note_versions` listet die letzten 100 Fassungen pro Pfad. `restore_note` übernimmt eine gewählte Fassung mit erwarteter aktueller Revision. Für eine inzwischen verschobene, fehlende Quelldatei `expected_revision="missing"` verwenden. Damit wird keine vorhandene Datei überschrieben.

Bei 256 MiB History stoppt weiteres Sichern und Schreiben. Den Verlauf dann auf dem Host geschützt archivieren und Speicher freigeben. History und eigentliche Notizen in TrueNAS-Snapshots einbeziehen. Die Dateihistorie ersetzt einen externen, getesteten Backup nicht.

Pro Note gelten 2 MiB UTF-8 und höchstens 16000 Zeichen pro Zeile. Pro Leseaufruf maximal 500 Zeilen, bei Bedarf `next_line` folgen. Für große Regelbestände kleine Markdown-Einträge mit Quellenangaben verwenden. Versteckte Obsidian-Konfiguration, Skripte und Binärdateien bleiben außerhalb der Dateischnittstelle. Eine schreibbare Freigabe bindet den ganzen gewählten Vault schreibbar ein, die Ordnergrenze wird von der Anwendung durchgesetzt. Für stärkere Dateisystemtrennung einen eigenen Unterordner als separate Vault-Freigabe mounten.
