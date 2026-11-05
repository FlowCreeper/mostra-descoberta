#!/usr/bin/env python3
"""Mostra em Descoberta - servidor da gamificação (somente biblioteca padrão).

Uso:  python3 server.py            (porta 8000)
      PORT=9000 ADMIN_PIN=1234 python3 server.py
"""
import json, os, re, secrets, sqlite3, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "mostra.db")
STATIC = os.path.join(BASE, "static")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "2026")  # PIN inicial; depois pode ser trocado no painel
META = 3  # projetos para concluir o desafio
DEFAULT_SETTINGS = {"min_avaliacoes": 10, "nota_minima": 4.5, "min_avaliacoes_nota": 4}
DEFAULT_CRITERIA = ["Clareza da explicação", "Criatividade da proposta", "Relevância ou utilidade"]
lock = threading.Lock()
RESERVA_SEG = 180
reservas = {}  # código -> instante em que a reserva expira (memória: some ao reiniciar)


def reservas_ativas():
    agora = time.time()
    for c in [c for c, t in reservas.items() if t < agora]:
        del reservas[c]
    return reservas


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS projects(
            code TEXT PRIMARY KEY, title TEXT NOT NULL, team TEXT DEFAULT '',
            summary TEXT DEFAULT '', criteria TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS passports(
            code TEXT PRIMARY KEY, created TEXT DEFAULT (datetime('now','localtime')));
        CREATE TABLE IF NOT EXISTS schools(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL REFERENCES schools(id), name TEXT NOT NULL, UNIQUE(school_id, name));
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL REFERENCES schools(id), class_id INTEGER REFERENCES classes(id),
            message TEXT NOT NULL, created TEXT DEFAULT (datetime('now','localtime')), ended TEXT);
        CREATE TABLE IF NOT EXISTS raffles(id INTEGER PRIMARY KEY AUTOINCREMENT,
            passport TEXT NOT NULL REFERENCES passports(code), prize TEXT NOT NULL, pickup TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now','localtime')), claimed TEXT);
        CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), pin TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS evaluations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            passport TEXT NOT NULL REFERENCES passports(code),
            project TEXT NOT NULL REFERENCES projects(code) ON DELETE CASCADE,
            scores TEXT NOT NULL, total INTEGER NOT NULL,
            created TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(passport, project));
        """)
        pcols = [r[1] for r in con.execute("PRAGMA table_info(passports)")]
        if "school_id" not in pcols:
            con.execute("ALTER TABLE passports ADD COLUMN school_id INTEGER REFERENCES schools(id)")
            con.execute("ALTER TABLE passports ADD COLUMN class_id INTEGER REFERENCES classes(id)")
        if "activated" not in pcols:
            con.execute("ALTER TABLE passports ADD COLUMN activated TEXT")
            # passaportes antigos que já avaliaram contam como em uso
            con.execute("UPDATE passports SET activated=datetime('now','localtime') WHERE code IN (SELECT passport FROM evaluations)")
        cols = [r[1] for r in con.execute("PRAGMA table_info(projects)")]
        if "course_id" not in cols:
            con.execute("ALTER TABLE projects ADD COLUMN course_id INTEGER REFERENCES courses(id)")
        if "location" not in cols:
            con.execute("ALTER TABLE projects ADD COLUMN location TEXT DEFAULT ''")
        if "token" not in cols:
            con.execute("ALTER TABLE projects ADD COLUMN token TEXT")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_token ON projects(token)")
        if "team_token" not in cols:
            con.execute("ALTER TABLE projects ADD COLUMN team_token TEXT")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_team ON projects(team_token)")
        con.execute("INSERT OR IGNORE INTO admin VALUES(1, ?)", (ADMIN_PIN,))
        if con.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            demo = [
                ("P01", "Horta automatizada", "Equipe Verde", "Sensor de umidade que liga a irrigação sozinho."),
                ("P02", "Robô seguidor de linha", "Equipe Circuito", "Robô com Arduino que percorre trajetos marcados."),
                ("P03", "Filtro de água caseiro", "Equipe Água Limpa", "Filtro com materiais recicláveis e testes de turbidez."),
                ("P04", "Mapa de calor do campus", "Equipe Dados", "Visualização das áreas mais quentes da faculdade."),
            ]
            for c, t, tm, s in demo:
                con.execute("INSERT INTO projects(code, title, team, summary, criteria) VALUES(?,?,?,?,?)",
                            (c, t, tm, s, json.dumps(DEFAULT_CRITERIA)))
        for (code,) in con.execute("SELECT code FROM projects WHERE token IS NULL").fetchall():
            con.execute("UPDATE projects SET token=? WHERE code=?", (new_token(con), code))
        for (code,) in con.execute("SELECT code FROM projects WHERE team_token IS NULL").fetchall():
            con.execute("UPDATE projects SET team_token=? WHERE code=?", (new_team_token(con), code))


def get_settings(con):
    s = dict(DEFAULT_SETTINGS)
    for r in con.execute("SELECT key, value FROM settings"):
        s[r[0]] = r[1]
    s["min_avaliacoes"] = int(s["min_avaliacoes"])
    s["min_avaliacoes_nota"] = int(s["min_avaliacoes_nota"])
    return s


def valid_passport(con, code):
    return bool(code) and con.execute("SELECT 1 FROM passports WHERE code=?", (code.upper(),)).fetchone() is not None


def new_token(con):
    """Código secreto do estande: só aparece no cartaz físico, para exigir a visita."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        t = "".join(secrets.choice(alphabet) for _ in range(5))
        if not con.execute("SELECT 1 FROM projects WHERE token=?", (t,)).fetchone():
            return t


