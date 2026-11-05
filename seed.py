#!/usr/bin/env python3
"""Seeds da Mostra em Descoberta: um cenário por seed.

Uso:
    python3 seed.py                    # lista os cenários disponíveis
    python3 seed.py <cenário>          # faz backup do mostra.db e recria o banco com esse cenário
    python3 seed.py <cenário> --reset-pin   # idem, voltando o PIN para o padrão (2026 ou ADMIN_PIN)
    python3 seed.py <cenário> --se-vazio    # só popula se o banco estiver vazio (inicialização no Heroku)

O PIN atual é mantido. O backup fica em backups/. Depois, reinicie o servidor (./restart.sh).
"""
import json, os, random, shutil, sqlite3, sys
from datetime import datetime, timedelta

import server  # reaproveita o esquema e os geradores de código

BASE = os.path.dirname(os.path.abspath(__file__))
fmt = lambda d: d.strftime("%Y-%m-%d %H:%M:%S")
D3 = server.DEFAULT_CRITERIA

# ---------------------------------------------------------------- catálogo base
# code, título, equipe, curso, local, critérios, resumo
CATALOGO = [
    ("P01", "Horta automatizada", "Equipe Verde", "Engenharia de Software", "Pátio abaixo do bloco B", D3, "Sensor de umidade que liga a irrigação sozinho."),
    ("P02", "App de carona solidária", "Equipe Rota", "Engenharia de Software", "Bloco E, 2º andar, sala 204", D3, "Aplicativo que conecta alunos que moram perto."),
    ("P03", "Robô seguidor de linha", "Equipe Circuito", "Engenharia de Software", "Laboratório de robótica, bloco C", D3, "Robô com Arduino que percorre trajetos marcados."),
    ("P04", "Mapa de calor do campus", "Equipe Dados", "Engenharia de Software", "Hall de entrada do bloco A", D3, "Visualização das áreas mais quentes da faculdade."),
    ("P05", "Bioplástico de mandioca", "Equipe Raiz", "Biologia", "Bloco D, térreo, laboratório 3",
     ["Clareza da explicação", "Criatividade da proposta", "Relevância ou utilidade", "Rigor científico"], "Plástico biodegradável feito com amido."),
    ("P06", "Compostagem com minhocas", "Equipe Húmus", "Biologia", "Jardim atrás do bloco D", D3, "Minhocário para reaproveitar resíduos da cantina."),
    ("P07", "Mosquitos e água parada", "Equipe Alerta", "Biologia", "Bloco D, 1º andar, sala 110", D3, "Mapeamento de focos de mosquito no bairro."),
    ("P08", "Filtro de água caseiro", "Equipe Água Limpa", "Química", "Pátio central, tenda 2", D3, "Filtro com materiais recicláveis e testes de turbidez."),
    ("P09", "Sabão de óleo reciclado", "Equipe Espuma", "Química", "Pátio central, tenda 3",
     ["Clareza da explicação", "Segurança do experimento"], "Sabão produzido com óleo de cozinha usado."),
    ("P10", "Indicador de pH com repolho", "Equipe Roxa", "Química", "Laboratório de química, bloco C", D3, "Indicador natural de acidez feito com repolho roxo."),
    ("P11", "Cadeira ergonômica de papelão", "Equipe Forma", "Design", "Ateliê de design, bloco F", D3, "Mobiliário sustentável montado sem cola."),
    ("P12", "Identidade visual da mostra", "Equipe Traço", "Design", "Ateliê de design, bloco F", D3, "Proposta de marca e sinalização para a mostra."),
    ("P13", "Jogo educativo de frações", "Equipe Pixel", None, "", D3, "Jogo de tabuleiro para ensinar frações."),
    ("P14", "Herbário digital", "Equipe Folha", "Biologia", "Biblioteca, 1º andar", D3, "Catálogo online das plantas do campus."),
    ("P15", "Tinta natural de urucum", "Equipe Cor", "Química", "Pátio central, tenda 4", D3, "Pigmentos naturais para artesanato."),
]
CURSOS = ["Engenharia de Software", "Biologia", "Química", "Design", "Administração"]  # Administração sem projetos
ESCOLAS = {
    "Escola Estadual Alfa": ["9º ano A", "9º ano B", "1º EM"],
    "Colégio Beta": ["Turma única"],
    "Escola Municipal Gama": [],
    "Instituto Delta": ["8º ano"],
}


