from flask import Flask, request, render_template_string
import requests
import base64
import re
import json

app = Flask(__name__)

# ── Detectar tipo de URL ──────────────────────────────────────────────────────
def detectar_tipo(url):
    url    = url.strip().rstrip("/")
    partes = [p for p in url.replace("https://github.com/","").replace("http://github.com/","").split("/") if p]
    if len(partes) == 1:
        return "perfil", partes[0], None
    elif len(partes) >= 2:
        return "repo", partes[0], partes[1]
    return None, None, None


# ── Perfil / Organización ─────────────────────────────────────────────────────
def get_perfil_info(username):
    headers  = {"Accept":"application/vnd.github.v3+json"}
    user     = requests.get(f"https://api.github.com/users/{username}", headers=headers).json()
    all_repos = []
    page = 1
    while True:
        r = requests.get(f"https://api.github.com/users/{username}/repos?per_page=100&page={page}&sort=pushed", headers=headers).json()
        if not isinstance(r, list) or not r: break
        all_repos.extend(r)
        if len(r) < 100: break
        page += 1
    events   = requests.get(f"https://api.github.com/users/{username}/events/public?per_page=10", headers=headers).json()
    es_org   = user.get("type") == "Organization"
    miembros = []
    if es_org:
        m = requests.get(f"https://api.github.com/orgs/{username}/members?per_page=6", headers=headers).json()
        if isinstance(m, list): miembros = m
    return {"user":user,"repos":all_repos,"events":events if isinstance(events,list) else [],"miembros":miembros,"es_org":es_org}


# ── Repo ──────────────────────────────────────────────────────────────────────
def get_repo_info(owner, repo):
    base         = f"https://api.github.com/repos/{owner}/{repo}"
    info         = requests.get(base).json()
    languages    = requests.get(f"{base}/languages").json()
    commits      = requests.get(f"{base}/commits?per_page=10").json()
    contributors = requests.get(f"{base}/contributors?per_page=5").json()
    contents     = requests.get(f"{base}/contents").json()
    releases     = requests.get(f"{base}/releases?per_page=3").json()
    topics_res   = requests.get(base, headers={"Accept":"application/vnd.github.mercy-preview+json"}).json()

    archivos = [f["name"] for f in contents if isinstance(contents, list)]
    topics   = topics_res.get("topics", [])

    dependencias = ""
    if "requirements.txt" in archivos:
        r = requests.get(f"{base}/contents/requirements.txt").json()
        dependencias = base64.b64decode(r["content"]).decode("utf-8")
    elif "package.json" in archivos:
        r = requests.get(f"{base}/contents/package.json").json()
        dependencias = base64.b64decode(r["content"]).decode("utf-8")

    readme = ""
    for nr in ["README.md","readme.md","README.rst","README.txt","README"]:
        if nr in archivos:
            r = requests.get(f"{base}/contents/{nr}").json()
            readme = base64.b64decode(r["content"]).decode("utf-8")
            break

    # Leer múltiples archivos clave
    archivos_contenido = {}
    extensiones_legibles = {".py",".js",".ts",".go",".rb",".java",".rs",".php",
                             ".jsx",".tsx",".css",".html",".md",".yml",".yaml",
                             ".toml",".sh",".sql"}
    if isinstance(contents, list):
        for item in contents:
            if not isinstance(item, dict): continue
            fname = item.get("name","")
            ext   = "." + fname.split(".")[-1].lower() if "." in fname else ""
            if ext in extensiones_legibles and item.get("type") == "file":
                try:
                    dl = item.get("download_url","")
                    if dl:
                        r = requests.get(dl)
                        if r.ok:
                            archivos_contenido[fname] = r.text[:3000]
                except:
                    pass

    codigo_principal = ""
    lang       = info.get("language","")
    candidatos = {
        "Python":     ["app.py","main.py","server.py","run.py","__init__.py"],
        "JavaScript": ["index.js","app.js","server.js","main.js"],
        "TypeScript": ["index.ts","app.ts","main.ts"],
        "Go":         ["main.go"],
        "Ruby":       ["app.rb","main.rb"],
        "Java":       ["Main.java","App.java"],
    }
    for c in candidatos.get(lang,[]):
        if c in archivos_contenido:
            codigo_principal = archivos_contenido[c]
            break

    return {
        "info":info,"languages":languages,"commits":commits,
        "contributors":contributors,"contents":archivos,
        "dependencias":dependencias,"readme":readme,
        "releases":releases if isinstance(releases,list) else [],
        "topics":topics,"codigo_principal":codigo_principal,
        "archivos_contenido":archivos_contenido,
    }


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
    return " ".join(lineas_es)," ".join(lineas_en)


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


