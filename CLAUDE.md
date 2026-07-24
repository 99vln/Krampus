# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Krampus é um bot Discord (discord.py) para uma guild de MMO (Where Winds Meet),
com três sistemas independentes: alistamentos de boss/andares (agendamento,
party, puxada de fila), formulários de recrutamento, e tickets de suporte.

## Comandos comuns

```bash
pip install -r requirements.txt   # discord.py, python-dotenv, tzdata
python main.py                    # roda o bot (precisa de .env com DISCORD_TOKEN)
```

Não há linter ou build configurados. Existe uma suíte de testes local
(`tests/test_heroes.py`, unittest, ~39 testes) que vive na máquina do Shinu e
NÃO é rastreada de propósito (`/tests/` está no `.gitignore`); rode-a quando
mexer no motor/heroes se ela estiver presente no clone.

Para sincronizar comandos slash manualmente sem reiniciar o bot, use `/sync`
no Discord (comando de prefixo, restrito ao dono do bot); ele chama
`bot.tree.sync()` diretamente. O boot também imprime a lista de comandos
sincronizados (diagnóstico de comando sumido do menu).

## Fluxo de trabalho

- Contribuições do Shinu chegam por PR do fork `Shinumino/Krampus`; branches
  são baseadas em `upstream/main` fresco porque o main anda entre PRs.
- A pasta onde o bot RODA precisa ser a branch completa (`motor_alistamento.py`
  fica na RAIZ, não em `cogs/`). Rodar de ZIP/cópia parcial já quebrou o bot;
  antes de caçar bug, rode `git log --oneline -1` na pasta de execução.
- Não editar código na mão na pasta de execução: conflita com o próximo
  `git pull` e reverte refactors. Mudança entra por branch + PR.
- Deploy: `.github/workflows/deploy.yml` (Discloud) está COMENTADO; não há
  auto-deploy no push. O bot roda onde o Logic hospeda; merge não publica nada
  sozinho.

## Arquitetura

### Carregamento

`main.py` cria o `Krampus(commands.Bot)`, chama `db.init_db()` e carrega
**todos** os arquivos de `cogs/` automaticamente no `setup_hook` (não precisa
registrar cog novo em lugar nenhum, só criar o arquivo em `cogs/`). Depois
sincroniza os comandos slash. Um cog que falha ao carregar não derruba os
outros.

Cuidado com os intents em `main.py`: feature que lê estado de voz ou conteúdo
de mensagem depende do intent certo ligado (e habilitado no Developer Portal).
Intent desligado mata a feature em silêncio; já aconteceu com `voice_states`
(puxada) e acontece hoje com `message_content` (ver Pendências).

### O motor de alistamentos (`motor_alistamento.py`)

Este é o núcleo do bot e **não é um cog**; é um módulo de estado
compartilhado, importado diretamente (como `config.py`/`database.py`) por:

- `cogs/alistamento.py` (comando `/alistamento`, modo "heroes")
- `cogs/andares.py` (comando `/andares`, modo "andares")
- `cogs/puxar.py` (comando `/puxar`)
- `cogs/relogio.py` (tarefa em loop a cada 60s que dispara lembretes,
  puxada automática, aviso ao criador e auto-finalização)

Cada cog chama `motor.inicializar(bot)` no próprio `setup()`; só a primeira
chamada faz efeito (recarrega as heroes ativas do disco e restaura os
botões). Isso permite que qualquer subconjunto dos quatro cogs funcione
sozinho.

O estado ativo vive em memória no dict `motor.ativas: dict[str, Heroes]`,
espelhado em disco como JSON (ver abaixo) para sobreviver a restarts.

### Modelo de domínio (`heroes.py`)

A dataclass `Heroes` representa um alistamento (boss OU andar agendado).
Dois "modos" compartilham o mesmo modelo mas têm regras diferentes,
centralizadas em `MODOS`, `MODOS_COM_RESERVA`, `MODOS_COM_PUXADA`:

| modo      | party                 | reserva (lista de espera) | puxada de fila |
| --------- | --------------------- | ------------------------- | -------------- |
| `heroes`  | 1 TANK/2 HEALER/6 DPS | não                       | sim            |
| `andares` | 1 TANK/2 HEALER/7 DPS | sim                       | não            |

Enquanto ativo, cada alistamento é um JSON em `data/heroes/<id>.json` ou
`data/andares/<id>.json` (escrita atômica via `.tmp` + `os.replace`). Ao
finalizar, os participantes migram para o SQLite (`heroes_historico` /
`heroes_participacao` em `database.py`, base do ranking de atividade) e o
JSON é apagado. `Heroes.carregar_todas()` roda no boot, migra JSONs que
estejam na pasta errada, e coloca em quarentena (`.corrupt`) qualquer JSON
inválido em vez de descartá-lo silenciosamente.

O ciclo de vida de um alistamento (`acoes_pendentes` em `heroes.py`, tudo
relativo ao horário agendado `inicio`):

