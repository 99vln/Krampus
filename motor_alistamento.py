# motor_alistamento.py
# O MOTOR compartilhado dos alistamentos (heroes e andares).
#
# Este arquivo NÃO é um cog e não tem nenhum comando. Aqui vive tudo que os
# comandos têm em comum: o estado das heroes ativas, o desenho do embed, os
# botões, a criação, a movimentação de membros na call e a finalização.
#
# Quem usa o motor (cada um importando este módulo diretamente, do mesmo
# jeito que todo mundo já importa config.py e database.py):
#   cogs/alistamento.py -> comando /alistamento
#   cogs/andares.py     -> comando /andares
#   cogs/puxar.py       -> comando /puxar
#   cogs/relogio.py     -> lembretes, puxada automática e auto-finalização
#
# Cada cog chama inicializar(bot) no seu setup(): o primeiro que carregar
# liga o motor, e a falha de um cog não derruba os comandos dos outros.

import re
from datetime import datetime, timedelta

import discord
from discord.ui import View, Button, DynamicItem

import config
import database as db
from heroes import (
    Heroes,
    proxima_ocorrencia,
    DIAS_SEMANA,
    AUTO_FINALIZAR_APOS,
    LEMBRETE_ANTECEDENCIAS_MIN,
)

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

# ----------------------------------------------------------------------
# Estado do motor (compartilhado por todos os comandos)
# ----------------------------------------------------------------------

ativas: dict[str, Heroes] = {}
_views: dict[str, list[View]] = {}
_finalizando: set[str] = set()
_bot: discord.Client | None = None


def inicializar(bot) -> None:
    """Liga o motor: recarrega as heroes ativas do disco e reativa os botões
    após um restart. Chamado pelo setup() de cada cog que usa o motor; só a
    PRIMEIRA chamada trabalha, as demais retornam na hora (registrar os
    dynamic items duas vezes causaria cliques respondidos em dobro)."""
    global _bot
    if _bot is not None:
        return
    _bot = bot
    bot.add_dynamic_items(BotaoOrfao)
    for heroes in Heroes.carregar_todas():
        ativas[heroes.id] = heroes
        if heroes.message_id:
            view = AlistamentoView(heroes.id)
            bot.add_view(view, message_id=heroes.message_id)
            _registrar_view(heroes.id, view)
        if heroes.aviso_criador_enviado:
            dm_view = FinalizarDMView(heroes.id)
            bot.add_view(dm_view)
            _registrar_view(heroes.id, dm_view)
    if ativas:
        print(f"[HEROES] {len(ativas)} heroes ativa(s) restaurada(s)")


def _registrar_view(heroes_id: str, view: View):
    _views.setdefault(heroes_id, []).append(view)


def _parar_views(heroes_id: str):
    """stop() desregistra a view do discord.py; sem isso, views de heroes
    finalizadas ficariam acumulando na memória até o próximo restart."""
    for view in _views.pop(heroes_id, []):
        view.stop()


async def _canal(channel_id: int):
    canal = _bot.get_channel(channel_id)
    if canal is None and channel_id:
        try:
            canal = await _bot.fetch_channel(channel_id)
        except discord.HTTPException:
            canal = None
    return canal


# ----------------------------------------------------------------------
# Embed
# ----------------------------------------------------------------------

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
            f"**Começa:** <t:{ts}:F> (<t:{ts}:R>)"
        ),
        color=COR_FINALIZADO if finalizado else COR_BORDA_ATIVA,
    )

    # Lista VERTICAL com emojis específicos para cada role; a quantidade de
    # linhas por classe vem do MODO (heroes: 1/2/6, andares: 1/2/7).
    # max(..., len(pessoas)) garante que ninguém alistado fique invisível
    # mesmo se um JSON vier com mais gente do que o limite atual
    linhas = []
    for classe in ("TANK", "HEALER", "DPS"):
        pessoas = heroes.por_classe(classe)
        for i in range(max(heroes.limites[classe], len(pessoas))):
            valor = f"<@{pessoas[i].user_id}>" if i < len(pessoas) else ""
            linhas.append(f"{EMOJIS[classe]} **{classe}:** {valor}")

    embed.add_field(name="​", value="\n".join(linhas), inline=False)

    # Lista de espera (aparece só quando tem alguém). Mostra no máximo 15
    # nomes: um campo de embed aguenta 1024 caracteres, e com ~33 reservas
    # o Discord recusaria a mensagem inteira
    if heroes.reservas:
        visiveis = [f"<@{r.user_id}> ({r.classe})" for r in heroes.reservas[:15]]
        extras = len(heroes.reservas) - 15
        if extras > 0:
            visiveis.append(f"… e mais {extras} na reserva")
        embed.add_field(name="🪑 RESERVA", value="\n".join(visiveis), inline=False)

    embed.set_footer(text=RODAPE)
    return embed


