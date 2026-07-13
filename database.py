import sqlite3
from typing import List, Tuple

# ======================================================
# CONFIGURAÇÃO
# ======================================================

# Caminho do arquivo de banco de dados SQLite
DB_PATH = "bot_data.db"

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
        # Migração: adiciona coluna custom_id em active_tickets
        # --------------------------------------------------
        c.execute("PRAGMA table_info(active_tickets)")
        existing_cols_tickets = [col[1] for col in c.fetchall()]
        if "custom_id" not in existing_cols_tickets:
            c.execute("ALTER TABLE active_tickets ADD COLUMN custom_id TEXT")
            print("[DB] Migração: coluna 'custom_id' adicionada em active_tickets")

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