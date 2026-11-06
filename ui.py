"""Escaped, responsive HTML. Form drafts are never replaced by background work."""
import html
import secrets
from starlette.responses import HTMLResponse

APPLY_COMMAND = (
    "sudo docker compose -f compose.yaml -f compose.override.yaml config --quiet && "
    "sudo docker compose -f compose.yaml -f compose.override.yaml up -d --remove-orphans"
)
RECOVERY_COMMAND = "sudo docker compose -f compose.yaml up -d app gateway"

CSS = """
:root{color-scheme:dark;--bg:#11151b;--panel:#1c232d;--muted:#a9b5c4;--line:#344252;--accent:#9ee5c0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f2f5f8;font:16px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:42px auto;padding:0 24px}h1{font-size:32px;line-height:1.15;margin:8px 0 18px}h2{font-size:21px}
.muted,small{color:var(--muted)}.tag{text-transform:uppercase;letter-spacing:.1em;font-size:12px;color:var(--accent)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:24px;margin:20px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.full{grid-column:1/-1}
label{display:block;font-size:14px}input,select,textarea{font:inherit;background:#101720;color:inherit;border:1px solid #526174;border-radius:6px;padding:11px;width:100%;margin-top:6px}textarea{resize:vertical;font-family:monospace}
input[type=checkbox]{width:auto;margin:0 10px 0 0}input:focus,button:focus,a:focus{outline:2px solid var(--accent);outline-offset:3px}
small{display:block;margin-top:6px}button,.button{font:inherit;cursor:pointer;background:var(--accent);border:0;color:#13281e;border-radius:6px;padding:10px 16px;text-decoration:none;display:inline-block}
.secondary{background:transparent;border:1px solid #77879a;color:#f2f5f8}.danger{color:#ffb4b4;border-color:#915757}.actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:20px}
.notice{padding:16px;border:1px solid #5c9b7c;border-radius:8px;background:#162c23}.error{border-color:#c07b7b;background:#351f25}code{font-size:13px;overflow-wrap:anywhere}a{color:var(--accent)}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px}.client{display:flex;justify-content:space-between;gap:16px;border-top:1px solid var(--line);padding:14px 0}
@media(max-width:650px){.grid{grid-template-columns:1fr}main{margin:24px auto;padding:0 16px}.panel{padding:18px}h1{font-size:27px}.top{align-items:flex-start}}
"""
JS = """
const rows=document.getElementById('vaults');
const form=document.querySelector('form[action="/admin/save"]');
const message=document.getElementById('save-status');
let editRevision=0, dirty=false;
function changed(){editRevision++;dirty=true;}
rows.addEventListener('input',changed);
document.getElementById('add-vault').addEventListener('click',()=>{
 rows.append(document.getElementById('vault-template').content.cloneNode(true));
 rows.lastElementChild.querySelector('input').focus();changed();});
rows.addEventListener('click',e=>{if(e.target.matches('[data-remove]')&&confirm('Freigabe entfernen? Nach dem Deploy verliert sie ihren Zugriff.')){e.target.closest('.vault').remove();changed();}});
form.addEventListener('submit',async e=>{
 e.preventDefault();const submittedRevision=editRevision;
 const button=form.querySelector('button[type="submit"]');button.disabled=true;
 try{
  const sessionResponse=await fetch('/admin/session',{credentials:'same-origin',mode:'same-origin',redirect:'error',headers:{Accept:'application/json'}});
  const session=await sessionResponse.json();
  if(!sessionResponse.ok){message.hidden=false;message.className='notice error';message.textContent=session.message;return;}
  document.querySelectorAll('input[name=csrf]').forEach(input=>input.value=session.csrf);
  const response=await fetch('/admin/save',{method:'POST',body:new FormData(form),credentials:'same-origin',mode:'same-origin',redirect:'error',headers:{Accept:'application/json'}});
  const result=await response.json();message.hidden=false;message.className='notice'+(response.ok?'':' error');
  message.textContent=result.message;
  if(response.ok){form.querySelector('[name=revision]').value=String(result.revision);dirty=editRevision!==submittedRevision;
   if(dirty)message.textContent='Vorheriger Stand gespeichert. Neuere Eingaben sind noch ungespeichert.';}
 }catch(error){message.hidden=false;message.className='notice error';message.textContent='Speichern nicht bestätigt. Deine Eingaben bleiben erhalten. Bei abgelaufener Sitzung in einem zweiten Tab erneut anmelden.';}
 finally{button.disabled=false;}
});
document.addEventListener('submit',e=>{if(e.target!==form&&dirty&&!confirm('Ungespeicherte Vault-Eingaben verwerfen und fortfahren?'))e.preventDefault();});
document.addEventListener('click',e=>{const a=e.target.closest('a');if(a&&a.target!=='_blank'&&dirty&&!confirm('Ungespeicherte Vault-Eingaben verwerfen und Seite verlassen?'))e.preventDefault();});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
document.getElementById('copy-apply').addEventListener('click',async()=>{
 const field=document.getElementById('apply-command');
 const status=document.getElementById('copy-status');
 try{
  await navigator.clipboard.writeText(field.value);
  status.textContent='Kopiert. Im Stack-Verzeichnis auf dem TrueNAS-Host ausführen. Nur gespeicherte Änderungen werden angewendet.';
 }catch(error){
  field.focus();field.select();
  status.textContent='Automatisches Kopieren nicht möglich. Markierten Befehl manuell kopieren.';
 }
});
"""


