# ChatGPT direkt über OAuth anbinden

Version 2.1 ergänzt einen getrennten Streamable-HTTP-Zugang für ChatGPT. Die bestehende Verwaltung bleibt hinter Pangolin-Anmeldung. Die neue MCP-Adresse nutzt GitHub OAuth, die serverseitige numerische Owner-ID und eine eigene Pangolin-Origin-Prüfung. Es gibt weiterhin genau eine GitHub OAuth App für die Instanz.

## 1. Dockge aktualisieren

Nach Veröffentlichung der neuen Images zuerst die Deployment-Dateien aus dem geprüften Release übernehmen. Ein reines Image-Update ergänzt keine neuen Compose-Variablen, Ports oder die eingebundene `nginx.conf`. Bestehende `.env`, `data/` und `compose.override.yaml` erhalten. Danach beide passenden Images in Dockge ziehen und neu bereitstellen.

Lokal in `.env` ergänzen, mit einer eigenen, separaten HTTPS-Domain:

```dotenv
MCP_PUBLIC_URL=https://mcp-vaults.example.invalid
MCP_ORIGIN_SECRET=HIER_LOKAL_ERZEUGTES_ZUFAELLIGES_GEHEIMNIS
MCP_CHATGPT_PORT=3062
```

Ein Geheimnis lokal erzeugen:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Den Wert weder in Git noch in ChatGPT eintragen. Die neue Compose-Datei ergänzt unter `services.app.environment`:

```yaml
MCP_PUBLIC_URL: ${MCP_PUBLIC_URL:-}
MCP_ORIGIN_SECRET: ${MCP_ORIGIN_SECRET:-}
```

Unter `services.gateway.ports` kommt diese zusätzliche Zeile hinzu:

```yaml
- ${MCP_BIND_IP:-127.0.0.1}:${MCP_CHATGPT_PORT:-3062}:8081
```

`PUBLIC_URL` und Port 3061 bleiben für die bestehende Verwaltung erhalten. Ohne beide neuen Variablen bleibt der direkte Zugang deaktiviert. Ein leerer oder schwacher Origin-Schlüssel lässt die aktivierte Anwendung nicht starten. Die App und Vault-Worker erhalten keine zusätzlichen veröffentlichten Ports.

## 2. Eine zusätzliche Pangolin-Ressource

Eine eigene Ressource für die neue MCP-Domain einrichten:

| Einstellung | Wert |
| --- | --- |
| Öffentlicher Host | Host aus `MCP_PUBLIC_URL` |
| Newt-Ziel bei Host-Netzwerk | `http://127.0.0.1:3062` |
| Host und Pfad | Ursprünglich weiterleiten, keine Präfixe entfernen |
| Request-Header | `X-Pangolin-Origin`, Wert von `MCP_ORIGIN_SECRET` |
| Header-Verhalten | Vom Proxy setzen und vorhandenen Client-Wert überschreiben |
| Interaktive Pangolin-Anmeldung | Für diese neue Maschinen-Ressource keine HTML-Anmeldeseite vorschalten |

Die **bestehende Verwaltungsressource auf Port 3061 behält ihre Pangolin-Anmeldung**. Keine pauschalen Bypass-Regeln auf dieser Ressource hinzufügen. Der neue Host stellt keine Verwaltungsoberfläche bereit. Auch ein manipulierter Host-Header öffnet keine Admin-Route über Port 3062.

Die komplette neue Domain muss für OAuth erreichbar sein, einschließlich `/.well-known/*`, `/authorize`, `/register`, `/token`, `/consent`, `/auth/mcp/callback` und `/mcp`. Auch Browser-Aufrufe der Zustimmungsseite brauchen den vom Proxy gesetzten Header. ChatGPT selbst muss keinen benutzerdefinierten Header senden.

Der Origin-Header ersetzt keine Nutzeranmeldung. MCP-Anfragen brauchen weiterhin ein gültiges OAuth-Token des konfigurierten GitHub-Owners. Alte `omcp_`-Client-Tokens gelten ausschließlich am bisherigen Zugang.

## 3. Bestehende GitHub OAuth App ergänzen

