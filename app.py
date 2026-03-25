from flask import Flask, request, render_template_string
import requests
import base64
import re
import json
import os
import zlib

app = Flask(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def github_headers(extra=None):
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    if extra:
        h.update(extra)
    return h


def detectar_tipo(url):
    url = url.strip().rstrip("/")
    partes = [p for p in url.replace("https://github.com/","").replace("http://github.com/","").split("/") if p]
    if len(partes) == 1:
        return "perfil", partes[0], None
    elif len(partes) >= 2:
        return "repo", partes[0], partes[1]
    return None, None, None


def get_perfil_info(username):
    user = requests.get(f"https://api.github.com/users/{username}", headers=github_headers()).json()
    if user.get("message") == "Not Found":
        return None
    all_repos = []
    page = 1
    while True:
        r = requests.get(f"https://api.github.com/users/{username}/repos?per_page=100&page={page}&sort=pushed", headers=github_headers()).json()
        if not isinstance(r, list) or not r: break
        all_repos.extend(r)
        if len(r) < 100: break
        page += 1
    events = requests.get(f"https://api.github.com/users/{username}/events/public?per_page=10", headers=github_headers()).json()
    es_org = user.get("type") == "Organization"
    miembros = []
    if es_org:
        m = requests.get(f"https://api.github.com/orgs/{username}/members?per_page=6", headers=github_headers()).json()
        if isinstance(m, list): miembros = m
    return {"user": user, "repos": all_repos, "events": events if isinstance(events, list) else [], "miembros": miembros, "es_org": es_org}


def get_repo_info(owner, repo):
    base = f"https://api.github.com/repos/{owner}/{repo}"
    info = requests.get(base, headers=github_headers()).json()
    if info.get("message") == "Not Found":
        return None
    languages    = requests.get(f"{base}/languages", headers=github_headers()).json()
    commits      = requests.get(f"{base}/commits?per_page=10", headers=github_headers()).json()
    contributors = requests.get(f"{base}/contributors?per_page=5", headers=github_headers()).json()
    contents     = requests.get(f"{base}/contents", headers=github_headers()).json()
    releases     = requests.get(f"{base}/releases?per_page=3", headers=github_headers()).json()
    topics_res   = requests.get(base, headers=github_headers({"Accept": "application/vnd.github.mercy-preview+json"})).json()

    archivos = [f["name"] for f in contents if isinstance(contents, list)]
    topics   = topics_res.get("topics", [])

    dependencias = ""
    if "requirements.txt" in archivos:
        r = requests.get(f"{base}/contents/requirements.txt", headers=github_headers()).json()
        dependencias = base64.b64decode(r["content"]).decode("utf-8")
    elif "package.json" in archivos:
        r = requests.get(f"{base}/contents/package.json", headers=github_headers()).json()
        dependencias = base64.b64decode(r["content"]).decode("utf-8")

    readme = ""
    for nr in ["README.md", "readme.md", "README.rst", "README.txt", "README"]:
        if nr in archivos:
            r = requests.get(f"{base}/contents/{nr}", headers=github_headers()).json()
            readme = base64.b64decode(r["content"]).decode("utf-8")
            break

    extensiones_legibles = {
        ".py", ".js", ".ts", ".go", ".rb", ".java", ".rs", ".php",
        ".jsx", ".tsx", ".css", ".html", ".md", ".yml", ".yaml",
        ".toml", ".sh", ".sql", ".cfg", ".ini", ".json", ".xml",
        ".graphql", ".prisma", ".swift", ".kt",
    }
    carpetas_clave = [
        "src", "app", "api", "routes", "controllers", "models", "views",
        "middleware", "services", "utils", "helpers", "lib", "core",
        "auth", "login", "config", "database", "db", "tests", "test",
        "components", "pages", "hooks",
    ]

    archivos_contenido = {}

    def leer_contenido(item):
        fname = item.get("name", "")
        ext = "." + fname.split(".")[-1].lower() if "." in fname else ""
        if ext in extensiones_legibles and item.get("type") == "file":
            try:
                dl = item.get("download_url", "")
                if dl:
                    r = requests.get(dl, timeout=5)
                    if r.ok:
                        return r.text[:4000]
            except:
                pass
        return None

    def leer_directorio(path, nivel=0):
        if nivel > 2: return
        try:
            items = requests.get(f"{base}/contents/{path}", headers=github_headers()).json()
            if not isinstance(items, list): return
            for item in items:
                nombre = item.get("name", "")
                ruta_completa = f"{path}/{nombre}"
                if item.get("type") == "file":
                    contenido = leer_contenido(item)
                    if contenido and ruta_completa not in archivos_contenido:
                        archivos_contenido[ruta_completa] = contenido
                elif item.get("type") == "dir" and nivel < 2:
                    if nivel == 0 or nombre.lower() in carpetas_clave:
                        leer_directorio(ruta_completa, nivel + 1)
        except:
            pass

    if isinstance(contents, list):
        for item in contents:
            if item.get("type") == "file":
                contenido = leer_contenido(item)
                if contenido:
                    archivos_contenido[item.get("name", "")] = contenido

    if isinstance(contents, list):
        for item in contents:
            if item.get("type") == "dir":
                nombre = item.get("name", "").lower()
                if nombre in carpetas_clave:
                    leer_directorio(item.get("name", ""), nivel=1)

    codigo_principal = ""
    lang = info.get("language", "")
    candidatos = {
        "Python":     ["app.py", "main.py", "server.py", "run.py", "__init__.py"],
        "JavaScript": ["index.js", "app.js", "server.js", "main.js"],
        "TypeScript": ["index.ts", "app.ts", "main.ts"],
        "Go":         ["main.go"],
        "Ruby":       ["app.rb", "main.rb"],
        "Java":       ["Main.java", "App.java"],
    }
    for c in candidatos.get(lang, []):
        if c in archivos_contenido:
            codigo_principal = archivos_contenido[c]
            break

    return {
        "info": info, "languages": languages, "commits": commits,
        "contributors": contributors, "contents": archivos,
        "dependencias": dependencias, "readme": readme,
        "releases": releases if isinstance(releases, list) else [],
        "topics": topics, "codigo_principal": codigo_principal,
        "archivos_contenido": archivos_contenido,
    }


def plantuml_encode(text):
    data = text.encode('utf-8')
    compressed = zlib.compress(data, 9)
    compressed = compressed[2:-4]
    b64chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
    def encode3(b1, b2, b3):
        c1 = b1 >> 2
        c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
        c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
        c4 = b3 & 0x3F
        return b64chars[c1] + b64chars[c2] + b64chars[c3] + b64chars[c4]
    data_bytes = list(compressed)
    while len(data_bytes) % 3 != 0:
        data_bytes.append(0)
    result = ""
    for i in range(0, len(data_bytes), 3):
        result += encode3(data_bytes[i], data_bytes[i + 1], data_bytes[i + 2])
    return "https://www.plantuml.com/plantuml/svg/" + result


def analizar_codigo_para_uml(archivos_contenido, lang):
    clases = {}; imports = {}; funciones = {}; relaciones = []
    for archivo, contenido in archivos_contenido.items():
        ext = archivo.split('.')[-1].lower() if '.' in archivo else ''
        lineas = contenido.splitlines()
        if ext == 'py':
            clase_actual = None; indent_clase = 0
            for linea in lineas:
                stripped = linea.strip(); indent = len(linea) - len(linea.lstrip())
                m = re.match(r'^class\s+(\w+)(?:\(([^)]*)\))?:', stripped)
                if m:
                    clase_actual = m.group(1); herencia = m.group(2) or ''
                    indent_clase = indent
                    clases[clase_actual] = {'attrs': [], 'methods': [], 'herencia': herencia}
                    for padre in herencia.split(','):
                        padre = padre.strip()
                        if padre and padre not in ('object', 'Exception', 'BaseException'):
                            relaciones.append((clase_actual, padre, 'extends'))
                elif clase_actual and re.match(r'^def\s+(\w+)\(', stripped) and indent > indent_clase:
                    mname = re.match(r'^def\s+(\w+)\(', stripped).group(1)
                    clases[clase_actual]['methods'].append(mname)
                elif clase_actual and re.match(r'^self\.(\w+)\s*=', stripped) and indent > indent_clase:
                    attr = re.match(r'^self\.(\w+)', stripped).group(1)
                    if attr not in clases[clase_actual]['attrs']:
                        clases[clase_actual]['attrs'].append(attr)
                elif clase_actual and indent <= indent_clase and stripped and not stripped.startswith('#'):
                    clase_actual = None
                m_imp = re.match(r'^(?:from\s+(\S+)\s+)?import\s+(.+)', stripped)
                if m_imp:
                    modulo = m_imp.group(1) or m_imp.group(2).split()[0]
                    imports.setdefault(archivo, []).append(modulo.split('.')[0])
            for linea in lineas:
                m = re.match(r'^def\s+(\w+)\(', linea.strip())
                if m: funciones.setdefault(archivo, []).append(m.group(1))
        elif ext in ('js', 'ts', 'jsx', 'tsx'):
            clase_actual = None
            for linea in lineas:
                stripped = linea.strip()
                m = re.match(r'(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?', stripped)
                if m:
                    clase_actual = m.group(1); herencia = m.group(2) or ''
                    clases[clase_actual] = {'attrs': [], 'methods': [], 'herencia': herencia}
                    if herencia: relaciones.append((clase_actual, herencia, 'extends'))
                elif clase_actual and re.match(r'(?:async\s+)?(?:static\s+)?(\w+)\s*\(', stripped):
                    mname = re.match(r'(?:async\s+)?(?:static\s+)?(\w+)\s*\(', stripped).group(1)
                    if mname not in ('if', 'for', 'while', 'switch', 'catch', 'constructor'):
                        clases[clase_actual]['methods'].append(mname)
                elif clase_actual and re.match(r'this\.(\w+)\s*=', stripped):
                    attr = re.match(r'this\.(\w+)', stripped).group(1)
                    if attr not in clases[clase_actual]['attrs']:
                        clases[clase_actual]['attrs'].append(attr)
                m_imp = re.match(r"(?:import|require)\s*[({'\"]?\s*['\"]?([^'\"}\s]+)", stripped)
                if m_imp: imports.setdefault(archivo, []).append(m_imp.group(1).split('/')[0])
                m_fn = re.match(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', stripped)
                if m_fn: funciones.setdefault(archivo, []).append(m_fn.group(1))
    return {'clases': clases, 'imports': imports, 'funciones': funciones, 'relaciones': relaciones}


def generar_uml_clases(analisis, nombre_repo):
    clases = analisis['clases']; relaciones = analisis['relaciones']
    if not clases: return None, None
    lineas = ['@startuml', f'title Class Diagram — {nombre_repo}', '',
        'skinparam classBackgroundColor #1c2128', 'skinparam classBorderColor #388bfd',
        'skinparam classArrowColor #8b949e', 'skinparam classFontColor #e6edf3',
        'skinparam classAttributeFontColor #8b949e', 'skinparam backgroundColor #0d1117',
        'skinparam defaultFontName Arial', '']
    for nombre, info in list(clases.items())[:12]:
        lineas.append(f'class {nombre} {{')
        for attr in info['attrs'][:6]: lineas.append(f'  +{attr}')
        if info['attrs'] and info['methods']: lineas.append('  --')
        for method in info['methods'][:8]: lineas.append(f'  +{method}()')
        lineas.append('}'); lineas.append('')
    for a, b, tipo in relaciones[:10]:
        if a in clases:
            if tipo == 'extends': lineas.append(f'{a} --|> {b}')
            elif tipo == 'implements': lineas.append(f'{a} ..|> {b}')
            else: lineas.append(f'{a} --> {b}')
    lineas += ['', '@enduml']
    texto = '\n'.join(lineas)
    return texto, plantuml_encode(texto)


def generar_uml_componentes(analisis, nombre_repo, archivos_contenido):
    imports = analisis['imports']
    if not imports: return None, None
    archivos = list(imports.keys())[:10]
    modulos_externos = set()
    for mods in imports.values():
        for m in mods:
            if m and not m.startswith('.'): modulos_externos.add(m[:15])
    lineas = ['@startuml', f'title Component Diagram — {nombre_repo}', '',
        'skinparam componentBackgroundColor #1c2128', 'skinparam componentBorderColor #388bfd',
        'skinparam componentArrowColor #8b949e', 'skinparam componentFontColor #e6edf3',
        'skinparam backgroundColor #0d1117', 'skinparam defaultFontName Arial', '']
    lineas.append(f'package "{nombre_repo}" {{')
    for archivo in archivos:
        nc = archivo.replace('/', '_').replace('.', '_'); nd = archivo.split('/')[-1][:20]
        lineas.append(f'  component [{nd}] as {nc}')
    lineas.append('}'); lineas.append('')
    deps_comunes = list(modulos_externos)[:8]
    if deps_comunes:
        lineas.append('package "Dependencies" {')
        for dep in deps_comunes:
            dep_l = re.sub(r'\W', '_', dep); lineas.append(f'  component [{dep}] as dep_{dep_l}')
        lineas.append('}'); lineas.append('')
    for archivo in archivos[:6]:
        nc = archivo.replace('/', '_').replace('.', '_')
        for mod in imports.get(archivo, [])[:3]:
            mod_l = re.sub(r'\W', '_', mod)
            if f'dep_{mod_l}' in '\n'.join(lineas): lineas.append(f'{nc} --> dep_{mod_l}')
    lineas += ['', '@enduml']
    texto = '\n'.join(lineas)
    return texto, plantuml_encode(texto)


def generar_uml_secuencia(analisis, nombre_repo, archivos_contenido):
    funciones = analisis['funciones']; clases = analisis['clases']
    candidatos = ['app.py', 'main.py', 'index.js', 'server.js', 'main.go', 'app.rb']
    archivo_principal = None
    for c in candidatos:
        if c in archivos_contenido: archivo_principal = c; break
    if not archivo_principal and archivos_contenido:
        archivo_principal = list(archivos_contenido.keys())[0]
    lineas = ['@startuml', f'title Sequence Diagram — {nombre_repo}', '',
        'skinparam sequenceArrowColor #388bfd', 'skinparam sequenceParticipantBackgroundColor #1c2128',
        'skinparam sequenceParticipantBorderColor #388bfd', 'skinparam sequenceFontColor #e6edf3',
        'skinparam backgroundColor #0d1117', 'skinparam defaultFontName Arial', '']
    lineas.append('actor User'); lineas.append('participant "App" as App')
    participantes = list(clases.keys())[:4]
    for p in participantes: lineas.append(f'participant "{p}" as {p}')
    if not participantes:
        lineas.append('participant "Service" as Service')
        lineas.append('participant "Database" as DB')
    lineas.append(''); lineas.append('User -> App: request'); lineas.append('activate App'); lineas.append('')
    fns = funciones.get(archivo_principal, [])[:6] if archivo_principal else []
    if fns:
        for i, fn in enumerate(fns):
            if participantes:
                t = participantes[i % len(participantes)]
                lineas += [f'App -> {t}: {fn}()', f'activate {t}', f'{t} --> App: result', f'deactivate {t}']
            else:
                lineas += [f'App -> Service: {fn}()', 'Service --> App: result']
    else:
        lineas += ['App -> Service: process()', 'Service -> DB: query()', 'DB --> Service: data', 'Service --> App: response']
    lineas += ['', 'App --> User: response', 'deactivate App', '', '@enduml']
    texto = '\n'.join(lineas)
    return texto, plantuml_encode(texto)


def generar_uml_casos_uso(analisis, nombre_repo, archivos_contenido):
    rutas = []; actores = set()
    for archivo, contenido in archivos_contenido.items():
        for linea in contenido.splitlines():
            stripped = linea.strip()
            m = re.match(r"@(?:app|router)\.(?:route|get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]", stripped)
            if m:
                metodo = 'POST' if '.post(' in stripped else ('PUT' if '.put(' in stripped else ('DELETE' if '.delete(' in stripped else 'GET'))
                rutas.append((metodo, m.group(1)))
            m2 = re.match(r"(?:app|router)\.(?:get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]", stripped)
            if m2:
                met = re.search(r'\.(get|post|put|delete|patch)\(', stripped)
                rutas.append((met.group(1).upper() if met else 'GET', m2.group(1)))
            if any(k in stripped.lower() for k in ['login', 'auth', 'token', 'jwt']): actores.add('AuthUser')
            if any(k in stripped.lower() for k in ['admin', 'staff', 'superuser']): actores.add('Admin')
    if not actores: actores = {'User'}
    lineas = ['@startuml', f'title Use Case Diagram — {nombre_repo}', '',
        'skinparam actorBackgroundColor #1c2128', 'skinparam actorBorderColor #388bfd',
        'skinparam usecaseBackgroundColor #1c2128', 'skinparam usecaseBorderColor #388bfd',
        'skinparam usecaseFontColor #e6edf3', 'skinparam actorFontColor #e6edf3',
        'skinparam backgroundColor #0d1117', 'skinparam defaultFontName Arial', '']
    for actor in actores: lineas.append(f'actor {actor}')
    lineas.append(''); lineas.append(f'rectangle "{nombre_repo}" {{')
    if rutas:
        for metodo, ruta in rutas[:10]:
            nc = ruta.replace('/', ' ').strip().replace('<', '').replace('>', '') or 'index'
            nc = f"{metodo} {nc}"[:30]; id_c = re.sub(r'\W', '_', nc)
            lineas.append(f'  usecase "{nc}" as {id_c}')
    else:
        for caso in ['View info', 'Search', 'Authenticate', 'Manage data', 'Export']:
            id_c = re.sub(r'\W', '_', caso); lineas.append(f'  usecase "{caso}" as {id_c}')
    lineas.append('}'); lineas.append('')
    casos_ids = re.findall(r'as (\w+)', '\n'.join(lineas))
    for actor in actores:
        for cid in casos_ids[:6]: lineas.append(f'{actor} --> {cid}')
    lineas += ['', '@enduml']
    texto = '\n'.join(lineas)
    return texto, plantuml_encode(texto)


def construir_seccion_uml(data):
    archivos_contenido = data.get('archivos_contenido', {})
    nombre_repo = data['info'].get('name', 'repo')
    lang = data['info'].get('language', '')
    if not archivos_contenido: return ''
    analisis = analizar_codigo_para_uml(archivos_contenido, lang)
    _, url_clases      = generar_uml_clases(analisis, nombre_repo)
    _, url_componentes = generar_uml_componentes(analisis, nombre_repo, archivos_contenido)
    _, url_secuencia   = generar_uml_secuencia(analisis, nombre_repo, archivos_contenido)
    _, url_casos       = generar_uml_casos_uso(analisis, nombre_repo, archivos_contenido)

    def card_uml(titulo_es, titulo_en, url):
        if not url: return ''
        return f"""<div class="card"><div class="card-header"><span class="lang-content active" data-l="es">{titulo_es}</span><span class="lang-content" data-l="en">{titulo_en}</span><span class="label">PlantUML</span></div><div class="card-body" style="padding:12px;text-align:center"><img src="{url}" alt="{titulo_en}" style="max-width:100%;border-radius:6px" onerror="this.parentElement.innerHTML='<span style=color:var(--text-muted);font-size:12px>No se pudo generar el diagrama</span>'"></div></div>"""

    cards = [
        card_uml('Diagrama de Clases', 'Class Diagram', url_clases),
        card_uml('Componentes', 'Component Diagram', url_componentes),
        card_uml('Secuencia', 'Sequence Diagram', url_secuencia),
        card_uml('Casos de Uso', 'Use Case Diagram', url_casos),
    ]
    cards = [c for c in cards if c]
    if not cards: return ''
    grid = ''
    for i in range(0, len(cards), 2):
        par = cards[i:i+2]
        if len(par) == 2: grid += f'<div class="grid-2">{"".join(par)}</div>'
        else: grid += f'<div class="grid-1">{par[0]}</div>'
    return f"""
    <div class="section-divider">
      <span class="lang-inline active" data-l="es">Diagramas UML</span>
      <span class="lang-inline" data-l="en">UML Diagrams</span>
    </div>{grid}"""


def generar_explicacion(data):
    info=data["info"]; languages=data["languages"]; contributors=data["contributors"]
    commits=data["commits"]; dependencias=data["dependencias"]
    nombre=info.get("name","this project"); descripcion=info.get("description","")
    estrellas=info.get("stargazers_count",0); forks=info.get("forks_count",0)
    creado=info.get("created_at","")[:4]; actualizado=info.get("updated_at","")[:10]
    langs=", ".join(languages.keys()) if languages else "unknown"
    lineas_es,lineas_en=[],[]
    lineas_es.append(f"<strong>{nombre}</strong> es un proyecto desarrollado en <strong>{langs}</strong>.")
    lineas_en.append(f"<strong>{nombre}</strong> is a project built with <strong>{langs}</strong>.")
    if descripcion:
        lineas_es.append(f"Su propósito: {descripcion}."); lineas_en.append(f"Its purpose: {descripcion}.")
    if dependencias:
        deps=dependencias.strip()[:180]
        lineas_es.append(f"Dependencias: <code>{deps}</code>."); lineas_en.append(f"Dependencies: <code>{deps}</code>.")
    if estrellas>1000:
        lineas_es.append(f"Popular con <strong>{estrellas:,}</strong> estrellas."); lineas_en.append(f"Popular with <strong>{estrellas:,}</strong> stars.")
    elif estrellas>0:
        lineas_es.append(f"Tiene <strong>{estrellas}</strong> estrellas."); lineas_en.append(f"Has <strong>{estrellas}</strong> stars.")
    if forks>100:
        lineas_es.append(f"Con <strong>{forks}</strong> forks."); lineas_en.append(f"With <strong>{forks}</strong> forks.")
    if isinstance(contributors,list) and contributors:
        top=contributors[0].get("login","")
        if top:
            lineas_es.append(f"Contribuidor principal: <strong>{top}</strong>."); lineas_en.append(f"Main contributor: <strong>{top}</strong>.")
    if isinstance(commits,list) and commits:
        ultimo=commits[0].get("commit",{}).get("message","")
        if ultimo:
            lineas_es.append(f'Último commit: <em>"{ultimo[:90]}"</em>.'); lineas_en.append(f'Latest commit: <em>"{ultimo[:90]}"</em>.')
    if creado:
        lineas_es.append(f"Creado en {creado}, actualizado el {actualizado}."); lineas_en.append(f"Created in {creado}, last updated {actualizado}.")
    return " ".join(lineas_es), " ".join(lineas_en)


def analizar_uso(data):
    info=data["info"]; archivos=data["contents"]; readme=data["readme"].lower()
    deps=data["dependencias"].lower(); lang=info.get("language","")
    owner=info.get("owner",{}).get("login","user"); repo=info.get("name","repo")
    desc=(info.get("description") or "").lower(); codigo=data["codigo_principal"]
    tipo="library"
    if any(a in archivos for a in ["Dockerfile","docker-compose.yml","docker-compose.yaml"]): tipo="service"
    if any(k in readme or k in desc for k in ["cli","command line","terminal","argparse","click"]): tipo="cli"
    if any(k in readme or k in deps or k in desc for k in ["web app","webapp","flask","django","express","fastapi","rails","nextjs","nuxt"]): tipo="webapp"
    if any(a in archivos for a in ["setup.py","setup.cfg","pyproject.toml"]):
        if "app.py" not in archivos and "main.py" not in archivos: tipo="library"
    pasos_install={
        "Python":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Virtualenv","python -m venv venv && source venv/bin/activate"),("Instalar","pip install -r requirements.txt"),("Ejecutar","python app.py" if "app.py" in archivos else "python main.py")],
        "JavaScript":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Instalar","npm install"),("Ejecutar","npm start" if '"start"' in deps else "node index.js")],
        "TypeScript":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Instalar","npm install"),("Build","npm run build"),("Ejecutar","npm start")],
        "Go":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Build","go build ./..."),("Ejecutar",f"./{repo}")],
        "Ruby":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Instalar","bundle install"),("Ejecutar","ruby main.rb" if "main.rb" in archivos else "rails server")],
        "Rust":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Build","cargo build --release"),("Ejecutar","cargo run")],
        "Java":[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Build","mvn package" if "pom.xml" in archivos else "gradle build"),("Ejecutar",f"java -jar target/{repo}.jar")],
    }
    pasos=pasos_install.get(lang,[("Clone",f"git clone https://github.com/{owner}/{repo}"),("Entrar",f"cd {repo}"),("Instalar","# see documentation"),("Ejecutar","# see documentation")])
    uso_desc_es={"webapp":f"{repo} es una aplicación web. Instálala y ábrela en <code>http://localhost:5000</code>.","cli":f"{repo} es una herramienta CLI. Usa <code>--help</code> para ver opciones.","library":f"{repo} es una librería. Instálala e impórtala en tu código.","service":f"{repo} es un servicio. Levántalo con <code>docker-compose up</code>."}
    uso_desc_en={"webapp":f"{repo} is a web app. Install it and open <code>http://localhost:5000</code>.","cli":f"{repo} is a CLI tool. Use <code>--help</code> to see options.","library":f"{repo} is a library. Install it and import it in your code.","service":f"{repo} is a service. Spin it up with <code>docker-compose up</code>."}
    ejemplos=[]
    if data["readme"]:
        bloques=re.findall(r'```[\w]*\n(.*?)```',data["readme"],re.DOTALL)
        for b in bloques[:3]:
            b=b.strip()
            if b and len(b)<300: ejemplos.append(b)
    features=[]
    if codigo:
        funcs=re.findall(r'def (\w+)\(|function (\w+)\(',codigo)
        names=[f[0] or f[1] for f in funcs[:6] if (f[0] or f[1]) and not (f[0] or f[1]).startswith('_')]
        if names: features.append(("Functions / Methods",", ".join(names)))
        classes=re.findall(r'class (\w+)',codigo)[:3]
        if classes: features.append(("Classes",", ".join(classes)))
        imports=re.findall(r'(?:import|require)\s+["\']?(\w+)',codigo)[:6]
        if imports: features.append(("Imports",", ".join(set(imports))))
    return {
        "tipo":tipo,"pasos":pasos,
        "uso_desc_es":uso_desc_es.get(tipo,""),"uso_desc_en":uso_desc_en.get(tipo,""),
        "ejemplos":ejemplos,"features":features,
        "tiene_tests":any("test" in a.lower() for a in archivos),
        "tiene_docker":any("docker" in a.lower() for a in archivos),
        "tiene_ci":any(a in [".github",".travis.yml",".circleci",".gitlab-ci.yml"] for a in archivos),
        "tiene_docs":any(a.lower() in ["docs","documentation","wiki"] for a in archivos),
        "tiene_license":any("license" in a.lower() for a in archivos),
    }


def analizar_actividad(data):
    commits=data["commits"]
    if not isinstance(commits,list): return []
    actividad=[]
    for c in commits[:8]:
        commit=c.get("commit",{})
        actividad.append({"mensaje":commit.get("message","")[:60],"fecha":commit.get("author",{}).get("date","")[:10],"autor":commit.get("author",{}).get("name","unknown")[:20]})
    return actividad


def generar_diagrama_flujo(data):
    info=data["info"]; nombre=info.get("name","project")[:16]; lang=info.get("language") or "code"
    desc=(info.get("description") or "")[:34]; archivos=data["contents"]
    tiene_tests=any("test" in a.lower() for a in archivos)
    tiene_docker=any("docker" in a.lower() for a in archivos)
    tiene_ci=any(a in [".github",".travis.yml",".circleci"] for a in archivos)
    paso3="Tests" if tiene_tests else "Core logic"
    paso4="Docker / Deploy" if tiene_docker else ("CI/CD" if tiene_ci else "Build / Deploy")
    pasos=[(nombre,desc or "entry point","#0969da"),(f"Lang: {lang}","primary technology","#1a7f37"),(paso3,"detected in repo","#9a6700"),(paso4,"final stage","#cf222e"),(f"{info.get('stargazers_count',0)} stars",f"{info.get('forks_count',0)} forks","#6e7781")]
    nodos=""
    for i,(titulo,sub,color) in enumerate(pasos):
        y=20+i*70; titulo=titulo[:22]; sub=sub[:28]
        nodos+=f'<rect x="80" y="{y}" width="200" height="46" rx="5" fill="var(--bg-card)" stroke="{color}" stroke-width="1"/><text x="180" y="{y+17}" text-anchor="middle" font-size="12" font-weight="600" fill="{color}" font-family="-apple-system,sans-serif">{titulo}</text><text x="180" y="{y+33}" text-anchor="middle" font-size="10" fill="var(--text-muted)" font-family="-apple-system,sans-serif">{sub}</text>'
        if i<len(pasos)-1:
            ly=y+46; nodos+=f'<line x1="180" y1="{ly}" x2="180" y2="{ly+24}" stroke="var(--border)" stroke-width="1.5" marker-end="url(#arr)"/>'
    return f'<svg width="100%" viewBox="0 0 360 380" xmlns="http://www.w3.org/2000/svg"><defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 2L8 5L2 8" fill="none" stroke="var(--border)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>{nodos}</svg>'


def generar_diagrama_estructura(data):
    archivos=data["contents"][:12]; nombre=data["info"].get("name","repo")[:20]
    ICONOS={"py":"py","js":"js","ts":"ts","jsx":"jsx","tsx":"tsx","html":"html","css":"css","json":"json","md":"md","yml":"yml","yaml":"yml","sh":"sh","txt":"txt","lock":"lock","go":"go","rs":"rs","java":"java","rb":"rb"}
    item_h=36; item_gap=6; pad_y=48; pad_x=16; ancho=320; alto=pad_y+len(archivos)*(item_h+item_gap)+16
    nodos=""
    for i,archivo in enumerate(archivos):
        y=pad_y+i*(item_h+item_gap); ext=archivo.split(".")[-1].lower() if "." in archivo else ""; tag=ICONOS.get(ext,"dir" if "." not in archivo else "file")
        nodos+=f'<rect x="{pad_x}" y="{y}" width="{ancho-pad_x*2}" height="{item_h}" rx="4" fill="var(--bg-card)" stroke="var(--border)" stroke-width="1"/><rect x="{pad_x}" y="{y}" width="36" height="{item_h}" rx="4" fill="var(--border)" stroke="none"/><text x="{pad_x+18}" y="{y+item_h//2+1}" dominant-baseline="central" text-anchor="middle" font-size="9" font-weight="600" fill="var(--text-muted)" font-family="ui-monospace,monospace">{tag}</text><text x="{pad_x+48}" y="{y+item_h//2+1}" dominant-baseline="central" font-size="12" fill="var(--text)" font-family="-apple-system,sans-serif">{archivo[:28]}</text>'
    return f'<svg width="100%" viewBox="0 0 {ancho} {alto}" xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="{ancho}" height="38" fill="var(--bg-header)" stroke="var(--border)" stroke-width="1"/><text x="16" y="24" font-size="12" font-weight="600" fill="var(--text)" font-family="-apple-system,sans-serif">{nombre}</text><text x="{ancho-16}" y="24" text-anchor="end" font-size="11" fill="var(--text-muted)" font-family="-apple-system,sans-serif">{len(archivos)} files</text>{nodos}</svg>'


def generar_diagrama_arquitectura(data):
    info=data["info"]; languages=data["languages"]; archivos=data["contents"]; nombre=info.get("name","project")[:18]
    todos_langs=list(languages.keys())[:3]; langs_texto="  /  ".join(todos_langs) if todos_langs else info.get("language","?")
    tiene_docker=any("docker" in a.lower() for a in archivos)
    tiene_db=any(a.lower() in ["db","database","models.py","schema.sql","prisma","migrations"] for a in archivos)
    tiene_api=any(a.lower() in ["api","routes","routes.py","controllers","endpoints.py"] for a in archivos)
    tiene_frontend=any(a.lower() in ["src","public","static","components","pages"] for a in archivos)
    capas=[("01","Frontend / UI" if tiene_frontend else "Interface","User entry point","#0969da"),("02","API / Routes" if tiene_api else "Business logic","Core processing","#1a7f37"),("03","Database" if tiene_db else "Storage","Data persistence","#9a6700"),("04","Docker / Containers" if tiene_docker else "Server / Host","Deployment infrastructure","#cf222e")]
    nodos=""
    for i,(num,titulo,sub,color) in enumerate(capas):
        y=56+i*66
        nodos+=f'<rect x="20" y="{y}" width="320" height="48" rx="5" fill="var(--bg-card)" stroke="{color}" stroke-width="1"/><text x="38" y="{y+18}" font-size="9" fill="{color}" font-family="ui-monospace,monospace" font-weight="600">LAYER {num}</text><text x="38" y="{y+34}" font-size="12" font-weight="600" fill="{color}" font-family="-apple-system,sans-serif">{titulo[:26]}</text><text x="336" y="{y+34}" text-anchor="end" font-size="10" fill="var(--text-muted)" font-family="-apple-system,sans-serif">{sub[:28]}</text>'
        if i<len(capas)-1:
            ly=y+48; nodos+=f'<line x1="180" y1="{ly}" x2="180" y2="{ly+18}" stroke="var(--border)" stroke-width="1.5" marker-end="url(#arr2)"/>'
    return f'<svg width="100%" viewBox="0 0 360 340" xmlns="http://www.w3.org/2000/svg"><defs><marker id="arr2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 2L8 5L2 8" fill="none" stroke="var(--border)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs><rect x="20" y="10" width="320" height="36" rx="5" fill="var(--bg-header)" stroke="var(--border)" stroke-width="1"/><text x="34" y="32" font-size="12" font-weight="600" fill="var(--text)" font-family="-apple-system,sans-serif">{nombre}</text><text x="336" y="32" text-anchor="end" font-size="10" fill="var(--text-muted)" font-family="ui-monospace,monospace">{langs_texto}</text>{nodos}</svg>'


def generar_diagrama_deps(data):
    deps_raw=data["dependencias"]; nombre=data["info"].get("name","project")[:10]; lang=data["info"].get("language","")
    if not deps_raw: return ""
    deps=[]
    if lang=="Python":
        for line in deps_raw.splitlines():
            line=line.strip()
            if line and not line.startswith("#"):
                name=re.split(r'[>=<!]',line)[0].strip()
                if name: deps.append(name[:10])
    elif lang in ["JavaScript","TypeScript"]:
        matches=re.findall(r'"([^"@][^"]+)"\s*:',deps_raw)
        deps=[m[:10] for m in matches if not m.startswith("_")][:12]
    deps=deps[:10]
    if not deps: return ""
    import math
    cx=180; cy=145; r_outer=110; r_node=28
    nodos=""; lineas=""
    for i,dep in enumerate(deps):
        angle=(2*math.pi*i/len(deps))-math.pi/2; x=cx+r_outer*math.cos(angle); y=cy+r_outer*math.sin(angle)
        lineas+=f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="var(--border)" stroke-width="1"/>'
        nodos+=f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r_node}" fill="var(--bg-card)" stroke="var(--border)" stroke-width="1"/><text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" dominant-baseline="central" font-size="9" fill="var(--text)" font-family="ui-monospace,monospace">{dep}</text>'
    return f'<svg width="100%" viewBox="0 0 360 295" xmlns="http://www.w3.org/2000/svg">{lineas}<circle cx="{cx}" cy="{cy}" r="36" fill="var(--bg-header)" stroke="var(--border)" stroke-width="1.5"/><text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" font-size="11" font-weight="600" fill="var(--text)" font-family="-apple-system,sans-serif">{nombre}</text>{nodos}</svg>'


LANG_COLORS = {
    "Python":"#3572A5","JavaScript":"#f1e05a","TypeScript":"#2b7489","Go":"#00ADD8",
    "Rust":"#dea584","Java":"#b07219","Ruby":"#701516","C++":"#f34b7d","C":"#555555",
    "C#":"#178600","PHP":"#4F5D95","Swift":"#F05138","Kotlin":"#A97BFF","Dart":"#00B4AB",
    "Shell":"#89e051","HTML":"#e34c26","CSS":"#563d7c","Vue":"#41b883","Svelte":"#ff3e00",
    "R":"#198CE7","Scala":"#c22d40","Haskell":"#5e5086","Lua":"#000080","Perl":"#0298c3",
}


def construir_repos_section(repos_validos):
    top5_repos=sorted(repos_validos,key=lambda r:r.get("stargazers_count",0),reverse=True)[:5]
    max_stars=max((r.get("stargazers_count",0) for r in top5_repos),default=1)
    if max_stars==0: max_stars=1
    top5_html=""
    for r in top5_repos:
        rname=r.get("name",""); rdesc=(r.get("description") or "Sin descripción")[:72]
        rstars=r.get("stargazers_count",0); rlang=r.get("language") or "—"
        rforks=r.get("forks_count",0); rurl=r.get("html_url",""); rupdated=r.get("updated_at","")[:10]
        bar_pct=int((rstars/max_stars)*100); lcolor=LANG_COLORS.get(rlang,"#8b949e")
        top5_html+=f'<div class="repo-card-item"><div class="repo-card-top"><a href="{rurl}" target="_blank" class="repo-card-name">{rname}</a><span class="repo-card-stars">★ {rstars:,}</span></div><div class="repo-card-desc">{rdesc}</div><div class="repo-card-bar"><div class="repo-card-bar-fill" style="width:{bar_pct}%;background:{lcolor}"></div></div><div class="repo-card-meta"><span class="repo-lang-dot" style="background:{lcolor}"></span><span class="repo-card-lang">{rlang}</span><span class="repo-card-forks">🍴 {rforks}</span><span class="repo-card-updated">{rupdated}</span></div></div>'
    contador={}
    for r in repos_validos:
        l=r.get("language")
        if l: contador[l]=contador.get(l,0)+1
    total_langs=sum(contador.values())
    items_langs=sorted(contador.items(),key=lambda x:x[1],reverse=True)[:8]
    langs_stack='<div class="lang-stack">'
    for lang,count in items_langs:
        pct=round(count/total_langs*100,1) if total_langs else 0; color=LANG_COLORS.get(lang,"#8b949e")
        langs_stack+=f'<div class="lang-stack-seg" style="width:{pct}%;background:{color}" title="{lang} {pct}%"></div>'
    langs_stack+='</div>'
    langs_list='<div class="lang-list">'
    for lang,count in items_langs:
        pct=round(count/total_langs*100,1) if total_langs else 0; color=LANG_COLORS.get(lang,"#8b949e")
        langs_list+=f'<div class="lang-item"><span class="lang-dot" style="background:{color}"></span><span class="lang-name">{lang}</span><div class="lang-bar-wrap"><div class="lang-bar-fill" style="width:{pct}%;background:{color}"></div></div><span class="lang-pct">{pct}%</span><span class="lang-count">{count} repo{"s" if count>1 else ""}</span></div>'
    langs_list+='</div>'

    # Donut chart data
    donut_data = json.dumps([{"lang": l, "count": c, "color": LANG_COLORS.get(l, "#8b949e")} for l, c in items_langs])

    langs_html=f'''<div class="langs-visual">
      <canvas id="langs-donut" width="200" height="200" style="display:block;margin:0 auto 16px"></canvas>
      {langs_stack}
      {langs_list}
    </div>
    <script>
    (function(){{
      const data = {donut_data};
      const canvas = document.getElementById('langs-donut');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const total = data.reduce((s,d)=>s+d.count,0);
      const cx=100,cy=100,r=80,inner=52;
      let start = -Math.PI/2;
      data.forEach(d=>{{
        const slice = (d.count/total)*Math.PI*2;
        ctx.beginPath();
        ctx.moveTo(cx,cy);
        ctx.arc(cx,cy,r,start,start+slice);
        ctx.closePath();
        ctx.fillStyle=d.color;
        ctx.fill();
        start+=slice;
      }});
      ctx.beginPath();
      ctx.arc(cx,cy,inner,0,Math.PI*2);
      const isDark = document.documentElement.dataset.theme==='dark';
      ctx.fillStyle = isDark?'#161b22':'#ffffff';
      ctx.fill();
      ctx.fillStyle = isDark?'#e6edf3':'#24292f';
      ctx.font='bold 14px -apple-system,sans-serif';
      ctx.textAlign='center';
      ctx.fillText(data.length+' langs',cx,cy+5);
    }})();
    </script>'''

    repos_json_list=[]
    for r in repos_validos:
        repos_json_list.append({"name":r.get("name",""),"desc":(r.get("description") or "")[:80],"stars":r.get("stargazers_count",0),"forks":r.get("forks_count",0),"lang":r.get("language") or "—","updated":r.get("updated_at","")[:10],"url":r.get("html_url",""),"fork":r.get("fork",False)})
    repos_json_str=json.dumps(repos_json_list)
    langs_unicos=sorted(set(r.get("language") or "—" for r in repos_validos if r.get("language")))
    lang_options="".join(f'<option value="{l}">{l}</option>' for l in langs_unicos)
    lang_colors_js=json.dumps(LANG_COLORS)
    uid="ru"
    all_repos_html=f"""<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Todos los repositorios</span><span class="lang-content" data-l="en">All repositories</span><span class="label" id="{uid}-count">{len(repos_validos)} repos</span></div><div class="card-body" style="padding:12px 16px"><div class="repos-filter-bar"><input type="text" id="{uid}-search" placeholder="Search repos..." class="filter-input" oninput="filterRepos_{uid}()"><select id="{uid}-lang" class="filter-select" onchange="filterRepos_{uid}()"><option value="">All languages</option>{lang_options}</select><select id="{uid}-sort" class="filter-select" onchange="filterRepos_{uid}()"><option value="stars">Stars</option><option value="forks">Forks</option><option value="updated">Updated</option><option value="name">Name</option></select><label class="filter-check"><input type="checkbox" id="{uid}-forks" onchange="filterRepos_{uid}()"><span class="lang-inline active" data-l="es">Ocultar forks</span><span class="lang-inline" data-l="en">Hide forks</span></label></div><div id="{uid}-list" class="repos-list-all"></div></div></div></div>
    <script>(function(){{const DATA={repos_json_str};const COLORS={lang_colors_js};function filterRepos_{uid}(){{const search=document.getElementById('{uid}-search').value.toLowerCase();const lang=document.getElementById('{uid}-lang').value;const sort=document.getElementById('{uid}-sort').value;const hideFork=document.getElementById('{uid}-forks').checked;let filtered=DATA.filter(r=>{{if(hideFork&&r.fork)return false;if(lang&&r.lang!==lang)return false;if(search&&!r.name.toLowerCase().includes(search)&&!r.desc.toLowerCase().includes(search))return false;return true;}});filtered.sort((a,b)=>{{if(sort==='stars')return b.stars-a.stars;if(sort==='forks')return b.forks-a.forks;if(sort==='updated')return b.updated.localeCompare(a.updated);if(sort==='name')return a.name.localeCompare(b.name);return 0;}});document.getElementById('{uid}-count').textContent=filtered.length+' repos';const container=document.getElementById('{uid}-list');if(!filtered.length){{container.innerHTML='<div style="color:var(--text-muted);font-size:13px;padding:12px 0">No repositories found.</div>';return;}}container.innerHTML=filtered.map(r=>{{const lc=COLORS[r.lang]||'#8b949e';return '<div class="repo-row-item"><div class="repo-row-left"><a href="'+r.url+'" target="_blank" class="repo-card-name">'+r.name+'</a>'+(r.fork?'<span class="repo-fork-badge">fork</span>':'')+'<span class="repo-row-desc">'+(r.desc||'—')+'</span></div><div class="repo-row-right"><span class="repo-lang-dot" style="background:'+lc+'"></span><span class="repo-card-lang" style="min-width:60px">'+r.lang+'</span><span class="repo-card-stars">★ '+r.stars.toLocaleString()+'</span><span class="repo-card-forks">🍴 '+r.forks+'</span><span class="repo-card-updated">'+r.updated+'</span></div></div>';}}).join('');}}window.filterRepos_{uid}=filterRepos_{uid};filterRepos_{uid}();}})();</script>"""
    return top5_html, langs_html, all_repos_html


def construir_perfil_html(pdata):
    user=pdata["user"]; repos=pdata["repos"]; events=pdata["events"]
    es_org=pdata["es_org"]; miembros=pdata["miembros"]
    login=user.get("login",""); nombre=user.get("name") or login
    bio=user.get("bio") or (user.get("description","") if es_org else "—")
    avatar=user.get("avatar_url",""); blog=user.get("blog",""); location=user.get("location","")
    company=user.get("company",""); twitter=user.get("twitter_username",""); email=user.get("email","")
    creado=user.get("created_at","")[:10]; pub_repos=user.get("public_repos",0)
    followers=user.get("followers",0)
    gh_url=f"https://github.com/{login}"; tipo_label="Organization" if es_org else "User"
    repos_validos=[r for r in repos if isinstance(r,dict)]
    total_stars=sum(r.get("stargazers_count",0) for r in repos_validos)
    total_forks=sum(r.get("forks_count",0) for r in repos_validos)
    insignias=[]
    if not es_org:
        if followers>10000: insignias.append(("Top contributor","#0969da"))
        if followers>1000:  insignias.append(("Popular","#1a7f37"))
    if pub_repos>100: insignias.append(("Power user","#cf222e"))
    elif pub_repos>50: insignias.append(("Prolific","#9a6700"))
    if total_stars>10000: insignias.append(("Hall of Fame","#6e40c9"))
    elif total_stars>1000: insignias.append(("Starred","#bf8700"))
    if es_org: insignias.append(("Organization","#0969da"))
    if blog:   insignias.append(("Has website","#1a7f37"))
    if not es_org and twitter: insignias.append(("On Twitter","#1d9bf0"))
    insignias_html="".join(f'<span class="badge" style="border-color:{c};color:{c}">{b}</span>' for b,c in insignias)
    info_rows=""
    if location: info_rows+=f'<div class="info-row"><span class="info-key">Location</span><span>{location}</span></div>'
    if company:  info_rows+=f'<div class="info-row"><span class="info-key">Company</span><span>{company}</span></div>'
    if email:    info_rows+=f'<div class="info-row"><span class="info-key">Email</span><span>{email}</span></div>'
    if blog:     info_rows+=f'<div class="info-row"><span class="info-key">Website</span><a href="{blog}" target="_blank" class="info-link">{blog[:40]}</a></div>'
    if not es_org and twitter: info_rows+=f'<div class="info-row"><span class="info-key">Twitter</span><span>@{twitter}</span></div>'
    info_rows+=f'<div class="info-row"><span class="info-key">Member since</span><span>{creado}</span></div>'
    info_rows+=f'<div class="info-row"><span class="info-key">GitHub</span><a href="{gh_url}" target="_blank" class="info-link">{gh_url}</a></div>'
    stats_section=""
    if not es_org:
        stats_section=f"""<div class="grid-1"><div class="card"><div class="card-header">GitHub Stats <span class="label"><a href="https://github.com/anuraghazra/github-readme-stats" target="_blank" class="info-link">github-readme-stats</a></span></div><div class="card-body" style="display:flex;flex-wrap:wrap;gap:12px;justify-content:center;padding:20px 16px"><img src="https://github-readme-stats-eight-theta.vercel.app/api?username={login}&show_icons=true&theme=github_dark&include_all_commits=true&count_private=true&hide_border=true" alt="Stats" style="height:160px;border-radius:6px;max-width:100%" onerror="this.style.display='none'"><img src="https://github-readme-stats-eight-theta.vercel.app/api/top-langs/?username={login}&layout=compact&langs_count=8&theme=github_dark&hide_border=true" alt="Top langs" style="height:160px;border-radius:6px;max-width:100%" onerror="this.style.display='none'"></div></div></div>
        <div class="grid-1"><div class="card"><div class="card-header">Contribution Streak <span class="label"><a href="https://github.com/DenverCoder1/github-readme-streak-stats" target="_blank" class="info-link">streak-stats</a></span></div><div class="card-body" style="display:flex;justify-content:center;padding:16px"><img src="https://streak-stats.demolab.com?user={login}&theme=github-dark-blue&hide_border=true&date_format=M%20j%5B%2C%20Y%5D" alt="Streak" style="border-radius:6px;max-width:100%" onerror="this.style.display='none'"></div></div></div>
        <div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Mapa de contribuciones</span><span class="lang-content" data-l="en">Contribution map</span></div><div class="card-body" style="display:flex;justify-content:center;padding:16px"><img src="https://github-profile-summary-cards.vercel.app/api/cards/profile-details?username={login}&theme=github_dark" alt="Contributions" style="border-radius:6px;max-width:100%;width:100%" onerror="this.style.display='none'"></div></div></div>"""
    readme_tips_html=""
    if not es_org:
        readme_tips_html=f"""<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Mejora tu README de perfil</span><span class="lang-content" data-l="en">Improve your profile README</span></div><div class="card-body"><div class="tips-intro"><span class="lang-content active" data-l="es">Crea un repo <code>{login}/{login}</code> con un README.md:</span><span class="lang-content" data-l="en">Create a repo <code>{login}/{login}</code> with a README.md:</span></div><div class="tips-grid"><div class="tip-item"><div class="tip-title">Stats + Languages</div><div class="tip-desc"><span class="lang-content active" data-l="es">Estadísticas y lenguajes.</span><span class="lang-content" data-l="en">Stats and languages.</span></div><a href="https://github.com/anuraghazra/github-readme-stats" target="_blank" class="tip-link">github-readme-stats →</a><div class="tip-code">![Stats](https://github-readme-stats.vercel.app/api?username={login}&show_icons=true&theme=github_dark)</div></div><div class="tip-item"><div class="tip-title">Streak</div><div class="tip-desc"><span class="lang-content active" data-l="es">Racha de commits.</span><span class="lang-content" data-l="en">Commit streak.</span></div><a href="https://github.com/DenverCoder1/github-readme-streak-stats" target="_blank" class="tip-link">streak-stats →</a><div class="tip-code">![Streak](https://streak-stats.demolab.com?user={login}&theme=github-dark-blue)</div></div><div class="tip-item"><div class="tip-title">Trophies</div><div class="tip-desc"><span class="lang-content active" data-l="es">Logros.</span><span class="lang-content" data-l="en">Achievements.</span></div><a href="https://github.com/ryo-ma/github-profile-trophy" target="_blank" class="tip-link">github-profile-trophy →</a><div class="tip-code">![Trophy](https://github-profile-trophy.vercel.app/?username={login}&theme=darkhub)</div></div></div></div></div></div>"""
    if es_org:
        stats_nums_html=f"""<div class="grid-3"><div class="card stat-card"><div class="card-body"><span class="stat-value">{pub_repos}</span><div class="stat-label">repos</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{total_stars:,}</span><div class="stat-label">total stars</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{total_forks:,}</span><div class="stat-label">total forks</div></div></div></div>"""
    else:
        stats_nums_html=f"""<div class="grid-4"><div class="card stat-card"><div class="card-body"><span class="stat-value">{pub_repos}</span><div class="stat-label">repos</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{followers:,}</span><div class="stat-label">followers</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{total_stars:,}</span><div class="stat-label">total stars</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{total_forks:,}</span><div class="stat-label">total forks</div></div></div></div>"""
    labels_ev={"PushEvent":"pushed to","PullRequestEvent":"opened PR in","IssuesEvent":"opened issue in","WatchEvent":"starred","ForkEvent":"forked","CreateEvent":"created","DeleteEvent":"deleted branch in","IssueCommentEvent":"commented in","ReleaseEvent":"released"}
    actividad_html=""
    for ev in events[:8]:
        tipo_ev=ev.get("type",""); repo_ev=ev.get("repo",{}).get("name",""); fecha_ev=ev.get("created_at","")[:10]
        accion=labels_ev.get(tipo_ev,tipo_ev.replace("Event","").lower())
        actividad_html+=f'<div class="timeline-item"><div class="timeline-dot"></div><div class="timeline-content"><div class="timeline-msg">{accion} <strong>{repo_ev}</strong></div><div class="timeline-meta">{fecha_ev}</div></div></div>'
    miembros_html=""
    if es_org and miembros:
        for m in miembros[:6]:
            mlogin=m.get("login",""); mavatar=m.get("avatar_url","")
            miembros_html+=f'<div class="member-item"><img src="{mavatar}" alt="{mlogin}" class="member-avatar" onerror="this.style.display=\'none\'"><span class="member-login">{mlogin}</span></div>'
    top5_html, langs_html, all_repos_html = construir_repos_section(repos_validos)
    return f"""
    <div class="section-divider"><span class="lang-inline active" data-l="es">{"Organización" if es_org else "Perfil"}</span><span class="lang-inline" data-l="en">{"Organization" if es_org else "Profile"}</span></div>
    <div class="grid-1"><div class="card"><div class="card-header">{tipo_label}<span class="label">{gh_url}</span></div><div class="card-body"><div class="perfil-hero"><img src="{avatar}" alt="{login}" class="perfil-avatar" onerror="this.style.background='var(--bg-card)'"><div class="perfil-info"><div class="perfil-nombre">{nombre}</div><div class="perfil-login">@{login}</div><div class="perfil-bio">{bio}</div><div class="badges" style="margin-top:10px">{insignias_html}</div></div></div></div></div></div>
    {stats_nums_html}
    <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Informacion</span><span class="lang-content" data-l="en">Information</span></div><div class="card-body"><div class="info-table">{info_rows}</div></div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Actividad reciente</span><span class="lang-content" data-l="en">Recent activity</span></div><div class="card-body scroll"><div class="timeline">{actividad_html or "<span style='color:var(--text-muted);font-size:13px'>No public activity</span>"}</div></div></div></div>
    {"" if not miembros_html else f'<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Miembros públicos</span><span class="lang-content" data-l="en">Public members</span></div><div class="card-body"><div class="members-grid">{miembros_html}</div></div></div></div>'}
    {stats_section}
    <div class="section-divider"><span class="lang-inline active" data-l="es">Repositorios</span><span class="lang-inline" data-l="en">Repositories</span></div>
    <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Top 5 por estrellas</span><span class="lang-content" data-l="en">Top 5 by stars</span></div><div class="card-body scroll">{top5_html}</div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Lenguajes</span><span class="lang-content" data-l="en">Languages</span></div><div class="card-body scroll">{langs_html}</div></div></div>
    {all_repos_html}
    {readme_tips_html}"""


def construir_seccion_preguntas(data):
    archivos_contenido=data.get("archivos_contenido",{})
    nombre_repo=data["info"].get("name","repo")
    archivos_lista=list(archivos_contenido.keys())
    archivos_lower=[a.lower() for a in archivos_lista]
    sugerencias=[]
    if any("auth" in a or "login" in a or "session" in a or "jwt" in a for a in archivos_lower): sugerencias.append("¿Cómo funciona el login?")
    if any("model" in a or "schema" in a or "db" in a or "database" in a or "migration" in a for a in archivos_lower): sugerencias.append("¿Cómo está la base de datos?")
    if any("route" in a or "router" in a or "api" in a or "endpoint" in a or "controller" in a for a in archivos_lower): sugerencias.append("¿Cuáles son las rutas?")
    if any("config" in a or ".env" in a or "setting" in a for a in archivos_lower): sugerencias.append("¿Cómo se configura?")
    if any("test" in a or "spec" in a for a in archivos_lower): sugerencias.append("¿Cómo están los tests?")
    if any("docker" in a for a in archivos_lower): sugerencias.append("¿Cómo funciona Docker?")
    if any("middleware" in a for a in archivos_lower): sugerencias.append("¿Qué middlewares usa?")
    if any("service" in a for a in archivos_lower): sugerencias.append("¿Cómo están los servicios?")
    sugerencias+=["¿Qué dependencias usa?","¿Cómo está estructurado?","¿Qué hace el archivo principal?"]
    sugerencias=sugerencias[:8]
    sugerencias_html="".join(f'<button class="suggestion-btn" onclick="hacerPregunta(this)">{s}</button>' for s in sugerencias)
    archivos_json=json.dumps(archivos_contenido)
    readme_json=json.dumps(data.get("readme",""))
    # Build a truncated context for AI
    context_files = {}
    for k, v in list(archivos_contenido.items())[:8]:
        context_files[k] = v[:800]
    context_json = json.dumps(context_files)
    readme_short = json.dumps(data.get("readme","")[:1000])

    return f"""
    <div class="section-divider"><span class="lang-inline active" data-l="es">Explorar el código</span><span class="lang-inline" data-l="en">Explore the code</span></div>
    <div class="grid-1"><div class="card">
      <div class="card-header">
        <span class="lang-content active" data-l="es">Pregunta sobre {nombre_repo}</span>
        <span class="lang-content" data-l="en">Ask about {nombre_repo}</span>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="label">{len(archivos_lista)} archivos indexados</span>
          <span class="ai-badge">✦ AI</span>
        </div>
      </div>
      <div class="card-body" style="padding:0">
        <div id="chat-messages" class="chat-messages">
          <div class="chat-msg chat-msg-system">
            <span class="lang-inline active" data-l="es">Tengo acceso a <strong>{len(archivos_lista)}</strong> archivos. Pregúntame lo que quieras — ahora con IA real.</span>
            <span class="lang-inline" data-l="en">I have access to <strong>{len(archivos_lista)}</strong> files. Ask me anything — now with real AI.</span>
          </div>
        </div>
        <div class="chat-suggestions" id="chat-suggestions">{sugerencias_html}</div>
        <div class="chat-input-row">
          <input type="text" id="chat-input" placeholder="¿Cómo funciona el login? / How does auth work?" class="chat-input" onkeydown="if(event.key==='Enter')enviarPregunta()">
          <button class="chat-send-btn" onclick="enviarPregunta()">
            <span class="lang-inline active" data-l="es">Preguntar ✦</span>
            <span class="lang-inline" data-l="en">Ask ✦</span>
          </button>
        </div>
      </div>
    </div></div>
    <script>
    const ARCHIVOS_REPO={archivos_json};
    const README_REPO={readme_json};
    const AI_CONTEXT={context_json};
    const AI_README={readme_short};
    const REPO_NAME="{nombre_repo}";
    const KEYWORDS_MAP={{
      "login":["login","auth","signin","sign_in","authenticate","session","jwt","token","password","credential","oauth","passport","bcrypt","hash","verify","user_id","current_user","logged"],
      "registro":["register","signup","sign_up","create_user","new_user","registration"],
      "base de datos":["database","db","sql","mongo","postgres","mysql","sqlite","orm","model","schema","migration","sequelize","mongoose","prisma","typeorm","knex","query","table","column","entity"],
      "api":["api","endpoint","route","router","request","response","fetch","axios","http","rest","graphql","webhook","handler","controller","get(","post(","put(","delete(","patch("],
      "config":["config","settings","env","environment","dotenv","setup","configuration","constant","variable","port","host","secret","key"],
      "test":["test","spec","unittest","pytest","jest","describe","it(","assert","expect","mock","fixture","beforeeach","aftereach","beforeall"],
      "docker":["docker","container","dockerfile","compose","image","kubernetes","k8s","helm","pod"],
      "deploy":["deploy","deployment","heroku","vercel","netlify","aws","gcp","azure","cloud","production","staging","ci","cd","pipeline","workflow","action"],
      "instalar":["install","setup","requirement","dependency","package","npm","pip","yarn","bundle","cargo","gem","poetry","venv"],
    }};
    function escapeHtml(t){{return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
    function hacerPregunta(btn){{document.getElementById('chat-input').value=btn.textContent.trim();enviarPregunta();}}

    async function enviarPregunta(){{
      const input=document.getElementById('chat-input');const pregunta=input.value.trim();
      if(!pregunta)return;
      document.getElementById('chat-suggestions').style.display='none';
      agregarMensaje('user',pregunta);input.value='';
      const loadId='load-'+Date.now();agregarMensaje('loading','',loadId);

      // Build context string
      const ctxParts = [];
      if(AI_README) ctxParts.push('README (excerpt):\\n'+AI_README);
      Object.entries(AI_CONTEXT).slice(0,6).forEach(([f,c])=>ctxParts.push('File: '+f+'\\n'+c));
      const contextStr = ctxParts.join('\\n\\n---\\n\\n').slice(0,6000);

      try {{
        const resp = await fetch('https://api.anthropic.com/v1/messages', {{
          method:'POST',
          headers:{{'Content-Type':'application/json'}},
          body: JSON.stringify({{
            model:'claude-sonnet-4-20250514',
            max_tokens:600,
            system:`You are an expert code analyst for the GitHub repository "${{REPO_NAME}}". Answer questions about this codebase concisely and clearly. Use code snippets when helpful. Be direct and technical. Respond in the same language as the user's question.`,
            messages:[{{role:'user',content:`Repository context:\\n${{contextStr}}\\n\\n---\\nQuestion: ${{pregunta}}`}}]
          }})
        }});
        const data = await resp.json();
        const loadEl=document.getElementById(loadId);if(loadEl)loadEl.remove();
        const text = data.content?.[0]?.text || 'No response.';
        agregarMensaje('assistant-ai', text);
      }} catch(e) {{
        // Fallback to local search
        const loadEl=document.getElementById(loadId);if(loadEl)loadEl.remove();
        const resultados=buscarEnRepo(pregunta);
        mostrarResultados(pregunta,resultados);
      }}
      sincronizarLang();
    }}

    function buscarEnRepo(pregunta){{
      const p=pregunta.toLowerCase();let palabras=[];
      for(const concepto in KEYWORDS_MAP){{
        const pals=KEYWORDS_MAP[concepto];
        if(pals.some(function(k){{return p.includes(k);}})||p.includes(concepto))palabras=palabras.concat(pals);
      }}
      if(!palabras.length)palabras=(p.match(/\w{{3,}}/g)||[]);
      const literales=(p.match(/\w{{3,}}/g)||[]);
      palabras=[...new Set(palabras.concat(literales))];
      const resultados=[];const fuentes=Object.entries(ARCHIVOS_REPO);
      if(README_REPO)fuentes.push(['README.md',README_REPO]);
      for(let fi=0;fi<fuentes.length;fi++){{
        const archivo=fuentes[fi][0];const contenido=fuentes[fi][1];
        const lineas=contenido.split('\\n');let score=0;const fragmentos=[];
        for(let i=0;i<lineas.length;i++){{
          const ll=lineas[i].toLowerCase();let hits=0;
          for(let pi=0;pi<palabras.length;pi++){{if(ll.includes(palabras[pi]))hits++;}}
          if(hits>0){{
            score+=hits;const inicio=Math.max(0,i-3);const fin=Math.min(lineas.length,i+12);
            const bloque=lineas.slice(inicio,fin).join('\\n').trim();
            if(bloque&&!fragmentos.some(function(f){{return f.bloque===bloque;}}))
              fragmentos.push({{hits:hits,linea:i+1,bloque:bloque}});
          }}
        }}
        if(fragmentos.length){{
          fragmentos.sort(function(a,b){{return b.hits-a.hits;}});
          const mejores=fragmentos.slice(0,2);
          resultados.push({{archivo:archivo,score:score,linea:mejores[0].linea,fragmento:mejores[0].bloque,extra:mejores.length>1?mejores[1].bloque:null,total:fragmentos.length}});
        }}
      }}
      resultados.sort(function(a,b){{return b.score-a.score;}});return resultados.slice(0,5);
    }}
    function mostrarResultados(pregunta,resultados){{
      if(!resultados.length){{
        agregarMensaje('assistant','<div class="chat-no-results">No encontré <strong>'+escapeHtml(pregunta)+'</strong> en los archivos.</div>');
        sincronizarLang();return;
      }}
      let html='<div class="chat-results-header">'+resultados.length+' archivo(s) relevante(s):</div>';
      for(let i=0;i<resultados.length;i++){{
        const r=resultados[i];const ext=r.archivo.includes('.')?r.archivo.split('.').pop():'file';
        const partes=r.archivo.split('/');const nombreCorto=partes.length>2?'.../ '+partes.slice(-2).join('/'):r.archivo;
        html+='<div class="chat-result-block'+(i===0?' chat-result-top':'')+'"><div class="chat-result-file"><span class="file-ext">'+ext.slice(0,6)+'</span><span class="chat-result-filename" title="'+r.archivo+'">'+nombreCorto+'</span><span class="chat-result-line">línea '+r.linea+'</span><span class="chat-result-score">'+r.score+' hits</span></div><pre class="chat-code-block"><code>'+escapeHtml(r.fragmento)+'</code></pre>'+(r.extra?'<pre class="chat-code-block" style="border-top:1px solid var(--border);opacity:.8"><code>'+escapeHtml(r.extra)+'</code></pre>':'')+'</div>';
      }}
      agregarMensaje('assistant',html);sincronizarLang();
    }}
    function sincronizarLang(){{
      const lang=document.documentElement.dataset.lang||'es';
      document.querySelectorAll('.lang-inline').forEach(function(el){{el.classList.toggle('active',el.dataset.l===lang);}});
    }}
    function agregarMensaje(tipo,contenido,id){{
      const container=document.getElementById('chat-messages');const div=document.createElement('div');
      if(tipo==='assistant-ai'){{
        div.className='chat-msg chat-msg-assistant-ai';
        // Simple markdown-like rendering
        let html = escapeHtml(contenido)
          .replace(/```([\\s\\S]*?)```/g,'<pre class="chat-code-block"><code>$1</code></pre>')
          .replace(/`([^`]+)`/g,'<code style="background:var(--code-bg);padding:1px 4px;border-radius:3px;font-family:monospace">$1</code>')
          .replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>')
          .replace(/\\n/g,'<br>');
        div.innerHTML='<span class="chat-msg-label">✦ AI · '+REPO_NAME+'</span><div class="chat-msg-text">'+html+'</div>';
      }} else {{
        div.className='chat-msg chat-msg-'+tipo;if(id)div.id=id;
        if(tipo==='user'){{div.innerHTML='<span class="chat-msg-label">You</span><div class="chat-msg-text">'+escapeHtml(contenido)+'</div>';}}
        else if(tipo==='loading'){{div.innerHTML='<div class="chat-typing"><span></span><span></span><span></span></div>';}}
        else{{div.innerHTML='<span class="chat-msg-label">EnkiDocs</span><div class="chat-msg-text">'+contenido+'</div>';}}
      }}
      container.appendChild(div);container.scrollTop=container.scrollHeight;
    }}
    </script>"""


def error_html(tipo, param=""):
    errores = {
        "user_not_found": {"icon":"👤","title_es":"Usuario no encontrado","title_en":"User not found","desc_es":f"El usuario <strong>{param}</strong> no existe en GitHub o el perfil es privado.","desc_en":f"The user <strong>{param}</strong> doesn't exist on GitHub or the profile is private.","hint":f"github.com/{param}"},
        "repo_not_found": {"icon":"📁","title_es":"Repositorio no encontrado","title_en":"Repository not found","desc_es":f"El repositorio <strong>{param}</strong> no existe, es privado o fue eliminado.","desc_en":f"The repository <strong>{param}</strong> doesn't exist, is private, or was deleted.","hint":f"github.com/{param}"},
        "rate_limit": {"icon":"⏱️","title_es":"Límite de API alcanzado","title_en":"API rate limit reached","desc_es":"GitHub ha limitado las solicitudes. Espera unos minutos e intenta de nuevo.","desc_en":"GitHub has rate-limited requests. Wait a few minutes and try again.","hint":"Error 403 — GitHub API rate limit exceeded"},
        "invalid_url": {"icon":"🔗","title_es":"URL no reconocida","title_en":"Unrecognized URL","desc_es":f"La URL <strong>{param}</strong> no es válida.","desc_en":f"The URL <strong>{param}</strong> is not valid.","hint":"Formatos válidos: github.com/usuario  ·  github.com/usuario/repositorio"},
        "server_error": {"icon":"🔧","title_es":"Error del servidor","title_en":"Server error","desc_es":f"Ocurrió un error inesperado. Detalle: <code>{param}</code>","desc_en":f"An unexpected error occurred. Detail: <code>{param}</code>","hint":"Si persiste, revisa githubstatus.com"},
    }
    e = errores.get(tipo, errores["server_error"])
    return f"""
    <div class="error-card card">
      <div class="error-icon">{e['icon']}</div>
      <div class="error-title">
        <span class="lang-content active" data-l="es">{e['title_es']}</span>
        <span class="lang-content" data-l="en">{e['title_en']}</span>
      </div>
      <div class="error-desc">
        <span class="lang-content active" data-l="es">{e['desc_es']}</span>
        <span class="lang-content" data-l="en">{e['desc_en']}</span>
      </div>
      <div class="error-hint">{e['hint']}</div>
    </div>"""


TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-lang="es" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EnkiDocs — GitHub Analyzer</title>
  <meta name="description" content="Analiza cualquier repositorio de GitHub al instante. Diagramas UML, análisis de código con IA y guías de instalación.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&family=Geist:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0a0c10;
      --bg-card: #0f1318;
      --bg-header: #13181f;
      --bg-hover: #161c24;
      --border: #1e2530;
      --border-bright: #2a3344;
      --text: #cdd5e0;
      --text-bright: #e8edf5;
      --text-muted: #4a5568;
      --text-mid: #6b7a90;
      --link: #4d9fff;
      --link-dim: #2e6fbd;
      --accent: #00d9b1;
      --accent-dim: #007a63;
      --green: #238636;
      --green-h: #2ea043;
      --gold: #e3a21a;
      --red: #f85149;
      --purple: #a371f7;
      --nav-bg: #080b0f;
      --shadow: 0 1px 3px rgba(0,0,0,0.5);
      --shadow-lg: 0 8px 32px rgba(0,0,0,0.4);
      --step-bg: #0d1f2d;
      --step-num: #4d9fff;
      --code-bg: #080b0f;
      --glow: 0 0 20px rgba(0,217,177,0.08);
    }
    [data-theme="light"] {
      --bg: #f8fafc;
      --bg-card: #ffffff;
      --bg-header: #f1f5f9;
      --bg-hover: #e8edf5;
      --border: #dde3ed;
      --border-bright: #c5cfd9;
      --text: #2d3748;
      --text-bright: #1a202c;
      --text-muted: #a0aec0;
      --text-mid: #718096;
      --link: #0969da;
      --link-dim: #054fb9;
      --accent: #00a88a;
      --accent-dim: #007a63;
      --green: #2da44e;
      --green-h: #2c974b;
      --gold: #b45309;
      --red: #cf222e;
      --purple: #6e40c9;
      --nav-bg: #1a202c;
      --shadow: 0 1px 3px rgba(0,0,0,0.08);
      --shadow-lg: 0 8px 32px rgba(0,0,0,0.1);
      --step-bg: #ddf4ff;
      --step-num: #0969da;
      --code-bg: #f1f5f9;
      --glow: none;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 13.5px;
      line-height: 1.65;
      color: var(--text);
      background: var(--bg);
      transition: background .25s, color .25s;
    }

    /* ── SCROLLBAR ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

    /* ── NAV ── */
    .nav {
      background: var(--nav-bg);
      padding: 0 24px;
      height: 54px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(12px);
    }
    .nav-left { display: flex; align-items: center; gap: 20px; }
    .nav-logo {
      color: #fff;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -.4px;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 6px;
      font-family: 'Geist', sans-serif;
    }

    .nav-logo span { color: var(--accent); }
    .nav-search-wrap {
      display: flex;
      align-items: center;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 8px;
      overflow: hidden;
      transition: border-color .2s, background .2s;
      height: 34px;
    }
    .nav-search-wrap:focus-within {
      background: rgba(255,255,255,0.06);
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(0,217,177,0.08);
    }
    .nav-search-icon { padding: 0 10px; color: rgba(255,255,255,0.3); display: flex; align-items: center; flex-shrink: 0; }
    .nav-search-icon svg { width: 13px; height: 13px; }
    .nav-search-input {
      background: transparent; border: none; outline: none;
      color: #fff; font-size: 12.5px; padding: 0 8px 0 0;
      width: 300px; height: 100%;
      font-family: 'Geist Mono', monospace;
    }
    .nav-search-input::placeholder { color: rgba(255,255,255,0.25); font-family: 'Geist', sans-serif; }
    .nav-search-btn {
      background: rgba(0,217,177,0.1);
      border: none; border-left: 1px solid rgba(0,217,177,0.2);
      color: var(--accent);
      padding: 0 14px; cursor: pointer;
      font-size: 12px; font-weight: 600; height: 100%;
      transition: background .15s; white-space: nowrap;
      font-family: 'Geist', sans-serif;
      letter-spacing: .3px;
    }
    .nav-search-btn:hover { background: rgba(0,217,177,0.18); }
    .nav-right { display: flex; align-items: center; gap: 6px; }
    .btn-nav {
      background: transparent; border: 1px solid rgba(255,255,255,0.1);
      color: rgba(255,255,255,0.5); border-radius: 7px;
      padding: 5px 10px; font-size: 12px; cursor: pointer;
      transition: all .2s; display: flex; align-items: center; gap: 5px;
    }
    .btn-nav:hover { border-color: rgba(255,255,255,0.25); color: #fff; }
    .btn-nav svg { width: 13px; height: 13px; flex-shrink: 0; }
    .btn-github {
      background: transparent; border: 1px solid rgba(255,255,255,0.1);
      color: rgba(255,255,255,0.5); border-radius: 7px;
      padding: 5px 10px; font-size: 12px; cursor: pointer;
      text-decoration: none; display: flex; align-items: center; gap: 5px;
      transition: all .2s;
    }
    .btn-github:hover { border-color: rgba(255,255,255,0.25); color: #fff; }
    .btn-github svg { width: 13px; height: 13px; flex-shrink: 0; }
    .lang-dropdown { position: relative; }
    .lang-menu {
      display: none; position: absolute; top: calc(100% + 8px); right: 0;
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 10px; box-shadow: var(--shadow-lg);
      z-index: 200; min-width: 150px; overflow: hidden;
    }
    .lang-menu.open { display: block; }
    .lang-option {
      display: flex; align-items: center; gap: 8px;
      padding: 9px 14px; font-size: 13px; color: var(--text);
      cursor: pointer; transition: background .1s;
    }
    .lang-option:hover { background: var(--bg-hover); }
    .lang-option.active { color: var(--accent); font-weight: 500; }
    .lang-flag { font-size: 15px; }

    /* ── LOADING SKELETON ── */
    .skeleton-page { padding: 28px 20px; max-width: 1000px; margin: 0 auto; }
    .skeleton-bar {
      background: linear-gradient(90deg, var(--border) 25%, var(--border-bright) 50%, var(--border) 75%);
      background-size: 200% 100%;
      animation: shimmer 1.6s infinite;
      border-radius: 4px;
    }
    @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
    .skeleton-card {
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 12px;
    }
    .skeleton-header { height: 40px; background: var(--bg-header); border-bottom: 1px solid var(--border); }
    .skeleton-body { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    .sk-grid { display: grid; gap: 12px; margin-bottom: 12px; }
    .sk-grid-4 { grid-template-columns: repeat(4,1fr); }
    .sk-grid-2 { grid-template-columns: 1fr 1fr; }

    /* ── LANDING ── */
    .landing {
      min-height: calc(100vh - 54px);
      display: flex; align-items: center; justify-content: center;
      padding: 48px 24px 80px;
      background:
        radial-gradient(ellipse 60% 40% at 50% 0%, rgba(0,217,177,0.06) 0%, transparent 70%),
        radial-gradient(ellipse 40% 30% at 80% 60%, rgba(77,159,255,0.04) 0%, transparent 60%),
        var(--bg);
    }
    [data-theme="light"] .landing {
      background:
        radial-gradient(ellipse 60% 40% at 50% 0%, rgba(0,168,138,0.05) 0%, transparent 70%),
        var(--bg);
    }
    .landing-inner { max-width: 620px; width: 100%; text-align: center; }
    .landing-eyebrow {
      display: inline-flex; align-items: center; gap: 7px;
      font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
      text-transform: uppercase; color: var(--accent);
      background: rgba(0,217,177,0.08); border: 1px solid rgba(0,217,177,0.2);
      border-radius: 20px; padding: 4px 12px; margin-bottom: 24px;
    }
    .landing-eyebrow-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.4; } }
    .landing-title {
      font-family: 'Instrument Serif', Georgia, serif;
      font-size: 42px; font-weight: 400;
      color: var(--text-bright);
      margin-bottom: 14px; letter-spacing: -.5px; line-height: 1.15;
    }
    .landing-title em { font-style: italic; color: var(--accent); }
    .landing-subtitle {
      font-size: 15px; color: var(--text-mid);
      margin-bottom: 36px; line-height: 1.7;
      max-width: 480px; margin-left: auto; margin-right: auto;
    }
    .landing-form-wrap {
      background: var(--bg-card);
      border: 1px solid var(--border-bright);
      border-radius: 10px; overflow: hidden;
      display: flex; align-items: center;
      box-shadow: var(--shadow-lg);
      transition: border-color .2s, box-shadow .2s;
    }
    .landing-form-wrap:focus-within {
      border-color: var(--accent);
      box-shadow: 0 0 0 4px rgba(0,217,177,0.1), var(--shadow-lg);
    }
    .landing-input-icon { padding: 0 14px; color: var(--text-muted); display: flex; align-items: center; flex-shrink: 0; }
    .landing-input-icon svg { width: 16px; height: 16px; }
    .landing-input {
      flex: 1; padding: 13px 8px;
      font-size: 13.5px; font-family: 'Geist Mono', monospace;
      border: none; outline: none; color: var(--text-bright); background: transparent;
    }
    .landing-input::placeholder { color: var(--text-muted); font-family: 'Geist', sans-serif; }
    .landing-btn {
      padding: 11px 22px; margin: 4px;
      font-size: 13px; font-weight: 600;
      color: #000; background: var(--accent);
      border: none; border-radius: 7px; cursor: pointer;
      white-space: nowrap; transition: all .15s;
      font-family: 'Geist', sans-serif; letter-spacing: .2px;
    }
    .landing-btn:hover { background: #00f5c8; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,217,177,0.3); }
    .landing-examples { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
    .landing-example-label { font-size: 12px; color: var(--text-muted); align-self: center; }
    .landing-example {
      padding: 5px 13px; border: 1px solid var(--border);
      border-radius: 20px; font-size: 12px; color: var(--text-mid);
      cursor: pointer; transition: all .15s;
      background: var(--bg-card); font-family: 'Geist Mono', monospace;
    }
    .landing-example:hover { border-color: var(--accent); color: var(--accent); background: rgba(0,217,177,0.05); }
    .landing-features { display: flex; gap: 28px; margin-top: 44px; justify-content: center; flex-wrap: wrap; }
    .landing-feat { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-muted); }
    .landing-feat-icon { width: 16px; height: 16px; color: var(--accent); flex-shrink: 0; }

    /* History dropdown */
    .history-wrap { position: relative; width: 100%; }
    .history-dropdown {
      display: none; position: absolute; top: calc(100% + 4px); left: 0; right: 0;
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 8px; box-shadow: var(--shadow-lg); z-index: 50;
      max-height: 220px; overflow-y: auto;
    }
    .history-dropdown.open { display: block; }
    .history-item {
      display: flex; align-items: center; gap: 10px;
      padding: 10px 14px; cursor: pointer; transition: background .1s;
      font-size: 12.5px; font-family: 'Geist Mono', monospace; color: var(--text);
    }
    .history-item:hover { background: var(--bg-hover); }
    .history-item-icon { color: var(--text-muted); flex-shrink: 0; }
    .history-item-del { margin-left: auto; color: var(--text-muted); font-size: 11px; opacity: 0; transition: opacity .1s; }
    .history-item:hover .history-item-del { opacity: 1; }
    .history-empty { padding: 14px; text-align: center; color: var(--text-muted); font-size: 12px; font-family: 'Geist', sans-serif; }

    /* ── PROGRESS BAR ── */
    .progress-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,0.7);
      z-index: 200; align-items: center; justify-content: center;
      backdrop-filter: blur(4px);
    }
    .progress-overlay.active { display: flex; }
    .progress-box {
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 14px; padding: 32px 40px; min-width: 320px;
      text-align: center; box-shadow: var(--shadow-lg);
    }
    .progress-title {
      font-size: 16px; font-weight: 600; color: var(--text-bright);
      margin-bottom: 6px; font-family: 'Geist', sans-serif;
    }
    .progress-subtitle { font-size: 12px; color: var(--text-muted); margin-bottom: 24px; font-family: 'Geist Mono', monospace; }
    .progress-bar-wrap { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; margin-bottom: 16px; }
    .progress-bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--link)); border-radius: 2px; transition: width .4s ease; width: 0%; }
    .progress-step { font-size: 12px; color: var(--text-muted); min-height: 18px; }
    .progress-step span { color: var(--accent); }

    /* ── ERROR ── */
    .error-card { max-width: 480px; margin: 60px auto; padding: 40px 32px; text-align: center; }
    .error-icon { font-size: 40px; margin-bottom: 18px; }
    .error-title { font-size: 20px; font-weight: 600; color: var(--text-bright); margin-bottom: 10px; font-family: 'Geist', sans-serif; }
    .error-desc { font-size: 13px; color: var(--text-mid); line-height: 1.7; margin-bottom: 18px; }
    .error-hint { font-size: 12px; color: var(--text-muted); background: var(--bg-header); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; font-family: 'Geist Mono', monospace; text-align: left; }

    /* ── CONTAINER ── */
    .container { max-width: 1000px; margin: 0 auto; padding: 28px 20px 72px; }

    /* ── CARDS ── */
    .grid-1 { margin-bottom: 12px; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
    .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 12px; }
    .grid-4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; margin-bottom: 12px; }
    .card {
      border: 1px solid var(--border);
      border-radius: 8px; background: var(--bg-card);
      box-shadow: var(--shadow); overflow: hidden; min-width: 0;
      transition: border-color .2s;
    }
    .card:hover { border-color: var(--border-bright); }
    .card-header {
      padding: 11px 16px; background: var(--bg-header);
      border-bottom: 1px solid var(--border);
      font-size: 12.5px; font-weight: 600; color: var(--text-bright);
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 4px; font-family: 'Geist', sans-serif;
    }
    .card-header .label { font-size: 11px; font-weight: 400; color: var(--text-muted); }
    .card-body { padding: 14px 16px; overflow: hidden; word-break: break-word; overflow-wrap: break-word; }
    .card-body.scroll { max-height: 380px; overflow-y: auto; overflow-x: hidden; }

    /* ── AI BADGE ── */
    .ai-badge {
      font-size: 10px; font-weight: 700; letter-spacing: .5px;
      color: var(--accent); background: rgba(0,217,177,0.1);
      border: 1px solid rgba(0,217,177,0.25); border-radius: 4px;
      padding: 2px 7px; font-family: 'Geist', sans-serif;
    }

    /* ── CHAT ── */
    .chat-messages {
      min-height: 80px; max-height: 520px; overflow-y: auto;
      padding: 16px; display: flex; flex-direction: column; gap: 14px;
      border-bottom: 1px solid var(--border);
    }
    .chat-msg { display: flex; flex-direction: column; gap: 4px; max-width: 100%; }
    .chat-msg-label { font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: .8px; font-family: 'Geist Mono', monospace; }
    .chat-msg-text { font-size: 13px; color: var(--text); line-height: 1.55; }
    .chat-msg-system .chat-msg-text {
      background: var(--bg-header); border: 1px solid var(--border);
      border-radius: 8px; padding: 12px 14px; font-size: 13px; color: var(--text-mid);
    }
    .chat-msg-user { align-items: flex-end; }
    .chat-msg-user .chat-msg-text {
      background: var(--link-dim); color: #fff;
      border-radius: 10px 10px 2px 10px; padding: 9px 14px;
      display: inline-block; max-width: 80%;
    }
    .chat-msg-user .chat-msg-label { color: var(--link); }
    .chat-msg-assistant .chat-msg-text { width: 100%; }
    .chat-msg-assistant-ai .chat-msg-label { color: var(--accent); }
    .chat-msg-assistant-ai .chat-msg-text {
      background: rgba(0,217,177,0.04); border: 1px solid rgba(0,217,177,0.15);
      border-radius: 8px; padding: 12px 14px; width: 100%; font-size: 13px;
    }
    .chat-typing { display: flex; gap: 4px; padding: 10px 14px; background: var(--bg-header); border-radius: 8px; width: fit-content; }
    .chat-typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: bounce .8s infinite; }
    .chat-typing span:nth-child(2) { animation-delay: .15s; }
    .chat-typing span:nth-child(3) { animation-delay: .3s; }
    @keyframes bounce { 0%,80%,100% { transform:translateY(0); } 40% { transform:translateY(-6px); } }
    .chat-no-results { color: var(--text-muted); font-size: 13px; padding: 8px 0; }
    .chat-results-header { font-size: 11px; color: var(--text-muted); margin-bottom: 10px; text-transform: uppercase; letter-spacing: .5px; font-family: 'Geist Mono', monospace; }
    .chat-result-block { border: 1px solid var(--border); border-radius: 7px; overflow: hidden; margin-bottom: 10px; }
    .chat-result-block:last-child { margin-bottom: 0; }
    .chat-result-top { border-color: var(--accent); }
    .chat-result-file { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg-header); border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .chat-result-filename { font-size: 12px; font-weight: 600; color: var(--text); font-family: 'Geist Mono', monospace; flex: 1; }
    .chat-result-line { font-size: 11px; color: var(--text-muted); font-family: 'Geist Mono', monospace; }
    .chat-result-score { font-size: 10px; color: var(--accent); background: rgba(0,217,177,0.1); border-radius: 10px; padding: 1px 7px; font-family: 'Geist Mono', monospace; }
    .chat-code-block { background: var(--code-bg); padding: 12px 14px; font-family: 'Geist Mono', monospace; font-size: 12px; line-height: 1.6; color: var(--text); overflow-x: auto; white-space: pre; max-height: 240px; overflow-y: auto; margin: 0; }
    .chat-suggestions { padding: 12px 16px; display: flex; flex-wrap: wrap; gap: 7px; border-bottom: 1px solid var(--border); }
    .suggestion-btn {
      padding: 5px 12px; font-size: 12px;
      border: 1px solid var(--border); border-radius: 20px;
      background: var(--bg-header); color: var(--text-mid);
      cursor: pointer; transition: all .15s; white-space: nowrap;
      font-family: 'Geist', sans-serif;
    }
    .suggestion-btn:hover { border-color: var(--accent); color: var(--accent); background: rgba(0,217,177,0.05); }
    .chat-input-row { display: flex; gap: 8px; padding: 12px 16px; }
    .chat-input {
      flex: 1; padding: 9px 13px; font-size: 13px;
      border: 1px solid var(--border); border-radius: 7px;
      outline: none; color: var(--text-bright); background: var(--bg-header);
      transition: border-color .2s; font-family: 'Geist', sans-serif;
    }
    .chat-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0,217,177,0.08); }
    .chat-send-btn {
      padding: 9px 18px; font-size: 12.5px; font-weight: 600;
      color: #000; background: var(--accent); border: none; border-radius: 7px;
      cursor: pointer; transition: all .15s; white-space: nowrap;
      font-family: 'Geist', sans-serif;
    }
    .chat-send-btn:hover { background: #00f5c8; }

    /* ── PROFILE ── */
    .perfil-hero { display: flex; gap: 20px; align-items: flex-start; }
    .perfil-avatar { width: 80px; height: 80px; border-radius: 50%; border: 2px solid var(--border-bright); flex-shrink: 0; background: var(--bg-header); }
    .perfil-info { flex: 1; min-width: 0; }
    .perfil-nombre { font-size: 18px; font-weight: 700; color: var(--text-bright); font-family: 'Geist', sans-serif; }
    .perfil-login { font-size: 13px; color: var(--text-muted); margin-bottom: 6px; font-family: 'Geist Mono', monospace; }
    .perfil-bio { font-size: 13px; color: var(--text); line-height: 1.5; }
    .info-table { display: flex; flex-direction: column; gap: 0; }
    .info-row { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--bg-hover); font-size: 13px; align-items: center; min-width: 0; }
    .info-row:last-child { border-bottom: none; }
    .info-key { font-size: 10.5px; font-weight: 700; color: var(--text-muted); min-width: 80px; flex-shrink: 0; text-transform: uppercase; letter-spacing: .5px; font-family: 'Geist', sans-serif; }
    .info-link { color: var(--link); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .info-link:hover { text-decoration: underline; }

    /* ── REPOS ── */
    .members-grid { display: flex; flex-wrap: wrap; gap: 10px; }
    .member-item { display: flex; align-items: center; gap: 8px; padding: 7px 11px; border: 1px solid var(--border); border-radius: 7px; background: var(--bg-header); }
    .member-avatar { width: 24px; height: 24px; border-radius: 50%; border: 1px solid var(--border); }
    .member-login { font-size: 12px; font-weight: 500; color: var(--link); font-family: 'Geist Mono', monospace; }
    .repo-card-item { padding: 12px 0; border-bottom: 1px solid var(--border); }
    .repo-card-item:last-child { border-bottom: none; }
    .repo-card-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }
    .repo-card-name { font-size: 13px; font-weight: 600; color: var(--link); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .repo-card-name:hover { text-decoration: underline; }
    .repo-card-stars { font-size: 12px; color: var(--gold); font-family: 'Geist Mono', monospace; flex-shrink: 0; }
    .repo-card-desc { font-size: 12px; color: var(--text-mid); margin-bottom: 8px; line-height: 1.4; }
    .repo-card-bar { height: 3px; background: var(--border); border-radius: 2px; margin-bottom: 8px; overflow: hidden; }
    .repo-card-bar-fill { height: 100%; border-radius: 2px; }
    .repo-card-meta { display: flex; align-items: center; gap: 10px; font-size: 11px; color: var(--text-muted); }
    .repo-lang-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
    .repo-card-lang { font-family: 'Geist Mono', monospace; font-size: 11px; }
    .repo-card-updated { margin-left: auto; }
    .repos-filter-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    .filter-input { flex: 1; min-width: 140px; padding: 7px 11px; font-size: 12px; border: 1px solid var(--border); border-radius: 6px; outline: none; color: var(--text); background: var(--bg-header); font-family: 'Geist', sans-serif; }
    .filter-input:focus { border-color: var(--accent); }
    .filter-select { padding: 7px 10px; font-size: 12px; border: 1px solid var(--border); border-radius: 6px; outline: none; color: var(--text); background: var(--bg-header); cursor: pointer; font-family: 'Geist', sans-serif; }
    .filter-check { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted); cursor: pointer; white-space: nowrap; }
    .repos-list-all { max-height: 420px; overflow-y: auto; overflow-x: hidden; }
    .repo-row-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--bg-hover); min-width: 0; }
    .repo-row-item:last-child { border-bottom: none; }
    .repo-row-left { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
    .repo-row-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; font-size: 11px; color: var(--text-muted); }
    .repo-row-desc { font-size: 11px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .repo-fork-badge { font-size: 10px; color: var(--text-muted); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; background: var(--bg-header); }

    /* ── LANGUAGES ── */
    .langs-visual { display: flex; flex-direction: column; gap: 16px; }
    .lang-stack { display: flex; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; }
    .lang-stack-seg { height: 100%; border-radius: 2px; }
    .lang-list { display: flex; flex-direction: column; gap: 8px; }
    .lang-item { display: flex; align-items: center; gap: 8px; font-size: 12px; min-width: 0; }
    .lang-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
    .lang-name { min-width: 80px; font-weight: 500; color: var(--text); font-family: 'Geist Mono', monospace; font-size: 11.5px; }
    .lang-bar-wrap { flex: 1; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
    .lang-bar-fill { height: 100%; border-radius: 3px; transition: width .5s ease; }
    .lang-pct { min-width: 36px; text-align: right; color: var(--text-muted); font-family: 'Geist Mono', monospace; font-size: 11px; }
    .lang-count { min-width: 52px; color: var(--text-muted); font-size: 11px; }

    /* ── TIPS ── */
    .tips-intro { font-size: 13px; color: var(--text); margin-bottom: 16px; line-height: 1.6; }
    .tips-intro code { font-family: 'Geist Mono', monospace; font-size: 12px; background: var(--bg-header); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
    .tips-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
    .tip-item { background: var(--bg-header); border: 1px solid var(--border); border-radius: 7px; padding: 13px; display: flex; flex-direction: column; gap: 6px; transition: border-color .2s; }
    .tip-item:hover { border-color: var(--border-bright); }
    .tip-title { font-size: 12px; font-weight: 600; color: var(--text-bright); }
    .tip-desc { font-size: 12px; color: var(--text-muted); line-height: 1.4; }
    .tip-link { font-size: 12px; color: var(--link); text-decoration: none; }
    .tip-link:hover { text-decoration: underline; }
    .tip-code { font-family: 'Geist Mono', monospace; font-size: 10px; color: var(--text-muted); background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 7px 9px; word-break: break-all; line-height: 1.5; }

    /* ── REPO PAGE ── */
    .repo-card .card-body { display: flex; flex-direction: column; gap: 10px; }
    .repo-name { font-size: 20px; font-weight: 700; color: var(--link); word-break: break-all; font-family: 'Geist', sans-serif; }
    .repo-desc { color: var(--text-mid); font-size: 13.5px; line-height: 1.5; }
    .badges { display: flex; flex-wrap: wrap; gap: 6px; }
    .badge { padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 500; border: 1px solid var(--border); background: var(--bg-header); color: var(--text-muted); white-space: nowrap; font-family: 'Geist', sans-serif; }
    .stat-card .card-body { text-align: center; padding: 20px 8px; }
    .stat-value { font-size: 26px; font-weight: 700; color: var(--text-bright); display: block; font-family: 'Geist', sans-serif; letter-spacing: -.5px; }
    .stat-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; font-family: 'Geist Mono', monospace; }
    .text-content { font-size: 13px; line-height: 1.7; color: var(--text); word-break: break-word; overflow-wrap: break-word; }
    .text-content strong { color: var(--text-bright); }
    .text-content code { font-family: 'Geist Mono', monospace; font-size: 12px; background: var(--bg-header); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
    .tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
    .tag { padding: 3px 10px; border-radius: 20px; font-size: 12px; border: 1px solid var(--border); background: var(--bg-header); color: var(--text); font-family: 'Geist Mono', monospace; white-space: nowrap; }
    .file-list { list-style: none; }
    .file-list li { padding: 6px 0; border-bottom: 1px solid var(--bg-hover); color: var(--text); font-size: 12px; font-family: 'Geist Mono', monospace; display: flex; align-items: center; gap: 8px; min-width: 0; }
    .file-list li:last-child { border-bottom: none; }
    .file-ext { font-size: 10px; color: var(--text-muted); background: var(--bg-header); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; min-width: 32px; text-align: center; flex-shrink: 0; }
    .contrib-list { list-style: none; }
    .contrib-list li { padding: 7px 0; border-bottom: 1px solid var(--bg-hover); font-size: 13px; display: flex; justify-content: space-between; align-items: center; gap: 8px; min-width: 0; }
    .contrib-list li:last-child { border-bottom: none; }
    .contrib-name { font-weight: 500; color: var(--link); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: 'Geist Mono', monospace; }
    .contrib-count { font-size: 11px; color: var(--text-muted); font-family: 'Geist Mono', monospace; flex-shrink: 0; }
    .readme-box { font-family: 'Geist Mono', monospace; font-size: 12px; line-height: 1.7; color: var(--text); white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; }
    .uso-desc { font-size: 13px; line-height: 1.7; color: var(--text); margin-bottom: 16px; padding-bottom: 14px; border-bottom: 1px solid var(--border); word-break: break-word; }
    .uso-desc code { font-family: 'Geist Mono', monospace; font-size: 12px; background: var(--bg-header); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
    .steps { display: flex; flex-direction: column; gap: 0; }
    .step { display: flex; gap: 12px; align-items: flex-start; padding: 13px 0; border-bottom: 1px solid var(--border); }
    .step:last-child { border-bottom: none; }
    .step-num { width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0; background: var(--step-bg); color: var(--step-num); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; font-family: 'Geist Mono', monospace; margin-top: 2px; }
    .step-content { flex: 1; min-width: 0; }
    .step-title { font-size: 12px; font-weight: 600; color: var(--text-bright); margin-bottom: 5px; }
    .step-cmd { font-family: 'Geist Mono', monospace; font-size: 12px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 5px; padding: 7px 11px; color: var(--accent); word-break: break-all; overflow-wrap: break-word; display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .step-cmd span { flex: 1; min-width: 0; }
    .copy-btn { background: none; border: none; cursor: pointer; color: var(--text-muted); font-size: 11px; padding: 0; flex-shrink: 0; font-family: 'Geist', sans-serif; transition: color .1s; }
    .copy-btn:hover { color: var(--accent); }
    .code-example { font-family: 'Geist Mono', monospace; font-size: 12px; line-height: 1.6; background: var(--code-bg); border: 1px solid var(--border); border-radius: 5px; padding: 11px 13px; color: var(--text-mid); white-space: pre-wrap; word-break: break-word; overflow-wrap: break-word; margin-top: 8px; }
    .code-example-label { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; margin-top: 12px; font-family: 'Geist Mono', monospace; }
    .checklist { list-style: none; display: flex; flex-direction: column; gap: 10px; }
    .checklist li { display: flex; align-items: center; gap: 10px; font-size: 13px; }
    .check-icon { width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; }
    .check-yes { background: rgba(0,217,177,0.1); color: var(--accent); border: 1px solid rgba(0,217,177,0.3); }
    .check-no { background: var(--bg-header); color: var(--text-muted); border: 1px solid var(--border); }
    .timeline { display: flex; flex-direction: column; gap: 0; }
    .timeline-item { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--bg-hover); align-items: flex-start; min-width: 0; }
    .timeline-item:last-child { border-bottom: none; }
    .timeline-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex-shrink: 0; margin-top: 6px; opacity: .5; }
    .timeline-content { flex: 1; min-width: 0; }
    .timeline-msg { font-size: 12px; color: var(--text); line-height: 1.4; word-break: break-word; }
    .timeline-meta { font-size: 11px; color: var(--text-muted); margin-top: 2px; font-family: 'Geist Mono', monospace; }
    .feature-list { list-style: none; display: flex; flex-direction: column; gap: 10px; }
    .feature-key { font-weight: 700; color: var(--text-bright); font-size: 10.5px; text-transform: uppercase; letter-spacing: .6px; margin-bottom: 2px; font-family: 'Geist', sans-serif; }
    .feature-val { font-family: 'Geist Mono', monospace; font-size: 12px; color: var(--text-muted); word-break: break-word; }
    .type-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid var(--border); background: var(--bg-header); font-family: 'Geist', sans-serif; }
    .type-webapp { border-color: rgba(0,217,177,0.4); color: var(--accent); background: rgba(0,217,177,0.05); }
    .type-cli { border-color: rgba(227,162,26,0.4); color: var(--gold); background: rgba(227,162,26,0.05); }
    .type-library { border-color: rgba(77,159,255,0.4); color: var(--link); background: rgba(77,159,255,0.05); }
    .type-service { border-color: rgba(248,81,73,0.4); color: var(--red); background: rgba(248,81,73,0.05); }
    .release-list { list-style: none; display: flex; flex-direction: column; gap: 0; }
    .release-item { display: flex; justify-content: space-between; align-items: center; padding: 9px 0; border-bottom: 1px solid var(--bg-hover); font-size: 13px; gap: 8px; min-width: 0; }
    .release-item:last-child { border-bottom: none; }
    .release-tag { font-family: 'Geist Mono', monospace; font-size: 12px; font-weight: 600; color: var(--accent); flex-shrink: 0; }
    .release-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); font-size: 12px; }
    .release-date { font-size: 11px; color: var(--text-muted); flex-shrink: 0; font-family: 'Geist Mono', monospace; }
    .diagram-wrap { overflow-x: auto; overflow-y: hidden; padding: 8px 0; }
    .diagram-wrap svg { display: block; min-width: 260px; max-width: 100%; height: auto; }
    .section-divider {
      font-size: 10.5px; font-weight: 700; text-transform: uppercase;
      letter-spacing: 1.2px; color: var(--text-muted);
      padding: 22px 0 9px; border-bottom: 1px solid var(--border);
      margin-bottom: 13px; font-family: 'Geist', sans-serif;
      display: flex; align-items: center; gap: 10px;
    }
    .section-divider::after { content: ''; flex: 1; height: 1px; background: var(--border); }
    .lang-content { display: none; }
    .lang-content.active { display: block; }
    .lang-inline { display: none; }
    .lang-inline.active { display: inline; }
    .footer { margin-top: 60px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 12px; text-align: center; font-family: 'Geist', sans-serif; }
    .footer a { color: var(--text-mid); text-decoration: none; }
    .footer a:hover { color: var(--accent); }

    /* Commit graph */
    .commit-graph-wrap { padding: 8px 0; }

    /* ── ANIMATIONS ── */
    @keyframes fadeUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
    .container > * { animation: fadeUp .3s ease both; }
    .container > *:nth-child(1) { animation-delay: .05s; }
    .container > *:nth-child(2) { animation-delay: .1s; }
    .container > *:nth-child(3) { animation-delay: .15s; }
    .container > *:nth-child(4) { animation-delay: .2s; }
    .container > *:nth-child(5) { animation-delay: .25s; }

    /* ── RESPONSIVE ── */
    @media(max-width:720px) {
      .grid-2,.grid-3,.grid-4 { grid-template-columns: 1fr; }
      .nav { padding: 0 14px; flex-wrap: wrap; height: auto; padding-top: 8px; padding-bottom: 8px; gap: 8px; }
      .nav-search-wrap { width: 100%; order: 3; }
      .nav-search-input { width: 100%; }
      .container { padding: 20px 14px 48px; }
      .stat-value { font-size: 20px; }
      .perfil-hero { flex-direction: column; align-items: center; text-align: center; }
      .tips-grid { grid-template-columns: 1fr; }
      .repo-row-right { display: none; }
      .landing-title { font-size: 30px; }
      .btn-github span,.landing-example-label { display: none; }
    }
  </style>
