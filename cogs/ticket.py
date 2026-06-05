import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
from datetime import datetime
import asyncio
import io

# ====== VIEW COM BOTÕES DO TICKET ======
class TicketView(View):
    def __init__(self, cog, user_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id

        fechar_btn = Button(
            style=discord.ButtonStyle.danger,
            label="❌ Fechar",
            custom_id=f"ticket_fechar_{user_id}",
            emoji="🔒"
        )
        fechar_btn.callback = self.fechar_callback
        self.add_item(fechar_btn)

        arquivar_btn = Button(
            style=discord.ButtonStyle.secondary,
            label="📦 Arquivar",
            custom_id=f"ticket_arquivar_{user_id}",
            emoji="📋"
        )
        arquivar_btn.callback = self.arquivar_callback
        self.add_item(arquivar_btn)

    async def fechar_callback(self, interaction: discord.Interaction):
        if not await self.cog.verificar_permissao_staff(interaction):
            return await interaction.response.send_message(
                "❌ Apenas staff pode fechar tickets!",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        await self.cog.fechar_ticket(interaction)

    async def arquivar_callback(self, interaction: discord.Interaction):
        if not await self.cog.verificar_permissao_staff(interaction):
            return await interaction.response.send_message(
                "❌ Apenas staff pode arquivar tickets!",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        await self.cog.arquivar_ticket(interaction)

# ====== COG PRINCIPAL DE TICKETS ======
class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # IDs de configuração
        self.CATEGORIA_TICKETS_ID = 1460288050566398075
        self.CANAL_LOGS_TRANSCRIPTS_ID = 1470070755604697212

        # IDs dos cargos de staff (mesmo do formulario.py)
        self.CARGOS_STAFF = [
            1449931317675429960,  # Dev
            1442625294078050456,  # Staff
        ]

    # ====== VERIFICAR PERMISSÃO STAFF ======
    async def verificar_permissao_staff(self, interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator:
            return True

        for cargo_id in self.CARGOS_STAFF:
            cargo = interaction.guild.get_role(cargo_id)
            if cargo and cargo in interaction.user.roles:
                return True

        return False

    # ====== CRIAR TICKET ======
    async def criar_ticket(self, interaction: discord.Interaction, user_id: int, user_name: str, nick: str):
        """Cria um novo ticket após aprovação do formulário"""
        try:
            guild = interaction.guild
            member = guild.get_member(user_id)

            if not member:
                print(f"❌ Membro não encontrado para criar ticket: {user_id}")
                return None

            # Obter a categoria
            categoria = guild.get_channel(self.CATEGORIA_TICKETS_ID)
            if not categoria or not isinstance(categoria, discord.CategoryChannel):
                print(f"❌ Categoria de tickets não encontrada ou inválida: {self.CATEGORIA_TICKETS_ID}")
                return None

            # Nome do canal: ticket-{user.name}
            nome_canal = f"ticket-{user_name.lower().replace(' ', '-')[:20]}"

            # Criar permissões
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }

            # Adicionar permissões para staff
            for cargo_id in self.CARGOS_STAFF:
                cargo = guild.get_role(cargo_id)
                if cargo:
                    overwrites[cargo] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

            # Criar o canal
            channel = await categoria.create_text_channel(
                nome_canal,
                overwrites=overwrites,
                reason=f"Ticket criado para {user_name} após aprovação de formulário"
            )

            # Criar embed inicial
            embed = discord.Embed(
                title=f"🎫 Ticket de {nick}",
                description=f"Bem-vindo(a) ao seu ticket! A staff está aqui para ajudar.",
                color=0x5865f2
            )
            embed.add_field(name="Usuário", value=member.mention, inline=False)
            embed.add_field(name="Nick In-Game", value=nick, inline=False)
            embed.add_field(name="Criado em", value=datetime.now().strftime("%d/%m/%Y às %H:%M:%S"), inline=False)
            embed.set_footer(text="Guilda Wanted © | Community Server")

            # Enviar mensagem inicial com botões
            await channel.send(embed=embed, view=TicketView(self, user_id))

            print(f"✅ Ticket criado com sucesso: {channel.name} (ID: {channel.id}) para {user_name}")
            return channel

        except discord.Forbidden:
            print(f"❌ Sem permissão para criar canal de ticket")
            return None
        except Exception as e:
            print(f"❌ Erro ao criar ticket: {e}")
            return None

    # ====== FECHAR TICKET ======
    async def fechar_ticket(self, interaction: discord.Interaction):
        """Fecha (deleta) um ticket"""
        try:
            canal = interaction.channel

            # Confirmar que é um canal de ticket
            if not canal.name.startswith("ticket-"):
                return await interaction.followup.send(
                    "❌ Este não é um canal de ticket!",
                    ephemeral=True
                )

            # Mensagem de confirmação
            await interaction.followup.send(
                f"🔒 Ticket fechado por {interaction.user.mention}. O canal será deletado em breve...",
                ephemeral=False
            )

            # Aguardar um pouco e deletar
            await asyncio.sleep(2)
            await canal.delete(reason=f"Ticket fechado por {interaction.user}")

            print(f"✅ Ticket deletado: {canal.name}")

        except Exception as e:
            print(f"❌ Erro ao fechar ticket: {e}")
            await interaction.followup.send(
                "❌ Erro ao fechar o ticket!",
                ephemeral=True
            )

    # ====== ARQUIVAR TICKET (TRANSCRIPT) ======
    async def arquivar_ticket(self, interaction: discord.Interaction):
        """Arquiva um ticket gerando um transcript"""
        try:
            canal = interaction.channel

            # Confirmar que é um canal de ticket
            if not canal.name.startswith("ticket-"):
                return await interaction.followup.send(
                    "❌ Este não é um canal de ticket!",
                    ephemeral=True
                )

            # Obter o canal de logs
            canal_logs = interaction.guild.get_channel(self.CANAL_LOGS_TRANSCRIPTS_ID)
            if not canal_logs:
                return await interaction.followup.send(
                    "❌ Canal de logs não configurado!",
                    ephemeral=True
                )

            # Gerar transcript
            transcript_lines = []
            transcript_lines.append(f"{'='*60}")
            transcript_lines.append(f"TRANSCRIPT - {canal.name}")
            transcript_lines.append(f"{'='*60}")
            transcript_lines.append(f"Data: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}")
            transcript_lines.append(f"Arquivado por: {interaction.user.mention}")
            transcript_lines.append(f"{'='*60}\n")

            # Coletar mensagens
            async for message in canal.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime("%d/%m/%Y %H:%M:%S")
                author = message.author.name
                content = message.content if message.content else "[Sem conteúdo]"

                # Adicionar embeds se houver
                if message.embeds:
                    for embed in message.embeds:
                        content += f" [EMBED: {embed.title}]" if embed.title else " [EMBED]"

                transcript_lines.append(f"[{timestamp}] {author}: {content}")

            transcript_text = "\n".join(transcript_lines)

            # Enviar para o canal de logs
            embed_log = discord.Embed(
                title=f"📦 Transcript Arquivado",
                description=f"Ticket: `{canal.name}`",
                color=0x5865f2
            )
            embed_log.add_field(name="Arquivado por", value=interaction.user.mention, inline=False)
            embed_log.add_field(name="Data", value=datetime.now().strftime("%d/%m/%Y às %H:%M:%S"), inline=False)
            embed_log.set_footer(text="Guilda Wanted © | Community Server")

            # Criar arquivo com o transcript
            transcript_file = discord.File(
                io.StringIO(transcript_text),
                filename=f"transcript-{canal.name}-{datetime.now().strftime('%d%m%Y_%H%M%S')}.txt"
            )

            await canal_logs.send(embed=embed_log, file=transcript_file)

            # Responder ao usuário
            await interaction.followup.send(
                f"✅ Ticket arquivado com sucesso! Transcript enviado para {canal_logs.mention}",
                ephemeral=False
            )

            print(f"✅ Ticket arquivado: {canal.name}")

        except Exception as e:
            print(f"❌ Erro ao arquivar ticket: {e}")
            await interaction.followup.send(
                "❌ Erro ao arquivar o ticket!",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(TicketCog(bot))
