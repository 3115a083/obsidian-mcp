# Verwaltung nach einem fehlerhaften Vault-Mount wieder starten

Ein nicht vorhandener oder nicht lesbarer Host-Ordner verhindert den Start seines Vault-Workers. Ein gemeinsamer Stack-Start kann dadurch abbrechen. Die Verwaltungs-App selbst benötigt keinen Vault-Mount und kann unabhängig starten.

## Sofortmaßnahme, auch mit der bisherigen Version

Auf dem Docker-/TrueNAS-Host in das **bestehende Dockge-Stack-Verzeichnis** wechseln. Das ist der Ordner mit `compose.yaml`, `compose.override.yaml`, `.env` und `data/`. Keinen neuen Stack anlegen.

```bash
sudo docker compose -f compose.yaml up -d app gateway
```

Der explizite einzelne `-f` lädt nur die Basisdatei. Der fehlerhafte Worker aus `compose.override.yaml` wird nicht gestartet. Die Override-Datei bleibt als Datei an die App gebunden, damit die Verwaltung sie nach einer Korrektur neu schreiben kann. Gespeicherte Freigaben, Schlüssel und Vault-Dateien werden nicht gelöscht. Bereits laufende Worker werden nicht gestoppt.

Wenn Dockge für den bestehenden Stack einen anderen Projektnamen verwendet, exakt denselben Namen angeben:

```bash
sudo docker compose -p DEIN_BESTEHENDER_PROJEKTNAME -f compose.yaml up -d app gateway
```

Danach `https://MCP-PROJEKT-DOMAIN/admin/` öffnen, anmelden und den falschen Eintrag korrigieren. Falls die Seite weiter nicht startet, die Meldung dieses Befehls und `sudo docker compose -f compose.yaml logs --tail=50 app gateway` lokal prüfen. Keine Tokens, Cookies, Secrets oder Vault-Inhalte veröffentlichen.

## Was in welches Feld gehört

| Feld | Beispiel | Bedeutung |
| --- | --- | --- |
| Name | `memory` | Interner Kurzname des Workers, unabhängig vom Verzeichnisnamen |
| Anzeigename | `Meine Notizen` | Frei wählbarer Text in der Oberfläche |
| Serververzeichnis | `/srv/obsidian/vaults/MeineNotizen` | Tatsächlich vorhandener absoluter Ordner auf dem Docker-Host |

Keine HTTPS-Adresse und keinen Pfad innerhalb eines anderen Containers als Serververzeichnis eintragen. Groß-/Kleinschreibung und NAS-ACLs beachten. Der ausgewählte Container-UID/GID braucht Lese- und Durchgangsrechte, keinen pauschalen Schreibzugriff.

Ein Docker-Bind-Mount mit `create_host_path: false` erzeugt absichtlich keinen fehlenden Ordner. Diesen Schutz nicht abschalten und keinen leeren Ersatzordner anlegen, um den Fehler zu verdecken. Die App hat keinen Host-Dateisystem-Mount und kann die Existenz beliebiger NAS-Pfade nicht selbst prüfen.

Nach dem Speichern die vollständige, korrigierte Konfiguration anwenden. Bei Bedarf auch hier den bestehenden Projektnamen ergänzen:

```bash
sudo docker compose -f compose.yaml -f compose.override.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.override.yaml up -d --remove-orphans
```

`config --quiet` prüft Compose-Syntax und Interpolation, nicht die Existenz und Lesbarkeit jedes Bind-Ordners. `--remove-orphans` entfernt nicht mehr konfigurierte Worker dieses Compose-Projekts. Es löscht keine Host-Vaults. Beim Ändern des Verzeichnisziels erhält die Freigabe eine neue Identität; alte begrenzte Client-Tokens erben diese Rechte nicht.

## MCP-Projektadresse und Vault-Adresse

`PUBLIC_URL` ist die HTTPS-Adresse **dieser MCP-Anwendung und ihrer Verwaltungsoberfläche**. Für ChatGPT auf derselben Projekt-Domain ist `MCP_PUBLIC_URL` identisch. Die separate Obsidian-Web-/Vault-Adresse wird dafür nicht verwendet. Die Vault-Verbindung erfolgt über den lokalen Host-Ordner, nicht über dessen Webadresse.

Beispiel ohne reale Betreiberadresse:

```dotenv
PUBLIC_URL=https://mcp-projekt.example.invalid
MCP_PUBLIC_URL=https://mcp-projekt.example.invalid
VAULT_PARENT=/srv/obsidian/vaults
```

Nach Veröffentlichung des neuen Releases enthält das Gateway-Image bereits die passende Nginx-Konfiguration. Die neue `compose.yaml` braucht dafür keinen zusätzlichen Host-Mount. Vor dem Wechsel von der alten Compose-Datei zuerst die zugehörigen neuen App- und Gateway-Images bereitstellen. Der oben gezeigte Wiederherstellungsbefehl funktioniert bereits mit der bisherigen korrekt eingerichteten Basisdatei.
