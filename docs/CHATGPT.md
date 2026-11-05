# ChatGPT über die vorhandene Obsidian-Domain anbinden

Ab Version 2.1 können Verwaltung und MCP dieselbe Domain und denselben Gateway-Port verwenden:

| URL | Aufgabe | Zugang |
| --- | --- | --- |
| `https://obsidian.example.invalid/admin/` | Verwaltung | Pangolin-Anmeldung und GitHub-Owner |
| `https://obsidian.example.invalid/mcp` | ChatGPT | GitHub OAuth, ausschließlich der konfigurierte Owner |

Eine zusätzliche Domain ist nicht erforderlich. Auf den exakt festgelegten MCP-/OAuth-Routen darf Pangolin keine HTML-Anmeldung vorschalten. Dort schützt die Anwendung mit OAuth. Alle anderen Pfade bleiben hinter Pangolin.

## 1. Dockge

Nach Veröffentlichung zuerst die geprüften Deployment-Dateien einschließlich `compose.yaml` übernehmen. Bestehende `.env`, `data/` und `compose.override.yaml` erhalten. Danach beide passenden Images in Dockge ziehen und neu bereitstellen. Ein Image-Update allein ergänzt keine neuen Compose-Variablen. Das neue Gateway-Image enthält bereits seine Nginx-Konfiguration; ein Host-Mount der Datei entfällt. Die neue Compose erst mit dem zugehörigen veröffentlichten Gateway-Image einsetzen.

`PUBLIC_URL` bezeichnet diese MCP-Anwendung mit ihrer Verwaltung. Sie ist unabhängig von einer separaten Obsidian-Web-/Vault-Adresse. Vaults werden über lokale Serverpfade angebunden. Bei einem fehlgeschlagenen Vault-Mount siehe [RECOVERY.md](RECOVERY.md).

In `.env` dieselbe vorhandene HTTPS-Origin für beide Variablen verwenden:

```dotenv
PUBLIC_URL=https://obsidian.example.invalid
MCP_PUBLIC_URL=https://obsidian.example.invalid
MCP_ORIGIN_SECRET=HIER_LOKAL_ERZEUGTES_ZUFAELLIGES_GEHEIMNIS
```

Ein Geheimnis lokal erzeugen:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Den Wert weder in Git noch in ChatGPT eintragen. Unter `services.app.environment` ergänzt die neue Compose-Datei:

```yaml
MCP_PUBLIC_URL: ${MCP_PUBLIC_URL:-}
MCP_ORIGIN_SECRET: ${MCP_ORIGIN_SECRET:-}
```

Der vorhandene Gateway-Port bleibt `127.0.0.1:3061:8080`. Kein zusätzlicher veröffentlichter Port ist erforderlich. Ohne beide neuen Variablen bleibt der bisherige Modus erhalten. Bei aktivem Modus lässt ein fehlender oder schwacher Origin-Schlüssel die Anwendung nicht starten.

## 2. Bestehende Pangolin-Ressource

Die Ressource zeigt weiterhin über Newt auf `http://127.0.0.1:3061`. Host und Pfad unverändert weiterleiten. Pangolin setzt auf allen weitergeleiteten Requests `X-Pangolin-Origin` auf den lokalen Wert von `MCP_ORIGIN_SECRET` und **überschreibt** vorhandene Client-Werte.

Die vorhandene Pangolin-Anmeldung bleibt aktiviert. Nur folgende exakte Pfade bekommen in dieser Ressource eine **Bypass Auth**-Regel, jeweils Match Type **Path**:

```text
/mcp
/mcp/
/.well-known/oauth-authorization-server
/.well-known/oauth-protected-resource/mcp
/authorize
/token
/register
/consent
/auth/mcp/callback
```

Diese Pfade übernehmen die OAuth-Anmeldung und Token-Prüfung der App. Die Regeln gelten unabhängig von Query-Parametern. Niemals pauschal `/auth/*`, `/admin/*`, `/.well-known/*` oder `*` von der Anmeldung ausnehmen. Insbesondere `/auth/login` und `/auth/callback` gehören weiterhin zur geschützten Verwaltung.

