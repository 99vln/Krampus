import asyncpg
import config

# ======================================================
# CONFIGURAÇÃO
# ======================================================
#
# Banco separado do SQLite (bot_data.db): só o sistema /board e o dashboard
# web usam este módulo. O pool é aberto sob demanda por quem precisar dele
# (hoje: cogs/board.py no próprio setup()) em vez de no setup_hook global do
# bot, para que uma falha de conexão com o Postgres derrube só o cog do
# board, não o bot inteiro — mesmo princípio do "um cog que falha ao
# carregar não derruba os outros" do main.py.

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """
    Abre o pool de conexões com o Postgres (se ainda não estiver aberto).
    Chamado uma vez no setup() de cogs/board.py.
    """
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL não encontrado no .env — configure a connection "
                "string do Postgres (Neon/Supabase) para usar o sistema /board."
            )
        _pool = await asyncpg.create_pool(config.DATABASE_URL)
    return _pool


def get_pool() -> asyncpg.Pool:
    """Devolve o pool já aberto. Lança erro se init_pool() ainda não rodou."""
    if _pool is None:
        raise RuntimeError("Pool do Postgres ainda não foi inicializado — chame init_pool() primeiro.")
    return _pool


async def close_pool() -> None:
    """Fecha o pool. Chamado no shutdown do bot (Krampus.close())."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ======================================================
# SCHEMA (enums + tabelas)
# ======================================================

_ENUMS = {
    "board_status": ["aberto", "fechado", "arquivado"],
    "board_role": ["tank", "melee", "ranged", "healer", "support"],
    "inscricao_status": ["bench", "late", "tentative", "absence"],
    "dashboard_papel": ["staff", "lead"],
    "sheets_sync_status": ["nunca", "sucesso", "erro"],
}


async def init_db_board() -> None:
    """
    Cria os enums e tabelas do sistema /board no Postgres, se ainda não
    existirem. Idempotente: seguro rodar toda vez que o cog carrega, igual
    o init_db() do SQLite em database.py.
    """
    pool = await init_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # CREATE TYPE não tem IF NOT EXISTS no Postgres; o jeito idiomático
            # de tornar isso idempotente é capturar duplicate_object no DO block.
            for nome, valores in _ENUMS.items():
                valores_sql = ", ".join(f"'{v}'" for v in valores)
                await conn.execute(f'''
                    DO $$ BEGIN
                        CREATE TYPE {nome} AS ENUM ({valores_sql});
                    EXCEPTION
                        WHEN duplicate_object THEN null;
                    END $$;
                ''')

            # --------------------------------------------------
            # Tabela: dashboard_users
            # Login da Staff/Lead no painel web. Sem rota de cadastro:
            # credenciais só são inseridas manualmente aqui.
            # --------------------------------------------------
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS dashboard_users (
                    id              BIGSERIAL PRIMARY KEY,
                    username        VARCHAR(64)  NOT NULL UNIQUE,
                    password_hash   VARCHAR(255) NOT NULL,
                    discord_user_id BIGINT       NULL,
                    papel           dashboard_papel NOT NULL DEFAULT 'staff',
                    ativo           BOOLEAN NOT NULL DEFAULT TRUE,
                    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
                    ultimo_login    TIMESTAMPTZ NULL
                )
            ''')

            # --------------------------------------------------
            # Tabela: boards
            # Um GvG criado por /board. sheets_* rastreia a sincronização
            # em lote com o Google Sheets (no fechamento ou via botão manual
            # no dashboard, nunca por clique de inscrição).
            # --------------------------------------------------
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS boards (
                    id                     BIGSERIAL PRIMARY KEY,
                    guild_id               BIGINT NOT NULL,
                    channel_id             BIGINT NOT NULL,
                    message_id             BIGINT NULL,
                    titulo                 VARCHAR(200) NOT NULL,
                    regras_texto           TEXT NULL,
                    data_evento            TIMESTAMPTZ NOT NULL,
                    status                 board_status NOT NULL DEFAULT 'aberto',
                    criado_por_discord_id  BIGINT NOT NULL,
                    criado_em              TIMESTAMPTZ NOT NULL DEFAULT now(),
                    fechado_em             TIMESTAMPTZ NULL,
                    sheets_spreadsheet_id  VARCHAR(100) NULL,
                    sheets_sincronizado_em TIMESTAMPTZ NULL,
                    sheets_sync_status     sheets_sync_status NOT NULL DEFAULT 'nunca',
                    sheets_sync_erro       TEXT NULL
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_boards_status ON boards (status)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_boards_data_evento ON boards (data_evento DESC)')

            # --------------------------------------------------
            # Tabela: board_vagas
            # Limite de vagas por role, configurável POR board (não fixo
            # no código, já que a composição muda por evento).
            # --------------------------------------------------
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS board_vagas (
                    id        BIGSERIAL PRIMARY KEY,
                    board_id  BIGINT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                    role      board_role NOT NULL,
                    max_vagas INT NOT NULL CHECK (max_vagas >= 0),
                    UNIQUE (board_id, role)
                )
            ''')

            # --------------------------------------------------
            # Tabela: board_inscricoes
            # role e status são colunas independentes (ex: Tank + Late ao
            # mesmo tempo é permitido); status NULL = confirmado normal.
            # --------------------------------------------------
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS board_inscricoes (
                    id                   BIGSERIAL PRIMARY KEY,
                    board_id             BIGINT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
                    discord_user_id      BIGINT NOT NULL,
                    discord_display_name VARCHAR(100) NOT NULL,
                    role                 board_role NULL,
                    status               inscricao_status NULL,
                    atualizado_em        TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (board_id, discord_user_id)
                )
            ''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_inscricoes_board ON board_inscricoes (board_id)')


# ======================================================
# CRUD: boards
# ======================================================

async def criar_board(
    guild_id: int,
    channel_id: int,
    titulo: str,
    regras_texto: str,
    data_evento,
    criado_por_discord_id: int,
    vagas: dict,
) -> int:
    """Cria o board e suas vagas por role numa única transação. Devolve o id gerado."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            board_id = await conn.fetchval('''
                INSERT INTO boards
                    (guild_id, channel_id, titulo, regras_texto, data_evento, criado_por_discord_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            ''', guild_id, channel_id, titulo, regras_texto, data_evento, criado_por_discord_id)
            for role, max_vagas in vagas.items():
                await conn.execute('''
                    INSERT INTO board_vagas (board_id, role, max_vagas)
                    VALUES ($1, $2, $3)
                ''', board_id, role, max_vagas)
    return board_id


async def definir_message_id(board_id: int, message_id: int) -> None:
    pool = get_pool()
    await pool.execute("UPDATE boards SET message_id = $1 WHERE id = $2", message_id, board_id)


async def buscar_board(board_id: int):
    """Devolve o registro do board (asyncpg.Record) ou None."""
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM boards WHERE id = $1", board_id)


async def listar_boards_abertos():
    """Boards com status='aberto' e mensagem publicada. Usado na restauração
    das views após um restart do bot (cogs/board.py:setup)."""
    pool = get_pool()
    return await pool.fetch(
        "SELECT * FROM boards WHERE status = 'aberto' AND message_id IS NOT NULL"
    )


async def fechar_board(board_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "UPDATE boards SET status = 'fechado', fechado_em = now() WHERE id = $1",
        board_id,
    )


async def listar_vagas(board_id: int) -> dict:
    """Devolve {role: max_vagas} do board."""
    pool = get_pool()
    linhas = await pool.fetch(
        "SELECT role, max_vagas FROM board_vagas WHERE board_id = $1", board_id
    )
    return {linha["role"]: linha["max_vagas"] for linha in linhas}


# ======================================================
# CRUD: board_inscricoes
# ======================================================

async def get_inscricao(board_id: int, discord_user_id: int):
    pool = get_pool()
    return await pool.fetchrow(
        "SELECT * FROM board_inscricoes WHERE board_id = $1 AND discord_user_id = $2",
        board_id, discord_user_id,
    )


async def listar_inscricoes(board_id: int):
    pool = get_pool()
    return await pool.fetch(
        "SELECT * FROM board_inscricoes WHERE board_id = $1 ORDER BY atualizado_em",
        board_id,
    )


async def upsert_role(board_id: int, discord_user_id: int, discord_display_name: str, role: str) -> None:
    """Marca a role escolhida e limpa o status: role e status são exclusivos
    na prática (quem participa marca role; quem não vai marca Late/Bench/etc)."""
    pool = get_pool()
    await pool.execute('''
        INSERT INTO board_inscricoes (board_id, discord_user_id, discord_display_name, role, status)
        VALUES ($1, $2, $3, $4, NULL)
        ON CONFLICT (board_id, discord_user_id) DO UPDATE SET
            discord_display_name = excluded.discord_display_name,
            role = excluded.role,
            status = NULL,
            atualizado_em = now()
    ''', board_id, discord_user_id, discord_display_name, role)


async def upsert_status(board_id: int, discord_user_id: int, discord_display_name: str, status: str) -> None:
    """Marca o status escolhido e limpa a role (ver upsert_role)."""
    pool = get_pool()
    await pool.execute('''
        INSERT INTO board_inscricoes (board_id, discord_user_id, discord_display_name, role, status)
        VALUES ($1, $2, $3, NULL, $4)
        ON CONFLICT (board_id, discord_user_id) DO UPDATE SET
            discord_display_name = excluded.discord_display_name,
            role = NULL,
            status = excluded.status,
            atualizado_em = now()
    ''', board_id, discord_user_id, discord_display_name, status)


async def remover_inscricao(board_id: int, discord_user_id: int) -> None:
    """Toggle off: clicar de novo no botão atual tira a pessoa do board por completo."""
    pool = get_pool()
    await pool.execute(
        "DELETE FROM board_inscricoes WHERE board_id = $1 AND discord_user_id = $2",
        board_id, discord_user_id,
    )
