import os
import sqlite3
from datetime import datetime
from typing import List, Tuple

# ======================================================
# CONFIGURAÇÃO
# ======================================================

# Caminho do arquivo de banco de dados SQLite, ancorado na pasta deste arquivo
# (um caminho relativo criaria um banco novo e vazio se o bot fosse iniciado
# de outro diretório de trabalho)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.db")

# ======================================================
# INICIALIZAÇÃO DO BANCO DE DADOS
# ======================================================

def init_db():
    """
    Inicializa o banco de dados criando as tabelas necessárias (se não existirem)
    e executa migrações para adicionar colunas que possam estar faltando
    em bancos de dados já existentes.

    Deve ser chamado uma vez na inicialização do bot.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # --------------------------------------------------
        # Tabela: persistent_formularios
        # Armazena os embeds com botões que o bot enviou,
        # para que as views possam ser restauradas após reinício.
        # --------------------------------------------------
        c.execute('''
                              CREATE TABLE IF NOT EXISTS persistent_formularios (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id            INTEGER NOT NULL,  -- canal onde o embed foi enviado
                message_id            INTEGER NOT NULL,  -- ID da mensagem do embed
                custom_id             TEXT    NOT NULL,  -- ID customizado da view/botão
                embed_title           TEXT,              -- título do embed
                embed_description     TEXT,              -- descrição do embed
                embed_color           INTEGER,           -- cor do embed (int)
                formulario_channel_id INTEGER,           -- canal onde os formulários são abertos
                resultados_channel_id INTEGER            -- canal onde os resultados são enviados
            )
        ''')

        # Índice em message_id para acelerar buscas e remoções por mensagem
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_formularios_message_id
            ON persistent_formularios(message_id)
        ''')

        # --------------------------------------------------
        # Migração: adiciona colunas que podem faltar em
        # bancos criados por versões anteriores do bot
        # --------------------------------------------------
        c.execute("PRAGMA table_info(persistent_formularios)")
        existing_cols = [col[1] for col in c.fetchall()]

        if "formulario_channel_id" not in existing_cols:
            c.execute("ALTER TABLE persistent_formularios ADD COLUMN formulario_channel_id INTEGER")
            print("[DB] Migração: coluna 'formulario_channel_id' adicionada")

        if "resultados_channel_id" not in existing_cols:
            c.execute("ALTER TABLE persistent_formularios ADD COLUMN resultados_channel_id INTEGER")
            print("[DB] Migração: coluna 'resultados_channel_id' adicionada")

        # --------------------------------------------------
        # Tabela: active_tickets
        # Nenhum código criava esta tabela (só existia dentro do
        # bot_data.db commitado); num banco novo a migração abaixo
        # quebrava com "no such table: active_tickets".
        # --------------------------------------------------
        c.execute('''
            CREATE TABLE IF NOT EXISTS active_tickets (
                channel_id         INTEGER PRIMARY KEY,
                user_id            INTEGER NOT NULL,
                welcome_message_id INTEGER NOT NULL,
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                custom_id          TEXT
            )
        ''')

        # --------------------------------------------------
        # Tabelas: histórico de heroes finalizadas
        # Uma linha por heroes + uma linha por participante,
        # para o ranking de participação da guild.
        # --------------------------------------------------
        c.execute('''
            CREATE TABLE IF NOT EXISTS heroes_historico (
                id             TEXT PRIMARY KEY,   -- mesmo id do JSON da heroes ativa
                boss           TEXT NOT NULL,
                mastery        TEXT,
                criador_id     INTEGER NOT NULL,
                criador_nome   TEXT,
                agendada_para  TEXT NOT NULL,      -- ISO 8601
                finalizada_em  TEXT NOT NULL,      -- ISO 8601
                finalizada_por TEXT NOT NULL,      -- nome de quem finalizou ou 'auto'
                modo           TEXT DEFAULT 'heroes'  -- heroes / andares
            )
        ''')

        # Migração: bancos criados antes do modo "andares" ganham a coluna
        c.execute("PRAGMA table_info(heroes_historico)")
        cols_historico = [col[1] for col in c.fetchall()]
        if "modo" not in cols_historico:
            c.execute("ALTER TABLE heroes_historico ADD COLUMN modo TEXT DEFAULT 'heroes'")
            print("[DB] Migração: coluna 'modo' adicionada em heroes_historico")
        c.execute('''
            CREATE TABLE IF NOT EXISTS heroes_participacao (
                heroes_id TEXT NOT NULL,
                user_id   INTEGER NOT NULL,
                user_nome TEXT,
                classe    TEXT NOT NULL,
                PRIMARY KEY (heroes_id, user_id)
            )
        ''')

        # --------------------------------------------------
        # Migração: adiciona coluna custom_id em active_tickets
        # --------------------------------------------------
        c.execute("PRAGMA table_info(active_tickets)")
        existing_cols_tickets = [col[1] for col in c.fetchall()]
        if "custom_id" not in existing_cols_tickets:
            c.execute("ALTER TABLE active_tickets ADD COLUMN custom_id TEXT")
            print("[DB] Migração: coluna 'custom_id' adicionada em active_tickets")

        # --------------------------------------------------
        # Tabela: freebies_config
        # Onde o /set_freebies guarda o canal (e o cargo opcional
        # que leva o ping) dos avisos de código de Where Winds Meet.
        # Uma linha por servidor.
        # --------------------------------------------------
        c.execute('''
            CREATE TABLE IF NOT EXISTS freebies_config (
                guild_id INTEGER PRIMARY KEY,  -- servidor
                canal_id INTEGER NOT NULL,     -- canal onde os códigos são postados
                cargo_id INTEGER               -- cargo mencionado (NULL = sem ping)
            )
        ''')

        # --------------------------------------------------
        # Tabela: freebies_codigos
        # Quais códigos já foram anunciados em cada servidor, para
        # não repetir a cada verificação. Sobrevive a reinício e a
        # redeploy (é o que faz o bot avisar só o que é novo).
        # --------------------------------------------------
        c.execute('''
            CREATE TABLE IF NOT EXISTS freebies_codigos (
                guild_id INTEGER NOT NULL,
                codigo   TEXT    NOT NULL,
                visto_em TEXT    NOT NULL,  -- quando o bot viu o código
                PRIMARY KEY (guild_id, codigo)
            )
        ''')

        #commit automatico ao sair do bloco `with` sem erros

# ======================================================
# FUNÇÕES: persistent_formularios
# ======================================================

def add_persistent_formulario(
    channel_id: int,
    message_id: int,
    custom_id: str,
    embed_title: str = None,
    embed_description: str = None,
    embed_color: int = None,
    formulario_channel_id: int = None,
    resultados_channel_id: int = None
    ) -> None:
    """
    Salva um formulário persistente no banco.
    Deve ser chamado após o bot enviar o embed com botões,
    passando os IDs necessários para restaurar a view depois.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO persistent_formularios
                (channel_id, message_id, custom_id, embed_title, embed_description,
                 embed_color, formulario_channel_id, resultados_channel_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            channel_id,
            message_id,
            custom_id,
            embed_title,
            embed_description,
            embed_color,
            formulario_channel_id,
            resultados_channel_id
        ))

