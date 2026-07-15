# cogs/andares.py
# Comando /andares: alistamento no modo andares (1 TANK / 2 HEALER / 7 DPS,
# com botão RESERVA). Andares não usa fila nem puxada: só organização.
#
# Este arquivo tem SÓ o comando. Toda a lógica compartilhada (estado, embed,
# botões, reserva, finalização) vive em motor_alistamento.py, importado
# diretamente. Vantagem: um erro em outro cog não afeta o /andares.

import discord
from discord import app_commands
from discord.ext import commands

import motor_alistamento as motor
from heroes import DIAS_SEMANA


class Andares(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="andares",
        description="Cria um alistamento para andares (1 TANK, 2 HEALER, 7 DPS)"
    )
    @app_commands.guild_only()
    @app_commands.describe(
        andar="Quais andares (ex: 80, 90-100)",
        dia="Dia da Semana",
        hora="Formato 00:00",
        mastery="Mastery requerida"
    )
    async def andares(
        self,
        interaction: discord.Interaction,
        andar: str,
        dia: str,
        hora: str,
        mastery: str
    ):
        """Cria um alistamento de andares com a party 1 TANK / 2 HEALER / 7 DPS"""
        andar = andar.strip()
        if not andar or len(andar) > 40:
            await interaction.response.send_message(
                "❌ Informe quais andares (ex: **80** ou **90-100**)!", ephemeral=True
            )
            return
        await alistamentos.criar_alistamento(
            interaction, f"ANDARES {andar.upper()}", dia, hora, mastery, modo="andares"
        )

    @andares.autocomplete("dia")
    async def dia_autocomplete(
        self, _interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=dia, value=dia)
            for dia in DIAS_SEMANA
            if current.lower() in dia.lower()
        ][:25]

    @andares.autocomplete("hora")
    async def hora_autocomplete(
        self, _interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Sugere horários comuns (de hora em hora e meias horas)."""
        sugestoes = [
            f"{h:02d}:{m:02d}"
            for h in range(0, 24)
            for m in (0, 30)
        ]
        return [
            app_commands.Choice(name=h, value=h)
            for h in sugestoes
            if current in h
        ][:25]

    @andares.autocomplete("mastery")
    async def mastery_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Sugere valores comuns de mastery."""
        sugestoes = ["100", "150", "200", "250", "300", "350", "400", "450", "500"]
        return [
            app_commands.Choice(name=m, value=m)
            for m in sugestoes
            if current in m
        ][:25]


async def setup(bot):
    motor.inicializar(bot)
    await bot.add_cog(Andares(bot))