Bei aktivierten Ressourcenregeln die bestehenden Zugriffsbeschränkungen erhalten. Eine abschließende **Pass to Auth**-Regel für alle übrigen Anfragen muss die vorhandene Anmeldung erzwingen. Bestehende Block-Regeln nicht durch vorgeschaltete Bypass-Regeln aushebeln. Pangolin verarbeitet Regeln nach Priorität. Bereits nötige Block-Regeln vor passende Bypass-Regeln stellen und das Ergebnis ohne bestehende Sitzung prüfen. Siehe [offizielle Pfadregeln](https://docs.pangolin.net/manage/access-control/rules).

**Vor Abnahme im privaten Browserfenster ohne Pangolin-Sitzung prüfen:** `/admin/`, `/login`, `/auth/login` und `/auth/callback` müssen weiter die Pangolin-Anmeldung verlangen. Discovery und `/consent` dürfen keine Pangolin-HTML-Seite liefern. `/mcp` ohne OAuth-Token muss die App mit 401 ablehnen. Bei abweichendem Verhalten die neuen Bypass-Regeln zurücknehmen und die Pangolin-Konfiguration prüfen.

Der Origin-Header ist eine zusätzliche Proxy-Prüfung, keine Nutzeranmeldung. Eine Browser-Session oder ein alter `omcp_`-Token authentifiziert keine direkte MCP-Verbindung.

## 3. Bestehende GitHub OAuth App

Dieselbe zentrale App weiterverwenden. Die bestehenden exakten Callback-URLs bleiben:

```text
https://obsidian.example.invalid/auth/callback
https://obsidian.example.invalid/auth/mcp/callback
```

Keine neue Callback-Domain und keine neue App pro Vault erforderlich. Wildcard-Matching deaktiviert lassen. Client ID, Client Secret und die numerische `GITHUB_OWNER_ID` bleiben ausschließlich in der Serverkonfiguration.

## 4. ChatGPT

Eine eigene MCP-App bzw. einen eigenen Connector anlegen, soweit das Konto diese Funktion anbietet:

| Einstellung | Wert |
| --- | --- |
| MCP-Server-URL | `https://obsidian.example.invalid/mcp` |
| Authentifizierung | OAuth |
| Client ID / Client Secret | Bei automatischer Registrierung leer lassen |

ChatGPT registriert seinen eigenen Client über DCR oder veröffentlichte Client-Metadaten. Die GitHub-App-Zugangsdaten gehören nicht in ChatGPT. Zugriff bestätigen und bei GitHub mit dem erlaubten Konto anmelden. Die Anwendung erlaubt nur ChatGPT-Redirects unter `https://chatgpt.com/connector/oauth/*` sowie die exakte Adresse `https://chatgpt.com/connector_platform_oauth_redirect`.

Der direkte Modus benötigt keinen lokalen STDIO-Prozess und keinen zusätzlichen Tunnel. Der Owner sieht alle **explizit in dieser Instanz freigegebenen** Vaults. Vier lesende Werkzeuge bleiben verfügbar: `list_vaults`, `list_notes`, `read_note`, `search_notes`. Schreiben bleibt ausgeschlossen.

**Bestehende Clients:** Im gemeinsamen Modus wird `/mcp` absichtlich OAuth-only. Alte Bridge-Clients mit `omcp_`-Tokens müssen auf OAuth wechseln oder beim bisherigen Modus bleiben. Ihre Tokens werden nicht gelöscht, erhalten aber am direkten Endpunkt keinen Zugriff. Für den parallelen Betrieb unveränderter Bridge-Clients ist der unten beschriebene getrennte Ursprung verfügbar.

## Rücknahme und Widerruf

Für die Rücknahme zuerst die neuen Pangolin-Bypass-Regeln entfernen, beide neuen `MCP_*`-Variablen leeren und den Stack neu starten. Die bisherige Verwaltung und deren verschlüsselte Zustände bleiben erhalten. Die Owner-Freigaben bleiben explizit; das Entfernen einer Vault-Freigabe entfernt sie auch aus den OAuth-Werkzeugen.

Die GUI widerruft alte App-Tokens, keine unabhängigen OAuth-Verbindungen. OAuth in ChatGPT trennen und bei Bedarf die GitHub-Berechtigung widerrufen. Für einen sofortigen vollständigen Stopp die Ressource deaktivieren oder den Stack stoppen. Ein geleaktes Origin-Geheimnis lokal erneuern und im Proxy ersetzen.

## Optional: getrennte Domain für unveränderte Bridge-Clients

Nur falls gewünscht `MCP_PUBLIC_URL` auf eine **andere** HTTPS-Origin setzen. Zusätzlich unter `gateway.ports` `127.0.0.1:3062:8081` veröffentlichen. Eine zweite Pangolin-Maschinenressource zeigt auf Port 3062 und setzt ebenfalls den Origin-Header, ohne eine interaktive Pangolin-Anmeldung vorzuschalten. Die bisherige Ressource auf Port 3061 behält ihre Anmeldung vollständig, ohne Bypass-Regeln. Bei der bestehenden GitHub App die zusätzliche exakte Callback-URL `https://NEUER_HOST/auth/mcp/callback` hinzufügen. Der neue Host stellt keine Verwaltungsoberfläche bereit; alte Client-Tokens bleiben am bisherigen Host verwendbar.

Automatisierte Tests verwenden synthetische Daten. Eine echte Abnahme der eigenen Pangolin-, GitHub- und ChatGPT-Konfiguration bleibt nach der Einrichtung erforderlich.