def construir_perfil_html(pdata):
    user=pdata["user"]; repos=pdata["repos"]; events=pdata["events"]
    es_org=pdata["es_org"]; miembros=pdata["miembros"]
    login=user.get("login",""); nombre=user.get("name") or login
    bio=user.get("bio") or (user.get("description","") if es_org else "—")
    avatar=user.get("avatar_url",""); blog=user.get("blog",""); location=user.get("location","")
    company=user.get("company",""); twitter=user.get("twitter_username",""); email=user.get("email","")
    creado=user.get("created_at","")[:10]; pub_repos=user.get("public_repos",0)
    followers=user.get("followers",0); following=user.get("following",0)
    gh_url=f"https://github.com/{login}"; tipo_label="Organization" if es_org else "User"
    repos_validos=[r for r in repos if isinstance(r,dict)]
    total_stars=sum(r.get("stargazers_count",0) for r in repos_validos)
    total_forks=sum(r.get("forks_count",0) for r in repos_validos)

    insignias=[]
    if followers>10000: insignias.append(("Top contributor","#0969da"))
    if followers>1000: insignias.append(("Popular","#1a7f37"))
    if pub_repos>100: insignias.append(("Power user","#cf222e"))
    elif pub_repos>50: insignias.append(("Prolific","#9a6700"))
    if total_stars>10000: insignias.append(("Hall of Fame","#6e40c9"))
    elif total_stars>1000: insignias.append(("Starred","#bf8700"))
    if es_org: insignias.append(("Organization","#0969da"))
    if blog: insignias.append(("Has website","#1a7f37"))
    if twitter: insignias.append(("On Twitter","#1d9bf0"))
    insignias_html="".join(f'<span class="badge" style="border-color:{c};color:{c}">{b}</span>' for b,c in insignias)

    info_rows=""
    if location: info_rows+=f'<div class="info-row"><span class="info-key">Location</span><span>{location}</span></div>'
    if company:  info_rows+=f'<div class="info-row"><span class="info-key">Company</span><span>{company}</span></div>'
    if email:    info_rows+=f'<div class="info-row"><span class="info-key">Email</span><span>{email}</span></div>'
    if blog:     info_rows+=f'<div class="info-row"><span class="info-key">Website</span><a href="{blog}" target="_blank" class="info-link">{blog[:40]}</a></div>'
    if twitter:  info_rows+=f'<div class="info-row"><span class="info-key">Twitter</span><span>@{twitter}</span></div>'
    info_rows+=f'<div class="info-row"><span class="info-key">Member since</span><span>{creado}</span></div>'
    info_rows+=f'<div class="info-row"><span class="info-key">GitHub</span><a href="{gh_url}" target="_blank" class="info-link">{gh_url}</a></div>'

    stats_cards_html=f"""<div class="grid-1"><div class="card"><div class="card-header">GitHub Stats <span class="label"><a href="https://github.com/anuraghazra/github-readme-stats" target="_blank" class="info-link">github-readme-stats</a></span></div><div class="card-body" style="display:flex;flex-wrap:wrap;gap:12px;justify-content:center;padding:20px 16px"><img src="https://github-readme-stats-eight-theta.vercel.app/api?username={login}&show_icons=true&theme=github_dark&include_all_commits=true&count_private=true&hide_border=true" alt="Stats" style="height:160px;border-radius:6px;max-width:100%" onerror="this.style.display='none'"><img src="https://github-readme-stats-eight-theta.vercel.app/api/top-langs/?username={login}&layout=compact&langs_count=8&theme=github_dark&hide_border=true" alt="Top langs" style="height:160px;border-radius:6px;max-width:100%" onerror="this.style.display='none'"></div></div></div>"""

    streak_html=f"""<div class="grid-1"><div class="card"><div class="card-header">Contribution Streak <span class="label"><a href="https://github.com/DenverCoder1/github-readme-streak-stats" target="_blank" class="info-link">streak-stats</a></span></div><div class="card-body" style="display:flex;justify-content:center;padding:16px"><img src="https://streak-stats.demolab.com?user={login}&theme=github-dark-blue&hide_border=true&date_format=M%20j%5B%2C%20Y%5D" alt="Streak" style="border-radius:6px;max-width:100%" onerror="this.style.display='none'"></div></div></div>"""

    contrib_graph_html=f"""<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Mapa de contribuciones</span><span class="lang-content" data-l="en">Contribution map</span> <span class="label"><a href="https://github.com/vn7n24fzkq/github-profile-summary-cards" target="_blank" class="info-link">profile-summary-cards</a></span></div><div class="card-body" style="display:flex;justify-content:center;padding:16px"><img src="https://github-profile-summary-cards.vercel.app/api/cards/profile-details?username={login}&theme=github_dark" alt="Contributions" style="border-radius:6px;max-width:100%;width:100%" onerror="this.style.display='none'"></div></div></div>"""

    top5_repos=sorted(repos_validos,key=lambda r:r.get("stargazers_count",0),reverse=True)[:5]
    max_stars_top5=max((r.get("stargazers_count",0) for r in top5_repos),default=1)
    if max_stars_top5==0: max_stars_top5=1
    top5_html=""
    for r in top5_repos:
        rname=r.get("name",""); rdesc=(r.get("description") or "Sin descripción")[:72]
        rstars=r.get("stargazers_count",0); rlang=r.get("language") or "—"
        rforks=r.get("forks_count",0); rurl=r.get("html_url",""); rupdated=r.get("updated_at","")[:10]
        bar_pct=int((rstars/max_stars_top5)*100); lcolor=LANG_COLORS.get(rlang,"#8b949e")
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
    langs_html=f'<div class="langs-visual">{langs_stack}{langs_list}</div>'

    repos_json_list=[]
    for r in repos_validos:
        repos_json_list.append({"name":r.get("name",""),"desc":(r.get("description") or "")[:80],"stars":r.get("stargazers_count",0),"forks":r.get("forks_count",0),"lang":r.get("language") or "—","updated":r.get("updated_at","")[:10],"url":r.get("html_url",""),"fork":r.get("fork",False)})
    repos_json_str=json.dumps(repos_json_list)
    langs_unicos=sorted(set(r.get("language") or "—" for r in repos_validos if r.get("language")))
    lang_options="".join(f'<option value="{l}">{l}</option>' for l in langs_unicos)
    lang_colors_js=json.dumps(LANG_COLORS)

    all_repos_html=f"""<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Todos los repositorios</span><span class="lang-content" data-l="en">All repositories</span><span class="label" id="repos-count">{len(repos_validos)} repos</span></div><div class="card-body" style="padding:12px 16px"><div class="repos-filter-bar"><input type="text" id="filter-search" placeholder="Search repos..." class="filter-input" oninput="filterRepos()"><select id="filter-lang" class="filter-select" onchange="filterRepos()"><option value="">All languages</option>{lang_options}</select><select id="filter-sort" class="filter-select" onchange="filterRepos()"><option value="stars">Stars</option><option value="forks">Forks</option><option value="updated">Updated</option><option value="name">Name</option></select><label class="filter-check"><input type="checkbox" id="filter-forks" onchange="filterRepos()"><span class="lang-inline active" data-l="es">Ocultar forks</span><span class="lang-inline" data-l="en">Hide forks</span></label></div><div id="repos-list-all" class="repos-list-all"></div></div></div></div>
    <script>
    const REPOS_DATA={repos_json_str};
    const LANG_COLORS_MAP={lang_colors_js};
    function filterRepos(){{
      const search=document.getElementById('filter-search').value.toLowerCase();
      const lang=document.getElementById('filter-lang').value;
      const sort=document.getElementById('filter-sort').value;
      const hideFork=document.getElementById('filter-forks').checked;
      let filtered=REPOS_DATA.filter(r=>{{
        if(hideFork&&r.fork)return false;
        if(lang&&r.lang!==lang)return false;
        if(search&&!r.name.toLowerCase().includes(search)&&!r.desc.toLowerCase().includes(search))return false;
        return true;
      }});
      filtered.sort((a,b)=>{{
        if(sort==='stars')return b.stars-a.stars;
        if(sort==='forks')return b.forks-a.forks;
        if(sort==='updated')return b.updated.localeCompare(a.updated);
        if(sort==='name')return a.name.localeCompare(b.name);
        return 0;
      }});
      document.getElementById('repos-count').textContent=filtered.length+' repos';
      const container=document.getElementById('repos-list-all');
      if(!filtered.length){{container.innerHTML='<div style="color:var(--text-muted);font-size:13px;padding:12px 0">No repositories found.</div>';return;}}
      container.innerHTML=filtered.map(r=>{{
        const lc=LANG_COLORS_MAP[r.lang]||'#8b949e';
        return `<div class="repo-row-item"><div class="repo-row-left"><a href="${{r.url}}" target="_blank" class="repo-card-name">${{r.name}}</a>${{r.fork?'<span class="repo-fork-badge">fork</span>':''}}<span class="repo-row-desc">${{r.desc||'—'}}</span></div><div class="repo-row-right"><span class="repo-lang-dot" style="background:${{lc}}"></span><span class="repo-card-lang" style="min-width:60px">${{r.lang}}</span><span class="repo-card-stars">★ ${{r.stars.toLocaleString()}}</span><span class="repo-card-forks">🍴 ${{r.forks}}</span><span class="repo-card-updated">${{r.updated}}</span></div></div>`;
      }}).join('');
    }}
    filterRepos();
    </script>"""

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

    readme_tips_html=f"""<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Mejora tu README de perfil</span><span class="lang-content" data-l="en">Improve your profile README</span></div><div class="card-body"><div class="tips-intro"><span class="lang-content active" data-l="es">Crea un repo <code>{login}/{login}</code> con un README.md:</span><span class="lang-content" data-l="en">Create a repo <code>{login}/{login}</code> with a README.md:</span></div><div class="tips-grid"><div class="tip-item"><div class="tip-title">Stats + Languages</div><div class="tip-desc"><span class="lang-content active" data-l="es">Estadísticas y lenguajes.</span><span class="lang-content" data-l="en">Stats and languages.</span></div><a href="https://github.com/anuraghazra/github-readme-stats" target="_blank" class="tip-link">github-readme-stats →</a><div class="tip-code">![Stats](https://github-readme-stats.vercel.app/api?username={login}&show_icons=true&theme=github_dark)</div></div><div class="tip-item"><div class="tip-title">Streak</div><div class="tip-desc"><span class="lang-content active" data-l="es">Racha de commits.</span><span class="lang-content" data-l="en">Commit streak.</span></div><a href="https://github.com/DenverCoder1/github-readme-streak-stats" target="_blank" class="tip-link">streak-stats →</a><div class="tip-code">![Streak](https://streak-stats.demolab.com?user={login}&theme=github-dark-blue)</div></div><div class="tip-item"><div class="tip-title">Profile Summary</div><div class="tip-desc"><span class="lang-content active" data-l="es">Resumen de contribuciones.</span><span class="lang-content" data-l="en">Contribution summary.</span></div><a href="https://github.com/vn7n24fzkq/github-profile-summary-cards" target="_blank" class="tip-link">profile-summary-cards →</a><div class="tip-code">![Summary](https://github-profile-summary-cards.vercel.app/api/cards/profile-details?username={login}&theme=github_dark)</div></div><div class="tip-item"><div class="tip-title">Trophies</div><div class="tip-desc"><span class="lang-content active" data-l="es">Logros.</span><span class="lang-content" data-l="en">Achievements.</span></div><a href="https://github.com/ryo-ma/github-profile-trophy" target="_blank" class="tip-link">github-profile-trophy →</a><div class="tip-code">![Trophy](https://github-profile-trophy.vercel.app/?username={login}&theme=darkhub)</div></div><div class="tip-item"><div class="tip-title">Activity Graph</div><div class="tip-desc"><span class="lang-content active" data-l="es">Gráfico de actividad.</span><span class="lang-content" data-l="en">Activity graph.</span></div><a href="https://github.com/Ashutosh00710/github-readme-activity-graph" target="_blank" class="tip-link">activity-graph →</a><div class="tip-code">![Activity](https://github-readme-activity-graph.vercel.app/graph?username={login}&theme=github-compact)</div></div><div class="tip-item"><div class="tip-title">Visitor Badge</div><div class="tip-desc"><span class="lang-content active" data-l="es">Contador de visitas.</span><span class="lang-content" data-l="en">Visitor counter.</span></div><a href="https://visitor-badge.glitch.me" target="_blank" class="tip-link">visitor-badge →</a><div class="tip-code">![Visitors](https://visitor-badge.glitch.me/badge?page_id={login}.{login})</div></div></div></div></div></div>"""

    return f"""
    <div class="section-divider"><span class="lang-inline active" data-l="es">{"Organización" if es_org else "Perfil"}</span><span class="lang-inline" data-l="en">{"Organization" if es_org else "Profile"}</span></div>
    <div class="grid-1"><div class="card"><div class="card-header">{tipo_label}<span class="label">{gh_url}</span></div><div class="card-body"><div class="perfil-hero"><img src="{avatar}" alt="{login}" class="perfil-avatar" onerror="this.style.background='var(--bg-card)'"><div class="perfil-info"><div class="perfil-nombre">{nombre}</div><div class="perfil-login">@{login}</div><div class="perfil-bio">{bio}</div><div class="badges" style="margin-top:10px">{insignias_html}</div></div></div></div></div></div>
    <div class="grid-4"><div class="card stat-card"><div class="card-body"><span class="stat-value">{pub_repos}</span><div class="stat-label">repos</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{followers:,}</span><div class="stat-label">followers</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{total_stars:,}</span><div class="stat-label">total stars</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{total_forks:,}</span><div class="stat-label">total forks</div></div></div></div>
    <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Informacion</span><span class="lang-content" data-l="en">Information</span></div><div class="card-body"><div class="info-table">{info_rows}</div></div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Actividad reciente</span><span class="lang-content" data-l="en">Recent activity</span></div><div class="card-body scroll"><div class="timeline">{actividad_html or "<span style='color:var(--text-muted);font-size:13px'>No public activity</span>"}</div></div></div></div>
    {"" if not miembros_html else f'<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Miembros públicos</span><span class="lang-content" data-l="en">Public members</span></div><div class="card-body"><div class="members-grid">{miembros_html}</div></div></div></div>'}
    {stats_cards_html}{streak_html}{contrib_graph_html}
    <div class="section-divider"><span class="lang-inline active" data-l="es">Repositorios</span><span class="lang-inline" data-l="en">Repositories</span></div>
    <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Top 5 por estrellas</span><span class="lang-content" data-l="en">Top 5 by stars</span></div><div class="card-body scroll">{top5_html}</div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Lenguajes</span><span class="lang-content" data-l="en">Languages</span></div><div class="card-body scroll">{langs_html}</div></div></div>
    {all_repos_html}
    {readme_tips_html}
    """