def new_team_token(con):
    """Código de acesso da equipe à própria página de acompanhamento."""
    while True:
        t = "EQ-" + secrets.token_urlsafe(6).replace("-", "x").replace("_", "y").upper()
        if not con.execute("SELECT 1 FROM projects WHERE team_token=?", (t,)).fetchone():
            return t


def active_alerts(con, school_id=None, class_id=None):
    """Alertas ativos. Com escola: só os que atingem essa escola/turma."""
    sql = """SELECT a.id, a.school_id, a.class_id, a.message, a.created, s.name AS escola, c.name AS turma
        FROM alerts a JOIN schools s ON s.id=a.school_id LEFT JOIN classes c ON c.id=a.class_id
        WHERE a.ended IS NULL"""
    args = []
    if school_id is not None:
        sql += " AND a.school_id=? AND (a.class_id IS NULL OR a.class_id=?)"
        args = [school_id, class_id]
    return [dict(r) for r in con.execute(sql + " ORDER BY a.id DESC", args)]


def raffle_pool(con):
    """Quem concorre ao sorteio: avaliou ao menos META projetos e ainda não ganhou (uma participação por visitante)."""
    return [r[0] for r in con.execute("""SELECT passport FROM evaluations GROUP BY passport HAVING COUNT(*) >= ?
        AND passport NOT IN (SELECT passport FROM raffles) ORDER BY passport""", (META,))]


def project_row(r, admin=False):
    keys = r.keys()
    out = {"code": r["code"], "title": r["title"], "team": r["team"],
           "summary": r["summary"], "criteria": json.loads(r["criteria"]),
           "course_id": r["course_id"], "course": r["course"] if "course" in keys else None,
           "location": r["location"] or ""}
    if admin:
        out["token"] = r["token"]
        out["team_token"] = r["team_token"]
    return out


PROJECTS_SQL = "SELECT p.*, c.name AS course FROM projects p LEFT JOIN courses c ON c.id=p.course_id"


# Selos: só dependem de quantos/quais projetos foram avaliados, nunca das notas dadas.
BADGES = [
    {"id": "primeira", "icon": "🔍", "name": "Primeira descoberta", "desc": "Avalie seu primeiro projeto."},
    {"id": "conheca3", "icon": "🏅", "name": "Conheça três", "desc": "Avalie 3 projetos diferentes.", "principal": True},
    {"id": "explorador", "icon": "🧭", "name": "Explorador", "desc": "Avalie 5 projetos diferentes."},
    {"id": "maratonista", "icon": "🏃", "name": "Maratonista da ciência", "desc": "Avalie 10 projetos diferentes."},
    {"id": "ponte", "icon": "🌉", "name": "Ponte entre cursos", "desc": "Avalie projetos de 2 cursos diferentes."},
    {"id": "multi", "icon": "🌐", "name": "Multidisciplinar", "desc": "Avalie projetos de 3 cursos diferentes."},
    {"id": "curso", "icon": "🎓", "name": "Curso completo", "desc": "Avalie todos os projetos de um curso (mínimo 2)."},
    {"id": "pioneiro", "icon": "🚀", "name": "Pioneiro", "desc": "Esteja entre os 10 primeiros a concluir o Conheça três."},
    {"id": "mostra", "icon": "🌟", "name": "Mostra completa", "desc": "Avalie todos os projetos da mostra."},
]


