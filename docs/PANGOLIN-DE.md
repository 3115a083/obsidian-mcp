# Pangolin sicher einrichten

Für eine direkte ChatGPT-Verbindung ab Version 2.1 siehe [CHATGPT.md](CHATGPT.md). Dafür eine separate OAuth-Ressource auf Port 3062 verwenden. Die bestehende Verwaltungsressource und ihre Pangolin-Anmeldung bleiben erhalten. Die folgenden Bridge-Einstellungen gelten für den bisherigen Zugang.


## Ressource und Verwaltung

1. Eine HTTPS-Ressource anlegen und die Newt-Site auswählen.
2. Bei Newt im Host-Netz und unveränderter Compose-Konfiguration auf HTTP `127.0.0.1:3061` weiterleiten. Bei geändertem Gateway-Port diesen verwenden. Den Gateway nicht zusätzlich öffentlich freigeben.
3. Den vollständigen Host samt Pfaden weiterleiten. `/admin`, `/auth`, `/mcp` und `/.well-known` nicht abschneiden oder umschreiben.
4. Pangolin-Anmeldung eingeschaltet lassen. `PUBLIC_URL` lokal auf den öffentlichen HTTPS-Ursprung setzen.
5. `/admin/` öffnen, bei Pangolin anmelden und anschließend mit dem freigegebenen GitHub-Konto anmelden. Die numerische Konto-ID wird von der App geprüft.

## MCP ohne interaktive Pangolin-Anmeldung

In der Ressourcen-Authentifizierung einen befristeten Link erstellen und dessen Zugangstoken sofort lokal sichern. Die Bridge sendet bei jeder Anfrage die beiden Standardheader `P-Access-Token-Id` und `P-Access-Token`. Zusätzlich verlangt die App ihren eigenen, auf ausgewählte Vaults begrenzten Bearer-Token.

Die drei Werte gehören in eine geschützte lokale Bridge-Umgebungsdatei, niemals in Git, URLs, Chat oder Screenshots. Die Variablen heißen `PANGOLIN_TOKEN_ID`, `PANGOLIN_ACCESS_TOKEN` und `MCP_CLIENT_TOKEN`. Der Endpunkt für `MCP_SERVER_URL` endet auf `/mcp`, ohne abschließenden Schrägstrich. Die [Verbindungsanleitung](CONNECTIONS.md) beschreibt den Start der STDIO-Bridge. Eine direkte Cloud-Verbindung kann nicht als Unterstützung beliebiger zusätzlicher Header vorausgesetzt werden.

## Warum keine pauschale Ausnahme für /mcp/?

Pangolins Aktion **Bypass Auth** überspringt für passende Anfragen die Pangolin-Authentifizierung. Sie schaltet nicht die Tokenprüfung der App aus. Dadurch wäre aber die äußere Schutzschicht für diesen Pfad entfernt. Diese Installation verwendet deshalb die Header-Bridge und behält Pangolin auch vor MCP bei.

Eine Ausnahme nur für `/mcp/` löst außerdem keine vollständige OAuth-Anbindung: Der eigentliche MCP-Endpunkt ist `/mcp`; Discovery und OAuth haben zusätzliche Pfade. Pfadregeln, Reihenfolge und Schrägstriche müssen zum konkreten Proxy passen. Keine Wildcard-Ausnahmen für `/*`, `/admin` oder `/auth` setzen, um einen Loginfehler zu umgehen.

## Einrichtung prüfen

- Ohne Pangolin-Sitzung und ohne Pangolin-Zugangstoken darf die öffentliche Ressource keine Vault-Daten liefern.
- Mit gültigem Pangolin-Zugang, aber ohne gültigen App-Token muss eine MCP-Anfrage an `/mcp` mit HTTP 401 abgewiesen werden. Eine Browser-Sitzung genügt nicht.
- Mit beiden Zugangsdaten muss ein erlaubter Vault lesbar sein; ein nicht freigegebener Vault darf nicht lesbar sein.
- App-Token widerrufen und erneut testen. Den Pangolin-Link separat löschen, um auch dessen Zugangstoken zu widerrufen.

Diese Live-Prüfungen führt der Betreiber aus. Automatisierte Tests ersetzen keine Prüfung der tatsächlichen Pangolin-Ressource.

## Vault-Konfiguration übernehmen

Nach dem Speichern in der Verwaltung den Befehl im Feld **Gespeicherte Konfiguration anwenden** kopieren. Per SSH auf dem TrueNAS-Host in das betreffende Dockge-Stack-Verzeichnis wechseln. Dort müssen `compose.yaml`, `compose.override.yaml` und `.env` liegen. Den gleichen Compose-Projektnamen wie Dockge verwenden; bei einem ausdrücklich abweichenden Namen bei beiden Compose-Aufrufen `-p PROJEKTNAME` ergänzen.

Der Befehl prüft die Konfiguration und startet die Dienste mit `--remove-orphans`. Das entfernt verwaiste Dienste dieses Projekts, einschließlich entfernter Vault-Worker. Er zieht keine neuen Images und berücksichtigt nur gespeicherte Änderungen. Die App führt ihn nicht aus und erhält keinen Docker-Socket. Bei gesperrtem Clipboard lässt sich der markierte Text manuell kopieren.

Quellen: [Pangolin-Zugangstoken](https://docs.pangolin.net/manage/access-control/links), [Pangolin-Pfadregeln](https://docs.pangolin.net/manage/access-control/rules).