</head>
<body>

<!-- Progress overlay -->
<div class="progress-overlay" id="progress-overlay">
  <div class="progress-box">
    <div class="progress-title">Analyzing repository</div>
    <div class="progress-subtitle" id="progress-repo-name">—</div>
    <div class="progress-bar-wrap"><div class="progress-bar-fill" id="progress-bar"></div></div>
    <div class="progress-step" id="progress-step">Starting...</div>
  </div>
</div>

<nav class="nav">
  <div class="nav-left">
    <a href="/" class="nav-logo">
<img src="{{ url_for('static', filename='img/logo.png') }}" alt="Logo" style="height:40px; width:auto;">
    </a>
    <form method="POST" id="nav-form" style="display:contents" onsubmit="showProgress(this)">
      <div class="nav-search-wrap">
        <span class="nav-search-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"/></svg>
        </span>
        <div class="history-wrap">
          <input
            class="nav-search-input"
            name="repo"
            id="nav-search-input"
            placeholder="Digite el repositorio, organizacion o perfil"
            value="{{ repo_url }}"
            autocomplete="off"
            spellcheck="false"
            onfocus="showHistory()"
          >
          <div class="history-dropdown" id="history-dropdown"></div>
        </div>
        <button type="submit" class="nav-search-btn">
          <span class="lang-inline active" data-l="es">Analizar</span>
          <span class="lang-inline" data-l="en">Analyze</span>
        </button>
      </div>
    </form>
  </div>
  <div class="nav-right">
    <a href="https://github.com/ChristianUtria/enkiDOCS" target="_blank" class="btn-github">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.929.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/></svg>
      <span>GitHub</span>
    </a>
    <div class="lang-dropdown">
      <button class="btn-nav" onclick="toggleLangMenu()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 010 20M12 2a15.3 15.3 0 000 20"/></svg>
        <span id="lang-label">ES</span>
      </button>
      <div class="lang-menu" id="lang-menu">
        <div class="lang-option active" data-lang="es" onclick="setLang('es')"><span class="lang-flag">🇪🇸</span> Español</div>
        <div class="lang-option" data-lang="en" onclick="setLang('en')"><span class="lang-flag">🇬🇧</span> English</div>
        <div class="lang-option" data-lang="fr" onclick="setLang('fr')"><span class="lang-flag">🇫🇷</span> Français</div>
        <div class="lang-option" data-lang="pt" onclick="setLang('pt')"><span class="lang-flag">🇧🇷</span> Português</div>
        <div class="lang-option" data-lang="de" onclick="setLang('de')"><span class="lang-flag">🇩🇪</span> Deutsch</div>
      </div>
    </div>
    <button class="btn-nav" onclick="toggleTheme()">
      <svg id="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
      <svg id="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:none"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
    </button>
  </div>