def compute_badges(con, code, regs):
    n = len(regs)
    done = {r["project"] for r in regs}
    proj = con.execute("SELECT code, course_id FROM projects").fetchall()
    course_of = {r["code"]: r["course_id"] for r in proj}
    my_courses = {course_of.get(c) for c in done} - {None}
    by_course = {}
    for r in proj:
        if r["course_id"] is not None:
            by_course.setdefault(r["course_id"], set()).add(r["code"])
    curso_completo = [cid for cid, codes in by_course.items() if len(codes) >= 2 and codes <= done]
    pioneiro = False
    if n >= META:
        # ordem de conclusão = horário da 3ª avaliação de cada passaporte
        row = con.execute("""SELECT COUNT(*) FROM (
            SELECT passport, (SELECT id FROM evaluations e2 WHERE e2.passport=e.passport ORDER BY id LIMIT 1 OFFSET ?) AS fim
            FROM evaluations e GROUP BY passport HAVING COUNT(*) >= ?) t
            WHERE fim < (SELECT id FROM evaluations WHERE passport=? ORDER BY id LIMIT 1 OFFSET ?)""",
                          (META - 1, META, code, META - 1)).fetchone()
        pioneiro = row[0] < 10
    got = {
        "primeira": n >= 1, "conheca3": n >= META, "explorador": n >= 5, "maratonista": n >= 10,
        "ponte": len(my_courses) >= 2, "multi": len(my_courses) >= 3, "curso": bool(curso_completo),
        "pioneiro": pioneiro, "mostra": bool(proj) and len(done) >= len(proj),
    }
    return [{**b, "conquistado": got[b["id"]]} for b in BADGES]


def passport_data(con, code):
    rows = con.execute("""SELECT e.project, p.title, e.scores, e.total, e.created
        FROM evaluations e JOIN projects p ON p.code=e.project
        WHERE e.passport=? ORDER BY e.id""", (code,)).fetchall()
    regs = [{"project": r["project"], "title": r["title"], "scores": json.loads(r["scores"]),
             "total": r["total"], "created": r["created"]} for r in rows]
    selos = compute_badges(con, code, regs)
    pp = con.execute("""SELECT p.created, p.activated, p.school_id, p.class_id, s.name AS escola, c.name AS turma
        FROM passports p LEFT JOIN schools s ON s.id=p.school_id LEFT JOIN classes c ON c.id=p.class_id
        WHERE p.code=?""", (code,)).fetchone()
    alertas = active_alerts(con, pp["school_id"], pp["class_id"]) if pp["school_id"] else []
    return {"code": code, "emitido": pp["created"], "ativado": pp["activated"],
            "school_id": pp["school_id"], "class_id": pp["class_id"], "escola": pp["escola"], "turma": pp["turma"],
            "alertas": alertas, "bloqueado": bool(alertas), "assinaturas": len(regs), "meta": META,
            "premios": [dict(r) for r in con.execute(
                "SELECT id, prize, pickup, created, claimed FROM raffles WHERE passport=? ORDER BY id", (code,))],
            "concluido": len(regs) >= META, "registros": regs,
            "selos": selos, "total_selos": sum(b["conquistado"] for b in selos)}