# ---------------------------------------------------------------- construtor genérico
class Seed:
    """Monta um cenário. Passaportes são criados na ordem em que são adicionados
    (a ordem das avaliações define o selo Pioneiro)."""

    def __init__(self, con, inicio_horas=4):
        self.con, self.rng = con, random.Random(2026)
        self.t0 = (datetime.now() - timedelta(hours=inicio_horas)).replace(second=0, microsecond=0)
        self.cursos, self.escolas, self.turmas = {}, {}, {}
        self.criterios, self.gens, self.cont = {}, {}, {}
        self.avals, self.n_pass, self.rotulos = [], 0, {}

    def add_cursos(self, nomes=CURSOS):
        for c in nomes:
            self.cursos[c] = self.con.execute("INSERT INTO courses(name) VALUES(?)", (c,)).lastrowid

    def add_projetos(self, codigos=None, extras=()):
        itens = [p for p in CATALOGO if codigos is None or p[0] in codigos] + list(extras)
        for code, title, team, curso, loc, crit, resumo in itens:
            self.con.execute("""INSERT INTO projects(code, title, team, summary, criteria, course_id, location, token, team_token)
                VALUES(?,?,?,?,?,?,?,?,?)""", (code, title, team, resumo, json.dumps(crit, ensure_ascii=False),
                                               self.cursos.get(curso), loc, server.new_token(self.con), server.new_team_token(self.con)))
            self.criterios[code], self.cont[code] = len(crit), 0
            self.gens.setdefault(code, ("alvo", 4.0))

    def notas(self, code, alvo=None):
        """Gera as notas da próxima avaliação do projeto conforme o gerador configurado."""
        kind, val = alvo or self.gens[code]
        k, n = self.cont[code], self.criterios[code]
        self.cont[code] += 1
        if kind == "fixo":
            return val[k % len(val)]
        if kind == "constante":
            return [val] * n
        base = int(val)
        return [max(1, min(5, base + (1 if self.rng.random() < val - base else 0) + self.rng.choice([0, 0, 0, -1, 1])))
                for _ in range(n)]

    def add_escolas(self, escolas=ESCOLAS):
        for s, turmas in escolas.items():
            self.escolas[s] = self.con.execute("INSERT INTO schools(name) VALUES(?)", (s,)).lastrowid
            for t in turmas:
                self.turmas[(s, t)] = self.con.execute("INSERT INTO classes(school_id, name) VALUES(?,?)",
                                                       (self.escolas[s], t)).lastrowid

    def passaporte(self, projetos=(), escola=None, turma=None, ativo=True, rotulo=None, gap_min=4):
        code = server.new_code(self.con)
        ativ = self.t0 + timedelta(minutes=gap_min * self.n_pass)
        self.n_pass += 1
        self.con.execute("INSERT INTO passports(code, created, activated, school_id, class_id) VALUES(?,?,?,?,?)",
                         (code, fmt(self.t0 - timedelta(hours=1)), fmt(ativ) if ativo else None,
                          self.escolas.get(escola), self.turmas.get((escola, turma))))
        for k, proj in enumerate(projetos):
            self.avals.append((ativ + timedelta(minutes=5 + 7 * k, seconds=self.rng.randint(0, 50)), code, proj, self.notas(proj)))
        if rotulo:
            self.rotulos[code] = rotulo
        return code

    def disponiveis(self, n):
        for _ in range(n):
            self.passaporte(ativo=False)

    def distribuir(self, cotas, planos, perfis=((None, None),)):
        """Cria passaportes conforme 'planos' (quantos projetos cada um avalia) cumprindo
        exatamente as 'cotas' de avaliações por projeto."""
        assert sum(planos) == sum(cotas.values()), (sum(planos), sum(cotas.values()))
        resto = dict(cotas)
        for i, n in enumerate(planos):
            escolha = sorted(resto, key=lambda c: (-resto[c], self.rng.random()))[:n]
            for c in escolha:
                resto[c] -= 1
            assert min(resto.values()) >= 0, "cotas impossíveis para esses planos"
            self.rng.shuffle(escolha)
            esc, tur = perfis[i % len(perfis)]
            self.passaporte(escolha, esc, tur)
        assert not any(resto.values()), resto

    def alerta(self, escola, turma=None, msg=None, minutos=200, encerrado_min=None):
        criado = self.t0 + timedelta(minutes=minutos)
        self.con.execute("INSERT INTO alerts(school_id, class_id, message, created, ended) VALUES(?,?,?,?,?)",
                         (self.escolas[escola], self.turmas.get((escola, turma)) if turma else None,
                          msg or f"{turma or escola}: retornem ao ônibus no estacionamento principal.", fmt(criado),
                          fmt(criado + timedelta(minutes=encerrado_min)) if encerrado_min else None))

    def gravar(self):
        for quando, code, proj, sc in sorted(self.avals):  # ordem cronológica
            self.con.execute("INSERT INTO evaluations(passport, project, scores, total, created) VALUES(?,?,?,?,?)",
                             (code, proj, json.dumps(sc), sum(sc), fmt(quando)))


