"""Interfaz web local sin dependencias externas."""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock, Thread
import time
from uuid import uuid4

from .adapters.postgres import validate_postgres
from .pipeline import design


HTML = r'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Modelador 3FN</title><style>
:root{font-family:system-ui,sans-serif;color:#192b32;background:#f4f6f5}*{box-sizing:border-box}body{margin:0}header{background:#123b42;color:white;padding:2rem max(2rem,calc((100vw - 1120px)/2))}header h1{margin:0 0 .4rem;font-size:2rem}header p{margin:0;color:#cce3e1}main{max-width:1120px;margin:2rem auto;padding:0 1.5rem;display:grid;grid-template-columns:1fr 1fr;gap:1.4rem}.card{background:white;border:1px solid #d7e1df;border-radius:14px;padding:1.4rem;box-shadow:0 3px 15px #173b4010}.wide{grid-column:1/-1}label{font-weight:700;display:block;margin-bottom:.5rem}textarea{width:100%;min-height:320px;border:1px solid #adc1bd;border-radius:8px;padding:1rem;font:inherit;resize:vertical}button,select{font:inherit}button{background:#087b72;color:white;border:0;border-radius:8px;padding:.8rem 1.2rem;font-weight:700;cursor:pointer}button:disabled{opacity:.5}select{padding:.7rem;border:1px solid #adc1bd;border-radius:8px;margin-right:.6rem}.row{display:flex;align-items:center;gap:.5rem;margin-top:1rem;flex-wrap:wrap}.muted{color:#58706f}pre{white-space:pre-wrap;overflow:auto;background:#eef4f3;padding:1rem;border-radius:8px;font-size:.86rem}table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{text-align:left;padding:.55rem;border-bottom:1px solid #dbe5e3}h2{margin-top:0;font-size:1.25rem}.ok{color:#087b72}.bad{color:#a33}details{border-top:1px solid #dbe5e3;padding:.7rem 0}@media(max-width:750px){main{grid-template-columns:1fr}.wide{grid-column:auto}}
</style></head><body><header><h1>Modelador autónomo 3FN</h1><p>Requisitos → agentes → dependencias → diccionario → PostgreSQL</p></header><main>
<section class="card"><h2>Nuevo diseño</h2><label for="req">Requisitos de negocio</label><textarea id="req" placeholder="Describa entidades, relaciones y reglas de negocio..."></textarea><div class="row"><select id="mode"><option value="multi">Sistema multiagente</option><option value="single">Un solo agente</option></select><button id="run">Diseñar</button></div><p id="status" class="muted">La ejecución puede tardar varios minutos con un modelo local.</p></section>
<section class="card"><h2>Resultado</h2><div id="overview" class="muted">Ingrese requisitos y ejecute el diseño.</div><div id="tables"></div></section>
<section class="card wide"><h2>Auditoría y trazabilidad</h2><div id="audit"></div><details><summary>Respuestas de los agentes</summary><pre id="trace"></pre></details></section>
<section class="card wide"><h2>Diccionario de datos</h2><div id="dictionary"></div></section>
<section class="card wide"><h2>DDL PostgreSQL</h2><pre id="ddl"></pre></section>
</main><script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function showResult(r){$('overview').innerHTML=r.status==='ok'?`<p class="ok"><b>Diseño generado</b> en ${esc(r.seconds)} s</p><p>Modelo: ${esc(r.model)} · PostgreSQL: ${esc(r.postgres?.status)}</p><p class="muted">Archivo: ${esc(r.saved_as)}</p>`:`<p class="bad">${esc(r.error)}</p>`;$('trace').textContent=JSON.stringify(r.trace,null,2);if(r.status==='ok'){const a=r.artifact;$('tables').innerHTML='<h3>Tablas</h3>'+a.tables.map(t=>`<p><b>${esc(t.name)}</b><br>${t.columns.map(esc).join(', ')}<br><small>PK: ${t.primary_key.map(esc).join(', ')}</small></p>`).join('');$('audit').innerHTML=`<p class="${a.audit.valid_3nf?'ok':'bad'}">3FN: ${a.audit.valid_3nf?'Cumple':'No cumple'} · Atributos faltantes: ${a.audit.missing_attributes.length} · Dependencias no preservadas: ${a.audit.unpreserved_dependencies.length}</p><p class="muted">${esc(a.audit.note)}</p>`+a.audit.tables.map(t=>`<p>${esc(t.table)}: claves candidatas ${esc(JSON.stringify(t.candidate_keys))}; violaciones ${esc(JSON.stringify(t.violations))}</p>`).join('');$('dictionary').innerHTML='<table><tr><th>Atributo</th><th>Tipo</th><th>Nulo</th><th>Descripción</th></tr>'+a.dictionary.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td>${c.nullable?'Sí':'No'}</td><td>${esc(c.description)}</td></tr>`).join('')+'</table>';$('ddl').textContent=a.ddl}else{$('tables').innerHTML='';$('audit').innerHTML='';$('dictionary').innerHTML='';$('ddl').textContent=''}}
$('run').onclick=async()=>{const requirements=$('req').value.trim();if(!requirements){$('status').textContent='Escriba los requisitos.';return}$('run').disabled=true;$('status').textContent='Iniciando diseño...';try{const response=await fetch('/api/design',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requirements,mode:$('mode').value})});const start=await response.json();if(!response.ok)throw Error(start.error||'No se pudo iniciar');while(true){await pause(1000);const job=await (await fetch('/api/jobs/'+start.job_id)).json();const last=job.events.at(-1);$('status').textContent=last?`${last.agent||'Modelo'}: ${last.event}${last.elapsed?' · '+last.elapsed+' s':''}${last.characters?' · '+last.characters+' caracteres':''}`:'Preparando consulta...';if(job.status==='finished'){showResult(job.result);break}}}catch(e){$('status').textContent='Error de conexión: '+e.message}finally{$('run').disabled=false}};
const originalShowResult=showResult;
showResult=function(r){originalShowResult(r);if(r.status==='ok'&&r.artifact?.coder_status==='fallback'){$('overview').insertAdjacentHTML('beforeend',`<p class="bad"><b>Advertencia:</b> el codificador falló. El DDL se generó con los tipos del diccionario. ${esc(r.artifact.coder_error)}</p>`)}};
</script></body></html>'''


def serve(host, port, output_dir, client):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs = {}
    lock = Lock()

    def run_job(job_id, requirements, mode):
        def progress(event):
            with lock:
                event = {**event, "agent": event.get("agent") or jobs[job_id].get("current_agent")}
                if event["event"] == "started":
                    jobs[job_id]["current_agent"] = event["agent"]
                jobs[job_id]["events"].append(event)
                jobs[job_id]["events"] = jobs[job_id]["events"][-100:]
        try:
            result = design(requirements, client, mode, progress=progress)
            if result["status"] == "ok":
                result["postgres"] = validate_postgres(result["artifact"]["ddl"])
            target = output_dir / f"web_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            result["saved_as"] = str(target)
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "trace": []}
        with lock:
            jobs[job_id]["status"] = "finished"
            jobs[job_id]["result"] = result

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/jobs/"):
                job_id = self.path.rsplit("/", 1)[-1]
                with lock:
                    job = jobs.get(job_id)
                    snapshot = {"status": job["status"], "events": list(job["events"]), "result": job.get("result")} if job else None
                if snapshot is None:
                    self.send_error(404)
                else:
                    self._json(200, snapshot)
                return
            if self.path != "/":
                self.send_error(404)
                return
            content = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            if self.path != "/api/design":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 100_000:
                    raise ValueError("La solicitud debe tener entre 1 y 100 000 bytes")
                data = json.loads(self.rfile.read(size))
                requirements = data["requirements"]
                mode = data.get("mode", "multi")
                if not isinstance(requirements, str) or not requirements.strip() or mode not in ("multi", "single"):
                    raise ValueError("Requisitos o modo inválidos")
                job_id = uuid4().hex
                with lock:
                    if len(jobs) >= 50:
                        for old in list(jobs):
                            if jobs[old]["status"] == "finished":
                                del jobs[old]
                                break
                    jobs[job_id] = {"status": "running", "events": [], "current_agent": None}
                Thread(target=run_job, args=(job_id, requirements, mode), daemon=True).start()
                self._json(202, {"job_id": job_id})
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def _json(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    print(f"Interfaz disponible en http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