</nav>

{% if not resultado %}
<div class="landing">
  <div class="landing-inner">

    <h1 class="landing-title">
      <span class="lang-content active" data-l="es">Entiende cualquier<br>repo de <em>GitHub</em></span>
      <span class="lang-content" data-l="en">Understand any<br><em>GitHub</em> repository</span>
    </h1>
    <p class="landing-subtitle">
      <span class="lang-content active" data-l="es">Diagramas UML reales, análisis de código con IA, guías de instalación automáticas y explorador de código — sin configuración.</span>
      <span class="lang-content" data-l="en">Real UML diagrams, AI-powered code analysis, auto install guides and code explorer — zero config.</span>
    </p>
    <form method="POST" onsubmit="showProgress(this)">
      <div class="landing-form-wrap">
        <span class="landing-input-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 00-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0020 4.77 5.07 5.07 0 0019.91 1S18.73.65 16 2.48a13.38 13.38 0 00-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 005 4.77a5.44 5.44 0 00-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 009 18.13V22"/></svg>
        </span>
        <input class="landing-input" name="repo" id="landing-input" placeholder="https://github.com/usuario/repositorio" value="{{ repo_url }}" autocomplete="off" spellcheck="false">
        <button type="submit" class="landing-btn">
          <span class="lang-content active" data-l="es">Analizar →</span>
          <span class="lang-content" data-l="en">Analyze →</span>
        </button>
      </div>
    </form>

    <div class="landing-features">
      <div class="landing-feat">
        <svg class="landing-feat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
        <span class="lang-inline active" data-l="es">Diagramas UML reales</span><span class="lang-inline" data-l="en">Real UML diagrams</span>
      </div>
      <div class="landing-feat">
        <svg class="landing-feat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        <span class="lang-inline active" data-l="es">IA integrada</span><span class="lang-inline" data-l="en">AI-powered chat</span>
      </div>
      <div class="landing-feat">
        <svg class="landing-feat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
        <span class="lang-inline active" data-l="es">Explorador de código</span><span class="lang-inline" data-l="en">Code explorer</span>
      </div>
    </div>
  </div>
