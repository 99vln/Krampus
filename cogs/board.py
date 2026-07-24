# cogs/board.py
# Comando /board: sign-up de eventos de GvG tático (Where Winds Meet), com
# embed ao vivo e botões de Role (Tank/Melee/Ranged/Healer/Support) e Status
# (Bench/Late/Tentative/Absence).
#
# Ao contrário do motor_alistamento.py, aqui o estado NÃO tem espelho em JSON:
# o board nasce direto no Postgres (database_board.py) porque o futuro
# dashboard web também precisa ler o estado "ao vivo" de um board aberto, não
# só o histórico depois de fechado. O Postgres é isolado do SQLite
# (bot_data.db) que os outros sistemas do bot continuam usando.
#
# Role e status são colunas independentes no banco, mas mutuamente exclusivos
# na prática: quem vai participar marca uma role; quem não vai marca um
# status (Bench/Late/Tentative/Absence). Clicar de novo no botão já selecionado
# tira a pessoa do board (toggle off).

import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, DynamicItem

import config
import database_board as db_board
from board_constants import ROLES, STATUSES, ROLE_LABELS, STATUS_LABELS

RODAPE = "Guilda Wanted © | GvG Board"


def _tem_permissao_lideranca(user: discord.Member) -> bool:
    cargos = [role.id for role in user.roles]
    return (
        any(cargo_id in config.CARGOS_BOARD_LIDERANCA for cargo_id in cargos)
        or user.guild_permissions.administrator
    )


# ----------------------------------------------------------------------
# Embed
# ----------------------------------------------------------------------

def render_embed(board, vagas: dict, inscricoes) -> discord.Embed:
    ts = int(board["data_evento"].timestamp())
    titulo = board["titulo"]
    if board["status"] != "aberto":
        titulo = f"[{board['status'].upper()}] {titulo}"

    embed = discord.Embed(
        title=titulo,
        description=(
            f"{board['regras_texto'] or ''}\n\n"
            f"**Início:** <t:{ts}:F> (<t:{ts}:R>)"
        ),
        color=0x23272A,
    )

    por_role = {r: [] for r in ROLES}
    por_status = {s: [] for s in STATUSES}
    for i in inscricoes:
        if i["role"]:
            por_role[i["role"]].append(i["discord_user_id"])
        elif i["status"]:
            por_status[i["status"]].append(i["discord_user_id"])

    for role in ROLES:
        pessoas = por_role[role]
        max_vagas = vagas.get(role, 0)
        valor = "\n".join(f"<@{uid}>" for uid in pessoas) or "—"
        embed.add_field(
            name=f"{ROLE_LABELS[role]} ({len(pessoas)}/{max_vagas})",
            value=valor,
            inline=True,
        )

    status_linhas = [
        f"{STATUS_LABELS[status]}: {', '.join(f'<@{uid}>' for uid in por_status[status])}"
        for status in STATUSES
        if por_status[status]
    ]
    if status_linhas:
        embed.add_field(name="​", value="\n".join(status_linhas), inline=False)

    embed.set_footer(text=RODAPE)
    return embed


# ----------------------------------------------------------------------
# Botões
# ----------------------------------------------------------------------

class BotaoOrfao(DynamicItem[Button], template=r"board:(?P<bid>\d+):(?P<tipo>role|status):(?P<valor>[a-z]+)"):
    """Rede de segurança: responde cliques em botões de boards que o bot não
    reconhece mais. Fica MUDO quando o board ainda tem a view real registrada
    (mesma regra do BotaoOrfao em motor_alistamento.py) para não roubar o ack
    do clique legítimo — o discord.py despacha DynamicItem em paralelo com a
    view da mensagem, não como fallback."""

    def __init__(self, custom_id: str, board_id: int = 0):
        super().__init__(Button(label="expirado", custom_id=custom_id))
        self.board_id = board_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.string, int(match["bid"]))

    async def callback(self, interaction: discord.Interaction):
        if self.board_id in Board.ids_ativos:
            return  # board vivo: a view real responde este clique
        await interaction.response.send_message(
            "Este board não está mais ativo.", ephemeral=True
        )


class BoardView(View):
    """Botões da mensagem do board. custom_ids únicos por board para poderem
    ser re-registrados depois de um restart do bot."""

    def __init__(self, board_id: int):
        super().__init__(timeout=None)
        self.board_id = board_id

        for role in ROLES:
            btn = Button(
                label=ROLE_LABELS[role],
                style=discord.ButtonStyle.primary,
                custom_id=f"board:{board_id}:role:{role}",
                row=0,
            )
            btn.callback = self._callback_factory("role", role)
            self.add_item(btn)

        for status in STATUSES:
            btn = Button(
                label=STATUS_LABELS[status],
                style=discord.ButtonStyle.secondary,
                custom_id=f"board:{board_id}:status:{status}",
                row=1,
            )
            btn.callback = self._callback_factory("status", status)
            self.add_item(btn)

    def _callback_factory(self, tipo: str, valor: str):
        async def _callback(interaction: discord.Interaction):
            await self._clicar(interaction, tipo, valor)
        return _callback

    async def _clicar(self, interaction: discord.Interaction, tipo: str, valor: str):
        board = await db_board.buscar_board(self.board_id)
        if board is None or board["status"] != "aberto":
            await interaction.response.send_message(
                "Este board não está mais aberto.", ephemeral=True
            )
            return

        atual = await db_board.get_inscricao(self.board_id, interaction.user.id)
        mesma_selecao = atual and (
            (tipo == "role" and atual["role"] == valor) or
            (tipo == "status" and atual["status"] == valor)
        )

        if mesma_selecao:
            await db_board.remover_inscricao(self.board_id, interaction.user.id)
        elif tipo == "role":
            vagas = await db_board.listar_vagas(self.board_id)
            inscricoes = await db_board.listar_inscricoes(self.board_id)
            ocupadas = sum(1 for i in inscricoes if i["role"] == valor)
            if ocupadas >= vagas.get(valor, 0):
                await interaction.response.send_message(
                    f"❌ Vagas de {ROLE_LABELS[valor]} já preenchidas!", ephemeral=True
                )
                return
            await db_board.upsert_role(
                self.board_id, interaction.user.id, interaction.user.display_name, valor
            )
        else:
            await db_board.upsert_status(
                self.board_id, interaction.user.id, interaction.user.display_name, valor
            )

        board = await db_board.buscar_board(self.board_id)
        vagas = await db_board.listar_vagas(self.board_id)
        inscricoes = await db_board.listar_inscricoes(self.board_id)
        await interaction.response.edit_message(embed=render_embed(board, vagas, inscricoes), view=self)


