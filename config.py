# config.py
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# IDs dos cargos por classe (DPS, TANK, HEALER)
ROLE_IDS = {
    "DPS": 1440390981307465949,
    "TANK": 1440391288615735380,
    "HEALER": 1440391235268378654,
}

# IDs das categorias correspondentes a cada classe
CATEGORY_IDS = {
    "DPS": 1460430637243568364,
    "TANK": 1460430679182672074,
    "HEALER": 1460430719489802434,
}

# IDs dos cargos com permissão de staff (DEV, STAFF)
CARGOS_STAFF = [
    1449931317675429960,  # DEV
    1442625294078050456,   # STAFF
]

# ID do canal onde os transcripts serão enviados
CANAL_LOGS_TRANSCRIPTS_ID = 1470070755604697212