</div>
{% else %}
<div class="container">
  {{ resultado|safe }}
  <div class="footer">
    EnkiDocs · Flask + GitHub API + Claude AI ·
    <a href="https://github.com/ChristianUtria/enkiDOCS" target="_blank">Open Source</a>
  </div>
</div>
{% endif %}

<script>
const html = document.documentElement;

// ── THEME ──
function toggleTheme() {
  const dark = html.dataset.theme !== 'dark';
  html.dataset.theme = dark ? 'dark' : 'light';
  localStorage.setItem('theme', html.dataset.theme);
  updateThemeIcon();
}
function updateThemeIcon() {
  const dark = html.dataset.theme === 'dark';
  document.getElementById('icon-moon').style.display = dark ? 'none' : 'block';
  document.getElementById('icon-sun').style.display  = dark ? 'block' : 'none';
}

// ── LANG ──
const LANGS = { es:{label:'ES'}, en:{label:'EN'}, fr:{label:'FR'}, pt:{label:'PT'}, de:{label:'DE'} };
function toggleLangMenu() { document.getElementById('lang-menu').classList.toggle('open'); }
document.addEventListener('click', function(e) {
  if (!e.target.closest('.lang-dropdown')) document.getElementById('lang-menu').classList.remove('open');
  if (!e.target.closest('.history-wrap')) closeHistory();
});
function setLang(lang) {
  html.dataset.lang = lang;
  localStorage.setItem('lang', lang);
  document.getElementById('lang-label').textContent = LANGS[lang]?.label || lang.toUpperCase();
  document.getElementById('lang-menu').classList.remove('open');
  document.querySelectorAll('.lang-option').forEach(el => el.classList.toggle('active', el.dataset.lang === lang));
  document.querySelectorAll('.lang-content,.lang-inline').forEach(el => {
    const match = el.dataset.l === lang;
    const fallback = el.dataset.l === 'en' && !document.querySelector('[data-l="'+lang+'"]');
    el.classList.toggle('active', match || fallback);
  });
}