def esc(value):
    return html.escape(str(value), quote=True)


def document(body, status=200, script=""):
    nonce = secrets.token_urlsafe(18)
    response = HTMLResponse('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Obsidian MCP</title>' + f'<style nonce="{nonce}">{CSS}</style></head><body><main>{body}</main>' + (f'<script nonce="{nonce}">{script}</script>' if script else '') + '</body></html>', status_code=status)
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Content-Security-Policy": f"default-src 'none'; connect-src 'self'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
    return response


def csrf_field(csrf):
    return f'<input type="hidden" name="csrf" value="{esc(csrf)}">'


def vault_row(item, parent):
    fields = [("name", "URL-Name", "llm oder strahd"), ("label", "Anzeigename", "Gedächtnis oder Kampagne"),
              ("directory", "Vault-Verzeichnis auf dem Server", str(parent) + "/")]
    out = '<section class="panel vault"><div class="grid">'
    for key, label, placeholder in fields:
        full = ' class="full"' if key == "directory" else ""
        # Validate on the server so invalid drafts remain visible and editable.
        out += f'<label{full}>{label}<input name="vault_{key}" value="{esc(item.get(key, ""))}" placeholder="{esc(placeholder)}" autocomplete="off"></label>'
    prefixes = item.get('write_paths', [])
    raw = prefixes if isinstance(prefixes, str) else '\n'.join(prefixes)
    out += '<label class="full">Erlaubte Schreibordner<textarea name="vault_write_paths" rows="3" spellcheck="false" placeholder="Leer lassen für Lesezugriff">' + esc(raw) + '</textarea></label>'
    return out + '</div><small>Ein relativer Ordner pro Zeile, ohne abschließenden Schrägstrich. / erlaubt den gesamten Vault. Leer bedeutet nur lesen. Nach dem Speichern die Konfiguration anwenden. Änderungen und Verschiebungen erhalten vorherige Fassungen im Vault-Ordner .mcp-history.</small><div class="actions"><button type="button" class="secondary danger" data-remove>Freigabe entfernen</button></div></section>'