# ----------------------------------------------------------------------
# Botões
# ----------------------------------------------------------------------

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
        if self.heroes_id in ativas:
            return  # heroes viva: a view real responde este clique
        await interaction.response.send_message(
            "Este alistamento não está mais ativo.", ephemeral=True
        )


class AlistamentoView(View):
    """Botões da mensagem de alistamento. custom_ids únicos por heroes para
    poderem ser re-registrados depois de um restart do bot."""

    def __init__(self, heroes_id: str):
        super().__init__(timeout=None)
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

        # O botão RESERVA só existe nos modos com lista de espera (andares)
        heroes = ativas.get(heroes_id)
        if heroes is not None and heroes.tem_reserva:
            reserva = Button(
                label="RESERVA 🪑",
                style=discord.ButtonStyle.secondary,
                custom_id=f"heroes:{heroes_id}:reserva",
            )
            reserva.callback = self.reserva_callback
            self.add_item(reserva)

        self.add_item(finalizar)

    def _heroes(self):
        return ativas.get(self.heroes_id)

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
            await interaction.response.edit_message(embed=render_embed(heroes), view=self)
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

        sucesso, mensagem, promovido = heroes.remover(interaction.user.id)
        if sucesso:
            heroes.salvar()
            await interaction.response.edit_message(embed=render_embed(heroes), view=self)
            await interaction.followup.send(mensagem, ephemeral=True)
            if promovido:
                try:
                    await interaction.channel.send(
                        f"📢 <@{promovido.user_id}> subiu da reserva para a party "
                        f"como **{promovido.classe}**!",
                        delete_after=300,
                    )
                except discord.HTTPException:
                    pass
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)

    async def reserva_callback(self, interaction: discord.Interaction):
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
        sucesso, mensagem = heroes.adicionar_reserva(
            interaction.user.id, interaction.user.display_name, cargos, config.ROLE_IDS
        )
        if sucesso:
            heroes.salvar()
            await interaction.response.edit_message(embed=render_embed(heroes), view=self)
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
        ok = await finalizar_heroes(heroes, finalizada_por=interaction.user.display_name)
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

    def __init__(self, heroes_id: str):
        super().__init__(timeout=None)
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
        heroes = ativas.get(self.heroes_id)
        if not heroes:
            await interaction.response.send_message("Essa heroes já foi finalizada. 👍")
            return
        await interaction.response.defer()
        ok = await finalizar_heroes(heroes, finalizada_por=interaction.user.display_name)
        if ok:
            await interaction.followup.send("✅ Heroes finalizada e registrada nos logs!")
        else:
            await interaction.followup.send("Essa heroes já estava sendo finalizada. 👍")

    async def depois_callback(self, interaction: discord.Interaction):
        heroes = ativas.get(self.heroes_id)
        if not heroes:
            await interaction.response.send_message("Essa heroes já foi finalizada. 👍")
            return
        limite = int((heroes.inicio + AUTO_FINALIZAR_APOS).timestamp())
        await interaction.response.send_message(
            f"Ok! Se ninguém finalizar até <t:{limite}:f>, eu mesmo finalizo e limpo o canal. 🧹"
        )


# ----------------------------------------------------------------------
# Criação (usada por /alistamento e /andares)
# ----------------------------------------------------------------------

