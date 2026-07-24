# board_constants.py
# Vocabulário de roles/status do sistema /board, compartilhado entre
# cogs/board.py (Discord) e dashboard/app.py (web) — nenhum dos dois importa
# o outro (o dashboard não depende do discord.py), por isso este módulo fica
# na raiz, sem import de discord.

ROLES = ("tank", "melee", "ranged", "healer", "support")
STATUSES = ("bench", "late", "tentative", "absence")

ROLE_LABELS = {
    "tank": "🛡️ TANK",
    "melee": "⚔️ MELEE",
    "ranged": "🏹 RANGED",
    "healer": "💉 HEALER",
    "support": "🛠️ SUPPORT",
}
STATUS_LABELS = {
    "bench": "🪑 BENCH",
    "late": "⏰ LATE",
    "tentative": "❓ TENTATIVE",
    "absence": "❌ ABSENCE",
}
