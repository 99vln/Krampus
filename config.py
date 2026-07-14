# config.py
import os
from datetime import timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")


def _env_int(nome: str, padrao: int) -> int:
    """Permite trocar um ID pelo .env (útil no servidor de teste) sem editar código."""
    valor = os.getenv(nome)
    return int(valor) if valor else padrao


# Fuso horário da guild (usado para agendar as heroes)
_tz_nome = os.getenv("GUILD_TIMEZONE", "America/Sao_Paulo")
try:
    TIMEZONE = ZoneInfo(_tz_nome)
except ZoneInfoNotFoundError:
    # Sem a base de fusos horários (no Windows ela vem do pacote pip "tzdata").
    # Cai para UTC-3 fixo (horário de Brasília) em vez de derrubar os cogs.
    TIMEZONE = timezone(timedelta(hours=-3), "UTC-3")
    print(
        f"[CONFIG] ⚠️ Fuso '{_tz_nome}' não encontrado; usando UTC-3 fixo. "
        f"Para corrigir: pip install -r requirements.txt"
    )

# IDs dos cargos por classe (DPS, TANK, HEALER)
ROLE_IDS = {
    "DPS": _env_int("ROLE_DPS", 1440390981307465949),
    "TANK": _env_int("ROLE_TANK", 1440391288615735380),
    "HEALER": _env_int("ROLE_HEALER", 1440391235268378654),
}

# Emojis por classe
EMOJIS_POR_CLASSE = {
    "DPS": "🔪",
    "HEALER": "🚑",
    "TANK": "🔰"
}

# IDs das categorias correspondentes a cada classe
CATEGORY_IDS = {
    "DPS": 1460430637243568364,
    "TANK": 1460430679182672074,
    "HEALER": 1460430719489802434,
}

# IDs dos cargos com permissão de staff (DEV, STAFF)
CARGOS_STAFF = [
    _env_int("ROLE_DEV", 1449931317675429960),   # DEV
    _env_int("ROLE_STAFF", 1442625294078050456),  # STAFF
]

# ID do canal onde os transcripts serão enviados
CANAL_LOGS_TRANSCRIPTS_ID = _env_int("CANAL_LOGS_TRANSCRIPTS", 1470070755604697212)

# Canal de logs dos alistamentos finalizados (antes hardcoded em cogs/alistamento.py)
CANAL_LOGS_ALISTAMENTO_ID = _env_int("CANAL_LOGS_ALISTAMENTO", 1450014685725200416)

# Canal de fila mencionado nos lembretes de heroes (0 = só texto, sem link)
CANAL_FILA_ID = _env_int("CANAL_FILA", 0)