# ----------------------------------------------------------------------
# Cog / comando
# ----------------------------------------------------------------------

class Board(commands.Cog):
    # ids dos boards com view registrada; usado pelo BotaoOrfao para saber
    # quando ficar mudo
    ids_ativos: set = set()

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="board", description="Cria um board de sign-up para um evento de GvG")
    @app_commands.guild_only()
    @app_commands.describe(
        titulo="Título do evento (ex: GvG vs Fulano)",
        data="Data no formato DD/MM/AAAA",
        hora="Horário no formato 00:00",
        regras="Regras de composição (ex: Ranged = Nameless e Guarda Chuva | Support = Debuffer)",
        vagas_tank="Vagas de Tank",
        vagas_melee="Vagas de Melee",
        vagas_ranged="Vagas de Ranged",
        vagas_healer="Vagas de Healer",
        vagas_support="Vagas de Support",
    )
    async def board(
        self,
        interaction: discord.Interaction,
        titulo: str,
        data: str,
        hora: str,
        regras: str,
        vagas_tank: app_commands.Range[int, 0, 50],
        vagas_melee: app_commands.Range[int, 0, 50],
        vagas_ranged: app_commands.Range[int, 0, 50],
        vagas_healer: app_commands.Range[int, 0, 50],
        vagas_support: app_commands.Range[int, 0, 50],
    ):
        if not _tem_permissao_lideranca(interaction.user):
            await interaction.response.send_message(
                "❌ Só Staff/Lead podem criar boards!", ephemeral=True
            )
            return

        if not re.match(r'^\d{2}/\d{2}/\d{4}$', data):
            await interaction.response.send_message(
                "❌ Formato de data inválido! Use **DD/MM/AAAA** (ex: 24/07/2026)", ephemeral=True
            )
            return
        if not re.match(r'^([0-1][0-9]|2[0-3]):([0-5][0-9])$', hora):
            await interaction.response.send_message(
                "❌ Formato de hora inválido! Use **00:00** (ex: 20:30)", ephemeral=True
            )
            return
        try:
            data_evento = datetime.strptime(f"{data} {hora}", "%d/%m/%Y %H:%M").replace(tzinfo=config.TIMEZONE)
        except ValueError:
            await interaction.response.send_message("❌ Data inválida!", ephemeral=True)
            return

        titulo = titulo.strip()
        if not titulo or len(titulo) > 200:
            await interaction.response.send_message("❌ Título inválido (máx. 200 caracteres)!", ephemeral=True)
            return
        if len(regras) > 500:
            await interaction.response.send_message("❌ Regras muito longas (máx. 500 caracteres)!", ephemeral=True)
            return

        vagas = {
            "tank": vagas_tank,
            "melee": vagas_melee,
            "ranged": vagas_ranged,
            "healer": vagas_healer,
            "support": vagas_support,
        }

        board_id = await db_board.criar_board(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            titulo=titulo,
            regras_texto=regras,
            data_evento=data_evento,
            criado_por_discord_id=interaction.user.id,
            vagas=vagas,
        )

        board = await db_board.buscar_board(board_id)
        view = BoardView(board_id)
        Board.ids_ativos.add(board_id)

        try:
            await interaction.response.send_message(embed=render_embed(board, vagas, []), view=view)
        except discord.HTTPException:
            # A mensagem não foi publicada: desfaz o rastreio para não deixar
            # um board fantasma sem mensagem
            Board.ids_ativos.discard(board_id)
            await db_board.fechar_board(board_id)
            raise

        try:
            message_id = (await interaction.original_response()).id
            await db_board.definir_message_id(board_id, message_id)
        except discord.HTTPException as e:
            print(f"[BOARD] Não consegui obter o id da mensagem do board {board_id}: {e}")

    @board.autocomplete("hora")
    async def hora_autocomplete(
        self, _interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        sugestoes = [f"{h:02d}:{m:02d}" for h in range(0, 24) for m in (0, 30)]
        return [
            app_commands.Choice(name=h, value=h) for h in sugestoes if current in h
        ][:25]


async def setup(bot):
    # Falha de conexão com o Postgres derruba só ESTE cog (main.py já isola
    # cada load_extension num try/except); o resto do bot continua no ar.
    await db_board.init_pool()
    await db_board.init_db_board()

    bot.add_dynamic_items(BotaoOrfao)
    boards_abertos = await db_board.listar_boards_abertos()
    for board in boards_abertos:
        view = BoardView(board["id"])
        bot.add_view(view, message_id=board["message_id"])
        Board.ids_ativos.add(board["id"])
    if boards_abertos:
        print(f"[BOARD] {len(boards_abertos)} board(s) restaurado(s)")

    await bot.add_cog(Board(bot))
