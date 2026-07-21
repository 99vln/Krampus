import discord
from discord.ext import commands
from datetime import datetime
import asyncio
import io
from config import ROLE_IDS, CATEGORY_IDS, CARGOS_STAFF, BUILD_LEADER_IDS, CANAL_LOGS_TRANSCRIPTS_ID, EMOJIS_POR_CLASSE
import database as db
from views.ticket_view import TicketPersistentView

# Categoria -> classe (para descobrir a classe de um ticket já criado)
CLASSE_POR_CATEGORIA = {cat_id: classe for classe, cat_id in CATEGORY_IDS.items()}

# ====== COG PRINCIPAL DE TICKETS ======
class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.CANAL_LOGS_TRANSCRIPTS_ID = CANAL_LOGS_TRANSCRIPTS_ID
        self.CARGOS_STAFF = CARGOS_STAFF
        db.init_db()  # garante que as tabelas existam

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
        O nome do canal usa emoji correspondente + nickname sanitizado.
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

            # 3. Sanitizar nickname e montar nome do canal com emoji
            nome_sanitizado = ''.join(c if c.isalnum() or c == '-' else '-' for c in nick.lower())
            nome_sanitizado = nome_sanitizado.replace(' ', '-')
            nome_sanitizado = '-'.join(filter(None, nome_sanitizado.split('-')))
            emoji = EMOJIS_POR_CLASSE.get(classe_encontrada, "📁")
            nome_canal = f"{emoji}・{nome_sanitizado}"

            # Verificar duplicidade
            for canal_existente in guild.text_channels:
                if canal_existente.name == nome_canal and canal_existente.category_id == categoria_id:
                    print(f"⚠️ Canal já existe: {nome_canal}")
                    return None

            # 4. Permissões
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, attach_files=True
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True
                )
            }
            for cargo_id in self.CARGOS_STAFF:
                cargo = guild.get_role(cargo_id)
                if cargo:
                    overwrites[cargo] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True, manage_channels=True
                    )

            # Build Leader da classe do ticket enxerga e conversa (sem gerenciar)
            bl_role = guild.get_role(BUILD_LEADER_IDS.get(classe_encontrada, 0))
            if bl_role:
                overwrites[bl_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

            # 5. Criar canal
            channel = await categoria.create_text_channel(
                name=nome_canal,
                overwrites=overwrites,
                reason=f"Ticket para {user_name} (aprovado)"
            )

            # 6. Embed de boas-vindas
            embed = discord.Embed(
                title=f"🎫 Ticket de {nick}",
                description=f"Bem-vindo(a) {member.mention}! A staff está aqui para ajudar.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Usuário", value=member.mention, inline=False)
            embed.add_field(name="Nick In-Game", value=nick, inline=False)
            embed.add_field(name="Criado em", value=datetime.now().strftime("%d/%m/%Y às %H:%M:%S"), inline=False)
            embed.set_footer(text="Guilda Wanted © | Community Server")

            # 7. Enviar com view persistente e salvar no banco
            view = TicketPersistentView(self)
            welcome_msg = await channel.send(embed=embed, view=view)
            db.add_active_ticket(channel.id, user_id, welcome_msg.id, custom_id="ticket_fechar,ticket_arquivar")

            print(f"✅ Ticket criado: {channel.name} (categoria {categoria.name}) para {user_name}")
            return channel

        except discord.Forbidden:
            print("❌ Sem permissão para criar canal")
            return None
        except Exception as e:
            print(f"❌ Erro ao criar ticket: {e}")
            return None

    # ====== GARANTIR ACESSO DO BUILD LEADER ======
    async def garantir_acesso_build_leader(self, channel: discord.TextChannel):
        """Dá acesso ao Build Leader da classe em tickets criados antes desse cargo existir."""
        classe = CLASSE_POR_CATEGORIA.get(channel.category_id)
        if not classe:
            return
        bl_role = channel.guild.get_role(BUILD_LEADER_IDS.get(classe, 0))
        if not bl_role or channel.overwrites_for(bl_role).view_channel:
            return
        try:
            await channel.set_permissions(
                bl_role,
                view_channel=True, send_messages=True, read_message_history=True,
                reason="Build Leader da classe ganhou acesso aos tickets"
            )
            print(f"✅ Build Leader '{bl_role.name}' adicionado ao ticket {channel.name}")
        except discord.Forbidden:
            print(f"❌ Sem permissão para dar acesso de Build Leader em {channel.name}")

    # ====== FECHAR TICKET ======
    async def fechar_ticket(self, interaction: discord.Interaction):
        canal = interaction.channel
        # Verifica se é ticket (novo padrão com emoji ou antigo)
        if not (canal.name.startswith(("🔪", "🚑", "🔰", "📁")) and "・" in canal.name) and not canal.name.startswith("ticket-"):
            return await interaction.followup.send("❌ Não é um canal de ticket.", ephemeral=True)

        await interaction.followup.send(f"🔒 Ticket fechado por {interaction.user.mention}. O canal será deletado...")
        db.remove_active_ticket(canal.id)
        await asyncio.sleep(2)
        await canal.delete(reason=f"Ticket fechado por {interaction.user}")
        print(f"✅ Ticket deletado: {canal.name}")

    # ====== ARQUIVAR TICKET (TRANSCRIPT) ======
    async def arquivar_ticket(self, interaction: discord.Interaction):
        canal = interaction.channel
        if not (canal.name.startswith(("🔪", "🚑", "🔰", "📁")) and "・" in canal.name) and not canal.name.startswith("ticket-"):
            return await interaction.followup.send("❌ Não é um canal de ticket.", ephemeral=True)

        canal_logs = interaction.guild.get_channel(self.CANAL_LOGS_TRANSCRIPTS_ID)
        if not canal_logs:
            return await interaction.followup.send("❌ Canal de logs não configurado!", ephemeral=True)

        # Gerar transcript
        transcript = []
        transcript.append(f"{'='*60}\nTRANSCRIPT - {canal.name}\n{'='*60}")
        transcript.append(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        async for msg in canal.history(limit=None, oldest_first=True):
            timestamp = msg.created_at.strftime("%d/%m/%Y %H:%M:%S")
            author = msg.author.name
            content = msg.content or "[sem conteúdo]"
            if msg.embeds:
                content += " [EMBED]"
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

    # ====== LISTENER PARA RESTAURAR VIEWS APÓS REINÍCIO ======
    @commands.Cog.listener()
    async def on_ready(self):
        """Restaura as views dos tickets ativos após reinicialização."""
        # Executar apenas uma vez (on_ready dispara a cada reconexão)
        if getattr(self, "_views_restored", False):
            return
        self._views_restored = True

        tickets = db.get_all_active_tickets()
        print(f"[DEBUG] Tickets carregados do banco: {len(tickets)} -> {tickets}")
        for channel_id, user_id, welcome_msg_id, custom_id in tickets:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await self.garantir_acesso_build_leader(channel)
                try:
                    await channel.fetch_message(welcome_msg_id)  # verifica se a mensagem existe
                    view = TicketPersistentView(self)
                    self.bot.add_view(view, message_id=welcome_msg_id)
                    print(f"View persistente restaurada para ticket {channel.name}")
                except discord.NotFound:
                    db.remove_active_ticket(channel_id)
                    print(f"Mensagem de boas-vindas do ticket {channel.name} não encontrada, removido do banco.")
            else:
                db.remove_active_ticket(channel_id)
                print(f"Canal {channel_id} não existe mais, removido do banco.")

async def setup(bot):
    await bot.add_cog(TicketCog(bot))