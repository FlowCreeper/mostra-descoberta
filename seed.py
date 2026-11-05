#!/usr/bin/env python3
"""Recria o banco com dados de demonstração que cobrem todos os cenários do sistema.

Uso:
    python3 seed.py              # faz backup do mostra.db atual e recria (mantém o PIN atual)
    python3 seed.py --reset-pin  # idem, mas volta o PIN para o padrão (2026 ou ADMIN_PIN)

O backup fica em backups/mostra-AAAAMMDD-HHMMSS.db. Reinicie o servidor depois (./restart.sh).

Cenários cobertos (ver resumo impresso no final):
  Projetos  - elegível por nº de avaliações, por média, pelas duas regras, exatamente no limite
              (10 avaliações / média 4,5), quase elegível, fora do ranking, empate de média,
              1 avaliação só, critérios personalizados (2 e 4), sem curso, sem localização.
  Cursos    - com vários projetos, com 2 projetos (selo Curso completo), curso sem projetos.
  Passaportes - disponíveis, ativados sem avaliação, 1, 2, 3, 5, 10 e todos os projetos;
              visitante livre, escola com turma, escola de turma única, escola sem turma.
  Selos     - todos os 9 aparecem em pelo menos um passaporte.
  Escolas   - com várias turmas, turma única, sem turmas, escola sem passaportes.
  Ônibus    - chamada ATIVA para uma turma (passaportes bloqueados) e uma chamada já encerrada.
"""
import json, os, random, shutil, sqlite3, sys
from datetime import datetime, timedelta

import server  # reaproveita o esquema e os geradores de código

BASE = os.path.dirname(os.path.abspath(__file__))
rng = random.Random(2026)  # determinístico: o mesmo seed sempre gera os mesmos dados
DIA = (datetime.now() - timedelta(hours=4)).replace(second=0, microsecond=0)  # dados nas últimas 4 horas
fmt = lambda d: d.strftime("%Y-%m-%d %H:%M:%S")
D3 = server.DEFAULT_CRITERIA

COURSES = ["Engenharia de Software", "Biologia", "Química", "Design", "Administração"]  # Administração fica sem projetos

# code, título, equipe, curso, local, critérios, resumo, cenário, gerador de notas
PROJECTS = [
    ("P01", "Horta automatizada", "Equipe Verde", "Engenharia de Software", "Pátio abaixo do bloco B", D3,
     "Sensor de umidade que liga a irrigação sozinho.", "elegível só por nº de avaliações (14, média < 4,5)", ("alvo", 4.1)),
    ("P02", "App de carona solidária", "Equipe Rota", "Engenharia de Software", "Bloco E, 2º andar, sala 204", D3,
     "Aplicativo que conecta alunos que moram perto.", "elegível pelas duas regras (12 avaliações, média ≥ 4,5)", ("alvo", 4.8)),
    ("P03", "Robô seguidor de linha", "Equipe Circuito", "Engenharia de Software", "Laboratório de robótica, bloco C", D3,
     "Robô com Arduino que percorre trajetos marcados.", "elegível só pela média (3 avaliações, média alta)", ("fixo", [[5, 5, 5], [5, 5, 4], [5, 5, 5]])),
    ("P04", "Mapa de calor do campus", "Equipe Dados", "Engenharia de Software", "Hall de entrada do bloco A", D3,
     "Visualização das áreas mais quentes da faculdade.", "exatamente 10 avaliações (limite), média ~3,5", ("alvo", 3.5)),
    ("P05", "Bioplástico de mandioca", "Equipe Raiz", "Biologia", "Bloco D, térreo, laboratório 3",
     ["Clareza da explicação", "Criatividade da proposta", "Relevância ou utilidade", "Rigor científico"],
     "Plástico biodegradável feito com amido.", "quase: 9 avaliações e média < 4,5 (4 critérios)", ("alvo", 3.9)),
    ("P06", "Compostagem com minhocas", "Equipe Húmus", "Biologia", "Jardim atrás do bloco D", D3,
     "Minhocário para reaproveitar resíduos da cantina.", "fora do ranking (2 avaliações, média baixa)", ("alvo", 2.3)),
    ("P07", "Mosquitos e água parada", "Equipe Alerta", "Biologia", "Bloco D, 1º andar, sala 110", D3,
     "Mapeamento de focos de mosquito no bairro.", "fora do ranking (1 avaliação, média baixa)", ("fixo", [[3, 2, 3]])),
    ("P08", "Filtro de água caseiro", "Equipe Água Limpa", "Química", "Pátio central, tenda 2", D3,
     "Filtro com materiais recicláveis e testes de turbidez.", "EMPATE com P09: 11 avaliações, média 4,0", ("constante", 4)),
    ("P09", "Sabão de óleo reciclado", "Equipe Espuma", "Química", "Pátio central, tenda 3",
     ["Clareza da explicação", "Segurança do experimento"],
     "Sabão produzido com óleo de cozinha usado.", "EMPATE com P08 (2 critérios), 11 avaliações, média 4,0", ("constante", 4)),
    ("P10", "Indicador de pH com repolho", "Equipe Roxa", "Química", "Laboratório de química, bloco C", D3,
     "Indicador natural de acidez feito com repolho roxo.", "1 avaliação só, nota máxima → elegível pela média", ("constante", 5)),
    ("P11", "Cadeira ergonômica de papelão", "Equipe Forma", "Design", "Ateliê de design, bloco F", D3,
     "Mobiliário sustentável montado sem cola.", "elegível pela média com 6 avaliações", ("alvo", 4.7)),
    ("P12", "Identidade visual da mostra", "Equipe Traço", "Design", "Ateliê de design, bloco F", D3,
     "Proposta de marca e sinalização para a mostra.", "4 avaliações, média ~3,0", ("alvo", 3.0)),
    ("P13", "Jogo educativo de frações", "Equipe Pixel", None, "", D3,
     "Jogo de tabuleiro para ensinar frações.", "SEM curso e SEM localização, 7 avaliações", ("alvo", 4.0)),
    ("P14", "Herbário digital", "Equipe Folha", "Biologia", "Biblioteca, 1º andar", D3,
     "Catálogo online das plantas do campus.", "5 avaliações, média ~3,6", ("alvo", 3.6)),
    ("P15", "Tinta natural de urucum", "Equipe Cor", "Química", "Pátio central, tenda 4", D3,
     "Pigmentos naturais para artesanato.", "média EXATAMENTE 4,5 (limite) com 2 avaliações", ("fixo", [[5, 4, 5], [4, 5, 4]])),
]
QUOTAS = {"P01": 14, "P02": 12, "P03": 3, "P04": 10, "P05": 9, "P06": 2, "P07": 1, "P08": 11, "P09": 11,
          "P10": 1, "P11": 6, "P12": 4, "P13": 7, "P14": 5, "P15": 2}

