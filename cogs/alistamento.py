import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, DynamicItem

import config
import database as db
from heroes import Heroes, proxima_ocorrencia, DIAS_SEMANA, AUTO_FINALIZAR_APOS

# Opções para boss (pode adicionar mais depois)
BOSSES = [
    "GUILD BOSS 10 PLAYERS",
    # Adicione mais bosses aqui quando quiser:
    # "NOME DO BOSS",
]

# Cores personalizadas
COR_BORDA_ATIVA = 0x23272A  # Cinza escuro
COR_FINALIZADO = 0x808080   # Cinza

# EMOJIS PERSONALIZADOS - IDs reais fornecidos
EMOJIS = {
    "SHOT": "<a:whitearrow1213:1451780689845555282>",      # Emoji animado branco para SHOT CALLER
    "TANK": "<a:orangearrow1213:1451795513790959747>",     # Emoji animado laranja para TANK
    "HEALER": "<a:greenarrow1213:1451780601270112276>",    # Emoji animado verde para HEALER
    "DPS": "<a:purplearrow1213:1451780718748504165>",      # Emoji animado roxo para DPS
}

RODAPE = "Guilda Wanted © | Community Server"


def render_embed(heroes: Heroes, finalizado: bool = False) -> discord.Embed:
    """Desenha o embed de uma heroes a partir do objeto (não da mensagem antiga)."""
    ts = int(heroes.inicio.timestamp())
    titulo = f"**{heroes.boss} - {heroes.dia} - {heroes.hora}**"
    if finalizado:
        titulo = f"[FINALIZADO] {titulo}"
    embed = discord.Embed(
        title=titulo,
        description=(
            f"**MASTERY MIN:** **{heroes.mastery}**\n\n"
            f"{EMOJIS['SHOT']} **SHOT CALLER:** <@{heroes.criador_id}>\n"
            f"⏰ **Começa:** <t:{ts}:F> (<t:{ts}:R>)"
        ),
        color=COR_FINALIZADO if finalizado else COR_BORDA_ATIVA,
    )

    # Lista VERTICAL com emojis específicos para cada role
    linhas = []
    tanks = heroes.por_classe("TANK")
    linhas.append(f"{EMOJIS['TANK']} **TANK:** {f'<@{tanks[0].user_id}>' if tanks else ''}")
    healers = heroes.por_classe("HEALER")
    for i in range(2):
        valor = f"<@{healers[i].user_id}>" if i < len(healers) else ""
        linhas.append(f"{EMOJIS['HEALER']} **HEALER:** {valor}")
    dps = heroes.por_classe("DPS")
    for i in range(6):
        valor = f"<@{dps[i].user_id}>" if i < len(dps) else ""
        linhas.append(f"{EMOJIS['DPS']} **DPS:** {valor}")

    embed.add_field(name="​", value="\n".join(linhas), inline=False)
    embed.set_footer(text=RODAPE)
    return embed