def construir_seccion_preguntas(data):
    archivos_contenido = data.get("archivos_contenido", {})
    nombre_repo        = data["info"].get("name","repo")
    archivos_lista     = list(archivos_contenido.keys())

    sugerencias = []
    if any("auth" in a.lower() or "login" in a.lower() for a in archivos_lista):
        sugerencias.append("¿Cómo funciona el login?")
    if any("model" in a.lower() or "db" in a.lower() or "schema" in a.lower() for a in archivos_lista):
        sugerencias.append("¿Cómo está la base de datos?")
    if any("route" in a.lower() or "api" in a.lower() for a in archivos_lista):
        sugerencias.append("¿Cuáles son las rutas de la API?")
    if any("config" in a.lower() or ".env" in a.lower() for a in archivos_lista):
        sugerencias.append("¿Cómo se configura el proyecto?")
    if any("test" in a.lower() or "spec" in a.lower() for a in archivos_lista):
        sugerencias.append("¿Cómo están los tests?")
    if any("docker" in a.lower() for a in archivos_lista):
        sugerencias.append("¿Cómo funciona Docker aquí?")
    sugerencias += ["¿Qué dependencias usa?","¿Cómo está estructurado?"]
    sugerencias = sugerencias[:6]

    sugerencias_html = "".join(
        f'<button class="suggestion-btn" onclick="hacerPregunta(this)">{s}</button>'
        for s in sugerencias
    )

    archivos_json = json.dumps(archivos_contenido)
    readme_json   = json.dumps(data.get("readme",""))

    return f"""
    <div class="section-divider">
      <span class="lang-inline active" data-l="es">Explorar el código</span>
      <span class="lang-inline" data-l="en">Explore the code</span>
    </div>
    <div class="grid-1">
      <div class="card">
        <div class="card-header">
          <span class="lang-content active" data-l="es">Pregunta sobre {nombre_repo}</span>
          <span class="lang-content" data-l="en">Ask about {nombre_repo}</span>
          <span class="label">{len(archivos_lista)} archivos indexados</span>
        </div>
        <div class="card-body" style="padding:0">
          <div id="chat-messages" class="chat-messages">
            <div class="chat-msg chat-msg-system">
              <span class="lang-inline active" data-l="es">Tengo acceso a <strong>{len(archivos_lista)}</strong> archivos. Pregúntame sobre el código, estructura o configuración.</span>
              <span class="lang-inline" data-l="en">I have access to <strong>{len(archivos_lista)}</strong> files. Ask me about the code, structure or configuration.</span>
            </div>
          </div>
          <div class="chat-suggestions" id="chat-suggestions">{sugerencias_html}</div>
          <div class="chat-input-row">
            <input type="text" id="chat-input"
                   placeholder="¿Cómo funciona el login? / How does auth work?"
                   class="chat-input"
                   onkeydown="if(event.key==='Enter')enviarPregunta()">
            <button class="chat-send-btn" onclick="enviarPregunta()">
              <span class="lang-inline active" data-l="es">Buscar</span>
              <span class="lang-inline" data-l="en">Search</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <script>
    const ARCHIVOS_REPO={archivos_json};
    const README_REPO={readme_json};
    const KEYWORDS_MAP={{
      "login":["login","auth","signin","sign_in","authenticate","session","jwt","token","password","credential"],
      "registro":["register","signup","sign_up","create_user","new_user"],
      "base de datos":["database","db","sql","mongo","postgres","mysql","sqlite","orm","model","schema","migration"],
      "api":["api","endpoint","route","router","request","response","fetch","axios","http"],
      "config":["config","settings","env","environment","dotenv","setup"],
      "test":["test","spec","unittest","pytest","jest","describe","assert"],
      "docker":["docker","container","dockerfile","compose","image"],
      "deploy":["deploy","deployment","heroku","vercel","netlify","aws","production"],
      "instalar":["install","setup","requirement","dependency","package","npm","pip","yarn"],
      "seguridad":["security","cors","ssl","https","encrypt","hash","bcrypt"],
      "cache":["cache","redis","memcache","session","cookie"],
      "email":["email","mail","smtp","sendgrid","mailgun"],
      "estructura":["structure","folder","directory","module","component","import","class"],
      "dependencias":["import","require","dependency","package","library","module"],
    }};

    function escapeHtml(t){{
      return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }}

    function hacerPregunta(btn){{
      document.getElementById('chat-input').value=btn.textContent.trim();
      enviarPregunta();
    }}

    function enviarPregunta(){{
      const input=document.getElementById('chat-input');
      const pregunta=input.value.trim();
      if(!pregunta) return;
      document.getElementById('chat-suggestions').style.display='none';
      agregarMensaje('user',pregunta);
      input.value='';
      const loadId='load-'+Date.now();
      agregarMensaje('loading','',loadId);
      setTimeout(()=>{{
        const resultados=buscarEnRepo(pregunta);
        const loadEl=document.getElementById(loadId);
        if(loadEl) loadEl.remove();
        mostrarResultados(pregunta,resultados);
      }},150);
    }}

    function buscarEnRepo(pregunta){{
      const p=pregunta.toLowerCase();
      let palabras=[];
      for(const [concepto,pals] of Object.entries(KEYWORDS_MAP)){{
        if(pals.some(k=>p.includes(k))||p.includes(concepto)) palabras.push(...pals);
      }}
      if(!palabras.length) palabras=p.match(/\w{{3,}}/g)||[];
      palabras=[...new Set(palabras)];
      const resultados=[];
      const fuentes=Object.entries(ARCHIVOS_REPO);
      if(README_REPO) fuentes.push(['README.md',README_REPO]);
      for(const [archivo,contenido] of fuentes){{
        const lineas=contenido.split('\\n');
        let score=0; const fragmentos=[];
        lineas.forEach((linea,i)=>{{
          const ll=linea.toLowerCase();
          const hits=palabras.filter(p=>ll.includes(p)).length;
          if(hits>0){{
            score+=hits;
            const inicio=Math.max(0,i-2); const fin=Math.min(lineas.length,i+10);
            const bloque=lineas.slice(inicio,fin).join('\\n').trim();
            if(bloque&&!fragmentos.some(f=>f.bloque===bloque)) fragmentos.push({{hits,linea:i+1,bloque}});
          }}
        }});
        if(fragmentos.length){{
          fragmentos.sort((a,b)=>b.hits-a.hits);
          resultados.push({{archivo,score,linea:fragmentos[0].linea,fragmento:fragmentos[0].bloque,total:fragmentos.length}});
        }}
      }}
      resultados.sort((a,b)=>b.score-a.score);
      return resultados.slice(0,4);
    }}

    function mostrarResultados(pregunta,resultados){{
      if(!resultados.length){{
        agregarMensaje('assistant',`<div class="chat-no-results"><span class="lang-inline active" data-l="es">No encontré coincidencias para "<strong>${{escapeHtml(pregunta)}}</strong>".</span><span class="lang-inline" data-l="en">No matches for "<strong>${{escapeHtml(pregunta)}}</strong>".</span></div>`);
        sincronizarLang(); return;
      }}
      let html=`<div class="chat-results-header"><span class="lang-inline active" data-l="es">${{resultados.length}} archivo(s) con coincidencias:</span><span class="lang-inline" data-l="en">${{resultados.length}} file(s) with matches:</span></div>`;
      resultados.forEach((r,i)=>{{
        const ext=r.archivo.includes('.')?r.archivo.split('.').pop():'file';
        html+=`<div class="chat-result-block ${{i===0?'chat-result-top':''}}"><div class="chat-result-file"><span class="file-ext">${{ext.slice(0,6)}}</span><span class="chat-result-filename">${{r.archivo}}</span><span class="chat-result-line"><span class="lang-inline active" data-l="es">línea ${{r.linea}}</span><span class="lang-inline" data-l="en">line ${{r.linea}}</span></span><span class="chat-result-score">${{r.score}} hits</span></div><pre class="chat-code-block"><code>${{escapeHtml(r.fragmento)}}</code></pre></div>`;
      }});
      agregarMensaje('assistant',html);
      sincronizarLang();
    }}

    function sincronizarLang(){{
      const lang=document.documentElement.dataset.lang||'es';
      document.querySelectorAll('.lang-inline').forEach(el=>{{
        el.classList.toggle('active',el.dataset.l===lang);
      }});
    }}

    function agregarMensaje(tipo,contenido,id=''){{
      const container=document.getElementById('chat-messages');
      const div=document.createElement('div');
      div.className=`chat-msg chat-msg-${{tipo}}`;
      if(id) div.id=id;
      if(tipo==='user'){{
        div.innerHTML=`<span class="chat-msg-label">You</span><div class="chat-msg-text">${{escapeHtml(contenido)}}</div>`;
      }}else if(tipo==='loading'){{
        div.innerHTML=`<div class="chat-typing"><span></span><span></span><span></span></div>`;
      }}else{{
        div.innerHTML=`<span class="chat-msg-label">EnkiDocs</span><div class="chat-msg-text">${{contenido}}</div>`;
      }}
      container.appendChild(div);
      container.scrollTop=container.scrollHeight;
    }}
    </script>"""