async def criar_alistamento(
    interaction: discord.Interaction,
    titulo: str,
    dia: str,
    hora: str,
    mastery: str,
    modo: str,
):
    """Fluxo comum de criação: permissão, 1 alistamento por pessoa por modo,
    validações, JSON e mensagem com botões."""
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

    # 1 alistamento aberto por pessoa POR MODO (dá para ter 1 heroes e
    # 1 andares ao mesmo tempo; são atividades independentes)
    for aberta in ativas.values():
        if aberta.criador_id == interaction.user.id and aberta.modo == modo:
            link = (
                f"https://discord.com/channels/{interaction.guild_id}"
                f"/{aberta.channel_id}/{aberta.message_id}"
            )
            await interaction.response.send_message(
                f"❌ Você já tem um alistamento aberto: **{aberta.boss} - "
                f"{aberta.dia} {aberta.hora}**.\n"
                f"Finalize-o antes de abrir outro: {link}",
                ephemeral=True,
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
        boss=titulo,
        modo=modo,
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
    ativas[heroes.id] = heroes
    heroes.salvar()

    view = AlistamentoView(heroes.id)
    _registrar_view(heroes.id, view)
    try:
        resposta = await interaction.response.send_message(embed=render_embed(heroes), view=view)
    except discord.HTTPException:
        # A mensagem não foi publicada: desfaz o rastreio para não deixar
        # uma heroes fantasma sem mensagem mandando lembretes no canal
        ativas.pop(heroes.id, None)
        heroes.apagar_json()
        _parar_views(heroes.id)
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


# ----------------------------------------------------------------------
# Movimentação na call (usada pelo /puxar e pela puxada automática)
# ----------------------------------------------------------------------

async def mover_membros(origem, destino, motivo: str, permitidos: set = None):
    """Move membros de um canal de voz para outro; devolve (movidos, falhas,
    deixados). Com `permitidos`, move só esses user_ids e conta em `deixados`
    quem ficou por não estar na lista. Ignora bots e quem já saiu do canal.
    Usado pela puxada automática (cogs/relogio.py) e pelo /puxar (cogs/puxar.py)."""
    movidos, falhas, deixados = 0, 0, 0
    for membro in list(origem.members):
        if membro.bot:
            continue
        if permitidos is not None and membro.id not in permitidos:
            deixados += 1
            continue  # não inscrito: fica na fila
        if membro.voice is None or membro.voice.channel != origem:
            continue  # saiu da fila enquanto movíamos os outros
        try:
            await membro.move_to(destino, reason=motivo)
            movidos += 1
        except discord.HTTPException:
            falhas += 1
    return movidos, falhas, deixados


async def puxar_fila_automatico(heroes: Heroes):
    """No horário da heroes: UMA única tentativa. Se o shot caller não
    estiver num canal de heroes nesse momento, ninguém é puxado (ele usa
    /puxar); quem não estiver na fila nesse momento fica de fora."""
    canal_texto = await _canal(heroes.channel_id)
    if canal_texto is None or canal_texto.guild is None:
        return  # sem acesso ao servidor NESTE tick; a janela dá nova chance

    # A tentativa é única: aconteça o que acontecer daqui para baixo,
    # não repete (marca antes de mover; padrão da casa)
    heroes.puxada_automatica_feita = True
    heroes.salvar()

    if not config.CANAL_FILA_ID:
        return

    guild = canal_texto.guild
    fila = guild.get_channel(config.CANAL_FILA_ID)
    if not isinstance(fila, (discord.VoiceChannel, discord.StageChannel)):
        print(f"[HEROES] CANAL_FILA {config.CANAL_FILA_ID} não é canal de voz; puxada automática desativada")
        return

    criador = guild.get_member(heroes.criador_id)
    if criador is None:
        try:
            criador = await guild.fetch_member(heroes.criador_id)
        except discord.HTTPException:
            criador = None
    voz = criador.voice.channel if (criador and criador.voice) else None
    if voz is None or voz.id == fila.id:
        return  # shot caller fora de call de heroes: /puxar manual resolve
    if config.CANAIS_HEROES and voz.id not in config.CANAIS_HEROES:
        return  # está numa call que não é de heroes; não puxa ninguém

    if not fila.members:
        return
    # Só os inscritos DESTA heroes (+ o shot caller) são puxados
    inscritos = {p.user_id for p in heroes.participantes} | {heroes.criador_id}
    movidos, falhas, deixados = await mover_membros(
        fila, voz, f"Início da heroes {heroes.boss}", permitidos=inscritos
    )
    if movidos or falhas or deixados:
        aviso = f"🎺 Puxei **{movidos}** pessoa(s) da fila {fila.mention} para {voz.mention}!"
        if deixados:
            aviso += f" ({deixados} ficaram por não estarem inscritas)"
        if falhas:
            aviso += f" ({falhas} não puderam ser movidas)"
        try:
            await canal_texto.send(aviso, delete_after=300)
        except discord.HTTPException:
            pass


# ----------------------------------------------------------------------
# Lembretes e aviso ao criador (disparados pelo cogs/relogio.py)
# ----------------------------------------------------------------------

async def enviar_lembrete(heroes: Heroes, minutos: int):
    # Marca antes de enviar para nunca spammar em caso de erro repetido
    heroes.marcar_lembrete(minutos)
    heroes.salvar()

    canal = await _canal(heroes.channel_id)
    if canal is None:
        print(f"[HEROES] Canal {heroes.channel_id} indisponível; lembrete da heroes {heroes.id} descartado")
        return
    # Minutos REAIS restantes (a heroes pode ter sido criada dentro da janela)
    restam = max(1, round((heroes.inicio - datetime.now(config.TIMEZONE)).total_seconds() / 60))
    mencoes = " ".join(
        [f"<@{heroes.criador_id}>"] + [f"<@{p.user_id}>" for p in heroes.participantes]
    )
    # Andares não usa a fila: o lembrete é só o "vai começar"
    if heroes.tem_puxada:
        fila = f" <#{config.CANAL_FILA_ID}>" if config.CANAL_FILA_ID else " de fila"
        chamada = f"Entrem no canal{fila}!"
    else:
        chamada = "Preparem-se!"
    # O lembrete se auto-apaga quando o próximo evento chega (o lembrete
    # seguinte ou o início da heroes), para não acumular sujeira no chat
    menores = [m for m in LEMBRETE_ANTECEDENCIAS_MIN if m < minutos]
    vida = max(60, (restam - (max(menores) if menores else 0)) * 60)
    mensagem = await canal.send(
        f"{mencoes}\n⏰ O Evento **{heroes.boss}** começa em **{restam} minutos**! "
        f"{chamada}",
        delete_after=vida,
    )
    # Registra a mensagem: o delete_after morre se o bot reiniciar, e aí
    # é o relógio quem apaga as vencidas (via apagar_lembretes)
    heroes.lembretes_mensagens.append({
        "message_id": mensagem.id,
        "channel_id": canal.id,
        "apagar_em": (datetime.now(config.TIMEZONE) + timedelta(seconds=vida)).isoformat(),
    })
    heroes.salvar()


async def apagar_lembretes(heroes: Heroes, apenas_vencidos_em: datetime = None):
    """Apaga as mensagens de lembrete registradas. Com `apenas_vencidos_em`,
    só as que passaram do prazo (caso o delete_after tenha morrido num
    restart); sem, apaga todas (finalização/cancelamento)."""
    restantes = []
    for registro in heroes.lembretes_mensagens:
        if apenas_vencidos_em is not None:
            if datetime.fromisoformat(registro["apagar_em"]) > apenas_vencidos_em:
                restantes.append(registro)
                continue
        canal = await _canal(registro["channel_id"])
        if canal:
            try:
                await canal.get_partial_message(registro["message_id"]).delete()
            except discord.HTTPException:
                pass  # já se auto-apagou (caminho normal do delete_after)
    if len(restantes) != len(heroes.lembretes_mensagens):
        heroes.lembretes_mensagens = restantes
        if heroes.id in ativas:
            heroes.salvar()


async def avisar_criador(heroes: Heroes):
    heroes.aviso_criador_enviado = True
    heroes.salvar()

    inicio_ts = int(heroes.inicio.timestamp())
    limite = int((heroes.inicio + AUTO_FINALIZAR_APOS).timestamp())
    try:
        criador = _bot.get_user(heroes.criador_id) or await _bot.fetch_user(
            heroes.criador_id
        )
        view = FinalizarDMView(heroes.id)
        mensagem = await criador.send(
            f"👋 A sua heroes **{heroes.boss}** ({heroes.dia} {heroes.hora}) começou "
            f"<t:{inicio_ts}:R>. Posso finalizar?\n"
            f"Se ninguém finalizar até <t:{limite}:f>, eu finalizo sozinho.",
            view=view,
        )
        _registrar_view(heroes.id, view)
        heroes.dm_message_id = mensagem.id
        heroes.salvar()
    except discord.HTTPException as e:
        # DM fechada ou usuário inacessível: a auto-finalização resolve depois
        print(f"[HEROES] Não consegui mandar DM para o criador da heroes {heroes.id}: {e}")


# ----------------------------------------------------------------------
# Finalização e cancelamento
# ----------------------------------------------------------------------

async def finalizar_heroes(heroes: Heroes, finalizada_por: str) -> bool:
    """Registra no histórico, manda o resumo para os logs, apaga a mensagem
    e o JSON. Retorna False se já estava sendo finalizada."""
    if heroes.id in _finalizando or heroes.id not in ativas:
        return False
    _finalizando.add(heroes.id)
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
            modo=heroes.modo,
        )

        # 2. Encerra o estado vivo ANTES do I/O com o Discord: se o bot cair
        #    no meio dos passos seguintes, a heroes não "revive" no restart
        #    nem é finalizada duas vezes
        heroes.apagar_json()
        ativas.pop(heroes.id, None)
        _parar_views(heroes.id)

        # 3. Resumo no canal de logs
        logs = await _canal(config.CANAL_LOGS_ALISTAMENTO_ID)
        if logs is None:
            print(f"[HEROES] Canal de logs {config.CANAL_LOGS_ALISTAMENTO_ID} indisponível; resumo da heroes {heroes.id} não enviado")
        else:
            try:
                await logs.send(embed=render_embed(heroes, finalizado=True))
            except discord.HTTPException as e:
                print(f"[HEROES] Falha ao enviar log da heroes {heroes.id}: {e}")

        # 4. Apaga a mensagem do canal (o canal fica limpo; o dado já está salvo)
        canal = await _canal(heroes.channel_id)
        if canal and heroes.message_id:
            try:
                await canal.get_partial_message(heroes.message_id).delete()
            except discord.HTTPException:
                pass  # mensagem já apagada manualmente

        # Lembretes que ainda estejam no chat somem junto
        await apagar_lembretes(heroes)

        # 5. Remove os botões da DM do criador (se ela existiu), para não
        #    deixar uma DM antiga com botões clicáveis apontando pro nada
        if heroes.dm_message_id:
            try:
                criador = _bot.get_user(heroes.criador_id) or await _bot.fetch_user(heroes.criador_id)
                dm = criador.dm_channel or await criador.create_dm()
                await dm.get_partial_message(heroes.dm_message_id).edit(view=None)
            except discord.HTTPException:
                pass
        return True
    finally:
        _finalizando.discard(heroes.id)


async def cancelar_por_mensagem(message_id: int):
    """Staff apagou a mensagem do alistamento na mão = raid cancelada.
    Some sem escrever no histórico (cancelada não conta no ranking)."""
    for heroes in list(ativas.values()):
        if heroes.message_id == message_id:
            heroes.apagar_json()
            ativas.pop(heroes.id, None)
            _parar_views(heroes.id)
            await apagar_lembretes(heroes)
            print(f"[HEROES] Heroes {heroes.id} ({heroes.boss}) cancelada: mensagem apagada manualmente")
            break