// ── HISTORY ──
function getHistory() {
  try { return JSON.parse(localStorage.getItem('enkidocs_history') || '[]'); } catch(e) { return []; }
}
function addHistory(url) {
  if (!url || url.length < 5) return;
  let hist = getHistory().filter(h => h !== url);
  hist.unshift(url);
  hist = hist.slice(0, 8);
  localStorage.setItem('enkidocs_history', JSON.stringify(hist));
}
function removeHistory(url, e) {
  e.stopPropagation();
  let hist = getHistory().filter(h => h !== url);
  localStorage.setItem('enkidocs_history', JSON.stringify(hist));
  renderHistory();
}
function renderHistory() {
  const drop = document.getElementById('history-dropdown');
  if (!drop) return;
  const hist = getHistory();
  if (!hist.length) {
    drop.innerHTML = '<div class="history-empty">No recent searches</div>';
    return;
  }
  drop.innerHTML = hist.map(url => `
    <div class="history-item" onclick="selectHistory('${url.replace(/'/g,"\\'")}')">
      <svg class="history-item-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      ${url}
      <span class="history-item-del" onclick="removeHistory('${url.replace(/'/g,"\\'")}', event)">✕</span>
    </div>
  `).join('');
}
function showHistory() {
  renderHistory();
  const drop = document.getElementById('history-dropdown');
  if (drop && getHistory().length) drop.classList.add('open');
}
function closeHistory() {
  const drop = document.getElementById('history-dropdown');
  if (drop) drop.classList.remove('open');
}
function selectHistory(url) {
  const input = document.getElementById('nav-search-input');
  if (input) { input.value = url; closeHistory(); }
}