TEMPLATE = """
<!DOCTYPE html>
<html lang="es" data-lang="es" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EnkiDocs</title>
  <style>
    :root{--bg:#ffffff;--bg-card:#f6f8fa;--bg-header:#f6f8fa;--border:#d0d7de;--text:#24292f;--text-muted:#57606a;--link:#0969da;--green:#2da44e;--green-h:#2c974b;--nav-bg:#24292f;--nav-text:#ffffff;--shadow:0 1px 3px rgba(0,0,0,0.08);--step-bg:#ddf4ff;--step-num:#0969da;--code-bg:#f6f8fa;}
    [data-theme="dark"]{--bg:#0d1117;--bg-card:#161b22;--bg-header:#21262d;--border:#30363d;--text:#e6edf3;--text-muted:#8b949e;--link:#58a6ff;--green:#238636;--green-h:#2ea043;--nav-bg:#161b22;--nav-text:#e6edf3;--shadow:0 1px 3px rgba(0,0,0,0.4);--step-bg:#1c2a3a;--step-num:#58a6ff;--code-bg:#161b22;}
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;color:var(--text);background:var(--bg);transition:background .2s,color .2s}
    .nav{background:var(--nav-bg);padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;border-bottom:1px solid var(--border)}
    .nav-left{display:flex;align-items:center;gap:20px}
    .nav-logo{color:var(--nav-text);font-size:15px;font-weight:600;letter-spacing:-.3px}
    .nav-logo span{color:#58a6ff}
    .nav-right{display:flex;align-items:center;gap:8px}
    .btn-nav{background:transparent;border:1px solid #444d56;color:#8b949e;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer;transition:border-color .2s,color .2s}
    .btn-nav:hover{border-color:#8b949e;color:var(--nav-text)}
    .container{max-width:1000px;margin:0 auto;padding:32px 20px 64px}
    .search-block{margin-bottom:36px}
    .search-block h1{font-size:22px;font-weight:600;margin-bottom:6px}
    .search-block p{color:var(--text-muted);font-size:13px;margin-bottom:14px}
    .search-row{display:flex;gap:8px}
    .search-row input{flex:1;padding:8px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;outline:none;color:var(--text);background:var(--bg-card);transition:border-color .2s,box-shadow .2s}
    .search-row input:focus{border-color:var(--link);box-shadow:0 0 0 3px rgba(9,105,218,.12)}
    .search-row button{padding:8px 18px;font-size:14px;font-weight:500;color:#fff;background:var(--green);border:1px solid rgba(31,35,40,.15);border-radius:6px;cursor:pointer;white-space:nowrap;transition:background .15s}
    .search-row button:hover{background:var(--green-h)}
    .grid-1{margin-bottom:12px}
    .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
    .grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px}
    .grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}
    .card{border:1px solid var(--border);border-radius:6px;background:var(--bg);box-shadow:var(--shadow);overflow:hidden;min-width:0}
    .card-header{padding:10px 16px;background:var(--bg-header);border-bottom:1px solid var(--border);font-size:13px;font-weight:600;color:var(--text);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:4px}
    .card-header .label{font-size:11px;font-weight:400;color:var(--text-muted)}
    .card-body{padding:14px 16px;overflow:hidden;word-break:break-word;overflow-wrap:break-word}
    .card-body.scroll{max-height:380px;overflow-y:auto;overflow-x:hidden}
    .scroll::-webkit-scrollbar{width:6px;height:6px}
    .scroll::-webkit-scrollbar-track{background:var(--bg-card)}
    .scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
    .scroll::-webkit-scrollbar-thumb:hover{background:var(--text-muted)}

    .chat-messages{min-height:80px;max-height:480px;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px;border-bottom:1px solid var(--border)}
    .chat-messages::-webkit-scrollbar{width:6px}
    .chat-messages::-webkit-scrollbar-track{background:var(--bg-card)}
    .chat-messages::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
    .chat-msg{display:flex;flex-direction:column;gap:4px;max-width:100%}
    .chat-msg-label{font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px}
    .chat-msg-text{font-size:13px;color:var(--text);line-height:1.5}
    .chat-msg-system .chat-msg-text{background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:10px 14px;font-size:13px;color:var(--text-muted)}
    .chat-msg-user{align-items:flex-end}
    .chat-msg-user .chat-msg-text{background:var(--link);color:#fff;border-radius:8px 8px 2px 8px;padding:8px 12px;display:inline-block;max-width:80%}
    .chat-msg-user .chat-msg-label{color:var(--link)}
    .chat-msg-assistant .chat-msg-text{width:100%}
    .chat-typing{display:flex;gap:4px;padding:8px 12px;background:var(--bg-card);border-radius:6px;width:fit-content}
    .chat-typing span{width:6px;height:6px;border-radius:50%;background:var(--text-muted);animation:bounce .8s infinite}
    .chat-typing span:nth-child(2){animation-delay:.15s}
    .chat-typing span:nth-child(3){animation-delay:.3s}
    @keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}}
    .chat-no-results{color:var(--text-muted);font-size:13px;padding:8px 0}
    .chat-results-header{font-size:11px;color:var(--text-muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}
    .chat-result-block{border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:10px}
    .chat-result-block:last-child{margin-bottom:0}
    .chat-result-top{border-color:var(--link)}
    .chat-result-file{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--bg-header);border-bottom:1px solid var(--border);flex-wrap:wrap}
    .chat-result-filename{font-size:12px;font-weight:600;color:var(--text);font-family:ui-monospace,monospace;flex:1}
    .chat-result-line{font-size:11px;color:var(--text-muted);font-family:ui-monospace,monospace}
    .chat-result-score{font-size:10px;color:var(--link);background:var(--step-bg);border-radius:10px;padding:1px 7px;font-family:ui-monospace,monospace}
    .chat-code-block{background:var(--code-bg);padding:12px 14px;font-family:ui-monospace,"SFMono-Regular",monospace;font-size:12px;line-height:1.6;color:var(--text);overflow-x:auto;white-space:pre;max-height:240px;overflow-y:auto;margin:0}
    .chat-code-block::-webkit-scrollbar{width:4px;height:4px}
    .chat-code-block::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
    .chat-suggestions{padding:12px 16px;display:flex;flex-wrap:wrap;gap:8px;border-bottom:1px solid var(--border)}
    .suggestion-btn{padding:5px 12px;font-size:12px;border:1px solid var(--border);border-radius:20px;background:var(--bg-card);color:var(--text-muted);cursor:pointer;transition:all .15s;white-space:nowrap}
    .suggestion-btn:hover{border-color:var(--link);color:var(--link);background:var(--step-bg)}
    .chat-input-row{display:flex;gap:8px;padding:12px 16px}
    .chat-input{flex:1;padding:8px 12px;font-size:13px;border:1px solid var(--border);border-radius:6px;outline:none;color:var(--text);background:var(--bg-card);transition:border-color .2s}
    .chat-input:focus{border-color:var(--link);box-shadow:0 0 0 3px rgba(9,105,218,.1)}
    .chat-send-btn{padding:8px 16px;font-size:13px;font-weight:500;color:#fff;background:var(--link);border:none;border-radius:6px;cursor:pointer;transition:opacity .15s;white-space:nowrap}
    .chat-send-btn:hover{opacity:.85}

    /* RESTO */
    .perfil-hero{display:flex;gap:20px;align-items:flex-start}
    .perfil-avatar{width:80px;height:80px;border-radius:50%;border:2px solid var(--border);flex-shrink:0;background:var(--bg-card)}
    .perfil-info{flex:1;min-width:0}
    .perfil-nombre{font-size:18px;font-weight:600;color:var(--text)}
    .perfil-login{font-size:13px;color:var(--text-muted);margin-bottom:6px;font-family:ui-monospace,monospace}
    .perfil-bio{font-size:13px;color:var(--text);line-height:1.5}
    .info-table{display:flex;flex-direction:column;gap:0}
    .info-row{display:flex;gap:12px;padding:7px 0;border-bottom:1px solid var(--bg-card);font-size:13px;align-items:center;min-width:0}
    .info-row:last-child{border-bottom:none}
    .info-key{font-size:11px;font-weight:600;color:var(--text-muted);min-width:80px;flex-shrink:0;text-transform:uppercase;letter-spacing:.3px}
    .info-link{color:var(--link);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .info-link:hover{text-decoration:underline}
    .members-grid{display:flex;flex-wrap:wrap;gap:12px}
    .member-item{display:flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card)}
    .member-avatar{width:24px;height:24px;border-radius:50%;border:1px solid var(--border)}
    .member-login{font-size:12px;font-weight:500;color:var(--link)}
    .repo-card-item{padding:12px 0;border-bottom:1px solid var(--border)}
    .repo-card-item:last-child{border-bottom:none}
    .repo-card-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px}
    .repo-card-name{font-size:13px;font-weight:600;color:var(--link);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .repo-card-name:hover{text-decoration:underline}
    .repo-card-stars{font-size:12px;color:var(--text-muted);font-family:ui-monospace,monospace;flex-shrink:0}
    .repo-card-desc{font-size:12px;color:var(--text-muted);margin-bottom:8px;line-height:1.4}
    .repo-card-bar{height:4px;background:var(--border);border-radius:2px;margin-bottom:8px;overflow:hidden}
    .repo-card-bar-fill{height:100%;border-radius:2px}
    .repo-card-meta{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--text-muted)}
    .repo-lang-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
    .repo-card-lang{font-family:ui-monospace,monospace}
    .repo-card-updated{margin-left:auto}
    .repos-filter-bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
    .filter-input{flex:1;min-width:140px;padding:6px 10px;font-size:12px;border:1px solid var(--border);border-radius:6px;outline:none;color:var(--text);background:var(--bg-card)}
    .filter-input:focus{border-color:var(--link)}
    .filter-select{padding:6px 10px;font-size:12px;border:1px solid var(--border);border-radius:6px;outline:none;color:var(--text);background:var(--bg-card);cursor:pointer}
    .filter-check{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-muted);cursor:pointer;white-space:nowrap}
    .repos-list-all{max-height:420px;overflow-y:auto;overflow-x:hidden}
    .repos-list-all::-webkit-scrollbar{width:6px}
    .repos-list-all::-webkit-scrollbar-track{background:var(--bg-card)}
    .repos-list-all::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
    .repo-row-item{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--bg-card);min-width:0}
    .repo-row-item:last-child{border-bottom:none}
    .repo-row-left{display:flex;flex-direction:column;gap:3px;flex:1;min-width:0}
    .repo-row-right{display:flex;align-items:center;gap:10px;flex-shrink:0;font-size:11px;color:var(--text-muted)}
    .repo-row-desc{font-size:11px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .repo-fork-badge{font-size:10px;color:var(--text-muted);border:1px solid var(--border);border-radius:3px;padding:1px 5px;background:var(--bg-card)}
    .langs-visual{display:flex;flex-direction:column;gap:16px}
    .lang-stack{display:flex;height:8px;border-radius:4px;overflow:hidden;gap:2px}
    .lang-stack-seg{height:100%;border-radius:2px}
    .lang-list{display:flex;flex-direction:column;gap:8px}
    .lang-item{display:flex;align-items:center;gap:8px;font-size:12px;min-width:0}
    .lang-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
    .lang-name{min-width:80px;font-weight:500;color:var(--text)}
    .lang-bar-wrap{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden}
    .lang-bar-fill{height:100%;border-radius:3px}
    .lang-pct{min-width:36px;text-align:right;color:var(--text-muted);font-family:ui-monospace,monospace}
    .lang-count{min-width:52px;color:var(--text-muted)}
    .tips-intro{font-size:13px;color:var(--text);margin-bottom:16px;line-height:1.6}
    .tips-intro code{font-family:ui-monospace,monospace;font-size:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:1px 5px}
    .tips-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
    .tip-item{background:var(--bg-card);border:1px solid var(--border);border-radius:6px;padding:12px;display:flex;flex-direction:column;gap:6px}
    .tip-title{font-size:12px;font-weight:600;color:var(--text)}
    .tip-desc{font-size:12px;color:var(--text-muted);line-height:1.4}
    .tip-link{font-size:12px;color:var(--link);text-decoration:none}
    .tip-link:hover{text-decoration:underline}
    .tip-code{font-family:ui-monospace,monospace;font-size:10px;color:var(--text-muted);background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px;word-break:break-all;line-height:1.5}
    .repo-card .card-body{display:flex;flex-direction:column;gap:10px}
    .repo-name{font-size:18px;font-weight:600;color:var(--link);word-break:break-all}
    .repo-desc{color:var(--text-muted);font-size:13px}
    .badges{display:flex;flex-wrap:wrap;gap:6px}
    .badge{padding:2px 10px;border-radius:20px;font-size:11px;font-weight:500;border:1px solid var(--border);background:var(--bg-card);color:var(--text-muted);white-space:nowrap}
    .stat-card .card-body{text-align:center;padding:18px 8px}
    .stat-value{font-size:24px;font-weight:600;color:var(--text);display:block}
    .stat-label{font-size:11px;color:var(--text-muted);margin-top:2px;font-family:ui-monospace,monospace}
    .text-content{font-size:13px;line-height:1.7;color:var(--text);word-break:break-word;overflow-wrap:break-word}
    .text-content strong{color:var(--text)}
    .text-content code{font-family:ui-monospace,monospace;font-size:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:1px 5px;word-break:break-all}
    .tag-list{display:flex;flex-wrap:wrap;gap:6px}
    .tag{padding:2px 10px;border-radius:20px;font-size:12px;border:1px solid var(--border);background:var(--bg-card);color:var(--text);font-family:ui-monospace,monospace;white-space:nowrap}
    .file-list{list-style:none}
    .file-list li{padding:5px 0;border-bottom:1px solid var(--bg-card);color:var(--text);font-size:12px;font-family:ui-monospace,monospace;display:flex;align-items:center;gap:8px;min-width:0}
    .file-list li:last-child{border-bottom:none}
    .file-list li span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .file-ext{font-size:10px;color:var(--text-muted);background:var(--bg-card);border:1px solid var(--border);border-radius:3px;padding:1px 5px;min-width:32px;text-align:center;flex-shrink:0}
    .contrib-list{list-style:none}
    .contrib-list li{padding:6px 0;border-bottom:1px solid var(--bg-card);font-size:13px;display:flex;justify-content:space-between;align-items:center;gap:8px;min-width:0}
    .contrib-list li:last-child{border-bottom:none}
    .contrib-name{font-weight:500;color:var(--link);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .contrib-count{font-size:11px;color:var(--text-muted);font-family:ui-monospace,monospace;flex-shrink:0}
    .readme-box{font-family:ui-monospace,monospace;font-size:12px;line-height:1.7;color:var(--text);white-space:pre-wrap;word-break:break-word;overflow-wrap:break-word}
    .uso-desc{font-size:13px;line-height:1.7;color:var(--text);margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--border);word-break:break-word}
    .uso-desc code{font-family:ui-monospace,monospace;font-size:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:1px 5px}
    .steps{display:flex;flex-direction:column;gap:0}
    .step{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--border)}
    .step:last-child{border-bottom:none}
    .step-num{width:26px;height:26px;border-radius:50%;flex-shrink:0;background:var(--step-bg);color:var(--step-num);font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;font-family:ui-monospace,monospace;margin-top:2px}
    .step-content{flex:1;min-width:0}
    .step-title{font-size:12px;font-weight:600;color:var(--text);margin-bottom:4px}
    .step-cmd{font-family:ui-monospace,monospace;font-size:12px;background:var(--code-bg);border:1px solid var(--border);border-radius:4px;padding:6px 10px;color:var(--text-muted);word-break:break-all;overflow-wrap:break-word;display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
    .step-cmd span{flex:1;min-width:0}
    .copy-btn{background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:11px;padding:0;flex-shrink:0}
    .copy-btn:hover{color:var(--text)}
    .code-example{font-family:ui-monospace,monospace;font-size:12px;line-height:1.6;background:var(--code-bg);border:1px solid var(--border);border-radius:4px;padding:10px 12px;color:var(--text-muted);white-space:pre-wrap;word-break:break-word;overflow-wrap:break-word;margin-top:8px}
    .code-example-label{font-size:11px;color:var(--text-muted);margin-bottom:4px;margin-top:12px;font-family:ui-monospace,monospace}
    .checklist{list-style:none;display:flex;flex-direction:column;gap:8px}
    .checklist li{display:flex;align-items:center;gap:10px;font-size:13px}
    .check-icon{width:18px;height:18px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:11px}
    .check-yes{background:#dafbe1;color:#1a7f37;border:1px solid #4ac26b}
    .check-no{background:var(--bg-card);color:var(--text-muted);border:1px solid var(--border)}
    [data-theme="dark"] .check-yes{background:#1a3a24;color:#4ac26b}
    .timeline{display:flex;flex-direction:column;gap:0}
    .timeline-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--bg-card);align-items:flex-start;min-width:0}
    .timeline-item:last-child{border-bottom:none}
    .timeline-dot{width:8px;height:8px;border-radius:50%;background:var(--border);flex-shrink:0;margin-top:6px}
    .timeline-content{flex:1;min-width:0}
    .timeline-msg{font-size:12px;color:var(--text);line-height:1.4;word-break:break-word}
    .timeline-meta{font-size:11px;color:var(--text-muted);margin-top:2px;font-family:ui-monospace,monospace}
    .feature-list{list-style:none;display:flex;flex-direction:column;gap:10px}
    .feature-key{font-weight:600;color:var(--text);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}
    .feature-val{font-family:ui-monospace,monospace;font-size:12px;color:var(--text-muted);word-break:break-word}
    .type-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid var(--border);background:var(--bg-card)}
    .type-webapp{border-color:#4ac26b;color:#1a7f37;background:#dafbe1}
    .type-cli{border-color:#d4a72c;color:#9a6700;background:#fff8c5}
    .type-library{border-color:#54aeff;color:#0969da;background:#ddf4ff}
    .type-service{border-color:#ff8182;color:#cf222e;background:#ffebe9}
    [data-theme="dark"] .type-webapp{background:#1a3a24}
    [data-theme="dark"] .type-cli{background:#2a2000}
    [data-theme="dark"] .type-library{background:#1c2a3a}
    [data-theme="dark"] .type-service{background:#3a1c1c}
    .release-list{list-style:none;display:flex;flex-direction:column;gap:0}
    .release-item{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--bg-card);font-size:13px;gap:8px;min-width:0}
    .release-item:last-child{border-bottom:none}
    .release-tag{font-family:ui-monospace,monospace;font-size:12px;font-weight:600;color:var(--link);flex-shrink:0}
    .release-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text);font-size:12px}
    .release-date{font-size:11px;color:var(--text-muted);flex-shrink:0}
    .diagram-wrap{overflow-x:auto;overflow-y:hidden;padding:8px 0}
    .diagram-wrap svg{display:block;min-width:260px;max-width:100%;height:auto}
    .section-divider{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);padding:20px 0 8px;border-bottom:1px solid var(--border);margin-bottom:12px}
    .lang-content{display:none}
    .lang-content.active{display:block}
    .lang-inline{display:none}
    .lang-inline.active{display:inline}
    .footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--border);color:var(--text-muted);font-size:12px;text-align:center}
    @media(max-width:720px){
      .grid-2,.grid-3,.grid-4{grid-template-columns:1fr}
      .nav{padding:0 16px}
      .container{padding:20px 14px 48px}
      .search-row{flex-direction:column}
      .search-row button{width:100%}
      .stat-value{font-size:18px}
      .perfil-hero{flex-direction:column;align-items:center;text-align:center}
      .tips-grid{grid-template-columns:1fr}
      .repo-row-right{display:none}
    }
  </style>
</head>
<body>
<nav class="nav">
  <div class="nav-left"><span class="nav-logo">Enki<span>Docs</span></span></div>
  <div class="nav-right">
    <button class="btn-nav" onclick="toggleLang()">EN / ES</button>
    <button class="btn-nav" onclick="toggleTheme()">Dark / Light</button>
  </div>
</nav>
<div class="container">
  <div class="search-block">
    <h1>
      <span class="lang-content active" data-l="es">Analiza GitHub</span>
      <span class="lang-content" data-l="en">Analyze GitHub</span>
    </h1>
    <p>
      <span class="lang-content active" data-l="es">Pega una URL de repositorio, usuario u organización de GitHub.</span>
      <span class="lang-content" data-l="en">Paste a GitHub repository, user or organization URL.</span>
    </p>
    <form method="POST">
      <div class="search-row">
        <input name="repo"
               placeholder="https://github.com/usuario  o  https://github.com/usuario/repo"
               value="{{ repo_url }}" autocomplete="off" spellcheck="false">
        <button type="submit">
          <span class="lang-content active" data-l="es">Analizar</span>
          <span class="lang-content" data-l="en">Analyze</span>
        </button>
      </div>
    </form>
  </div>
  {{ resultado|safe }}
  <div class="footer">EnkiDocs &middot; Flask + GitHub API</div>
</div>
<script>
const html=document.documentElement;
function toggleTheme(){html.dataset.theme=html.dataset.theme==='dark'?'light':'dark';localStorage.setItem('theme',html.dataset.theme)}
function toggleLang(){const lang=html.dataset.lang==='es'?'en':'es';html.dataset.lang=lang;localStorage.setItem('lang',lang);document.querySelectorAll('.lang-content,.lang-inline').forEach(el=>{el.classList.toggle('active',el.dataset.l===lang)})}
function copyCmd(btn){const text=btn.previousElementSibling.textContent.trim();navigator.clipboard.writeText(text).then(()=>{btn.textContent='copied';setTimeout(()=>btn.textContent='copy',1500)})}
const savedTheme=localStorage.getItem('theme');const savedLang=localStorage.getItem('lang');
if(savedTheme)html.dataset.theme=savedTheme;
if(savedLang&&savedLang!=='es')toggleLang();
</script>
</body>
</html>
"""


