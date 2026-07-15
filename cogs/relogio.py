# cogs/relogio.py
# O relógio dos alistamentos: a cada minuto verifica lembretes (15/5 min),
# puxada automática no horário, aviso ao criador (+30 min) e auto-finalização
# (+5h) de todas as heroes/andares ativas. Também detecta quando a staff
# apaga a mensagem do alistamento na mão (= cancelamento).
#
# Este arquivo não tem comando nenhum: ele só dispara as ações do motor
# (motor_alistamento.py) na hora certa. Os comandos moram cada um no seu
# arquivo: cogs/alistamento.py, cogs/andares.py e cogs/puxar.py.

from datetime import datetime

import discord
from discord.ext import commands, tasks

import config
import motor_alistamento as motor


class Relogio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.relogio.start()

    def cog_unload(self):
        self.relogio.cancel()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        await motor.cancelar_por_mensagem(payload.message_id)

    @tasks.loop(seconds=60)
    async def relogio(self):
        agora = datetime.now(config.TIMEZONE)
        for heroes in list(motor.ativas.values()):
            try:
                for acao in heroes.acoes_pendentes(agora):
                    if acao.startswith("lembrete_"):
                        await motor.enviar_lembrete(heroes, int(acao.split("_")[1]))
                    elif acao == "auto_puxar":
                        await motor.puxar_fila_automatico(heroes)
                    elif acao == "aviso_criador":
                        await motor.avisar_criador(heroes)
                    elif acao == "auto_finalizar":
                        await motor.finalizar_heroes(heroes, finalizada_por="auto")
                # Apaga lembretes cujo prazo venceu com o bot desligado
                if heroes.id in motor.ativas:
                    await motor.apagar_lembretes(heroes, apenas_vencidos_em=agora)
            except Exception as e:
                print(f"[HEROES] Erro no relógio para heroes {heroes.id}: {e}")

    @relogio.before_loop
    async def antes_do_relogio(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    motor.inicializar(bot)
    await bot.add_cog(Relogio(bot))