def remove_persistent_formulario(message_id: int) -> None:
    """
    Remove um formulário persistente pelo ID da mensagem.
    Deve ser chamado quando a mensagem não for mais encontrada no Discord
    (ex: foi deletada manualmente).
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM persistent_formularios WHERE message_id = ?",
            (message_id,)
        )

def get_all_persistent_formularios() -> List[Tuple]:
    """
    Retorna uma lista de todos os formulários persistentes salvos.
    Usado no on_ready para restaurar as views após reinício do bot.

    Retorna uma lista de tuplas com:
    (channel_id, message_id, custom_id, embed_title, embed_description, embed_color,
     formulario_channel_id, resultados_channel_id)
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT
                channel_id,
                message_id,
                custom_id,
                embed_title,
                embed_description,
                embed_color,
                formulario_channel_id,
                resultados_channel_id
            FROM persistent_formularios
        ''')
        return c.fetchall()

# ======================================================
# FUNÇÕES: histórico de heroes
# ======================================================

def registrar_heroes_finalizada(
    heroes_id: str,
    boss: str,
    mastery: str,
    criador_id: int,
    criador_nome: str,
    agendada_para: str,
    finalizada_em: str,
    finalizada_por: str,
    participantes: List[Tuple[int, str, str]],  # (user_id, nome, classe)
    modo: str = "heroes",
) -> None:
    """
    Grava uma heroes finalizada no histórico permanente.
    Chamado no momento da finalização (manual ou automática); é daqui
    que sai o ranking de participação da guild.
    """
    with sqlite3.connect(DB_PATH) as conn:
        # OR IGNORE: se uma finalização for reexecutada (ex: crash no meio),
        # o registro original (quem finalizou, quando) é preservado
        conn.execute('''
            INSERT OR IGNORE INTO heroes_historico
                (id, boss, mastery, criador_id, criador_nome,
                 agendada_para, finalizada_em, finalizada_por, modo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (heroes_id, boss, mastery, criador_id, criador_nome,
              agendada_para, finalizada_em, finalizada_por, modo))
        # Limpa e regrava os participantes na mesma transação (idempotente)
        conn.execute("DELETE FROM heroes_participacao WHERE heroes_id = ?", (heroes_id,))
        conn.executemany('''
            INSERT INTO heroes_participacao
                (heroes_id, user_id, user_nome, classe)
            VALUES (?, ?, ?, ?)
        ''', [(heroes_id, uid, nome, classe) for uid, nome, classe in participantes])