// ── PROGRESS ──
const STEPS_ES = ['Conectando con GitHub API...', 'Analizando repositorio...', 'Leyendo archivos de código...', 'Generando diagramas...', 'Preparando análisis...'];
const STEPS_EN = ['Connecting to GitHub API...', 'Analyzing repository...', 'Reading code files...', 'Generating diagrams...', 'Preparing analysis...'];
function showProgress(form) {
  const input = form.querySelector('input[name="repo"]');
  const url = input ? input.value.trim() : '';
  if (url) addHistory(url);
  const overlay = document.getElementById('progress-overlay');
  const bar = document.getElementById('progress-bar');
  const step = document.getElementById('progress-step');
  const repoName = document.getElementById('progress-repo-name');
  if (!overlay) return;
  const lang = html.dataset.lang || 'es';
  const steps = lang === 'es' ? STEPS_ES : STEPS_EN;
  repoName.textContent = url || '—';
  overlay.classList.add('active');
  let pct = 0; let si = 0;
  const iv = setInterval(() => {
    pct = Math.min(pct + (pct < 60 ? 8 : pct < 85 ? 3 : 1), 95);
    bar.style.width = pct + '%';
    if (si < steps.length) { step.textContent = steps[si++]; }
  }, 600);
}

// ── EXAMPLE ──
function setExample(url) {
  const inputs = document.querySelectorAll('input[name="repo"]');
  inputs.forEach(i => i.value = url);
  const landingInput = document.querySelector('.landing-input');
  if (landingInput) { addHistory(url); landingInput.closest('form').submit(); }
}

