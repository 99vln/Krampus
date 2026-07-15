import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View, Button, TextInput, Modal
from datetime import datetime
import database as db
from views.formulario_view import FormularioPersistentView

# ====== MODAL PARA MOTIVO DA RECUSA ======
class MotivoRecusaModal(Modal, title="Motivo da Recusa"):
    motivo = TextInput(
        label="Motivo da recusa",
        placeholder="Explique o motivo da recusa...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    def __init__(self, cog, user_id, user_name, nick, classe, recrutador):
        super().__init__()
        self.cog = cog
        self.user_id = user_id
        self.user_name = user_name
        self.nick = nick
        self.classe = classe
        self.recrutador = recrutador
        self.timeout = 300

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.processar_recusa(
            interaction,
            self.user_id,
            self.user_name,
            self.nick,
            self.classe,
            self.recrutador,
            self.motivo.value
        )

# ====== VIEW COM BOTÕES DE APROVAÇÃO ======
class AprovacaoView(View):
    def __init__(self, cog, user_id, user_name, nick, classe, recrutador):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id
        self.user_name = user_name
        self.nick = nick
        self.classe = classe
        self.recrutador = recrutador

        aprovar_btn = Button(
            style=discord.ButtonStyle.success,
            label="✅ Aprovar",
            custom_id=f"aprovar_{user_id}_{datetime.now().timestamp()}"
        )
        aprovar_btn.callback = self.aprovar_callback
        self.add_item(aprovar_btn)

        recusar_btn = Button(
            style=discord.ButtonStyle.danger,
            label="❌ Recusar",
            custom_id=f"recusar_{user_id}_{datetime.now().timestamp()}"
        )
        recusar_btn.callback = self.recusar_callback
        self.add_item(recusar_btn)

    async def aprovar_callback(self, interaction: discord.Interaction):
        if not await self.cog.verificar_permissao_aprovacao(interaction):
            return await interaction.response.send_message(
                "❌ Você não tem permissão para aprovar formulários!",
                ephemeral=True
            )
        await self.cog.processar_aprovacao(
            interaction,
            self.user_id,
            self.user_name,
            self.nick,
            self.classe,
            self.recrutador
        )

    async def recusar_callback(self, interaction: discord.Interaction):
        if not await self.cog.verificar_permissao_aprovacao(interaction):
            return await interaction.response.send_message(
                "❌ Você não tem permissão para recusar formulários!",
                ephemeral=True
            )
        modal = MotivoRecusaModal(
            self.cog,
            self.user_id,
            self.user_name,
            self.nick,
            self.classe,
            self.recrutador
        )
        await interaction.response.send_modal(modal)

# ====== MODAL PARA FORMULÁRIO ======
class FormularioModal(Modal, title="Formulário de Recrutamento"):
    nick_ingame = TextInput(
        label="Nick In-Game",
        placeholder="Escreva o nome usado dentro do jogo!",
        style=discord.TextStyle.short,
        required=True,
        max_length=30
    )
    classe = TextInput(
        label="Sua Classe",
        placeholder="Exemplo: DPS, TANK, HEALER (ou apenas as 3 primeiras letras)",
        style=discord.TextStyle.short,
        required=True,
        max_length=20
    )
    recrutador = TextInput(
        label="Recrutador(a)",
        placeholder="Nome do responsável pelo seu recrutamento",
        style=discord.TextStyle.short,
        required=True,
        max_length=30
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        self.timeout = 300

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.mostrar_dropdown_regras(interaction, self)

# ====== VIEW COM DROPDOWN DE REGRAS ======
class RegrasView(View):
    def __init__(self, cog, nick, classe, recrutador):
        super().__init__(timeout=300)
        self.cog = cog
        self.nick = nick
        self.classe = classe
        self.recrutador = recrutador

        select_regras = Select(
            placeholder="Selecione sua resposta...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Eu compreendo!",
                    value="EU_COMPREENDO",
                    description="Confirmo que compreendo todas as regras",
                )
            ]
        )
        select_regras.callback = self.regras_callback
        self.add_item(select_regras)

    async def regras_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.enviar_formulario_aprovacao(
            interaction,
            self.nick,
            self.classe,
            self.recrutador
        )