def dashboard(settings, state, csrf, notice="", status=200, draft=None, revision=None, raw_token=None, client_draft=None):
    current_revision, config = state.config()
    if draft is not None:
        config = {"vaults": draft}
    revision = current_revision if revision is None else revision
    token = csrf_field(csrf)
    out = '<div class="top"><div><div class="tag">Obsidian MCP · Verwaltung</div><h1>Vault-Freigaben</h1></div><form method="post" action="/logout">' + token + '<button class="secondary">Abmelden</button></form></div>'
    out += '<p class="muted">Eine GitHub-Anmeldung. Getrennte Vault-Dateirechte. Updates über fertige Container-Images.</p>'
    if notice:
        out += f'<p role="status" class="notice{" error" if status >= 400 else ""}">{esc(notice)}</p>'
    if raw_token:
        out += '<section class="panel"><h2>Zugriffstoken einmalig kopieren</h2><p>Dieses Token wird nur jetzt angezeigt. Lokal in der Bridge hinterlegen. Nicht in Git, Screenshots oder Chat übernehmen.</p><label>Vault-Zugriffstoken<input readonly autocomplete="off" value="' + esc(raw_token) + '"></label></section>'
    out += '<section class="panel"><h2>Verbindung</h2><p>MCP-Endpunkt: <code>' + esc((settings.mcp_public_url or settings.public_url) + '/mcp') + '</code></p><p>GitHub gilt zentral. Für weitere Vaults brauchst du keine weitere OAuth App.</p><small>Diese Adresse gehört zur MCP-Anwendung, nicht zur separaten Obsidian-Weboberfläche. ' + ('ChatGPT nutzt OAuth. Die Verwaltung behält ihre Pangolin-Anmeldung.' if settings.mcp_public_url else 'Die Bridge ergänzt Pangolin-Header vor dem Proxy und verwendet einen begrenzten Zugriffstoken.') + '</small></section>'
    out += '<form method="post" action="/admin/save">' + token + f'<input type="hidden" name="revision" value="{esc(revision)}">'
    out += '<div id="vaults">' + ''.join(vault_row(v, settings.vault_parent) for v in config['vaults']) + '</div>'
    out += '<div class="actions"><button class="secondary" type="button" id="add-vault">+ Vault hinzufügen</button><button type="submit">Konfiguration speichern</button></div><p id="save-status" class="notice" role="status" hidden></p><p class="muted">Danach in Dockge neu einlesen und deployen. Entfernte Dienste ebenfalls entfernen. Die GUI ruft keinen Docker-Socket auf. <a href="/admin/" target="_blank" rel="noopener">Aktuellen Stand in zweitem Tab öffnen</a>.</p></form>'
    out += '<template id="vault-template">' + vault_row({}, settings.vault_parent) + '</template>'
    out += '<section class="panel"><h2>Startfehler durch einen Vault-Ordner beheben</h2><p>Auf dem Docker-Host im bestehenden Stack-Verzeichnis nur die Verwaltung starten. Verwende denselben Compose-Projektnamen wie Dockge. Die erzeugten Vault-Mounts werden dabei nicht geladen.</p><label>Wiederherstellungsbefehl<textarea id="recovery-command" readonly rows="2" spellcheck="false">' + esc(RECOVERY_COMMAND) + '</textarea></label><small>Danach hier den absoluten Serverpfad korrigieren, speichern und die gespeicherte Konfiguration anwenden. Name, Anzeigename und Ordnerpfad sind unterschiedliche Felder. Keine Vault-URL als Ordnerpfad verwenden. Vorhandene Worker werden durch diesen Befehl nicht gestoppt. Keine Daten oder Freigaben werden gelöscht.</small></section>'
    out += '<section class="panel"><h2>Gespeicherte Konfiguration anwenden</h2><p>Erst speichern. Dann auf dem TrueNAS-Host per SSH in das Dockge-Stack-Verzeichnis wechseln, das <code>compose.yaml</code>, <code>compose.override.yaml</code> und <code>.env</code> enthält. Dort diesen Befehl ausführen:</p><label for="apply-command">Befehl für die TrueNAS-Shell</label><textarea id="apply-command" readonly rows="5" spellcheck="false">' + esc(APPLY_COMMAND) + '</textarea><div class="actions"><button type="button" id="copy-apply">Befehl kopieren</button></div><p id="copy-status" role="status" aria-live="polite"></p><small>Prüft die Compose-Konfiguration und startet oder aktualisiert die Dienste. Entfernt verwaiste Dienste dieses Compose-Projekts, auch entfernte Vault-Worker. Verwende denselben Projektnamen wie Dockge. Ungespeicherte Eingaben bleiben hier erhalten. Kein Image-Update, kein Docker-Socket und keine Befehlsausführung durch die App. Alternativ in Dockge neu einlesen und deployen.</small></section>'
    out += '<section class="panel"><h2>Pangolin sicher einrichten</h2><ol><li>HTTPS-Ressource zur Newt-Site anlegen. Bei Newt im Host-Netz und unverändertem Gateway-Port als Ziel <code>http://127.0.0.1:3061</code> verwenden. Den ganzen Host weiterleiten, keine Pfad-Präfixe entfernen.</li><li>Pangolin-Anmeldung aktiviert lassen. Die Verwaltung unter <code>/admin/</code> verlangt danach zusätzlich den freigegebenen GitHub-Account.</li><li>Für die Bridge in der Ressource einen befristeten Link mit Zugangstoken erstellen. Lokal als <code>PANGOLIN_TOKEN_ID</code> und <code>PANGOLIN_ACCESS_TOKEN</code> hinterlegen. Die Bridge sendet <code>P-Access-Token-Id</code> und <code>P-Access-Token</code>.</li><li>Hier einen auf die benötigten Vaults begrenzten Client-Token erstellen und separat als <code>MCP_CLIENT_TOKEN</code> in der Bridge hinterlegen. Keine Tokens in URLs, Git oder Chat kopieren.</li></ol><details><summary>Warum kein Auth-Bypass für /mcp/?</summary><p>Der Endpunkt lautet <code>/mcp</code>. Eine Pangolin-Regel „Bypass Auth“ entfernt dort die äußere Authentifizierung. Die App verlangt weiterhin einen gültigen MCP-Token; eine Browser-Sitzung genügt nicht. Eine Ausnahme nur für <code>/mcp/</code> ist außerdem keine vollständige OAuth-Einrichtung, da Discovery und OAuth eigene Pfade nutzen. Für diese Installation bleibt Pangolin auch vor MCP aktiv. Die Header-Bridge ermöglicht Zugriff ohne interaktive Pangolin-Anmeldung. Keine pauschalen Ausnahmen für <code>/*</code>, <code>/admin</code> oder <code>/auth</code> einrichten.</p></details><p><a href="https://docs.pangolin.net/manage/access-control/links" target="_blank" rel="noopener noreferrer">Pangolin: Zugangstoken und Header</a></p></section>'
    _, saved = state.config()
    client_draft = client_draft or {"label": "", "days": "30", "vault_ids": [], "write_vault_ids": []}
    out += '<section class="panel"><h2>Client-Zugriff begrenzen</h2><p>Ein eigener Zugriffstoken pro Verbindung. Nur die ausgewählten Freigaben sind damit erreichbar. Neue oder ersetzte Vaults werden nicht automatisch freigegeben.</p><form method="post" action="/admin/clients">' + token
    out += '<div class="grid"><label>Client-Name<input name="client_label" maxlength="100" value="' + esc(client_draft['label']) + '" placeholder="Zum Beispiel D&D-Assistent"></label><label>Gültigkeit in Tagen<input name="days" inputmode="numeric" value="' + esc(client_draft['days']) + '"></label></div>'
    for vault in saved['vaults']:
        out += '<p><label><input type="checkbox" name="vault_id" value="' + esc(vault['id']) + '"' + (' checked' if vault['id'] in client_draft['vault_ids'] else '') + '>' + esc(vault['label']) + '</label></p>'
    for vault in saved['vaults']:
        if vault.get('write_paths'):
            out += '<p><label><input type="checkbox" name="write_vault_id" value="' + esc(vault['id']) + '"' + (' checked' if vault['id'] in client_draft.get('write_vault_ids', []) else '') + '>Zusätzlich schreiben: ' + esc(vault['label']) + '</label></p>'
    out += '<div class="actions"><button>Zugriffstoken erstellen</button></div></form>'
    for client in state.clients():
        out += '<div class="client"><span>' + esc(client['label']) + (' · widerrufen' if client['revoked'] else ' · Ablauf: ' + str(client['expires'])) + '</span>'
        if not client['revoked']:
            out += '<form method="post" action="/admin/revoke">' + token + '<input type="hidden" name="client_id" value="' + esc(client['id']) + '"><button class="secondary danger">Widerrufen</button></form>'
        out += '</div>'
    out += '</section><p class="muted">Version 2.2.0 · Revision ' + str(current_revision) + ' · <a href="/admin/deployment">Erzeugte Konfiguration prüfen</a></p>'
    return document(out, status=status, script=JS)
