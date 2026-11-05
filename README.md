# Mostra em Descoberta

Sistema de gamificação para uma mostra científica. O visitante recebe um passaporte
anônimo, visita os estandes, avalia cada projeto em critérios de 1 a 5 e ganha
assinaturas e selos. A organização acompanha tudo por um painel e cada equipe tem
uma página para ver as avaliações do próprio projeto.

Feito em Python 3 puro (sem dependências) com SQLite e páginas HTML/JS estáticas.

## Como rodar

```bash
python3 seed.py      # opcional: cria dados de demonstração (faz backup do banco atual)
./restart.sh         # sobe o servidor em http://localhost:8000 (log em server.log)
# ou: python3 server.py   |   PORT=9000 ADMIN_PIN=1234 python3 server.py
```

PIN inicial do painel: `2026` (pode ser trocado no próprio painel, aba Indicadores).

## Páginas

| Endereço | Quem usa | O que faz |
|---|---|---|
| `/` | visitante | ativa o passaporte (QR do cartão ou código), mostra assinaturas, progresso e selos; botão "Onde estão os projetos?" com a localização de cada um |
| `/avaliar/<código do estande>` | visitante | formulário do projeto; o código é secreto e fica só no cartaz do estande, então só dá para avaliar estando lá |
| `/equipe/<link da equipe>` | alunos do projeto | avaliações recebidas em tempo real, média geral e por critério (sem ranking) |
| `/admin` | organização | passaportes, escolas e chamada para o ônibus, ranking, cursos, montagem avaliativa e cartazes com QR |

## Regras

- Passaportes são emitidos só pela organização. Na entrega, o atendente marca se é visitante livre ou de uma escola/turma.
- Avaliação válida = todos os critérios respondidos (1 a 5). Cada passaporte avalia cada projeto uma vez.
- Cada avaliação dá 1 assinatura no passaporte; o projeto soma os pontos recebidos.
- Desafio principal: avaliar 3 projetos diferentes (selo "Conheça três"). Há mais 8 selos, todos baseados em quais projetos o visitante conheceu, nunca nas notas que deu.
- Ranking: entram os projetos com **N+ avaliações OU média ≥ X** (configurável no painel). Empates ficam na mesma posição. O reconhecimento de cada posição é definido pelos professores.
- Chamada para o ônibus: a organização chama uma escola ou turma; os celulares desses visitantes mostram o aviso, as avaliações deles ficam pausadas e atendentes e equipes são avisados.
- Nenhum dado pessoal do visitante é coletado.

## Dados de demonstração

`python3 seed.py` recria o banco com 15 projetos, 5 cursos, 4 escolas e 43 passaportes cobrindo
os cenários do sistema (elegível por avaliações, por média, nos limites, empate, critérios
personalizados, todos os selos, chamada de ônibus ativa e encerrada…). O resumo impresso no
final mostra a situação de cada projeto e os links das equipes.

## Acesso pelo celular

Rode o servidor numa máquina da mesma rede Wi-Fi e acesse pelo IP dela
(ex.: `http://192.168.0.10:8000`), ou publique num serviço de hospedagem.
No WSL é preciso redirecionar a porta no Windows (`netsh interface portproxy`).