1. lembretes em -15min e -5min (no máximo um por tick; atrasado = pulado)
2. puxada automática da fila no horário exato (janela de 3min). A tentativa é
   ÚNICA e é marcada como feita ANTES de mover: se o shot caller não estiver
   num canal de heroes naquele momento, ninguém é puxado e a tentativa é
   consumida (o `/puxar` manual continua disponível)
3. DM ao criador perguntando se pode finalizar, a partir de +30min
4. auto-finalização pelo bot em +5h

Todas as flags de "já disparei isso" (`lembretes_enviados`,
`puxada_automatica_feita`, `aviso_criador_enviado`) são persistidas no JSON
para não repetir ações após um restart do bot.

### Botões e views

`AlistamentoView` (PARTICIPAR/SAIR/RESERVA/FINALIZAR) e `FinalizarDMView`
usam `custom_id` fixos com o id do alistamento embutido
(`heroes:<id>:<ação>`), registradas via `bot.add_view(..., message_id=...)`
no `inicializar()` para sobreviver a restarts. `BotaoOrfao` é uma rede de
segurança (`DynamicItem` com regex `heroes:...`) que responde cliques em
botões de alistamentos que não existem mais.

REGRA DA CASA: o discord.py despacha `DynamicItem` em PARALELO com a view
registrada da mensagem (não é fallback). Todo catch-all precisa checar estado
e ficar MUDO quando o handler real existe, senão rouba o ack (erro 40060,
"dado salvo mas embed não atualiza"). Ver comentário em
`motor_alistamento.py`.

### Permissões

- `config.CARGOS_STAFF` (DEV/STAFF): pode tudo.
- `config.CARGOS_ALISTAMENTO` (STAFF + cargos de "caller", ex.: Heroes Helm):
  só `/alistamento`, `/andares` e `/puxar`. Não ganham acesso de staff a
  tickets nem finalizam alistamento alheio.
- `config.BUILD_LEADER_IDS` (PR #12): BL Tank/Healer/DPS veem e conversam nos
  tickets da PRÓPRIA classe (sem `manage_channels`); fechar/arquivar ticket
  segue sendo só staff.

### Configuração (`config.py`)

Todos os IDs de cargo/canal têm um valor hardcoded (o servidor real) com
override opcional via variável de ambiente (`_env_int`/`_env_int_list`),
para poder trocar por um servidor de teste sem editar código. `TIMEZONE` cai
para UTC-3 fixo se o pacote `tzdata` não estiver instalado (Windows sem
`pip install tzdata`).

`utils/` (roles.py, emojis.py) é código MORTO no momento: nada no repo
importa esses módulos. Eles eram usados pelo cog `gvgcheck`, cujo `.py` nunca
foi commitado (só existia o `.pyc`). Não confundir os IDs de `utils/roles.py`
com os de `config.py`; os vivos são os do `config.py`.

### Formulários e tickets

`cogs/formulario.py` e `cogs/ticket.py` são sistemas à parte (recrutamento
via formulário com aprovação/recusa por botão, e tickets de suporte criados
na categoria da classe do usuário: DPS/TANK/HEALER). Ambos persistem estado
próprio no SQLite (`persistent_formularios`, `active_tickets`) para restaurar
views após um restart, seguindo o mesmo padrão do motor de alistamentos.
`views/` guarda as views persistentes desses dois sistemas.

### Banco de dados (`database.py`)

SQLite simples (sem ORM), caminho ancorado no diretório do arquivo (não no
cwd). `init_db()` cria tabelas com `CREATE TABLE IF NOT EXISTS` e roda
migrações idempotentes (`PRAGMA table_info` + `ALTER TABLE` condicional); ao
adicionar uma coluna nova num banco existente, siga esse padrão em vez de
assumir um banco vazio.

## Gotchas de repositório

- O git RASTREIA `__pycache__/*.pyc` e `bot_data.db` apesar do `.gitignore`
  (entraram antes do ignore; `.gitignore` não des-rastreia). `rm -rf
__pycache__` deleta arquivo rastreado; confira `git status` antes de
  commitar. Cleanup pendente: `git rm --cached` neles.
- `bot_data.db` rastreado significa que um checkout/deploy por cima da pasta
  de produção sobrescreve o banco vivo. Sem auto-deploy hoje, mas não reative
  o deploy.yml antes de resolver isso.
- `git checkout` sobrescreve SEM AVISO um arquivo ignorado quando o mesmo
  caminho é rastreado na branch de destino (foi assim que a suíte de testes
  local já foi perdida uma vez).

## Pendências conhecidas

- `main.py` seta `intents.message_content = True` e logo depois `= False`
  (linhas 14/19). Efeito: transcript de ticket sai tudo "[sem conteúdo]".
  Decidir se liga o intent (tem que habilitar no Developer Portal também) e
  remover a linha duplicada.
- Commitar `cogs/gvgcheck.py` (se ainda quiser a feature) ou apagar `utils/`.