class BotaoOrfao(DynamicItem[Button], template=r"heroes:(?P<hid>[0-9a-f]+):(?P<acao>[a-z_]+)"):
    """Rede de segurança: responde cliques em botões de heroes que o bot não
    conhece mais (ex: a mensagem sobreviveu mas o estado se perdeu). Sem isso,
    o usuário veria só o erro genérico "Esta interação falhou" do Discord.

    CUIDADO: o discord.py despacha dynamic items para TODO clique cujo
    custom_id case com o template, EM PARALELO com a view registrada da
    mensagem (ui/view.py: dispatch_view chama dispatch_dynamic_items
    incondicionalmente). Por isso este callback PRECISA ficar mudo quando a
    heroes ainda está ativa, senão ele "rouba" a resposta do botão real e o
    clique legítimo morre com erro 40060 (already acknowledged)."""

    def __init__(self, custom_id: str, heroes_id: str = ""):
        super().__init__(Button(label="expirado", custom_id=custom_id))
        self.heroes_id = heroes_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.string, match["hid"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Alistamento")
        if cog and self.heroes_id in cog.ativas:
            return  # heroes viva: a view real responde este clique
        await interaction.response.send_message(
            "Este alistamento não está mais ativo.", ephemeral=True
        )


class AlistamentoView(View):
    """Botões da mensagem de alistamento. custom_ids únicos por heroes para
    poderem ser re-registrados depois de um restart do bot."""

    def __init__(self, cog: "Alistamento", heroes_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.heroes_id = heroes_id

        participar = Button(
            label="PARTICIPAR 🎉",
            style=discord.ButtonStyle.success,
            custom_id=f"heroes:{heroes_id}:participar",
        )
        participar.callback = self.participar_callback

        sair = Button(
            label="SAIR 💨",
            style=discord.ButtonStyle.danger,
            custom_id=f"heroes:{heroes_id}:sair",
        )
        sair.callback = self.sair_callback

        finalizar = Button(
            label="FINALIZAR 📋",
            style=discord.ButtonStyle.primary,
            custom_id=f"heroes:{heroes_id}:finalizar",
        )
        finalizar.callback = self.finalizar_callback

        self.add_item(participar)
        self.add_item(sair)
        self.add_item(finalizar)

    def _heroes(self):
        return self.cog.ativas.get(self.heroes_id)

    async def participar_callback(self, interaction: discord.Interaction):
        heroes = self._heroes()
        if not heroes:
            await interaction.response.send_message(
                "Este alistamento não está mais ativo.", ephemeral=True
            )
            return
        if interaction.user.id == heroes.criador_id:
            await interaction.response.send_message(
                "Você é o SHOT CALLER e não pode se inscrever!", ephemeral=True
            )
            return

        cargos = [role.id for role in interaction.user.roles]
        sucesso, mensagem = heroes.adicionar(
            interaction.user.id, interaction.user.display_name, cargos, config.ROLE_IDS
        )
        if sucesso:
            heroes.salvar()
            await interaction.response.edit_message(embed=render_embed(heroes))
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)

    async def sair_callback(self, interaction: discord.Interaction):
        heroes = self._heroes()
        if not heroes:
            await interaction.response.send_message(
                "Este alistamento não está mais ativo.", ephemeral=True
            )
            return
        if interaction.user.id == heroes.criador_id:
            await interaction.response.send_message(
                "Você é o SHOT CALLER e não pode sair!", ephemeral=True
            )
            return

        sucesso, mensagem = heroes.remover(interaction.user.id)
        if sucesso:
            heroes.salvar()
            await interaction.response.edit_message(embed=render_embed(heroes))
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)

    async def finalizar_callback(self, interaction: discord.Interaction):
        heroes = self._heroes()
        if not heroes:
            await interaction.response.send_message(
                "Este alistamento não está mais ativo.", ephemeral=True
            )
            return

        cargos = [role.id for role in interaction.user.roles]
        pode_finalizar = (
            any(role_id in config.CARGOS_STAFF for role_id in cargos)
            or interaction.user.guild_permissions.administrator
            or interaction.user.id == heroes.criador_id  # criador também pode
        )
        if not pode_finalizar:
            await interaction.response.send_message(
                "❌ Você não tem permissão para finalizar alistamentos!", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        ok = await self.cog.finalizar_heroes(heroes, finalizada_por=interaction.user.display_name)
        if ok:
            await interaction.followup.send(
                "✅ Alistamento finalizado, mensagem apagada e enviada para os logs!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "⚠️ Este alistamento já estava sendo finalizado.", ephemeral=True
            )


class FinalizarDMView(View):
    """Botões da DM que pergunta ao criador se a heroes pode ser finalizada."""

    def __init__(self, cog: "Alistamento", heroes_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.heroes_id = heroes_id

        sim = Button(
            label="Finalizar agora ✅",
            style=discord.ButtonStyle.success,
            custom_id=f"heroes:{heroes_id}:dm_finalizar",
        )
        sim.callback = self.finalizar_callback

        depois = Button(
            label="Ainda não ⏳",
            style=discord.ButtonStyle.secondary,
            custom_id=f"heroes:{heroes_id}:dm_depois",
        )
        depois.callback = self.depois_callback

        self.add_item(sim)
        self.add_item(depois)

    async def finalizar_callback(self, interaction: discord.Interaction):
        heroes = self.cog.ativas.get(self.heroes_id)
        if not heroes:
            await interaction.response.send_message("Essa heroes já foi finalizada. 👍")
            return
        await interaction.response.defer()
        ok = await self.cog.finalizar_heroes(heroes, finalizada_por=interaction.user.display_name)
        if ok:
            await interaction.followup.send("✅ Heroes finalizada e registrada nos logs!")
        else:
            await interaction.followup.send("Essa heroes já estava sendo finalizada. 👍")

    async def depois_callback(self, interaction: discord.Interaction):
        heroes = self.cog.ativas.get(self.heroes_id)
        if not heroes:
            await interaction.response.send_message("Essa heroes já foi finalizada. 👍")
            return
        limite = int((heroes.inicio + AUTO_FINALIZAR_APOS).timestamp())
        await interaction.response.send_message(
            f"Ok! Se ninguém finalizar até <t:{limite}:f>, eu mesmo finalizo e limpo o canal. 🧹"
        )


class Alistamento(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ativas: dict[str, Heroes] = {}
        self.views: dict[str, list[View]] = {}
        self._finalizando: set[str] = set()
        self.relogio.start()

    async def cog_load(self):
        """Recarrega heroes ativas do disco e reativa os botões após restart."""
        self.bot.add_dynamic_items(BotaoOrfao)
        for heroes in Heroes.carregar_todas():
            self.ativas[heroes.id] = heroes
            if heroes.message_id:
                view = AlistamentoView(self, heroes.id)
                self.bot.add_view(view, message_id=heroes.message_id)
                self._registrar_view(heroes.id, view)
            if heroes.aviso_criador_enviado:
                dm_view = FinalizarDMView(self, heroes.id)
                self.bot.add_view(dm_view)
                self._registrar_view(heroes.id, dm_view)
        if self.ativas:
            print(f"[HEROES] {len(self.ativas)} heroes ativa(s) restaurada(s)")

    def cog_unload(self):
        self.relogio.cancel()

    def _registrar_view(self, heroes_id: str, view: View):
        self.views.setdefault(heroes_id, []).append(view)

    def _parar_views(self, heroes_id: str):
        """stop() desregistra a view do discord.py; sem isso, views de heroes
        finalizadas ficariam acumulando na memória até o próximo restart."""
        for view in self.views.pop(heroes_id, []):
            view.stop()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Staff apagou a mensagem do alistamento na mão = raid cancelada.
        Some sem escrever no histórico (cancelada não conta no ranking)."""
        for heroes in list(self.ativas.values()):
            if heroes.message_id == payload.message_id:
                heroes.apagar_json()
                self.ativas.pop(heroes.id, None)
                self._parar_views(heroes.id)
                print(f"[HEROES] Heroes {heroes.id} ({heroes.boss}) cancelada: mensagem apagada manualmente")
                break

    # ------------------------------------------------------------------
    # Relógio: a cada minuto verifica lembretes, aviso ao criador e
    # auto-finalização de todas as heroes ativas.
    # ------------------------------------------------------------------

    @tasks.loop(seconds=60)
    async def relogio(self):
        agora = datetime.now(config.TIMEZONE)
        for heroes in list(self.ativas.values()):
            try:
                for acao in heroes.acoes_pendentes(agora):
                    if acao.startswith("lembrete_"):
                        await self._enviar_lembrete(heroes, int(acao.split("_")[1]))
                    elif acao == "aviso_criador":
                        await self._avisar_criador(heroes)
                    elif acao == "auto_finalizar":
                        await self.finalizar_heroes(heroes, finalizada_por="auto")
            except Exception as e:
                print(f"[HEROES] Erro no relógio para heroes {heroes.id}: {e}")

    @relogio.before_loop
    async def antes_do_relogio(self):
        await self.bot.wait_until_ready()

    async def _canal(self, channel_id: int):
        canal = self.bot.get_channel(channel_id)
        if canal is None and channel_id:
            try:
                canal = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                canal = None
        return canal

    async def _enviar_lembrete(self, heroes: Heroes, minutos: int):
        # Marca antes de enviar para nunca spammar em caso de erro repetido
        heroes.marcar_lembrete(minutos)
        heroes.salvar()

        canal = await self._canal(heroes.channel_id)
        if canal is None:
            print(f"[HEROES] Canal {heroes.channel_id} indisponível; lembrete da heroes {heroes.id} descartado")
            return
        # Minutos REAIS restantes (a heroes pode ter sido criada dentro da janela)
        restam = max(1, round((heroes.inicio - datetime.now(config.TIMEZONE)).total_seconds() / 60))
        mencoes = " ".join(
            [f"<@{heroes.criador_id}>"] + [f"<@{p.user_id}>" for p in heroes.participantes]
        )
        fila = f" <#{config.CANAL_FILA_ID}>" if config.CANAL_FILA_ID else " de fila"
        await canal.send(
            f"{mencoes}\n⏰ A heroes **{heroes.boss}** começa em **{restam} minutos**! "
            f"Entrem no canal{fila}!"
        )

    async def _avisar_criador(self, heroes: Heroes):
        heroes.aviso_criador_enviado = True
        heroes.salvar()

        inicio_ts = int(heroes.inicio.timestamp())
        limite = int((heroes.inicio + AUTO_FINALIZAR_APOS).timestamp())
        try:
            criador = self.bot.get_user(heroes.criador_id) or await self.bot.fetch_user(
                heroes.criador_id
            )
            view = FinalizarDMView(self, heroes.id)
            mensagem = await criador.send(
                f"👋 A sua heroes **{heroes.boss}** ({heroes.dia} {heroes.hora}) começou "
                f"<t:{inicio_ts}:R>. Posso finalizar?\n"
                f"Se ninguém finalizar até <t:{limite}:f>, eu finalizo sozinho.",
                view=view,
            )
            self._registrar_view(heroes.id, view)
            heroes.dm_message_id = mensagem.id
            heroes.salvar()
        except discord.HTTPException as e:
            # DM fechada ou usuário inacessível: a auto-finalização resolve depois
            print(f"[HEROES] Não consegui mandar DM para o criador da heroes {heroes.id}: {e}")

    # ------------------------------------------------------------------
    # Finalização (manual, via DM ou automática)
    # ------------------------------------------------------------------

    async def finalizar_heroes(self, heroes: Heroes, finalizada_por: str) -> bool:
        """Registra no histórico, manda o resumo para os logs, apaga a mensagem
        e o JSON. Retorna False se já estava sendo finalizada."""
        if heroes.id in self._finalizando or heroes.id not in self.ativas:
            return False
        self._finalizando.add(heroes.id)
        try:
            # 1. Histórico permanente (o dado do líder mora aqui)
            db.registrar_heroes_finalizada(
                heroes_id=heroes.id,
                boss=heroes.boss,
                mastery=heroes.mastery,
                criador_id=heroes.criador_id,
                criador_nome=heroes.criador_nome,
                agendada_para=heroes.agendada_para,
                finalizada_em=datetime.now(config.TIMEZONE).isoformat(),
                finalizada_por=finalizada_por,
                participantes=[(p.user_id, p.nome, p.classe) for p in heroes.participantes],
            )

            # 2. Encerra o estado vivo ANTES do I/O com o Discord: se o bot cair
            #    no meio dos passos seguintes, a heroes não "revive" no restart
            #    nem é finalizada duas vezes
            heroes.apagar_json()
            self.ativas.pop(heroes.id, None)
            self._parar_views(heroes.id)

            # 3. Resumo no canal de logs
            logs = await self._canal(config.CANAL_LOGS_ALISTAMENTO_ID)
            if logs is None:
                print(f"[HEROES] Canal de logs {config.CANAL_LOGS_ALISTAMENTO_ID} indisponível; resumo da heroes {heroes.id} não enviado")
            else:
                try:
                    await logs.send(embed=render_embed(heroes, finalizado=True))
                except discord.HTTPException as e:
                    print(f"[HEROES] Falha ao enviar log da heroes {heroes.id}: {e}")

            # 4. Apaga a mensagem do canal (o canal fica limpo; o dado já está salvo)
            canal = await self._canal(heroes.channel_id)
            if canal and heroes.message_id:
                try:
                    await canal.get_partial_message(heroes.message_id).delete()
                except discord.HTTPException:
                    pass  # mensagem já apagada manualmente

            # 5. Remove os botões da DM do criador (se ela existiu), para não
            #    deixar uma DM antiga com botões clicáveis apontando pro nada
            if heroes.dm_message_id:
                try:
                    criador = self.bot.get_user(heroes.criador_id) or await self.bot.fetch_user(heroes.criador_id)
                    dm = criador.dm_channel or await criador.create_dm()
                    await dm.get_partial_message(heroes.dm_message_id).edit(view=None)
                except discord.HTTPException:
                    pass
            return True
        finally:
            self._finalizando.discard(heroes.id)

    # ------------------------------------------------------------------
    # Comando
    # ------------------------------------------------------------------

    @app_commands.command(name="alistamento", description="Cria um novo alistamento para boss")
    @app_commands.guild_only()
    @app_commands.describe(
        boss="Nome do Boss",
        dia="Dia da Semana",
        hora="Formato 00:00",
        mastery="Mastery requerida"
    )
    async def alistamento(
        self,
        interaction: discord.Interaction,
        boss: str,
        dia: str,
        hora: str,
        mastery: str
    ):
        """Cria um alistamento para boss com seleções para boss e dia"""
        # Verificar permissão
        user_roles = [role.id for role in interaction.user.roles]
        user_has_permission = (
            any(role_id in config.CARGOS_STAFF for role_id in user_roles) or
            interaction.user.guild_permissions.administrator
        )
        if not user_has_permission:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando!", ephemeral=True
            )
            return

        # Validar boss
        if boss not in BOSSES:
            await interaction.response.send_message(
                f"❌ Boss inválido! Opções disponíveis: {', '.join(BOSSES)}", ephemeral=True
            )
            return

        # Validar dia
        if dia.upper() not in DIAS_SEMANA:
            await interaction.response.send_message(
                f"❌ Dia inválido! Opções disponíveis: {', '.join(DIAS_SEMANA)}", ephemeral=True
            )
            return

        # Validar formato da hora
        if not re.match(r'^([0-1][0-9]|2[0-3]):([0-5][0-9])$', hora):
            await interaction.response.send_message(
                "❌ Formato de hora inválido! Use o formato **00:00** (ex: 20:30)", ephemeral=True
            )
            return

        # Validar mastery (deve ser número)
        if not mastery.isdigit():
            await interaction.response.send_message(
                "❌ Mastery deve conter apenas números!", ephemeral=True
            )
            return

        # Criar a heroes já agendada para a próxima ocorrência do dia/hora
        agora = datetime.now(config.TIMEZONE)
        inicio = proxima_ocorrencia(dia, hora, agora)
        heroes = Heroes(
            boss=boss,
            dia=dia.upper(),
            hora=hora,
            mastery=mastery,
            criador_id=interaction.user.id,
            criador_nome=interaction.user.display_name,
            agendada_para=inicio.isoformat(),
        )
        heroes.channel_id = interaction.channel_id

        # Rastreia ANTES de enviar: os botões ficam vivos no instante em que a
        # mensagem aparece, então a heroes já precisa existir para o bot
        self.ativas[heroes.id] = heroes
        heroes.salvar()

        view = AlistamentoView(self, heroes.id)
        self._registrar_view(heroes.id, view)
        try:
            resposta = await interaction.response.send_message(embed=render_embed(heroes), view=view)
        except discord.HTTPException:
            # A mensagem não foi publicada: desfaz o rastreio para não deixar
            # uma heroes fantasma sem mensagem mandando lembretes no canal
            self.ativas.pop(heroes.id, None)
            heroes.apagar_json()
            self._parar_views(heroes.id)
            raise

        # Guarda o id da mensagem para conseguir apagá-la/reativá-la depois
        try:
            message_id = getattr(resposta, "message_id", None)
            if not message_id:
                message_id = (await interaction.original_response()).id
            heroes.message_id = message_id
        except discord.HTTPException as e:
            # Sem o id, a mensagem não poderá ser apagada na finalização, mas a
            # heroes continua rastreada (lembretes, DM e histórico funcionam)
            print(f"[HEROES] Não consegui obter o id da mensagem da heroes {heroes.id}: {e}")
        heroes.salvar()

    @alistamento.autocomplete("boss")
    async def boss_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        filtered = [
            app_commands.Choice(name=boss, value=boss)
            for boss in BOSSES
            if current.lower() in boss.lower()
        ]
        return filtered[:25]  # Discord limita a 25 opções

    @alistamento.autocomplete("dia")
    async def dia_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        filtered = [
            app_commands.Choice(name=dia, value=dia)
            for dia in DIAS_SEMANA
            if current.lower() in dia.lower()
        ]
        return filtered[:25]


async def setup(bot):
    await bot.add_cog(Alistamento(bot))