# ====== COG PRINCIPAL ======
class FormularioCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.formulario_channel = None
        self.resultados_channel = None

        self.CARGOS_POR_CLASSE = {
            "DPS": 1440390981307465949,
            "TANK": 1440391288615735380,
            "HEALER": 1440391235268378654,
        }
        self.CARGO_FIXO_ID = 1440392071910264853 # Wanted
        self.CARGO_A_REMOVER_ID = 779618880028803083 # .gg/wantedd
        self.CARGOS_PERMITIDOS = [
            1449931317675429960,  # Dev
            1442625294078050456,   # Staff
        ]
        self.CARGOS_APROVACAO = [
            1449931317675429960,  # Dev
            1442625294078050456,   # Staff
            1452881617726083256,  # Recrutador
        ]

        # Inicializa o banco de dados (se ainda não existir)
        db.init_db()

    # ====== COMANDO PARA CONFIGURAR FORMULÁRIO ======
    @app_commands.command(
        name="formulario",
        description="Configura os canais do formulário de recrutamento"
    )
    @app_commands.describe(
        canal_formulario="Canal onde o formulário será enviado",
        canal_resultados="Canal onde os resultados serão enviados"
    )
    async def config_formulario(self, interaction: discord.Interaction,
                             canal_formulario: discord.TextChannel,
                             canal_resultados: discord.TextChannel):

        if not await self.verificar_permissao_config(interaction):
            return await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando!",
                ephemeral=True
            )

        self.formulario_channel = canal_formulario
        self.resultados_channel = canal_resultados

        # Limpar mensagens antigas do bot neste canal (e remover do banco)
        try:
            async for message in canal_formulario.history(limit=10):
                if message.author == self.bot.user and message.embeds:
                    for embed in message.embeds:
                        if "Formulário de Recrutamento" in embed.title:
                            db.remove_persistent_formulario(message.id)
                            await message.delete()
                            break
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ Não tenho permissão para limpar o formulário anterior!",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📝 Formulário de Recrutamento 📝",
            description="Clique no botão abaixo para iniciar o formulário.",
            color=0xed4245
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Guilda Wanted © | Community Server")

        view = FormularioPersistentView(self)
        message = await canal_formulario.send(embed=embed, view=view)

        # Salvar a mensagem no banco para restaurar após reinício
        db.add_persistent_formulario(
            channel_id=canal_formulario.id,
            message_id=message.id,
            custom_id="iniciar_formulario",
            embed_title=embed.title,
            embed_description=embed.description,
            embed_color=embed.color.value,
            formulario_channel_id=canal_formulario.id,
            resultados_channel_id=canal_resultados.id
        )

        await interaction.response.send_message(
            f"✅ Formulário configurado com sucesso!\n"
            f"• Canal do formulário: {canal_formulario.mention}\n"
            f"• Canal de resultados: {canal_resultados.mention}",
            ephemeral=True
        )

    # ====== CALLBACK DO BOTÃO PERSISTENTE ======
    async def iniciar_formulario_callback(self, interaction: discord.Interaction):
        """Abre o modal do formulário quando o botão é clicado."""
        if not self.formulario_channel or not self.resultados_channel:
            return await interaction.response.send_message(
                "❌ O formulário não foi configurado corretamente.",
                ephemeral=True
            )
        await interaction.response.send_modal(FormularioModal(self))

    # ====== MOSTRAR DROPDOWN DE REGRAS ======
    async def mostrar_dropdown_regras(self, interaction: discord.Interaction, modal: FormularioModal):
        embed = discord.Embed(
            title="📋 Confirmação de Regras",
            description=(
                f"**Você compreende que o uso do Discord e a Contribuição Semanal com a Guilda são obrigatórios?**\n\n"
                f"**Seus dados:**\n"
                f"• **Nick In-Game:** {modal.nick_ingame.value}\n"
                f"• **Classe:** {modal.classe.value}\n"
                f"• **Recrutador:** {modal.recrutador.value}"
            ),
            color=0x5865f2
        )
        embed.set_footer(text="Guilda Wanted © | Community Server")

        await interaction.response.send_message(
            embed=embed,
            view=RegrasView(
                self,
                modal.nick_ingame.value,
                modal.classe.value,
                modal.recrutador.value
            ),
            ephemeral=True
        )

    # ====== ENVIAR FORMULÁRIO PARA APROVAÇÃO ======
    async def enviar_formulario_aprovacao(self, interaction: discord.Interaction, nick: str, classe: str, recrutador: str):
        embed = discord.Embed(
            title=f"📋 Formulário Pendente",
            description=f"**Usuário:** {interaction.user.mention} (`{interaction.user}`)",
            color=0xfee75c
        )
        embed.add_field(name="Nick In-Game", value=nick, inline=False)
        embed.add_field(name="Classe", value=classe, inline=False)
        embed.add_field(name="Recrutador(a)", value=recrutador, inline=False)
        embed.add_field(name="Regras Confirmadas", value="✅", inline=False)
        embed.add_field(name="Status", value="⏳ **Pendente de aprovação**", inline=False)
        embed.set_footer(text="Guilda Wanted © | Community Server")
        embed.timestamp = datetime.now()
        mentions = "".join([interaction.guild.get_role(c).mention for c in self.CARGOS_APROVACAO if interaction.guild.get_role(c)])

        await self.resultados_channel.send(
            content=mentions or None,
            embed=embed,
            view=AprovacaoView(
                self,
                interaction.user.id,
                str(interaction.user),
                nick,
                classe,
                recrutador
            )
        )

        confirmacao_embed = discord.Embed(
            title="Formulário Enviado! ✅",
            description="**Seu formulário foi enviado com sucesso, aguarde a aprovação!**\n\n"
                       "Nossa equipe irá analisar seu formulário em breve. "
                       "Você será notificado por DM quando for aprovado ou recusado.",
            color=0x57f287
        )
        confirmacao_embed.add_field(name="📋 Dados Enviados", value=f"**Nick:** {nick}\n**Classe:** {classe}\n**Recrutador:** {recrutador}", inline=False)
        confirmacao_embed.set_footer(text="Guilda Wanted © | Community Server")

        await interaction.followup.send(embed=confirmacao_embed, ephemeral=True)

    # ====== VERIFICAÇÕES DE PERMISSÃO ======
    async def verificar_permissao_config(self, interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator:
            return True
        for cargo_id in self.CARGOS_PERMITIDOS:
            cargo = interaction.guild.get_role(cargo_id)
            if cargo and cargo in interaction.user.roles:
                return True
        return False

    async def verificar_permissao_aprovacao(self, interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator:
            return True
        for cargo_id in self.CARGOS_APROVACAO:
            cargo = interaction.guild.get_role(cargo_id)
            if cargo and cargo in interaction.user.roles:
                return True
        return False

    # ====== FUNÇÃO PARA RECONHECER CLASSE PELAS 3 PRIMEIRAS LETRAS ======
    def reconhecer_classe(self, classe_input: str):
        classe_limpa = classe_input.upper().strip()
        for classe, cargo_id in self.CARGOS_POR_CLASSE.items():
            if classe_limpa == classe.upper():
                return classe, cargo_id
        for classe, cargo_id in self.CARGOS_POR_CLASSE.items():
            if classe_limpa.startswith(classe.upper()[:3]):
                return classe, cargo_id
        for classe, cargo_id in self.CARGOS_POR_CLASSE.items():
            if classe.upper()[:3] in classe_limpa:
                return classe, cargo_id
        return None, None

    # ====== PROCESSAR APROVAÇÃO ======
    async def processar_aprovacao(self, interaction: discord.Interaction, user_id: int, user_name: str, nick: str, classe: str, recrutador: str):
        try:
            await interaction.response.defer(ephemeral=True)

            user = await self.bot.fetch_user(user_id)
            member = interaction.guild.get_member(user_id)
            if not member:
                return await interaction.followup.send("❌ Usuário não encontrado no servidor!", ephemeral=True)

            classe_reconhecida, cargo_classe_id = self.reconhecer_classe(classe)
            if not classe_reconhecida:
                classe_reconhecida = "Não reconhecida"

            # Remover cargo específico
            cargo_a_remover = interaction.guild.get_role(self.CARGO_A_REMOVER_ID)
            if cargo_a_remover and cargo_a_remover in member.roles:
                try:
                    await member.remove_roles(cargo_a_remover)
                except:
                    pass

            # Atribuir cargos
            cargos_atribuidos = []
            cargo_fixo = interaction.guild.get_role(self.CARGO_FIXO_ID)
            if cargo_fixo:
                try:
                    await member.add_roles(cargo_fixo)
                    cargos_atribuidos.append(cargo_fixo.mention)
                except:
                    pass

            if cargo_classe_id:
                cargo_especifico = interaction.guild.get_role(cargo_classe_id)
                if cargo_especifico:
                    try:
                        await member.add_roles(cargo_especifico)
                        cargos_atribuidos.append(cargo_especifico.mention)
                    except:
                        pass

            # Alterar nickname
            nick_alterado = False
            try:
                await member.edit(nick=nick)
                nick_alterado = True
            except:
                pass

            # Criar ticket (usando a nova lógica que já está no ticket.py)
            try:
                ticket_cog = self.bot.get_cog("TicketCog")
                if ticket_cog:
                    await ticket_cog.criar_ticket(interaction, user_id, user_name, nick)
            except Exception as e:
                print(f"Erro ao criar ticket: {e}")

            # Atualizar embed original para aprovado
            embed = discord.Embed(
                title=f"Formulário Aprovado ✅",
                description=f"**Usuário:** {member.mention} (`{member}`)",
                color=0x57f287
            )
            embed.add_field(name="Nick In-Game", value=nick, inline=False)
            embed.add_field(name="Classe Informada", value=classe, inline=False)
            embed.add_field(name="Classe Reconhecida", value=classe_reconhecida, inline=False)
            embed.add_field(name="Recrutador(a)", value=recrutador, inline=False)
            embed.add_field(name="Cargos Atribuídos", value=", ".join(cargos_atribuidos) if cargos_atribuidos else "❌ Nenhum", inline=False)
            embed.add_field(name="Nickname Alterado", value="Sim ✅" if nick_alterado else "Não ❌", inline=False)
            embed.add_field(name="Regras Confirmadas", value="Sim ✅", inline=False)
            embed.add_field(name="Aprovado por", value=interaction.user.mention, inline=False)
            embed.set_footer(text="Guilda Wanted © | Community Server")
            embed.timestamp = datetime.now()
            await interaction.message.edit(embed=embed, view=None)

            # DM de aprovação
            try:
                dm_embed = discord.Embed(
                    title="Formulário Aprovado",
                    description="Seja Bem-Vindo(a) à Wanted!",
                    color=0x57f287
                )
                dm_embed.set_footer(text="Guilda Wanted © | Community Server")
                await user.send(embed=dm_embed)
            except:
                pass

        except Exception as e:
            print(f"Erro ao aprovar formulário: {e}")

    # ====== PROCESSAR RECUSA ======
    async def processar_recusa(self, interaction: discord.Interaction, user_id: int, user_name: str, nick: str, classe: str, recrutador: str, motivo: str):
        try:
            user = await self.bot.fetch_user(user_id)

            embed = discord.Embed(
                title=f"❌ Formulário Recusado",
                description=f"**Usuário:** <@{user_id}> (`{user_name}`)",
                color=0xed4245
            )
            embed.add_field(name="Nick In-Game", value=nick, inline=False)
            embed.add_field(name="Classe", value=classe, inline=False)
            embed.add_field(name="Recrutador(a)", value=recrutador, inline=False)
            embed.add_field(name="Regras Confirmadas", value="Sim ✅", inline=False)
            embed.add_field(name="Recusado por", value=interaction.user.mention, inline=False)
            embed.add_field(name="Motivo", value=motivo[:1024], inline=False)
            embed.set_footer(text="Guilda Wanted © | Community Server")
            embed.timestamp = datetime.now()

            await interaction.message.edit(embed=embed, view=None)
            await interaction.response.send_message("Formulário recusado com sucesso! ✅", ephemeral=True)

            try:
                dm_embed = discord.Embed(
                    title="Formulário Recusado",
                    description=f"Motivo:\n\n{motivo}",
                    color=0xed4245
                )
                dm_embed.set_footer(text="Guilda Wanted © | Community Server")
                await user.send(embed=dm_embed)
            except:
                await self.resultados_channel.send(
                    f"<@{user_id}>, seu formulário foi recusado. Motivo: {motivo[:500]}..."
                )
        except Exception as e:
            print(f"Erro ao recusar formulário: {e}")
            await interaction.response.send_message("❌ Ocorreu um erro ao recusar o formulário.", ephemeral=True)

    # ====== COMANDO STATUS ======
    @app_commands.command(name="status_formulario", description="Verifica a configuração atual do formulário")
    async def status_formulario(self, interaction: discord.Interaction):
        if not await self.verificar_permissao_config(interaction):
            return await interaction.response.send_message("❌ Você não tem permissão para usar este comando!", ephemeral=True)
        embed = discord.Embed(title="⚙️ Status do Formulário", color=0x5865f2)
        embed.add_field(name="Canal do Formulário", value=f"{self.formulario_channel.mention if self.formulario_channel else '❌ Não configurado'}", inline=False)
        embed.add_field(name="Canal de Resultados", value=f"{self.resultados_channel.mention if self.resultados_channel else '❌ Não configurado'}", inline=False)
        embed.set_footer(text="Guilda Wanted © | Community Server")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ====== LISTENER PARA RESTAURAR VIEWS APÓS REINÍCIO ======
    @commands.Cog.listener()
    async def on_ready(self):
        # Executar apenas uma vez (on_ready dispara a cada reconexão)
        if getattr(self, "_views_restored", False):
            return
        self._views_restored = True

        formularios = db.get_all_persistent_formularios()
        print(f"[DEBUG] Formulários carregados do banco: {len(formularios)}")

        for form in formularios:
            (channel_id, message_id, custom_id, embed_title, embed_description,
             embed_color, form_channel_id, resultados_channel_id) = form

            # RESTAURAR CANAIS CONFIGURADOS (FALTANTE - CORREÇÃO PRINCIPAL)
            if form_channel_id and not self.formulario_channel:
                self.formulario_channel = self.bot.get_channel(form_channel_id)
            if resultados_channel_id and not self.resultados_channel:
                self.resultados_channel = self.bot.get_channel(resultados_channel_id)

            # Restaurar a view persistente
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.fetch_message(message_id)
                    view = FormularioPersistentView(self)
                    self.bot.add_view(view, message_id=message_id)
                    print(f"View persistente restaurada: mensagem {message_id}")
                except discord.NotFound:
                    db.remove_persistent_formulario(message_id)
            else:
                db.remove_persistent_formulario(message_id)

async def setup(bot):
    await bot.add_cog(FormularioCog(bot))