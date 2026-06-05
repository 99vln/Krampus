import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

class Krampus(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.presences = False
        intents.voice_states = False
        intents.message_content = False
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        # Carrega todos os Cogs da pasta cogs
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("_"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"✅ Cog '{filename}' carregado com sucesso!")
                except Exception as e:
                    print(f"❌ Erro ao carregar '{filename}': {e}")

        # Sincroniza os comandos slash
        await self.tree.sync()
        print("✅ Comandos slash sincronizados!")

    async def on_ready(self):
        print(f"✅ Bot {self.user} online e pronto!")
        print(f"👉 Prefixo: /")
        print(f"👉 Comandos slash carregados")

# Verifica se o token existe
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise ValueError("❌ Token não encontrado no arquivo .env!")

bot = Krampus()

# Comando para sincronizar manualmente (opcional)
@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sincroniza os comandos slash manualmente"""
    await bot.tree.sync()
    await ctx.send("✅ Comandos slash sincronizados!")

bot.run(token)