PERFIS_MISTOS = ((None, None), ("Escola Estadual Alfa", "9º ano A"), ("Escola Estadual Alfa", "9º ano B"),
                 ("Escola Estadual Alfa", "1º EM"), ("Colégio Beta", "Turma única"), ("Escola Municipal Gama", None))


# ---------------------------------------------------------------- cenários
def c_completo(s):
    """Tudo junto: todos os casos de ranking, selos, perfis e chamada de ônibus num banco só."""
    s.gens.update({"P01": ("alvo", 4.1), "P02": ("alvo", 4.8), "P03": ("fixo", [[5, 5, 5], [5, 5, 4], [5, 5, 5]]),
                   "P04": ("alvo", 3.5), "P05": ("alvo", 3.9), "P06": ("alvo", 2.3), "P07": ("fixo", [[3, 2, 3]]),
                   "P08": ("constante", 4), "P09": ("constante", 4), "P10": ("constante", 5), "P11": ("alvo", 4.7),
                   "P12": ("alvo", 3.0), "P13": ("alvo", 4.0), "P14": ("alvo", 3.6), "P15": ("fixo", [[5, 4, 5], [4, 5, 4]])})
    s.add_cursos(); s.add_projetos(); s.add_escolas()
    cotas = {"P01": 14, "P02": 12, "P03": 3, "P04": 10, "P05": 9, "P06": 2, "P07": 1, "P08": 11, "P09": 11,
             "P10": 1, "P11": 6, "P12": 4, "P13": 7, "P14": 5, "P15": 2}
    s.distribuir(cotas, [15, 10, 5, 5, 5, 5] + [3] * 15 + [2, 2, 2] + [1, 1] + [0, 0], PERFIS_MISTOS)
    s.disponiveis(15)
    s.alerta("Escola Estadual Alfa", "9º ano A", minutos=230)
    s.alerta("Colégio Beta", minutos=120, encerrado_min=15)


def c_antes(s):
    """Antes da mostra: tudo cadastrado, 50 passaportes impressos, nenhum entregue. Testa as telas vazias
    (indicador 0%, ranking sem projetos, página da equipe sem avaliações)."""
    s.add_cursos(); s.add_projetos(); s.add_escolas()
    s.disponiveis(50)


def c_inicio(s):
    """Primeira meia hora: poucos visitantes ativos, ninguém concluiu o desafio, ranking ainda vazio."""
    s.t0 = datetime.now().replace(second=0, microsecond=0) - timedelta(minutes=30)
    s.gens.update({p[0]: ("alvo", 3.6) for p in CATALOGO})  # nenhuma média chega a 4,5 ainda
    s.add_cursos(); s.add_projetos(); s.add_escolas()
    for projs, esc, tur in [(["P01", "P08"], None, None), (["P02"], "Escola Estadual Alfa", "9º ano A"),
                            (["P11", "P05"], "Escola Estadual Alfa", "9º ano B"), ([], "Colégio Beta", "Turma única"),
                            (["P03"], None, None), ([], None, None)]:
        s.passaporte(projs, esc, tur)
    s.disponiveis(44)


