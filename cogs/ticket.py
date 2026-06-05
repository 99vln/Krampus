import discord
from discord.ext import commands
from discord.ui import Button, View
from datetime import datetime
import asyncio
import io
from config import ROLE_IDS, CATEGORY_IDS, CARGOS_STAFF, CANAL_LOGS_TRANSCRIPTS_ID

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
        self.CANAL_LOGS_TRANSCRIPTS_ID = CANAL_LOGS_TRANSCRIPTS_ID
        self.CARGOS_STAFF = CARGOS_STAFF

    async def verificar_permissao_staff(self, interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator:
            return True
        for cargo_id in self.CARGOS_STAFF:
            cargo = interaction.guild.get_role(cargo_id)
            if cargo and cargo in interaction.user.roles:
                return True
        return False

    # ====== MÉTODO PRINCIPAL CRIAR TICKET ======
    async def criar_ticket(self, interaction: discord.Interaction, user_id: int, user_name: str, nick: str):
        """
        Cria um ticket após aprovação.
        A categoria é definida dinamicamente com base nos cargos do usuário (DPS/TANK/HEALER).
        """
        try:
            guild = interaction.guild
            member = guild.get_member(user_id)
            if not member:
                print(f"❌ Membro não encontrado: {user_id}")
                return None

            # 1. Descobrir a classe do usuário pelos cargos
            member_role_ids = [role.id for role in member.roles]
            classe_encontrada = None
            for role_name, role_id in ROLE_IDS.items():
                if role_id in member_role_ids:
                    classe_encontrada = role_name
                    break

            if not classe_encontrada:
                print(f"❌ Usuário {user_name} (ID {user_id}) não possui cargo DPS/TANK/HEALER. Ticket NÃO criado.")
                return None

            # 2. Obter ID da categoria correspondente
            categoria_id = CATEGORY_IDS.get(classe_encontrada)
            if not categoria_id:
                print(f"❌ Categoria não mapeada para a classe {classe_encontrada}")
                return None

            categoria = guild.get_channel(categoria_id)
            if not categoria or not isinstance(categoria, discord.CategoryChannel):
                print(f"❌ Categoria {categoria_id} não encontrada ou inválida")
                return None

            # 3. Criar o canal
            nome_canal = f"ticket-{user_name.lower().replace(' ', '-')[:20]}"
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            for cargo_id in self.CARGOS_STAFF:
                cargo = guild.get_role(cargo_id)
                if cargo:
                    overwrites[cargo] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )

            channel = await categoria.create_text_channel(
                nome_canal,
                overwrites=overwrites,
                reason=f"Ticket para {user_name} (aprovado)"
            )

            # 4. Embed de boas‑vindas
            embed = discord.Embed(
                title=f"🎫 Ticket de {nick}",
                description=f"Bem-vindo(a) {member.mention}! A staff está aqui para ajudar.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Usuário", value=member.mention, inline=False)
            embed.add_field(name="Nick In-Game", value=nick, inline=False)
            embed.add_field(name="Criado em", value=datetime.now().strftime("%d/%m/%Y às %H:%M:%S"), inline=False)
            embed.set_footer(text="Guilda Wanted © | Community Server")

            await channel.send(embed=embed, view=TicketView(self, user_id))

            print(f"✅ Ticket criado: {channel.name} (categoria {categoria.name}) para {user_name}")
            return channel

        except discord.Forbidden:
            print("❌ Sem permissão para criar canal")
            return None
        except Exception as e:
            print(f"❌ Erro ao criar ticket: {e}")
            return None

    # ====== FECHAR TICKET ======
    async def fechar_ticket(self, interaction: discord.Interaction):
        canal = interaction.channel
        if not canal.name.startswith("ticket-"):
            return await interaction.followup.send("❌ Não é um canal de ticket.", ephemeral=True)

        await interaction.followup.send(f"🔒 Ticket fechado por {interaction.user.mention}. O canal será deletado...")
        await asyncio.sleep(2)
        await canal.delete(reason=f"Ticket fechado por {interaction.user}")
        print(f"✅ Ticket deletado: {canal.name}")

    # ====== ARQUIVAR TICKET (TRANSCRIPT) ======
    async def arquivar_ticket(self, interaction: discord.Interaction):
        canal = interaction.channel
        if not canal.name.startswith("ticket-"):
            return await interaction.followup.send("❌ Não é um canal de ticket.", ephemeral=True)

        canal_logs = interaction.guild.get_channel(self.CANAL_LOGS_TRANSCRIPTS_ID)
        if not canal_logs:
            return await interaction.followup.send("❌ Canal de logs não configurado!", ephemeral=True)

        # Coletar mensagens
        transcript = []
        transcript.append(f"{'='*60}\nTRANSCRIPT - {canal.name}\n{'='*60}")
        transcript.append(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        async for msg in canal.history(limit=None, oldest_first=True):
            timestamp = msg.created_at.strftime("%d/%m/%Y %H:%M:%S")
            author = msg.author.name
            content = msg.content or "[sem conteúdo]"
            transcript.append(f"[{timestamp}] {author}: {content}")

        texto = "\n".join(transcript)
        arquivo = discord.File(io.StringIO(texto), filename=f"transcript-{canal.name}.txt")

        embed = discord.Embed(
            title="📦 Transcript arquivado",
            description=f"Ticket: {canal.name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Arquivado por", value=interaction.user.mention)
        embed.add_field(name="Data", value=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        await canal_logs.send(embed=embed, file=arquivo)

        await interaction.followup.send(f"✅ Ticket arquivado! Transcript enviado para {canal_logs.mention}")
        print(f"✅ Ticket arquivado: {canal.name}")


async def setup(bot):
    await bot.add_cog(TicketCog(bot))