Bei derselben App eine zusätzliche **exakte** Callback-URL registrieren:

```text
https://mcp-vaults.example.invalid/auth/mcp/callback
```

Die bisherigen Callback-URLs unter `PUBLIC_URL` beibehalten. Wildcard-Matching ausgeschaltet lassen. GitHub unterstützt mehrere Callback-URLs für eine OAuth App, siehe [offizielle Ankündigung](https://github.blog/changelog/2026-08-14-multiple-redirect-uris-and-token-refresh-for-oauth-apps/).

Client ID, Client Secret und `GITHUB_OWNER_ID` auf dem Server bleiben unverändert. Keine zweite OAuth App pro Vault anlegen. Als GitHub-Nutzer ist ausschließlich die serverseitig hinterlegte numerische ID zugelassen.

## 4. In ChatGPT verbinden

In ChatGPT eine eigene MCP-App bzw. einen eigenen Connector anlegen, soweit diese Funktion im Konto verfügbar ist:

| Einstellung | Wert |
| --- | --- |
| MCP-Server-URL | `https://mcp-vaults.example.invalid/mcp` |
| Authentifizierung | OAuth |
| Client ID / Client Secret | Bei automatischer Registrierung leer lassen |

Die GitHub-App-Zugangsdaten gehören nur in die Serverkonfiguration. ChatGPT registriert seinen eigenen OAuth-Client über DCR oder seine veröffentlichte Client-Metadaten-URL. Die Anwendung erlaubt ausschließlich ChatGPT-Redirects unter `https://chatgpt.com/connector/oauth/*` sowie die exakte Adresse `https://chatgpt.com/connector_platform_oauth_redirect`. Keine fremden Callback-Domains hinzufügen.

Zugriff bestätigen, bei GitHub mit dem erlaubten Konto anmelden und die Verbindung abschließen. Der direkte Modus benötigt keinen lokalen STDIO-Bridge-Prozess und keinen zusätzlichen Tunnel. Die bisherige Bridge bleibt für kompatible lokale Clients verfügbar.

Der Owner sieht alle **explizit in dieser Instanz freigegebenen** Vaults. Das ist kein pro-Connector eingeschränkter Client-Token. Für enger begrenzte lokale Clients die vorhandene Bridge mit ausgewählten Client-Rechten verwenden. Vier lesende Werkzeuge bleiben verfügbar: `list_vaults`, `list_notes`, `read_note`, `search_notes`.

## Prüfung und Rücknahme

- `GET /healthz` auf dem neuen Host liefert Version und Build-Revision.
- `GET /.well-known/oauth-protected-resource/mcp` nennt die neue MCP-Adresse.
- `GET /.well-known/oauth-authorization-server` nennt ausschließlich den neuen Issuer und seine Endpunkte.
- MCP ohne OAuth-Token antwortet mit 401; Verwaltungsrouten am neuen Host mit 404.
- Eine direkt erreichte Origin-Adresse ohne den Proxy-Header lehnt geschützte Routen ab.

Beim Entfernen einer Vault-Freigabe verschwindet sie aus den erlaubten Owner-Werkzeugen. Alte Client-Tokens widerruft die GUI; das widerruft keine unabhängige OAuth-Verbindung. Für OAuth die Verbindung in ChatGPT trennen und die GitHub-Berechtigung bei Bedarf widerrufen. Für einen sofortigen vollständigen Stopp die neue Pangolin-Ressource deaktivieren oder den Stack stoppen.

Für eine Rücknahme die neue Ressource deaktivieren, beide `MCP_*`-Zugangsvariablen leeren und den Stack neu starten. Die bisherige Verwaltung und ihre verschlüsselten Zustände bleiben erhalten. Origin-Schlüssel bei Verdacht auf Offenlegung lokal erneuern und im Proxy ersetzen.

Automatisierte Tests verwenden synthetische Daten und prüfen OAuth, PKCE, Zustimmung, Owner- und Ingress-Grenzen. Ein erfolgreicher Test ersetzt keine echte Verbindung mit dem eigenen Pangolin-, GitHub- und ChatGPT-Konto.