def c_ranking(s):
    """Regras de reconhecimento nos limites: exatamente 10 avaliações, 9, média exatamente 4,5, 4,44,
    empate triplo (inclusive entre cursos) e projeto de 2 e de 4 critérios. Todos visitantes livres."""
    s.gens.update({
        "P01": ("constante", 3),                                   # 10 aval, média 3,0 -> entra por avaliações (limite)
        "P02": ("constante", 3),                                   # 9 aval, média 3,0 -> fica de fora por 1
        "P03": ("fixo", [[5, 4, 5], [4, 5, 4]]),                   # 2 aval, média 4,5 exata -> entra pela nota (limite)
        "P04": ("fixo", [[5, 4, 4], [4, 5, 4], [5, 4, 5]]),        # 3 aval, média 4,44 -> fica de fora por pouco
        "P05": ("constante", 4), "P08": ("constante", 4), "P11": ("constante", 4),  # empate triplo 4,0 (12 aval cada)
        "P09": ("constante", 5),                                   # 1 aval, 2 critérios, média 5 -> 1º lugar pela nota
        "P06": ("alvo", 2.0),                                      # 12 aval, média baixa -> entra por avaliações, último
        "P14": ("constante", 2),                                   # 0 avaliações
    })
    s.add_cursos(); s.add_projetos(["P01", "P02", "P03", "P04", "P05", "P06", "P08", "P09", "P11", "P14"])
    cotas = {"P01": 10, "P02": 9, "P03": 2, "P04": 3, "P05": 12, "P08": 12, "P11": 12, "P09": 1, "P06": 12, "P14": 0}
    del cotas["P14"]
    s.distribuir(cotas, [6] * 4 + [5] * 6 + [3] * 5 + [2] * 2)
    s.disponiveis(10)


def c_sem_ranking(s):
    """Fim da mostra sem nenhum projeto elegível: ninguém chegou a 10 avaliações nem à média mínima."""
    s.add_cursos(); s.add_projetos(["P01", "P02", "P03", "P05", "P08", "P11", "P12"])
    s.gens.update({c: ("alvo", 3.3) for c in s.cont})
    cotas = {"P01": 9, "P02": 8, "P03": 6, "P05": 7, "P08": 9, "P11": 5, "P12": 4}
    s.distribuir(cotas, [3] * 12 + [2] * 6, PERFIS_MISTOS[:1])
    s.disponiveis(8)


def c_selos(s):
    """Um passaporte para cada selo (e combinações), com rótulo no resumo. Os 10 primeiros a concluir
    o Conheça três são 'pioneiros'; o passaporte 'Conheça três sem Pioneiro' conclui depois deles."""
    extras = [("P16", "Jardim vertical", "Equipe Muro", "Design", "Ateliê de design, bloco F", D3, "Painel de plantas com irrigação por gotejamento.")]
    s.add_cursos(); s.add_projetos(extras=extras); s.add_escolas()
    eng, bio, qui, des = ["P01", "P02", "P03", "P04"], ["P05", "P06", "P07", "P14"], ["P08", "P09", "P10", "P15"], ["P11", "P12", "P16"]
    for i in range(10):  # pioneiros: concluem cedo
        s.passaporte([eng[i % 4], bio[i % 4], qui[i % 4]], rotulo=f"Pioneiro nº {i + 1}", gap_min=2)
    s.passaporte([], rotulo="Ativado, sem nenhum selo")
    s.passaporte(["P01"], rotulo="Só Primeira descoberta")
    s.passaporte(["P01", "P02"], rotulo="2 projetos do mesmo curso (sem Ponte)")
    s.passaporte(["P01", "P05"], rotulo="Ponte entre cursos")
    s.passaporte(["P01", "P02", "P03"], rotulo="Conheça três sem Pioneiro (mesmo curso)")
    s.passaporte(["P01", "P05", "P08"], rotulo="Multidisciplinar (3 cursos)")
    s.passaporte(["P11", "P12", "P16"], rotulo="Curso completo (Design inteiro)")
    s.passaporte(["P13", "P01", "P02", "P03", "P04"], rotulo="Explorador + Curso completo (Eng.) + projeto sem curso")
    s.passaporte(eng + bio + ["P08", "P09"], rotulo="Maratonista (10 projetos)")
    s.passaporte([p[0] for p in CATALOGO] + ["P16"], rotulo="Mostra completa (todos)")
    s.disponiveis(5)