// ── COPY CMD ──
function copyCmd(btn) {
  const text = btn.previousElementSibling.textContent.trim();
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'copied ✓';
    btn.style.color = 'var(--accent)';
    setTimeout(() => { btn.textContent = 'copy'; btn.style.color = ''; }, 1500);
  });
}

// ── INIT ──
const savedTheme = localStorage.getItem('theme') || 'dark';
const savedLang  = localStorage.getItem('lang');
html.dataset.theme = savedTheme;
updateThemeIcon();
if (savedLang && LANGS[savedLang]) setLang(savedLang);

// Close overlay if page loaded (back navigation etc.)
window.addEventListener('pageshow', () => {
  const overlay = document.getElementById('progress-overlay');
  if (overlay) overlay.classList.remove('active');
});
</script>
</body>
</html>
"""


@app.route('/', methods=['GET', 'POST'])
def home():
    resultado = ""; repo_url = ""
    if request.method == 'POST':
        repo_url = request.form.get('repo', '').strip()
        tipo_url, param1, param2 = detectar_tipo(repo_url)

        if not tipo_url:
            resultado = error_html("invalid_url", repo_url)
        else:
            try:
                if tipo_url == "perfil":
                    pdata = get_perfil_info(param1)
                    if pdata is None:
                        resultado = error_html("user_not_found", param1)
                    else:
                        resultado = construir_perfil_html(pdata)

                elif tipo_url == "repo":
                    owner = param1; repo = param2
                    data = get_repo_info(owner, repo)
                    if data is None:
                        resultado = error_html("repo_not_found", f"{owner}/{repo}")
                    else:
                        info = data["info"]; uso = analizar_uso(data)
                        actividad = analizar_actividad(data); exp_es, exp_en = generar_explicacion(data)
                        stars = info.get("stargazers_count", 0); forks = info.get("forks_count", 0)
                        issues = info.get("open_issues_count", 0); watchers = info.get("watchers_count", 0)
                        badges = ""
                        if info.get("language"): badges += f'<span class="badge">{info["language"]}</span>'
                        if info.get("license") and info["license"].get("spdx_id"): badges += f'<span class="badge">{info["license"]["spdx_id"]}</span>'
                        for t in data.get("topics", [])[:5]: badges += f'<span class="badge">{t}</span>'
                        tipo_labels = {"webapp": ("Web App", "Web App"), "cli": ("CLI Tool", "CLI Tool"), "library": ("Library", "Library"), "service": ("Service", "Service")}
                        tipo = uso["tipo"]; tipo_es, tipo_en = tipo_labels.get(tipo, ("Project", "Project"))
                        tipo_html = f'<span class="type-badge type-{tipo}"><span class="lang-inline active" data-l="es">{tipo_es}</span><span class="lang-inline" data-l="en">{tipo_en}</span></span>'
                        langs_html = "".join(f'<span class="tag">{l}</span>' for l in data["languages"].keys())
                        archivos_html = "".join(f'<li><span class="file-ext">{(a.split(".")[-1].lower() if "." in a else "dir")[:6]}</span><span>{a}</span></li>' for a in data["contents"])
                        contributors_html = ""
                        if isinstance(data["contributors"], list):
                            for c in data["contributors"]:
                                contributors_html += f'<li><span class="contrib-name">{c.get("login", "")}</span><span class="contrib-count">{c.get("contributions", 0)} commits</span></li>'
                        steps_html = "".join(f'<div class="step"><div class="step-num">{i}</div><div class="step-content"><div class="step-title">{t}</div><div class="step-cmd"><span>{cmd}</span><button class="copy-btn" onclick="copyCmd(this)">copy</button></div></div></div>' for i, (t, cmd) in enumerate(uso["pasos"], 1))
                        ejemplos_html = ""
                        if uso["ejemplos"]:
                            ejemplos_html = '<div class="code-example-label"><span class="lang-inline active" data-l="es">Ejemplos del README:</span><span class="lang-inline" data-l="en">Examples from README:</span></div>'
                            for ej in uso["ejemplos"]: ejemplos_html += f'<div class="code-example">{ej}</div>'
                        checklist_html = ""
                        for ok, label_es, label_en in [(uso["tiene_tests"], "Tests", "Tests"), (uso["tiene_docker"], "Docker", "Docker"), (uso["tiene_ci"], "CI/CD", "CI/CD"), (uso["tiene_docs"], "Documentación", "Documentation"), (uso["tiene_license"], "Licencia", "License")]:
                            icon = "✓" if ok else "·"; cls = "check-yes" if ok else "check-no"
                            checklist_html += f'<li><span class="check-icon {cls}">{icon}</span><span class="lang-inline active" data-l="es">{label_es}</span><span class="lang-inline" data-l="en">{label_en}</span></li>'
                        features_html = ""
                        if uso["features"]:
                            for key, val in uso["features"]: features_html += f'<li><div class="feature-key">{key}</div><div class="feature-val">{val}</div></li>'
                        timeline_html = "".join(f'<div class="timeline-item"><div class="timeline-dot"></div><div class="timeline-content"><div class="timeline-msg">{item["mensaje"]}</div><div class="timeline-meta">{item["fecha"]} &middot; {item["autor"]}</div></div></div>' for item in actividad)

                        # Commit graph data
                        commit_dates = []
                        if isinstance(data["commits"], list):
                            for c in data["commits"]:
                                d = c.get("commit",{}).get("author",{}).get("date","")[:10]
                                if d: commit_dates.append(d)
                        commit_dates_json = json.dumps(commit_dates)

                        releases_html = ""
                        for rel in data["releases"][:3]:
                            releases_html += f'<li class="release-item"><span class="release-tag">{rel.get("tag_name", "")}</span><span class="release-name">{rel.get("name", rel.get("tag_name", ""))[:36]}</span><span class="release-date">{rel.get("published_at", "")[:10]}</span></li>'
                        readme_html = ""
                        if data.get("readme"):
                            readme_html = f'<div class="grid-1"><div class="card"><div class="card-header">README <span class="label">{info.get("name")}</span></div><div class="card-body scroll"><div class="readme-box">{data["readme"]}</div></div></div></div>'
                        d_flujo = generar_diagrama_flujo(data); d_estruc = generar_diagrama_estructura(data)
                        d_arq = generar_diagrama_arquitectura(data); d_deps = generar_diagrama_deps(data)
                        seccion_uml = construir_seccion_uml(data)
                        seccion_preguntas = construir_seccion_preguntas(data)

                        # Commit frequency graph HTML
                        commit_graph_html = f"""
                        <div class="card"><div class="card-header">
                          <span class="lang-content active" data-l="es">Actividad de commits</span>
                          <span class="lang-content" data-l="en">Commit activity</span>
                        </div><div class="card-body commit-graph-wrap">
                          <canvas id="commit-graph" height="80"></canvas>
                        </div></div>
                        <script>
                        (function(){{
                          const dates = {commit_dates_json};
                          const canvas = document.getElementById('commit-graph');
                          if (!canvas || !dates.length) return;
                          canvas.width = canvas.parentElement.offsetWidth - 32 || 400;
                          const ctx = canvas.getContext('2d');
                          const isDark = document.documentElement.dataset.theme === 'dark';
                          const counts = {{}};
                          dates.forEach(d => {{ counts[d] = (counts[d]||0)+1; }});
                          const labels = Object.keys(counts).sort();
                          const vals = labels.map(l => counts[l]);
                          const maxVal = Math.max(...vals, 1);
                          const w = canvas.width, h = canvas.height;
                          const pad = 8, barW = Math.max(2, (w - pad*2) / labels.length - 3);
                          ctx.clearRect(0, 0, w, h);
                          labels.forEach((label, i) => {{
                            const x = pad + i * ((w - pad*2) / labels.length);
                            const barH = ((vals[i] / maxVal) * (h - pad*2));
                            const y = h - pad - barH;
                            ctx.fillStyle = isDark ? 'rgba(0,217,177,0.5)' : 'rgba(0,168,138,0.5)';
                            ctx.beginPath();
                            ctx.roundRect ? ctx.roundRect(x, y, barW, barH, [3,3,0,0]) : ctx.rect(x, y, barW, barH);
                            ctx.fill();
                          }});
                          if (labels.length > 0) {{
                            ctx.fillStyle = isDark ? '#4a5568' : '#a0aec0';
                            ctx.font = '10px Geist Mono, monospace';
                            ctx.textAlign = 'left';
                            ctx.fillText(labels[0], pad, h - 1);
                            ctx.textAlign = 'right';
                            ctx.fillText(labels[labels.length-1], w - pad, h - 1);
                          }}
                        }})();
                        </script>"""

                        resultado = f"""
                        <div class="section-divider"><span class="lang-inline active" data-l="es">Repositorio</span><span class="lang-inline" data-l="en">Repository</span></div>
                        <div class="grid-1"><div class="card repo-card"><div class="card-header">{tipo_html}<span class="label">{info.get('full_name', '')}</span></div><div class="card-body"><div class="repo-name">{info.get('name')}</div><div class="repo-desc">{info.get('description') or '—'}</div><div class="badges">{badges}</div></div></div></div>
                        <div class="grid-4"><div class="card stat-card"><div class="card-body"><span class="stat-value">{stars:,}</span><div class="stat-label">stars</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{forks:,}</span><div class="stat-label">forks</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{issues}</span><div class="stat-label">open issues</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{watchers:,}</span><div class="stat-label">watchers</div></div></div></div>
                        <div class="section-divider"><span class="lang-inline active" data-l="es">Descripcion</span><span class="lang-inline" data-l="en">About</span></div>
                        <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Que es</span><span class="lang-content" data-l="en">What it is</span></div><div class="card-body scroll"><div class="text-content"><span class="lang-content active" data-l="es">{exp_es}</span><span class="lang-content" data-l="en">{exp_en}</span></div></div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Lenguajes</span><span class="lang-content" data-l="en">Languages</span></div><div class="card-body"><div class="tag-list">{langs_html}</div></div></div></div>
                        <div class="section-divider"><span class="lang-inline active" data-l="es">Como se usa</span><span class="lang-inline" data-l="en">How to use</span></div>
                        <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Instalacion</span><span class="lang-content" data-l="en">Installation</span></div><div class="card-body scroll"><div class="uso-desc"><span class="lang-content active" data-l="es">{uso['uso_desc_es']}</span><span class="lang-content" data-l="en">{uso['uso_desc_en']}</span></div><div class="steps">{steps_html}</div>{ejemplos_html}</div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Incluye</span><span class="lang-content" data-l="en">Includes</span></div><div class="card-body"><ul class="checklist">{checklist_html}</ul></div></div></div>
                        {"" if not features_html else f'<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Analisis del codigo</span><span class="lang-content" data-l="en">Code analysis</span></div><div class="card-body scroll"><ul class="feature-list">{features_html}</ul></div></div></div>'}
                        {seccion_preguntas}
                        <div class="section-divider"><span class="lang-inline active" data-l="es">Actividad</span><span class="lang-inline" data-l="en">Activity</span></div>
                        <div class="grid-2">{commit_graph_html}<div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Contribuidores</span><span class="lang-content" data-l="en">Contributors</span></div><div class="card-body scroll"><ul class="contrib-list">{contributors_html}</ul></div></div></div>
                        <div class="grid-{"3" if releases_html else "2"}"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Commits recientes</span><span class="lang-content" data-l="en">Recent commits</span></div><div class="card-body scroll"><div class="timeline">{timeline_html}</div></div></div>{"" if not releases_html else f'<div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Versiones</span><span class="lang-content" data-l="en">Releases</span></div><div class="card-body scroll"><ul class="release-list">{releases_html}</ul></div></div>'}<div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Top contributores</span><span class="lang-content" data-l="en">Top contributors</span></div><div class="card-body scroll"><ul class="contrib-list">{contributors_html}</ul></div></div></div>
                        <div class="section-divider"><span class="lang-inline active" data-l="es">Estructura</span><span class="lang-inline" data-l="en">Structure</span></div>
                        <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Archivos raiz</span><span class="lang-content" data-l="en">Root files</span></div><div class="card-body scroll"><ul class="file-list">{archivos_html}</ul></div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Estructura</span><span class="lang-content" data-l="en">File structure</span></div><div class="card-body diagram-wrap">{d_estruc}</div></div></div>
                        {readme_html}
                        <div class="section-divider"><span class="lang-inline active" data-l="es">Diagramas</span><span class="lang-inline" data-l="en">Diagrams</span></div>
                        <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Flujo</span><span class="lang-content" data-l="en">Flow</span></div><div class="card-body diagram-wrap">{d_flujo}</div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Arquitectura</span><span class="lang-content" data-l="en">Architecture</span></div><div class="card-body diagram-wrap">{d_arq}</div></div></div>
                        {"" if not d_deps else f'<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Dependencias</span><span class="lang-content" data-l="en">Dependencies</span></div><div class="card-body diagram-wrap">{d_deps}</div></div></div>'}
                        {seccion_uml}
                        """

            except requests.exceptions.ConnectionError:
                resultado = error_html("server_error", "No se pudo conectar con la API de GitHub")
            except requests.exceptions.Timeout:
                resultado = error_html("server_error", "La solicitud tardó demasiado (timeout)")
            except Exception as e:
                err_str = str(e)
                if "rate limit" in err_str.lower() or "403" in err_str:
                    resultado = error_html("rate_limit")
                else:
                    resultado = error_html("server_error", err_str[:120])

    return render_template_string(TEMPLATE, resultado=resultado, repo_url=repo_url)


if __name__ == '__main__':
    app.run(debug=True)