SCHOOLS = {  # escola: turmas
    "Escola Estadual Alfa": ["9º ano A", "9º ano B", "1º EM"],
    "Colégio Beta": ["Turma única"],
    "Escola Municipal Gama": [],
    "Instituto Delta": ["8º ano"],  # cadastrada, mas sem passaportes
}

# quantos projetos cada passaporte ativo avalia (soma = soma das cotas)
PLANS = [15, 10, 5, 5, 5, 5] + [3] * 15 + [2, 2, 2] + [1, 1] + [0, 0]
AVAILABLE = 15  # passaportes emitidos e ainda não entregues


def notas(gen, n_crit, k):
    kind, val = gen
    if kind == "fixo":
        return val[k]
    if kind == "constante":
        return [val] * n_crit
    out = []
    for _ in range(n_crit):  # sorteia em torno do alvo
        base = int(val)
        out.append(max(1, min(5, base + (1 if rng.random() < val - base else 0) + rng.choice([0, 0, 0, -1, 1]))))
    return out


def main():
    db_path = server.DB_PATH
    pin = None
    if os.path.exists(db_path):
        if "--reset-pin" not in sys.argv:
            try:
                pin = sqlite3.connect(db_path).execute("SELECT pin FROM admin WHERE id=1").fetchone()[0]
            except sqlite3.Error:
                pin = None
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
        con.execute("DELETE FROM projects")  # remove os 4 projetos de exemplo do init_db

        course_id = {}
        for c in COURSES:
            course_id[c] = con.execute("INSERT INTO courses(name) VALUES(?)", (c,)).lastrowid
        for code, title, team, course, loc, crit, summary, *_ in PROJECTS:
            con.execute("""INSERT INTO projects(code, title, team, summary, criteria, course_id, location, token, team_token)
                VALUES(?,?,?,?,?,?,?,?,?)""", (code, title, team, summary, json.dumps(crit, ensure_ascii=False),
                                               course_id.get(course), loc, server.new_token(con), server.new_team_token(con)))

        school_id, class_ids = {}, {}
        for s, turmas in SCHOOLS.items():
            school_id[s] = con.execute("INSERT INTO schools(name) VALUES(?)", (s,)).lastrowid
            class_ids[s] = [con.execute("INSERT INTO classes(school_id, name) VALUES(?,?)", (school_id[s], t)).lastrowid
                            for t in turmas]

        # perfis variados, em rodízio: livre, Alfa (3 turmas), Beta (turma única), Gama (sem turma)
        perfis = [(None, None)]
        perfis += [(school_id["Escola Estadual Alfa"], c) for c in class_ids["Escola Estadual Alfa"]]
        perfis += [(school_id["Colégio Beta"], class_ids["Colégio Beta"][0]), (school_id["Escola Municipal Gama"], None)]

        # distribui as avaliações: cada passaporte pega os projetos com mais cota restante
        restante = dict(QUOTAS)
        assert sum(PLANS) == sum(QUOTAS.values()), (sum(PLANS), sum(QUOTAS.values()))
        planos = []
        for i, n in enumerate(PLANS):
            escolhidos = sorted(restante, key=lambda c: (-restante[c], rng.random()))[:n]
            for c in escolhidos:
                restante[c] -= 1
            assert all(v >= 0 for v in restante.values()), "cotas impossíveis"
            planos.append(escolhidos)
        assert not any(restante.values()), restante

        gens = {p[0]: (len(p[5]), p[8]) for p in PROJECTS}
        contador = {c: 0 for c in QUOTAS}
        avals = []
        emitido = DIA - timedelta(hours=2)
        for i, escolhidos in enumerate(planos):
            code = server.new_code(con)
            sid, cid = perfis[i % len(perfis)]
            ativ = DIA + timedelta(minutes=4 * i)
            con.execute("INSERT INTO passports(code, created, activated, school_id, class_id) VALUES(?,?,?,?,?)",
                        (code, fmt(emitido), fmt(ativ), sid, cid))
            rng.shuffle(escolhidos)
            for k, proj in enumerate(escolhidos):
                n_crit, gen = gens[proj]
                sc = notas(gen, n_crit, contador[proj])
                contador[proj] += 1
                avals.append((ativ + timedelta(minutes=6 + 9 * k, seconds=rng.randint(0, 50)), code, proj, sc))
        for _ in range(AVAILABLE):
            con.execute("INSERT INTO passports(code, created) VALUES(?,?)", (server.new_code(con), fmt(emitido)))
        # insere em ordem cronológica (o selo Pioneiro usa a ordem das avaliações)
        for quando, code, proj, sc in sorted(avals):
            con.execute("INSERT INTO evaluations(passport, project, scores, total, created) VALUES(?,?,?,?,?)",
                        (code, proj, json.dumps(sc), sum(sc), fmt(quando)))

        # chamada ATIVA só para o 9º ano A e uma chamada já encerrada para o Colégio Beta
        con.execute("INSERT INTO alerts(school_id, class_id, message, created) VALUES(?,?,?,?)",
                    (school_id["Escola Estadual Alfa"], class_ids["Escola Estadual Alfa"][0],
                     "Turma do 9º ano A: retornem ao ônibus no estacionamento principal.", fmt(DIA + timedelta(hours=3))))
        con.execute("INSERT INTO alerts(school_id, class_id, message, created, ended) VALUES(?,?,?,?,?)",
                    (school_id["Colégio Beta"], None, "Colégio Beta: retornem ao ônibus.",
                     fmt(DIA + timedelta(hours=2)), fmt(DIA + timedelta(hours=2, minutes=15))))
        for k, v in server.DEFAULT_SETTINGS.items():
            con.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))

    resumo(con, pin)


