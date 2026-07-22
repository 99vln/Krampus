# cogs/freebies.py
# Avisa no canal de freebies quando sai código novo de Where Winds Meet.
#
# A cada 30 minutos o bot consulta o site (codigos_wwm.py), compara com o que
# já anunciou (tabela freebies_codigos) e posta SÓ o que é novo, mencionando
# o cargo escolhido no /set_freebies.
#
# Na PRIMEIRA vez que um servidor é configurado o bot apenas memoriza a lista
# que já está no ar, sem postar nada: senão o canal levaria uma enxurrada de
# quase 90 códigos velhos de uma vez.
#
# O que já foi anunciado mora no banco, então reiniciar o bot ou subir versão
# nova na Discloud não faz ele repetir aviso.
#
# Comandos (staff): /set_freebies, /clear_freebies e /codigos.

import asyncio
import traceback

import discord
from discord import app_commands
from discord.ext import commands, tasks

import codigos_wwm
import config
import database as db

# O site tem cooldown próprio para quem consulta demais; 30 minutos é educado
# e mesmo assim pega o código no mesmo dia em que ele sai
INTERVALO_MINUTOS = 30

COR_FREEBIES = discord.Color.from_rgb(88, 214, 141)

# A descrição de um embed aceita 4096 caracteres; paramos antes e avisamos
LIMITE_DESCRICAO = 3800


def _e_staff(interaction: discord.Interaction) -> bool:
    """Mesma regra dos outros comandos de configuração: staff ou admin."""
    cargos = [role.id for role in interaction.user.roles]
    return (
        any(role_id in config.CARGOS_STAFF for role_id in cargos)
        or interaction.user.guild_permissions.administrator
    )


def _codigos_de(entradas: list) -> list:
    """Só os códigos das entradas do site, ignorando o que vier sem 'code'."""
    return [e["code"] for e in entradas if e.get("code")]


def _formatar(entradas: list) -> str:
    """Lista os códigos em bloco, um por linha, cortando se ficar gigante."""
    linhas = []
    total = 0
    for i, codigo in enumerate(_codigos_de(entradas)):
        linha = f"`{codigo}`"
        if total + len(linha) > LIMITE_DESCRICAO:
            restantes = len(entradas) - i
            linhas.append(f"... e mais {restantes}")
            break
        linhas.append(linha)
        total += len(linha) + 1
    return "\n".join(linhas)


