"""Escaped, responsive HTML. Form drafts are never replaced by background work."""
import html
import secrets
from starlette.responses import HTMLResponse

CSS = """
:root{color-scheme:dark;--bg:#11151b;--panel:#1c232d;--muted:#a9b5c4;--line:#344252;--accent:#9ee5c0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f2f5f8;font:16px/1.5 system-ui,sans-serif}
main{max-width:1000px;margin:42px auto;padding:0 24px}h1{font-size:32px;line-height:1.15;margin:8px 0 18px}h2{font-size:21px}
.muted,small{color:var(--muted)}.tag{text-transform:uppercase;letter-spacing:.1em;font-size:12px;color:var(--accent)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:24px;margin:20px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.full{grid-column:1/-1}
label{display:block;font-size:14px}input,select{font:inherit;background:#101720;color:inherit;border:1px solid #526174;border-radius:6px;padding:11px;width:100%;margin-top:6px}
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
    return out + '</div><div class="actions"><button type="button" class="secondary danger" data-remove>Freigabe entfernen</button><small>Eigener Container. Nur Lesen und Suchen.</small></div></section>'


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
    out += '<section class="panel"><h2>Verbindung</h2><p>MCP-Endpunkt: <code>' + esc(settings.public_url + '/mcp') + '</code></p><p>GitHub gilt zentral. Für weitere Vaults brauchst du keine weitere OAuth App.</p><small>Pangolin-Schutz bleibt aktiv. Die Bridge ergänzt Pangolin-Header vor dem Proxy und verwendet einen begrenzten Zugriffstoken. Direkte ChatGPT-Verbindungen mit eigenen Headern werden nicht vorausgesetzt.</small></section>'
    out += '<form method="post" action="/admin/save">' + token + f'<input type="hidden" name="revision" value="{esc(revision)}">'
    out += '<div id="vaults">' + ''.join(vault_row(v, settings.vault_parent) for v in config['vaults']) + '</div>'
    out += '<div class="actions"><button class="secondary" type="button" id="add-vault">+ Vault hinzufügen</button><button type="submit">Konfiguration speichern</button></div><p id="save-status" class="notice" role="status" hidden></p><p class="muted">Danach in Dockge neu einlesen und deployen. Entfernte Dienste ebenfalls entfernen. Die GUI ruft keinen Docker-Socket auf. <a href="/admin/" target="_blank" rel="noopener">Aktuellen Stand in zweitem Tab öffnen</a>.</p></form>'
    out += '<template id="vault-template">' + vault_row({}, settings.vault_parent) + '</template>'
    _, saved = state.config()
    client_draft = client_draft or {"label": "", "days": "30", "vault_ids": []}
    out += '<section class="panel"><h2>Client-Zugriff begrenzen</h2><p>Ein eigener Zugriffstoken pro Verbindung. Nur die ausgewählten Freigaben sind damit erreichbar. Neue oder ersetzte Vaults werden nicht automatisch freigegeben.</p><form method="post" action="/admin/clients">' + token
    out += '<div class="grid"><label>Client-Name<input name="client_label" maxlength="100" value="' + esc(client_draft['label']) + '" placeholder="Zum Beispiel D&D-Assistent"></label><label>Gültigkeit in Tagen<input name="days" inputmode="numeric" value="' + esc(client_draft['days']) + '"></label></div>'
    for vault in saved['vaults']:
        out += '<p><label><input type="checkbox" name="vault_id" value="' + esc(vault['id']) + '"' + (' checked' if vault['id'] in client_draft['vault_ids'] else '') + '>' + esc(vault['label']) + '</label></p>'
    out += '<div class="actions"><button>Zugriffstoken erstellen</button></div></form>'
    for client in state.clients():
        out += '<div class="client"><span>' + esc(client['label']) + (' · widerrufen' if client['revoked'] else ' · Ablauf: ' + str(client['expires'])) + '</span>'
        if not client['revoked']:
            out += '<form method="post" action="/admin/revoke">' + token + '<input type="hidden" name="client_id" value="' + esc(client['id']) + '"><button class="secondary danger">Widerrufen</button></form>'
        out += '</div>'
    out += '</section><p class="muted">Version 2.0.0 · Revision ' + str(current_revision) + ' · <a href="/admin/deployment">Erzeugte Konfiguration prüfen</a></p>'
    return document(out, status=status, script=JS)