def c_onibus(s):
    """Chamada para o ônibus: chamada ativa para UMA turma, chamada ativa para a escola INTEIRA,
    chamada encerrada, e passaportes da mesma escola em turma não chamada (seguem avaliando)."""
    s.add_cursos(); s.add_projetos(); s.add_escolas()
    plano = [("Escola Estadual Alfa", "9º ano A", "BLOQUEADO (turma 9º ano A chamada)"),
             ("Escola Estadual Alfa", "9º ano B", "livre para avaliar (turma não chamada)"),
             ("Escola Estadual Alfa", "1º EM", "livre para avaliar (turma não chamada)"),
             ("Colégio Beta", "Turma única", "BLOQUEADO (escola inteira chamada)"),
             ("Escola Municipal Gama", None, "livre para avaliar (chamada encerrada)"),
             (None, None, "visitante livre (nunca é chamado)")]
    for esc, tur, rot in plano:
        for k in range(3):
            s.passaporte(s.rng.sample([p[0] for p in CATALOGO], k + 1), esc, tur, rotulo=rot)
    s.alerta("Escola Estadual Alfa", "9º ano A", minutos=200)
    s.alerta("Colégio Beta", None, "Colégio Beta: todos de volta ao ônibus, saída em 10 minutos.", minutos=210)
    s.alerta("Escola Municipal Gama", None, minutos=120, encerrado_min=20)
    s.disponiveis(10)


def c_lotado(s):
    """Volume alto para testar rolagem infinita, paginação (30 projetos) e desempenho:
    600 passaportes (450 em uso) e cerca de 1.600 avaliações."""
    extras = [(f"P{n:02d}", f"Projeto de demonstração {n}", f"Equipe {n}", CURSOS[n % 4],
               f"Bloco {'ABCDEF'[n % 6]}, sala {100 + n}", D3, "Projeto extra para teste de volume.") for n in range(16, 31)]
    s.add_cursos(); s.add_projetos(extras=extras); s.add_escolas()
    codigos = list(s.cont)
    for i in range(450):
        n = [0, 1, 2, 3, 3, 3, 4, 5, 6, 8][i % 10]
        esc, tur = PERFIS_MISTOS[i % len(PERFIS_MISTOS)]
        s.passaporte(s.rng.sample(codigos, n), esc, tur, gap_min=0.5)
    s.disponiveis(150)