def resumo(con, pin):
    st = server.get_settings(con)
    print(f"\nPIN do painel: {pin or server.ADMIN_PIN}{' (mantido)' if pin else ' (padrão)'}")
    print(f"Regras: {st['min_avaliacoes']}+ avaliações OU média ≥ {st['nota_minima']}\n")
    print(f"{'Proj':5}{'aval':>5}{'média':>7}  {'regra':10} cenário")
    cen = {p[0]: p[7] for p in PROJECTS}
    for r in con.execute("SELECT p.code, p.criteria, COUNT(e.id) n, SUM(e.total) s FROM projects p "
                         "LEFT JOIN evaluations e ON e.project=p.code GROUP BY p.code ORDER BY p.code"):
        n, nc = r["n"], len(json.loads(r["criteria"]))
        media = round(r["s"] / (n * nc), 2) if n else None
        regra = "+".join(x for x, ok in [("aval", n >= st["min_avaliacoes"]), ("nota", bool(n) and media >= st["nota_minima"])] if ok) or "-"
        print(f"{r['code']:5}{n:>5}{str(media):>7}  {regra:10} {cen[r['code']]}")
    ps = [r[0] for r in con.execute("SELECT code FROM passports WHERE activated IS NOT NULL")]
    sel = {}
    for c in ps:
        for b in server.passport_data(con, c)["selos"]:
            sel[b["name"]] = sel.get(b["name"], 0) + b["conquistado"]
    livres = con.execute("SELECT COUNT(*) FROM passports WHERE activated IS NULL").fetchone()[0]
    bloq = sum(server.passport_data(con, c)["bloqueado"] for c in ps)
    print(f"\nPassaportes: {len(ps)} em uso, {livres} disponíveis, {bloq} bloqueados pela chamada do ônibus")
    print("Selos (passaportes que têm):", ", ".join(f"{k} {v}" for k, v in sel.items()))
    print("\nLinks das equipes:")
    for r in con.execute("SELECT code, team_token, token FROM projects ORDER BY code"):
        print(f"  {r['code']}  /equipe/{r['team_token']}   (estande: /avaliar/{r['token']})")


if __name__ == "__main__":
    main()