class Freebies(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.verificar_codigos.start()

    def cog_unload(self):
        self.verificar_codigos.cancel()

    # ------------------------------------------------------------------
    # Motor: buscar, comparar e anunciar
    # ------------------------------------------------------------------

    async def _buscar(self) -> list | None:
        """
        Consulta o site fora do event loop (a busca é bloqueante e ainda dorme
        entre as tentativas; no loop ela travaria o bot inteiro).
        None = site inacessível, que NÃO é a mesma coisa que "nenhum código".
        """
        return await asyncio.to_thread(codigos_wwm.buscar_codigos)

    async def _anunciar(self, canal_id: int, cargo_id: int | None, novos: list) -> bool:
        """
        Posta os códigos novos no canal configurado.
        Devolve True só se a mensagem foi realmente enviada: quem chama usa
        isso para decidir se pode marcar os códigos como anunciados. Se der
        errado, eles continuam "novos" e entram no próximo aviso.
        """
        canal = self.bot.get_channel(canal_id)
        if canal is None:
            try:
                canal = await self.bot.fetch_channel(canal_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"[FREEBIES] Canal {canal_id} inacessível ({e}); avisando ninguém desta vez")
                return False

        plural = "s" if len(novos) > 1 else ""
        embed = discord.Embed(
            title=f"🎁 Código{plural} novo{plural} de Where Winds Meet!",
            description=f"{_formatar(novos)}\n\nResgate no jogo antes de expirar.",
            color=COR_FREEBIES,
        )
        embed.set_footer(text="Fonte: codes.yar.gg")

        # everyone/users desligados de propósito: este aviso só menciona o
        # cargo escolhido no /set_freebies, nunca o servidor inteiro
        try:
            await canal.send(
                content=f"<@&{cargo_id}>" if cargo_id else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=True
                ),
            )
            return True
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"[FREEBIES] Não consegui postar em {canal_id}: {e}")
            return False

    async def _processar(self, entradas: list, apenas_guild: int = None) -> dict:
        """
        Compara a lista do site com o que cada servidor já viu e anuncia o
        resto. Devolve {guild_id: [entradas novas]} do que foi anunciado agora.
        """
        anunciados = {}
        for guild_id, canal_id, cargo_id in db.get_all_freebies_configs():
            if apenas_guild is not None and guild_id != apenas_guild:
                continue

            vistos = db.codigos_ja_vistos(guild_id)
            if not vistos:
                # Servidor recém-configurado (ou o site estava fora quando ele
                # foi configurado): memoriza calado em vez de despejar tudo
                db.marcar_codigos_vistos(guild_id, _codigos_de(entradas))
                print(f"[FREEBIES] Guild {guild_id}: lista inicial memorizada, nada postado")
                continue

            novos = [e for e in entradas if e.get("code") and e["code"] not in vistos]
            if not novos:
                continue

            if await self._anunciar(canal_id, cargo_id, novos):
                db.marcar_codigos_vistos(guild_id, _codigos_de(novos))
                anunciados[guild_id] = novos
        return anunciados

    @tasks.loop(minutes=INTERVALO_MINUTOS)
    async def verificar_codigos(self):
        try:
            entradas = await self._buscar()
            if not entradas:
                return  # site fora do ar: tentamos de novo no próximo ciclo
            await self._processar(entradas)
        except Exception:
            # Um erro aqui não pode matar o loop, senão o bot para de avisar
            # em silêncio até alguém reiniciar
            print(f"[FREEBIES] Erro na verificação automática:\n{traceback.format_exc()}")

    @verificar_codigos.before_loop
    async def antes_de_verificar(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    @app_commands.command(
        name="set_freebies",
        description="Staff: define o canal (e o cargo) dos avisos de código de Where Winds Meet",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        canal="Canal onde os códigos serão postados (padrão: este canal)",
        cargo="Cargo mencionado a cada código novo (deixe vazio para não marcar ninguém)",
    )
    async def set_freebies(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        cargo: discord.Role | None = None,
    ):
        if not _e_staff(interaction):
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando!", ephemeral=True
            )
            return

        destino = canal or interaction.channel
        permissoes = destino.permissions_for(interaction.guild.me)
        if not (permissoes.send_messages and permissoes.embed_links):
            await interaction.response.send_message(
                f"❌ Não consigo postar em {destino.mention}: preciso de "
                "**Enviar mensagens** e **Inserir links** nesse canal.",
                ephemeral=True,
            )
            return

        # A primeira configuração consulta o site, o que demora
        await interaction.response.defer(ephemeral=True)

        db.set_freebies_config(interaction.guild.id, destino.id, cargo.id if cargo else None)

        base = ""
        if not db.codigos_ja_vistos(interaction.guild.id):
            entradas = await self._buscar()
            if entradas:
                db.marcar_codigos_vistos(interaction.guild.id, _codigos_de(entradas))
                base = (
                    f"\nGuardei os **{len(entradas)}** códigos que já estão no ar sem postar "
                    "nada. Daqui pra frente só aviso o que for novo."
                )
            else:
                base = (
                    "\n⚠️ O site não respondeu agora; a primeira verificação automática "
                    "memoriza a lista atual sem postar tudo de uma vez."
                )

        if cargo:
            aviso_cargo = f" mencionando {cargo.mention}"
            if not cargo.mentionable and not interaction.guild.me.guild_permissions.mention_everyone:
                base += (
                    f"\n⚠️ O cargo {cargo.mention} não é mencionável e eu não tenho a permissão "
                    "**Mencionar @everyone, @here e todos os cargos**, então o ping não vai sair. "
                    "Marque o cargo como mencionável ou me dê essa permissão."
                )
        else:
            aviso_cargo = " sem mencionar ninguém"

        await interaction.followup.send(
            f"✅ Avisos de freebies ligados em {destino.mention}{aviso_cargo}.\n"
            f"Verifico a cada {INTERVALO_MINUTOS} minutos.{base}",
            ephemeral=True,
        )

    @app_commands.command(
        name="clear_freebies",
        description="Staff: desliga os avisos de código de Where Winds Meet",
    )
    @app_commands.guild_only()
    async def clear_freebies(self, interaction: discord.Interaction):
        if not _e_staff(interaction):
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando!", ephemeral=True
            )
            return

        if db.remove_freebies_config(interaction.guild.id):
            await interaction.response.send_message(
                "✅ Parei de avisar sobre códigos novos. Os que já foram anunciados "
                "continuam salvos, então religar não repete nada.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "ℹ️ Não havia canal de freebies configurado.", ephemeral=True
            )

    @app_commands.command(
        name="codigos",
        description="Staff: verifica agora e mostra os códigos de Where Winds Meet ativos",
    )
    @app_commands.guild_only()
    async def codigos(self, interaction: discord.Interaction):
        if not _e_staff(interaction):
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando!", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        entradas = await self._buscar()
        if not entradas:
            await interaction.followup.send(
                "❌ Não consegui falar com o site dos códigos agora. Tente de novo em alguns minutos.",
                ephemeral=True,
            )
            return

        anunciados = await self._processar(entradas, apenas_guild=interaction.guild.id)
        novos = anunciados.get(interaction.guild.id, [])

        if novos:
            rodape = f"\n\n📣 **{len(novos)}** código(s) novo(s) postado(s) no canal de freebies agora."
        elif db.get_freebies_config(interaction.guild.id):
            rodape = "\n\nNenhum código novo desde o último aviso."
        else:
            rodape = "\n\n⚠️ Nenhum canal configurado: use `/set_freebies` para ligar os avisos."

        await interaction.followup.send(
            f"**{len(entradas)} códigos ativos agora:**\n{_formatar(entradas)}{rodape}",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Freebies(bot))