def ranking_participacao(limite: int = 20) -> List[Tuple]:
    """
    Retorna [(user_id, user_nome, total de heroes)], do mais ativo para o menos.
    Base para um futuro comando /atividade.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # O nome exibido vem da heroes finalizada mais RECENTE de cada pessoa
        # (nomes mudam; MAX(user_nome) pegaria o alfabeticamente maior)
        c.execute('''
            SELECT p.user_id,
                   (SELECT p2.user_nome
                    FROM heroes_participacao p2
                    JOIN heroes_historico h2 ON h2.id = p2.heroes_id
                    WHERE p2.user_id = p.user_id
                    ORDER BY h2.finalizada_em DESC
                    LIMIT 1) AS nome,
                   COUNT(*) AS total
            FROM heroes_participacao p
            GROUP BY p.user_id
            ORDER BY total DESC
            LIMIT ?
        ''', (limite,))
        return c.fetchall()


# ======================================================
# FUNÇÕES: active_tickets
# ======================================================

def add_active_ticket(channel_id: int, user_id: int, welcome_message_id: int, custom_id: str = None) -> None:
    """
    Registra um ticket ativo no banco.
    Usa INSERT OR IGNORE + UPDATE para não resetar o created_at.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT OR IGNORE INTO active_tickets
                (channel_id, user_id, welcome_message_id, custom_id)
            VALUES (?, ?, ?, ?)
        ''', (
            channel_id,
            user_id,
            welcome_message_id,
            custom_id
        ))
        # Se já existe, atualiza apenas os campos necessários
        conn.execute('''
            UPDATE active_tickets
            SET user_id = ?, welcome_message_id = ?, custom_id = ?
            WHERE channel_id = ?
        ''', (
            user_id,
            welcome_message_id,
            custom_id,
            channel_id
        ))

def remove_active_ticket(channel_id: int) -> None:
    """
    Remove um ticket ativo pelo ID do canal.
    Deve ser chamado quando o canal de ticket for fechado/deletado.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM active_tickets WHERE channel_id = ?",
            (channel_id,)
        )

def get_all_active_tickets() -> List[Tuple]:
    """
    Retorna todos os tickets ativos salvos.
    Usado no on_ready para recarregar o estado dos tickets após reinício.

    Retorna uma lista de tuplas com:
        (channel_id, user_id, welcome_message_id, custom_id)
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT channel_id, user_id, welcome_message_id, custom_id FROM active_tickets")
        return c.fetchall()
# ======================================================
# FUNÇÕES: freebies (códigos de Where Winds Meet)
# ======================================================

def set_freebies_config(guild_id: int, canal_id: int, cargo_id: int = None) -> None:
    """
    Define (ou troca) o canal de freebies do servidor e o cargo que recebe o
    ping. cargo_id None = o bot posta sem mencionar ninguém.
    Chamado pelo /set_freebies.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO freebies_config (guild_id, canal_id, cargo_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                canal_id = excluded.canal_id,
                cargo_id = excluded.cargo_id
        ''', (guild_id, canal_id, cargo_id))

def get_freebies_config(guild_id: int) -> Tuple | None:
    """
    Devolve (canal_id, cargo_id) do servidor, ou None se ninguém configurou.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT canal_id, cargo_id FROM freebies_config WHERE guild_id = ?",
            (guild_id,)
        )
        return c.fetchone()

def get_all_freebies_configs() -> List[Tuple]:
    """
    Devolve [(guild_id, canal_id, cargo_id), ...] de todos os servidores
    configurados. Usado pela verificação automática, que roda sem interação.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT guild_id, canal_id, cargo_id FROM freebies_config")
        return c.fetchall()

def remove_freebies_config(guild_id: int) -> bool:
    """
    Desliga os avisos no servidor. Devolve True se havia algo configurado.

    Os códigos já anunciados continuam salvos de propósito: se o canal for
    reconfigurado depois, o bot não repete tudo o que já postou.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM freebies_config WHERE guild_id = ?", (guild_id,))
        return cur.rowcount > 0

def codigos_ja_vistos(guild_id: int) -> set:
    """Conjunto dos códigos que o bot já anunciou neste servidor."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT codigo FROM freebies_codigos WHERE guild_id = ?", (guild_id,))
        return {linha[0] for linha in c.fetchall()}

def marcar_codigos_vistos(guild_id: int, codigos: List[str]) -> None:
    """
    Marca códigos como já anunciados. INSERT OR IGNORE: chamar duas vezes com
    o mesmo código não quebra nem muda a data da primeira vez.
    """
    if not codigos:
        return
    agora = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO freebies_codigos (guild_id, codigo, visto_em) VALUES (?, ?, ?)",
            [(guild_id, codigo, agora) for codigo in codigos]
        )