def new_code(con):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "MD-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not con.execute("SELECT 1 FROM passports WHERE code=?", (code,)).fetchone():
            return code


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass

    # ---------- helpers ----------
    def send(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def is_admin(self):
        with db() as con:
            pin = con.execute("SELECT pin FROM admin WHERE id=1").fetchone()[0]
        return secrets.compare_digest(self.headers.get("X-Admin-Pin") or "", pin)

    def static(self, name):
        path = os.path.join(STATIC, name)
        if not os.path.isfile(path):
            return self.send(404, {"erro": "não encontrado"})
        ctype = {"html": "text/html", "js": "application/javascript", "css": "text/css"}.get(
            name.rsplit(".", 1)[-1], "application/octet-stream")
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- routes ----------
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/" or p.startswith("/avaliar/") or p == "/passaporte":
            return self.static("index.html")
        if p == "/admin":
            return self.static("admin.html")
        if p.startswith("/equipe/"):
            return self.static("equipe.html")
        if p.startswith("/static/"):
            return self.static(os.path.basename(p))
        qs = parse_qs(urlparse(self.path).query)
        with db() as con:
            if p.startswith("/api/projects") and not (self.is_admin() or valid_passport(con, (qs.get("passport") or [""])[0])):
                return self.send(403, {"erro": "É preciso um passaporte válido para acessar os projetos."})
            if p == "/api/projects":
                rows = con.execute(PROJECTS_SQL + " ORDER BY p.code").fetchall()
                return self.send(200, [project_row(r) for r in rows])
            m = re.fullmatch(r"/api/equipe/([\w-]+)", p)
            if m:  # página de acompanhamento da equipe (só o próprio projeto, sem ranking)
                r = con.execute(PROJECTS_SQL + " WHERE p.team_token=?", (m[1].upper(),)).fetchone()
                if not r:
                    return self.send(404, {"erro": "Link da equipe inválido. Peça um novo à organização."})
                pr = project_row(r)
                evs = con.execute("SELECT scores, total, created FROM evaluations WHERE project=? ORDER BY id DESC",
                                  (pr["code"],)).fetchall()
                n = len(evs)
                per = [0.0] * len(pr["criteria"])
                for e in evs:
                    for i, sc in enumerate(json.loads(e["scores"])[:len(per)]):
                        per[i] += sc
                soma = sum(e["total"] for e in evs)
                pr.update({"avaliacoes": n, "soma": soma,
                           "media_geral": round(soma / (n * len(per)), 2) if n else None,
                           "media_criterios": [round(x / n, 2) if n else None for x in per],
                           "registros": [{"scores": json.loads(e["scores"]), "total": e["total"], "created": e["created"]} for e in evs],
                           "alertas": active_alerts(con)})
                return self.send(200, pr)
            m = re.fullmatch(r"/api/estande/([\w-]+)", p)
            if m:  # formulário: só com o código secreto do cartaz do estande
                if not valid_passport(con, (qs.get("passport") or [""])[0]):
                    return self.send(403, {"erro": "É preciso um passaporte válido para avaliar."})
                r = con.execute(PROJECTS_SQL + " WHERE p.token=?", (m[1].upper(),)).fetchone()
                return self.send(200, project_row(r)) if r else self.send(404, {"erro": "Código de estande não encontrado. Confira o código no cartaz do projeto."})
            m = re.fullmatch(r"/api/passports/([\w-]+)", p)
            if m:
                code = m[1].upper()
                if not con.execute("SELECT 1 FROM passports WHERE code=?", (code,)).fetchone():
                    return self.send(404, {"erro": "Passaporte não encontrado."})
                return self.send(200, passport_data(con, code))
            if p.startswith("/api/admin/"):
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                return self.admin_get(con, p)
        self.send(404, {"erro": "não encontrado"})

    def admin_get(self, con, p):
        if p == "/api/admin/passports/versao":  # leve, para atualização em tempo real
            r = con.execute("""SELECT (SELECT COUNT(*) FROM passports), (SELECT COUNT(activated) FROM passports),
                (SELECT IFNULL(MAX(id), 0) FROM evaluations), (SELECT COUNT(*) FROM evaluations),
                (SELECT COUNT(school_id) || '.' || IFNULL(SUM(school_id), 0) || '.' || IFNULL(SUM(class_id), 0) FROM passports),
                (SELECT COUNT(*) || '.' || COUNT(ended) FROM alerts),
                (SELECT COUNT(*) || '.' || COUNT(claimed) FROM raffles)""").fetchone()
            res = reservas_ativas()
            return self.send(200, {"versao": "-".join(map(str, r)) + "|" + ",".join(sorted(res)), "reservados": sorted(res)})
        if p == "/api/admin/passports":
            codes = [r[0] for r in con.execute("SELECT code FROM passports ORDER BY created DESC")]
            res = reservas_ativas()
            return self.send(200, [{**passport_data(con, c), "reservado": c in res} for c in codes])
        if p == "/api/admin/projects":
            st = get_settings(con)
            out = []
            for r in con.execute(PROJECTS_SQL + " ORDER BY p.code").fetchall():
                pr = project_row(r, admin=True)
                evs = con.execute("SELECT passport, scores, total, created FROM evaluations WHERE project=? ORDER BY id",
                                  (pr["code"],)).fetchall()
                n = len(evs)
                soma = sum(e["total"] for e in evs)
                per = [0.0] * len(pr["criteria"])
                for e in evs:
                    for i, s in enumerate(json.loads(e["scores"])[:len(per)]):
                        per[i] += s
                pr.update({
                    "avaliacoes": n, "soma": soma,
                    "media_geral": round(soma / (n * len(pr["criteria"])), 2) if n else None,
                    "media_criterios": [round(x / n, 2) if n else None for x in per],
                    "por_avaliacoes": n >= st["min_avaliacoes"],
                    # regra da nota só vale com um mínimo de avaliações (evita 1 pessoa dar 5 e o projeto entrar)
                    "por_nota": n >= st["min_avaliacoes_nota"] and soma / (n * len(pr["criteria"])) >= st["nota_minima"],
                    "registros": [{"passport": e["passport"], "scores": json.loads(e["scores"]),
                                   "total": e["total"], "created": e["created"]} for e in evs]})
                pr["elegivel"] = pr["por_avaliacoes"] or pr["por_nota"]
                out.append(pr)
            return self.send(200, out)
        if p == "/api/admin/indicador":
            total = con.execute("SELECT COUNT(*) FROM passports").fetchone()[0]
            ok = con.execute("""SELECT COUNT(*) FROM (SELECT passport FROM evaluations
                GROUP BY passport HAVING COUNT(*)>=?)""", (META,)).fetchone()[0]
            nev = con.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
            return self.send(200, {"visitantes": total, "concluiram": ok, "avaliacoes": nev,
                                   "percentual": round(ok * 100 / total, 1) if total else 0,
                                   "meta_percentual": 60, **get_settings(con)})
        if p == "/api/admin/settings":
            return self.send(200, get_settings(con))
        if p == "/api/admin/alerts":
            return self.send(200, active_alerts(con))
        if p == "/api/admin/sorteios":
            return self.send(200, {"elegiveis": len(raffle_pool(con)), "sorteios": [dict(r) for r in con.execute(
                """SELECT r.*, s.name AS escola, c.name AS turma FROM raffles r JOIN passports p ON p.code=r.passport
                LEFT JOIN schools s ON s.id=p.school_id LEFT JOIN classes c ON c.id=p.class_id ORDER BY r.id DESC""")]})
        if p == "/api/admin/schools":
            out = []
            for s_ in con.execute("SELECT id, name FROM schools ORDER BY name").fetchall():
                classes = [dict(c) for c in con.execute("""SELECT c.id, c.name,
                    (SELECT COUNT(*) FROM passports p WHERE p.class_id=c.id) AS passaportes
                    FROM classes c WHERE c.school_id=? ORDER BY c.name""", (s_["id"],))]
                n = con.execute("SELECT COUNT(*) FROM passports WHERE school_id=?", (s_["id"],)).fetchone()[0]
                out.append({"id": s_["id"], "name": s_["name"], "classes": classes, "passaportes": n,
                            "alertas": [a for a in active_alerts(con) if a["school_id"] == s_["id"]]})
            return self.send(200, out)
        if p == "/api/admin/courses":
            rows = con.execute("""SELECT c.id, c.name, COUNT(p.code) AS projetos FROM courses c
                LEFT JOIN projects p ON p.course_id=c.id GROUP BY c.id ORDER BY c.name""").fetchall()
            return self.send(200, [dict(r) for r in rows])
        self.send(404, {"erro": "não encontrado"})

    def do_POST(self):
        p = urlparse(self.path).path
        data = self.body()
        with lock, db() as con:
            m = re.fullmatch(r"/api/passports/([\w-]+)/ativar", p)
            if m:
                code = m[1].upper()
                if not con.execute("SELECT 1 FROM passports WHERE code=?", (code,)).fetchone():
                    return self.send(404, {"erro": "Passaporte não encontrado. Confira o código do cartão."})
                con.execute("UPDATE passports SET activated=COALESCE(activated, datetime('now','localtime')) WHERE code=?", (code,))
                return self.send(200, passport_data(con, code))
            m = re.fullmatch(r"/api/admin/passports/([\w-]+)/(reservar|liberar)", p)
            if m:
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                code = m[1].upper()
                res = reservas_ativas()
                if m[2] == "liberar":
                    res.pop(code, None)
                    return self.send(200, {"ok": True})
                row = con.execute("SELECT activated FROM passports WHERE code=?", (code,)).fetchone()
                if not row:
                    return self.send(404, {"erro": "Passaporte não encontrado."})
                if row[0]:
                    return self.send(409, {"erro": "Este passaporte já está em uso."})
                if code in res and not data.get("renovar"):
                    return self.send(409, {"erro": "Este passaporte está sendo entregue em outro atendimento."})
                res[code] = time.time() + RESERVA_SEG
                return self.send(200, {"ok": True, "expira_em": RESERVA_SEG})
            if p == "/api/passports":  # emissão somente pela organização
                if not self.is_admin():
                    return self.send(401, {"erro": "Passaportes são emitidos pela organização na entrada."})
                try:
                    qtd = max(1, min(500, int(data.get("quantidade", 1))))
                except (TypeError, ValueError):
                    return self.send(400, {"erro": "Quantidade inválida."})
                codes = []
                for _ in range(qtd):
                    codes.append(new_code(con))
                    con.execute("INSERT INTO passports(code) VALUES(?)", (codes[-1],))
                return self.send(201, {"codes": codes})
            if p == "/api/admin/courses":
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                name = str(data.get("name", "")).strip()
                if not name:
                    return self.send(400, {"erro": "Informe o nome do curso."})
                try:
                    if data.get("id"):
                        con.execute("UPDATE courses SET name=? WHERE id=?", (name, int(data["id"])))
                    else:
                        con.execute("INSERT INTO courses(name) VALUES(?)", (name,))
                except sqlite3.IntegrityError:
                    return self.send(409, {"erro": "Já existe um curso com esse nome."})
                return self.send(200, {"ok": True})
            if p == "/api/admin/pin":
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                nova = str(data.get("nova", ""))
                if not re.fullmatch(r"\d{4,8}", nova):
                    return self.send(400, {"erro": "O novo PIN deve ter de 4 a 8 números."})
                con.execute("UPDATE admin SET pin=? WHERE id=1", (nova,))
                return self.send(200, {"ok": True})
            if p == "/api/admin/settings":
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                try:
                    mi = int(data["min_avaliacoes"]); nm = float(data["nota_minima"]); mn = int(data["min_avaliacoes_nota"])
                    assert mi >= 1 and 1 <= nm <= 5 and 1 <= mn
                except Exception:
                    return self.send(400, {"erro": "Use mínimos de avaliações ≥ 1 e nota mínima entre 1 e 5."})
                con.execute("INSERT OR REPLACE INTO settings VALUES('min_avaliacoes', ?)", (mi,))
                con.execute("INSERT OR REPLACE INTO settings VALUES('nota_minima', ?)", (nm,))
                con.execute("INSERT OR REPLACE INTO settings VALUES('min_avaliacoes_nota', ?)", (mn,))
                return self.send(200, get_settings(con))
            if p == "/api/evaluate":
                return self.evaluate(con, data)
            if p.startswith("/api/admin/") and not self.is_admin():
                return self.send(401, {"erro": "PIN inválido"})
            m = re.fullmatch(r"/api/admin/passports/([\w-]+)/perfil", p)
            if m:
                code = m[1].upper()
                if not con.execute("SELECT 1 FROM passports WHERE code=?", (code,)).fetchone():
                    return self.send(404, {"erro": "Passaporte não encontrado."})
                sid = cid = None
                if data.get("tipo") == "escola":
                    try:
                        sid = int(data.get("school_id"))
                    except (TypeError, ValueError):
                        return self.send(400, {"erro": "Selecione a escola."})
                    if not con.execute("SELECT 1 FROM schools WHERE id=?", (sid,)).fetchone():
                        return self.send(400, {"erro": "Escola não encontrada."})
                    turmas = [r[0] for r in con.execute("SELECT id FROM classes WHERE school_id=?", (sid,))]
                    if data.get("class_id"):
                        cid = int(data["class_id"])
                        if cid not in turmas:
                            return self.send(400, {"erro": "Turma não pertence a essa escola."})
                    elif len(turmas) > 1:
                        return self.send(400, {"erro": "Essa escola tem mais de uma turma: selecione a turma."})
                    elif len(turmas) == 1:
                        cid = turmas[0]
                con.execute("UPDATE passports SET school_id=?, class_id=? WHERE code=?", (sid, cid, code))
                return self.send(200, {"ok": True})
            if p == "/api/admin/schools":
                name = str(data.get("name", "")).strip()[:120]
                if not name:
                    return self.send(400, {"erro": "Informe o nome da escola."})
                try:
                    if data.get("id"):
                        con.execute("UPDATE schools SET name=? WHERE id=?", (name, int(data["id"])))
                        return self.send(200, {"ok": True, "id": int(data["id"])})
                    cur = con.execute("INSERT INTO schools(name) VALUES(?)", (name,))
                except sqlite3.IntegrityError:
                    return self.send(409, {"erro": "Já existe uma escola com esse nome."})
                return self.send(200, {"ok": True, "id": cur.lastrowid})
            if p == "/api/admin/classes":
                name = str(data.get("name", "")).strip()[:80]
                try:
                    sid = int(data.get("school_id"))
                except (TypeError, ValueError):
                    return self.send(400, {"erro": "Escola inválida."})
                if not name or not con.execute("SELECT 1 FROM schools WHERE id=?", (sid,)).fetchone():
                    return self.send(400, {"erro": "Informe a escola e o nome da turma."})
                try:
                    cur = con.execute("INSERT INTO classes(school_id, name) VALUES(?,?)", (sid, name))
                except sqlite3.IntegrityError:
                    return self.send(409, {"erro": "Essa escola já tem uma turma com esse nome."})
                return self.send(200, {"ok": True, "id": cur.lastrowid})
            if p == "/api/admin/sorteios":
                prize = str(data.get("prize", "")).strip()[:120]
                pickup = str(data.get("pickup", "")).strip()[:200] or "Balcão da organização"
                if not prize:
                    return self.send(400, {"erro": "Informe o prêmio."})
                pool = raffle_pool(con)
                if not pool:
                    return self.send(409, {"erro": "Ninguém pode concorrer: é preciso ter avaliado 3 projetos e ainda não ter sido sorteado."})
                winner = secrets.choice(pool)
                con.execute("INSERT INTO raffles(passport, prize, pickup) VALUES(?,?,?)", (winner, prize, pickup))
                return self.send(200, {"ok": True, "ganhador": passport_data(con, winner), "concorreram": len(pool)})
            m = re.fullmatch(r"/api/admin/sorteios/(\d+)/(retirado|desfazer)", p)
            if m:
                con.execute("UPDATE raffles SET claimed=? WHERE id=?",
                            (time.strftime("%Y-%m-%d %H:%M:%S") if m[2] == "retirado" else None, int(m[1])))
                return self.send(200, {"ok": True})
            if p == "/api/admin/alerts":
                try:
                    sid = int(data.get("school_id"))
                except (TypeError, ValueError):
                    return self.send(400, {"erro": "Escola inválida."})
                cid = int(data["class_id"]) if data.get("class_id") else None
                srow = con.execute("SELECT name FROM schools WHERE id=?", (sid,)).fetchone()
                if not srow:
                    return self.send(400, {"erro": "Escola não encontrada."})
                msg = str(data.get("message", "")).strip()[:300] or "Visitantes desta escola: retornem ao ônibus."
                con.execute("INSERT INTO alerts(school_id, class_id, message) VALUES(?,?,?)", (sid, cid, msg))
                return self.send(200, {"ok": True})
            m = re.fullmatch(r"/api/admin/alerts/(\d+)/encerrar", p)
            if m:
                con.execute("UPDATE alerts SET ended=datetime('now','localtime') WHERE id=?", (int(m[1]),))
                return self.send(200, {"ok": True})
            m = re.fullmatch(r"/api/admin/projects/([\w-]+)/novo-acesso-equipe", p)
            if m:
                t = new_team_token(con)
                con.execute("UPDATE projects SET team_token=? WHERE code=?", (t, m[1].upper()))
                return self.send(200, {"ok": True, "team_token": t})
            m = re.fullmatch(r"/api/admin/projects/([\w-]+)/novo-codigo", p)
            if m:
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                t = new_token(con)
                con.execute("UPDATE projects SET token=? WHERE code=?", (t, m[1].upper()))
                return self.send(200, {"ok": True, "token": t})
            if p == "/api/admin/projects":
                if not self.is_admin():
                    return self.send(401, {"erro": "PIN inválido"})
                return self.save_project(con, data)
        self.send(404, {"erro": "não encontrado"})

    def do_DELETE(self):
        ms = re.fullmatch(r"/api/admin/(schools|classes)/(\d+)", urlparse(self.path).path)
        if ms:
            if not self.is_admin():
                return self.send(401, {"erro": "PIN inválido"})
            i = int(ms[2])
            with lock, db() as con:
                if ms[1] == "classes":
                    con.execute("UPDATE passports SET class_id=NULL WHERE class_id=?", (i,))
                    con.execute("DELETE FROM alerts WHERE class_id=?", (i,))
                    con.execute("DELETE FROM classes WHERE id=?", (i,))
                else:
                    con.execute("UPDATE passports SET school_id=NULL, class_id=NULL WHERE school_id=?", (i,))
                    con.execute("DELETE FROM alerts WHERE school_id=?", (i,))
                    con.execute("DELETE FROM classes WHERE school_id=?", (i,))
                    con.execute("DELETE FROM schools WHERE id=?", (i,))
            return self.send(200, {"ok": True})
        mc = re.fullmatch(r"/api/admin/courses/(\d+)", urlparse(self.path).path)
        if mc:
            if not self.is_admin():
                return self.send(401, {"erro": "PIN inválido"})
            with lock, db() as con:
                con.execute("UPDATE projects SET course_id=NULL WHERE course_id=?", (int(mc[1]),))
                con.execute("DELETE FROM courses WHERE id=?", (int(mc[1]),))
            return self.send(200, {"ok": True})
        m = re.fullmatch(r"/api/admin/projects/([\w-]+)", urlparse(self.path).path)
        if not m or not self.is_admin():
            return self.send(401, {"erro": "PIN inválido"})
        with lock, db() as con:
            con.execute("DELETE FROM evaluations WHERE project=?", (m[1],))
            con.execute("DELETE FROM projects WHERE code=?", (m[1],))
        self.send(200, {"ok": True})

    def evaluate(self, con, d):
        passport = str(d.get("passport", "")).strip().upper()
        token = str(d.get("estande", "")).strip().upper()
        if not con.execute("SELECT 1 FROM passports WHERE code=?", (passport,)).fetchone():
            return self.send(404, {"erro": "Passaporte não encontrado."})
        r = con.execute("SELECT * FROM projects WHERE token=?", (token,)).fetchone()
        if not r:
            return self.send(404, {"erro": "Código de estande inválido. Use o QR ou o código do cartaz do projeto."})
        project = r["code"]
        pp = con.execute("SELECT school_id, class_id FROM passports WHERE code=?", (passport,)).fetchone()
        if pp["school_id"] and active_alerts(con, pp["school_id"], pp["class_id"]):
            return self.send(423, {"erro": "Avaliações pausadas: sua escola foi chamada para retornar ao ônibus."})
        criteria = json.loads(r["criteria"])
        scores = d.get("scores")
        if (not isinstance(scores, list) or len(scores) != len(criteria)
                or not all(isinstance(s, int) and 1 <= s <= 5 for s in scores)):
            return self.send(400, {"erro": "Responda todos os critérios com notas de 1 a 5."})
        if con.execute("SELECT 1 FROM evaluations WHERE passport=? AND project=?", (passport, project)).fetchone():
            return self.send(409, {"erro": "Este passaporte já avaliou este projeto. A média e o progresso não foram alterados.",
                                   "passaporte": passport_data(con, passport)})
        antes = {b["id"] for b in passport_data(con, passport)["selos"] if b["conquistado"]}
        con.execute("INSERT INTO evaluations(passport, project, scores, total) VALUES(?,?,?,?)",
                    (passport, project, json.dumps(scores), sum(scores)))
        pp = passport_data(con, passport)
        novos = [b for b in pp["selos"] if b["conquistado"] and b["id"] not in antes]
        return self.send(201, {"ok": True, "pontos": sum(scores), "passaporte": pp, "novos_selos": novos})

    def save_project(self, con, d):
        code = re.sub(r"[^\w-]", "", str(d.get("code", "")).upper())
        title = str(d.get("title", "")).strip()
        criteria = [str(c).strip() for c in d.get("criteria", []) if str(c).strip()]
        if not code or not title or not criteria:
            return self.send(400, {"erro": "Código, título e ao menos um critério são obrigatórios."})
        course_id = d.get("course_id") or None
        if course_id is not None:
            try:
                course_id = int(course_id)
            except (TypeError, ValueError):
                return self.send(400, {"erro": "Curso inválido."})
            if not con.execute("SELECT 1 FROM courses WHERE id=?", (course_id,)).fetchone():
                return self.send(400, {"erro": "Curso não encontrado."})
        exists = con.execute("SELECT 1 FROM projects WHERE code=?", (code,)).fetchone()
        if exists and con.execute("SELECT 1 FROM evaluations WHERE project=?", (code,)).fetchone():
            old = json.loads(con.execute("SELECT criteria FROM projects WHERE code=?", (code,)).fetchone()[0])
            if len(old) != len(criteria):
                return self.send(409, {"erro": "Projeto já tem avaliações: não é possível mudar a quantidade de critérios."})
        con.execute("""INSERT INTO projects(code, title, team, summary, criteria, course_id, location, token, team_token)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(code) DO UPDATE SET title=excluded.title, team=excluded.team, summary=excluded.summary,
            criteria=excluded.criteria, course_id=excluded.course_id, location=excluded.location""",
                    (code, title, str(d.get("team", "")).strip(), str(d.get("summary", "")).strip(),
                     json.dumps(criteria), course_id, str(d.get("location", "")).strip()[:200], new_token(con),
                     new_team_token(con)))
        self.send(200, {"ok": True, "code": code})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8000))
    print(f"Mostra em Descoberta rodando em http://0.0.0.0:{port}  (admin: /admin)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
