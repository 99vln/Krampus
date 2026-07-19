# cogs/puxar.py
# Comando /puxar: o caller puxa os inscritos do SEU alistamento de heroes
# do canal de fila para a call de heroes onde ele está.
#
# Este arquivo tem SÓ o comando. O estado (alistamentos ativos) e a lógica
# de mover membros vivem em motor_alistamento.py, importado diretamente.
# Vantagem: um erro em outro cog não afeta o /puxar.

import discord
from discord import app_commands
from discord.ext import commands

import config
import motor_alistamento as motor


class Puxar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="puxar",
        description="Caller: puxa os inscritos do seu alistamento da fila para a sua call",
    )
    @app_commands.guild_only()
    @app_commands.describe(fila="Canal de voz de origem (padrão: o canal de fila configurado)")
    async def puxar(
        self,
        interaction: discord.Interaction,
        fila: discord.VoiceChannel | discord.StageChannel | None = None,
    ):
        # Mesmos cargos que podem criar alistamentos (staff + callers extras)
        cargos = [role.id for role in interaction.user.roles]
        pode = (
            any(role_id in config.CARGOS_ALISTAMENTO for role_id in cargos)
            or interaction.user.guild_permissions.administrator
        )
        if not pode:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando!", ephemeral=True
            )
            return

        # O /puxar é do caller: exige um alistamento de HEROES ativo seu, e é a
        # lista de inscritos dele que define quem sai da fila (andares não usa)
        minha_heroes = None
        for aberta in motor.ativas.values():
            if aberta.criador_id == interaction.user.id and aberta.tem_puxada:
                minha_heroes = aberta
                break
        if minha_heroes is None:
            await interaction.response.send_message(
                "❌ O /puxar é para o caller de heroes: você precisa ter um "
                "alistamento de heroes ativo para puxar os inscritos dele.",
                ephemeral=True,
            )
            return

        # O destino é o canal de voz onde QUEM CHAMOU está (a call da heroes)
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await interaction.response.send_message(
                "❌ Entre primeiro no canal de voz da heroes: o destino é onde você está.",
                ephemeral=True,
            )
            return
        destino = interaction.user.voice.channel
        if config.CANAIS_HEROES and destino.id not in config.CANAIS_HEROES:
            canais = ", ".join(f"<#{c}>" for c in config.CANAIS_HEROES)
            await interaction.response.send_message(
                f"❌ Você precisa estar em um dos canais de heroes para puxar a fila: {canais}",
                ephemeral=True,
            )
            return

        origem = fila
        if origem is None and config.CANAL_FILA_ID:
            canal_cfg = interaction.guild.get_channel(config.CANAL_FILA_ID)
            if isinstance(canal_cfg, (discord.VoiceChannel, discord.StageChannel)):
                origem = canal_cfg
        if origem is None:
            await interaction.response.send_message(
                "❌ Nenhum canal de fila configurado. Informe no parâmetro `fila` "
                "ou configure CANAL_FILA no .env.",
                ephemeral=True,
            )
            return
        if origem.id == destino.id:
            await interaction.response.send_message(
                "❌ A fila e o destino são o mesmo canal.", ephemeral=True
            )
            return

        # Só os inscritos DA SUA heroes (+ você) saem da fila
        permitidos = {p.user_id for p in minha_heroes.participantes} | {minha_heroes.criador_id}

        # Mover várias pessoas leva mais de 3s; defer segura a interação aberta
        await interaction.response.defer(ephemeral=True)
        movidos, falhas, deixados = await motor.mover_membros(
            origem, destino, f"/puxar por {interaction.user.display_name}", permitidos=permitidos
        )

        if movidos == 0 and falhas == 0:
            if deixados:
                await interaction.followup.send(
                    f"Ninguém foi puxado: **{deixados}** pessoa(s) na fila, mas nenhuma "
                    f"inscrita na sua heroes **{minha_heroes.boss}**.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"O canal {origem.mention} está vazio, ninguém para puxar.", ephemeral=True
                )
            return
        resposta = f"✅ **{movidos}** pessoa(s) puxada(s) de {origem.mention} para {destino.mention}."
        if deixados:
            resposta += f"\n👥 **{deixados}** ficaram na fila por não estarem inscritas na sua heroes."
        if falhas:
            resposta += (
                f"\n⚠️ **{falhas}** não puderam ser movidas. Confira se tenho as permissões "
                f"**Mover Membros** e **Conectar** no canal de destino (quem é movido não "
                f"precisa poder conectar, mas EU preciso), ou se essas pessoas saíram da "
                f"call durante o comando."
            )
        if isinstance(destino, discord.StageChannel):
            resposta += (
                "\n⚠️ O destino é um canal **Stage**: quem chega entra como plateia (mudo) "
                "e precisa ser promovido para falar."
            )
        await interaction.followup.send(resposta, ephemeral=True)


async def setup(bot):
    motor.inicializar(bot)
    await bot.add_cog(Puxar(bot))