def c_fim(s):
    """Fim da mostra com meta batida: todos os passaportes entregues, ~75% concluíram o desafio
    (meta hipotética é 60%), nenhuma chamada de ônibus ativa."""
    s.add_cursos(); s.add_projetos(); s.add_escolas()
    codigos = [p[0] for p in CATALOGO]
    for i in range(40):
        n = 3 + (i % 4) if i % 4 else (i // 4) % 3  # 30 com 3+ projetos, 10 com 0 a 2
        esc, tur = PERFIS_MISTOS[i % len(PERFIS_MISTOS)]
        s.passaporte(s.rng.sample(codigos, n), esc, tur, gap_min=5)
    s.alerta("Colégio Beta", minutos=180, encerrado_min=10)


CENARIOS = {
    "completo": c_completo,
    "antes-da-mostra": c_antes,
    "inicio": c_inicio,
    "ranking": c_ranking,
    "sem-ranking": c_sem_ranking,
    "selos": c_selos,
    "onibus": c_onibus,
    "lotado": c_lotado,
    "fim-da-mostra": c_fim,
}


# ---------------------------------------------------------------- execução
def recriar_banco(reset_pin):
    db_path, pin = server.DB_PATH, None
    if os.path.exists(db_path):
        if not reset_pin:
            try:
                pin = sqlite3.connect(db_path).execute("SELECT pin FROM admin WHERE id=1").fetchone()[0]
            except sqlite3.Error:
                pass
        os.makedirs(os.path.join(BASE, "backups"), exist_ok=True)
        bkp = os.path.join(BASE, "backups", datetime.now().strftime("mostra-%Y%m%d-%H%M%S.db"))
        shutil.copy2(db_path, bkp)
        os.remove(db_path)
        print("backup do banco anterior:", os.path.relpath(bkp, BASE))
    server.init_db()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    with con:
        if pin:
            con.execute("UPDATE admin SET pin=? WHERE id=1", (pin,))
        con.execute("DELETE FROM projects")  # tira os projetos de exemplo do init_db
    return con, pin


def resumo(con, nome, s, pin):
    st = server.get_settings(con)
    print(f"\n== cenário: {nome} ==\n{CENARIOS[nome].__doc__.strip()}\n")
    print(f"PIN do painel: {pin or server.ADMIN_PIN}{' (mantido)' if pin else ' (padrão)'}"
          f"   ·   regras: {st['min_avaliacoes']}+ avaliações OU média ≥ {st['nota_minima']}")
    rows = con.execute("""SELECT p.code, p.title, p.criteria, COUNT(e.id) n, SUM(e.total) s FROM projects p
        LEFT JOIN evaluations e ON e.project=p.code GROUP BY p.code ORDER BY p.code""").fetchall()
    if len(rows) <= 16:
        print(f"\n{'Proj':5}{'aval':>5}{'média':>7}  {'ranking':10} título")
        for r in rows:
            n, nc = r["n"], len(json.loads(r["criteria"]))
            media = round(r["s"] / (n * nc), 2) if n else None
            regra = "+".join(x for x, ok in [("aval", n >= st["min_avaliacoes"]),
                                             ("nota", bool(n) and media >= st["nota_minima"])] if ok) or "-"
            print(f"{r['code']:5}{n:>5}{str(media):>7}  {regra:10} {r['title']}")
    else:
        print(f"\n{len(rows)} projetos")
    ativos = [r[0] for r in con.execute("SELECT code FROM passports WHERE activated IS NOT NULL ORDER BY activated")]
    livres = con.execute("SELECT COUNT(*) FROM passports WHERE activated IS NULL").fetchone()[0]
    n_av = con.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    dados = {c: server.passport_data(con, c) for c in ativos} if len(ativos) <= 60 else {}
    print(f"\nPassaportes: {len(ativos)} em uso, {livres} disponíveis · {n_av} avaliações")
    if dados:
        bloq = sum(d["bloqueado"] for d in dados.values())
        concl = sum(d["concluido"] for d in dados.values())
        print(f"Concluíram o Conheça três: {concl} · bloqueados por chamada de ônibus: {bloq}")
    if s.rotulos:
        print(f"\n{'Passaporte':11} {'situação':48} selos")
        for code, rot in s.rotulos.items():
            d = dados.get(code) or server.passport_data(con, code)
            selos = " ".join(b["icon"] for b in d["selos"] if b["conquistado"]) or "—"
            print(f"{code:11} {rot[:48]:48} {selos}")
        print("(abra no celular: /?p=CÓDIGO para entrar com o passaporte)")
    al = server.active_alerts(con)
    if al:
        print("\nChamadas de ônibus ativas: " + "; ".join(f"{a['escola']}{' · ' + a['turma'] if a['turma'] else ' (escola inteira)'}" for a in al))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args or args[0] not in CENARIOS:
        if args:
            print(f"cenário desconhecido: {args[0]}\n")
        print("Cenários disponíveis (python3 seed.py <cenário>):\n")
        for nome, f in CENARIOS.items():
            print(f"  {nome:16} {' '.join(f.__doc__.split())}\n")
        sys.exit(1 if args else 0)
    nome = args[0]
    if "--se-vazio" in sys.argv and os.path.exists(server.DB_PATH):
        try:
            if sqlite3.connect(server.DB_PATH).execute("SELECT COUNT(*) FROM passports").fetchone()[0]:
                print("seed: banco já tem dados, nada a fazer")
                return
        except sqlite3.Error:
            pass
    con, pin = recriar_banco("--reset-pin" in sys.argv)
    s = Seed(con)
    with con:
        CENARIOS[nome](s)
        s.gravar()
        for k, v in server.DEFAULT_SETTINGS.items():
            con.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
    resumo(con, nome, s, pin)


if __name__ == "__main__":
    main()
