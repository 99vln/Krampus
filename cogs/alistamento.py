# cogs/alistamento.py
# Comando /alistamento: alistamento no modo heroes (1 TANK / 2 HEALER / 6 DPS).
#
# Este arquivo tem SÓ o comando. Toda a lógica compartilhada (estado, embed,
# botões, finalização) vive em motor_alistamento.py, importado diretamente,
# do mesmo jeito que config.py e database.py são importados em todo lugar.
# Vantagem: um erro em outro cog não afeta o /alistamento, e vice-versa.

import discord
from discord import app_commands
from discord.ext import commands

import motor_alistamento as motor
from heroes import DIAS_SEMANA

# Opções para boss (pode adicionar mais depois)
BOSSES = [
    "GUILD BOSS 10 PLAYERS",
    # Adicione mais bosses aqui quando quiser:
    # "NOME DO BOSS",
]


class Alistamento(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
        if boss not in BOSSES:
            await interaction.response.send_message(
                f"❌ Boss inválido! Opções disponíveis: {', '.join(BOSSES)}", ephemeral=True
            )
            return
        await motor.criar_alistamento(interaction, boss, dia, hora, mastery, modo="heroes")

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
    motor.inicializar(bot)
    await bot.add_cog(Alistamento(bot))