@app.route('/', methods=['GET','POST'])
def home():
    resultado=""; repo_url=""
    if request.method=='POST':
        repo_url=request.form['repo']
        tipo_url,param1,param2=detectar_tipo(repo_url)
        try:
            if tipo_url=="perfil":
                pdata=get_perfil_info(param1)
                resultado=construir_perfil_html(pdata)

            elif tipo_url=="repo":
                owner=param1; repo=param2
                data=get_repo_info(owner,repo)
                info=data["info"]; uso=analizar_uso(data)
                actividad=analizar_actividad(data); exp_es,exp_en=generar_explicacion(data)
                stars=info.get("stargazers_count",0); forks=info.get("forks_count",0)
                issues=info.get("open_issues_count",0); watchers=info.get("watchers_count",0)
                badges=""
                if info.get("language"): badges+=f'<span class="badge">{info["language"]}</span>'
                if info.get("license") and info["license"].get("spdx_id"): badges+=f'<span class="badge">{info["license"]["spdx_id"]}</span>'
                for t in data.get("topics",[])[:5]: badges+=f'<span class="badge">{t}</span>'
                tipo_labels={"webapp":("Web App","Web App"),"cli":("CLI Tool","CLI Tool"),"library":("Library","Library"),"service":("Service","Service")}
                tipo=uso["tipo"]; tipo_es,tipo_en=tipo_labels.get(tipo,("Project","Project"))
                tipo_html=f'<span class="type-badge type-{tipo}"><span class="lang-inline active" data-l="es">{tipo_es}</span><span class="lang-inline" data-l="en">{tipo_en}</span></span>'
                langs_html="".join(f'<span class="tag">{l}</span>' for l in data["languages"].keys())
                archivos_html="".join(f'<li><span class="file-ext">{(a.split(".")[-1].lower() if "." in a else "dir")[:6]}</span><span>{a}</span></li>' for a in data["contents"])
                contributors_html=""
                if isinstance(data["contributors"],list):
                    for c in data["contributors"]:
                        contributors_html+=f'<li><span class="contrib-name">{c.get("login","")}</span><span class="contrib-count">{c.get("contributions",0)} commits</span></li>'
                steps_html="".join(f'<div class="step"><div class="step-num">{i}</div><div class="step-content"><div class="step-title">{t}</div><div class="step-cmd"><span>{cmd}</span><button class="copy-btn" onclick="copyCmd(this)">copy</button></div></div></div>' for i,(t,cmd) in enumerate(uso["pasos"],1))
                ejemplos_html=""
                if uso["ejemplos"]:
                    ejemplos_html='<div class="code-example-label"><span class="lang-inline active" data-l="es">Ejemplos del README:</span><span class="lang-inline" data-l="en">Examples from README:</span></div>'
                    for ej in uso["ejemplos"]: ejemplos_html+=f'<div class="code-example">{ej}</div>'
                checklist_html=""
                for ok,label_es,label_en in [(uso["tiene_tests"],"Tests","Tests"),(uso["tiene_docker"],"Docker","Docker"),(uso["tiene_ci"],"CI/CD","CI/CD"),(uso["tiene_docs"],"Documentación","Documentation"),(uso["tiene_license"],"Licencia","License")]:
                    icon="✓" if ok else "·"; cls="check-yes" if ok else "check-no"
                    checklist_html+=f'<li><span class="check-icon {cls}">{icon}</span><span class="lang-inline active" data-l="es">{label_es}</span><span class="lang-inline" data-l="en">{label_en}</span></li>'
                features_html=""
                if uso["features"]:
                    for key,val in uso["features"]: features_html+=f'<li><div class="feature-key">{key}</div><div class="feature-val">{val}</div></li>'
                timeline_html="".join(f'<div class="timeline-item"><div class="timeline-dot"></div><div class="timeline-content"><div class="timeline-msg">{item["mensaje"]}</div><div class="timeline-meta">{item["fecha"]} &middot; {item["autor"]}</div></div></div>' for item in actividad)
                releases_html=""
                for rel in data["releases"][:3]:
                    releases_html+=f'<li class="release-item"><span class="release-tag">{rel.get("tag_name","")}</span><span class="release-name">{rel.get("name",rel.get("tag_name",""))[:36]}</span><span class="release-date">{rel.get("published_at","")[:10]}</span></li>'
                readme_html=""
                if data.get("readme"):
                    readme_html=f'<div class="grid-1"><div class="card"><div class="card-header">README <span class="label">{info.get("name")}</span></div><div class="card-body scroll"><div class="readme-box">{data["readme"]}</div></div></div></div>'
                d_flujo=generar_diagrama_flujo(data); d_estruc=generar_diagrama_estructura(data)
                d_arq=generar_diagrama_arquitectura(data); d_deps=generar_diagrama_deps(data)
                seccion_preguntas=construir_seccion_preguntas(data)

                resultado=f"""
                <div class="section-divider"><span class="lang-inline active" data-l="es">Repositorio</span><span class="lang-inline" data-l="en">Repository</span></div>
                <div class="grid-1"><div class="card repo-card"><div class="card-header">{tipo_html}<span class="label">{info.get('full_name','')}</span></div><div class="card-body"><div class="repo-name">{info.get('name')}</div><div class="repo-desc">{info.get('description') or '—'}</div><div class="badges">{badges}</div></div></div></div>
                <div class="grid-4"><div class="card stat-card"><div class="card-body"><span class="stat-value">{stars:,}</span><div class="stat-label">stars</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{forks:,}</span><div class="stat-label">forks</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{issues}</span><div class="stat-label">open issues</div></div></div><div class="card stat-card"><div class="card-body"><span class="stat-value">{watchers:,}</span><div class="stat-label">watchers</div></div></div></div>
                <div class="section-divider"><span class="lang-inline active" data-l="es">Descripcion</span><span class="lang-inline" data-l="en">About</span></div>
                <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Que es</span><span class="lang-content" data-l="en">What it is</span></div><div class="card-body scroll"><div class="text-content"><span class="lang-content active" data-l="es">{exp_es}</span><span class="lang-content" data-l="en">{exp_en}</span></div></div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Lenguajes</span><span class="lang-content" data-l="en">Languages</span></div><div class="card-body"><div class="tag-list">{langs_html}</div></div></div></div>
                <div class="section-divider"><span class="lang-inline active" data-l="es">Como se usa</span><span class="lang-inline" data-l="en">How to use</span></div>
                <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Instalacion</span><span class="lang-content" data-l="en">Installation</span></div><div class="card-body scroll"><div class="uso-desc"><span class="lang-content active" data-l="es">{uso['uso_desc_es']}</span><span class="lang-content" data-l="en">{uso['uso_desc_en']}</span></div><div class="steps">{steps_html}</div>{ejemplos_html}</div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Incluye</span><span class="lang-content" data-l="en">Includes</span></div><div class="card-body"><ul class="checklist">{checklist_html}</ul></div></div></div>
                {"" if not features_html else f'<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Analisis del codigo</span><span class="lang-content" data-l="en">Code analysis</span></div><div class="card-body scroll"><ul class="feature-list">{features_html}</ul></div></div></div>'}
                {seccion_preguntas}
                <div class="section-divider"><span class="lang-inline active" data-l="es">Actividad</span><span class="lang-inline" data-l="en">Activity</span></div>
                <div class="grid-{"3" if releases_html else "2"}"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Commits recientes</span><span class="lang-content" data-l="en">Recent commits</span></div><div class="card-body scroll"><div class="timeline">{timeline_html}</div></div></div>{"" if not releases_html else f'<div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Versiones</span><span class="lang-content" data-l="en">Releases</span></div><div class="card-body scroll"><ul class="release-list">{releases_html}</ul></div></div>'}<div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Contribuidores</span><span class="lang-content" data-l="en">Contributors</span></div><div class="card-body scroll"><ul class="contrib-list">{contributors_html}</ul></div></div></div>
                <div class="section-divider"><span class="lang-inline active" data-l="es">Estructura</span><span class="lang-inline" data-l="en">Structure</span></div>
                <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Archivos raiz</span><span class="lang-content" data-l="en">Root files</span></div><div class="card-body scroll"><ul class="file-list">{archivos_html}</ul></div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Estructura</span><span class="lang-content" data-l="en">File structure</span></div><div class="card-body diagram-wrap">{d_estruc}</div></div></div>
                {readme_html}
                <div class="section-divider"><span class="lang-inline active" data-l="es">Diagramas</span><span class="lang-inline" data-l="en">Diagrams</span></div>
                <div class="grid-2"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Flujo</span><span class="lang-content" data-l="en">Flow</span></div><div class="card-body diagram-wrap">{d_flujo}</div></div><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Arquitectura</span><span class="lang-content" data-l="en">Architecture</span></div><div class="card-body diagram-wrap">{d_arq}</div></div></div>
                {"" if not d_deps else f'<div class="grid-1"><div class="card"><div class="card-header"><span class="lang-content active" data-l="es">Dependencias</span><span class="lang-content" data-l="en">Dependencies</span></div><div class="card-body diagram-wrap">{d_deps}</div></div></div>'}
                """
            else:
                resultado='<div class="card"><div class="card-body" style="color:var(--text-muted);font-size:13px">URL no reconocida. Usa github.com/usuario o github.com/usuario/repo</div></div>'
        except Exception as e:
            resultado=f'<div class="card"><div class="card-body" style="color:#cf222e;font-size:13px">Error: {str(e)}</div></div>'

    return render_template_string(TEMPLATE,resultado=resultado,repo_url=repo_url)


if __name__ == '__main__':
    app.run(debug=True)