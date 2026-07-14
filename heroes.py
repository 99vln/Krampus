# heroes.py
# Modelo de domínio de uma "heroes" (alistamento de boss agendado).
# Uma heroes ATIVA vive como um arquivo JSON em data/heroes/<id>.json (estado de controle).
# Quando finalizada, os dados de participação migram para o SQLite (ver database.py)
# e o JSON é apagado.

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

# Pasta dos JSONs ancorada no arquivo, não no diretório de onde o bot foi iniciado
HEROES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "heroes")

# Índices compatíveis com datetime.weekday() (segunda = 0)
DIAS_SEMANA = ["SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SÁBADO", "DOMINGO"]

LIMITES_POR_CLASSE = {"TANK": 1, "HEALER": 2, "DPS": 6}

# Prazos do ciclo de vida (sempre relativos ao horário AGENDADO da heroes)
LEMBRETE_ANTECEDENCIAS_MIN = [15, 5]          # avisos antes de começar
AUTO_PUXAR_JANELA = timedelta(minutes=3)      # tolerância p/ o tick do relógio pegar o início (a tentativa é ÚNICA)
AVISO_CRIADOR_APOS = timedelta(minutes=30)    # DM perguntando se pode finalizar
AUTO_FINALIZAR_APOS = timedelta(hours=5)      # bot finaliza sozinho


def proxima_ocorrencia(dia: str, hora: str, agora: datetime) -> datetime:
    """
    Calcula o próximo datetime em que cai `dia` da semana às `hora` (HH:MM),
    a partir de `agora` (datetime com timezone). Se o horário de hoje já passou,
    vai para a próxima semana.
    """
    alvo_weekday = DIAS_SEMANA.index(dia.upper())
    hh, mm = (int(p) for p in hora.split(":"))
    candidato = agora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    dias_a_frente = (alvo_weekday - agora.weekday()) % 7
    candidato = candidato + timedelta(days=dias_a_frente)
    if candidato <= agora:
        candidato = candidato + timedelta(days=7)
    return candidato


@dataclass
class Participante:
    user_id: int
    nome: str
    classe: str  # TANK / HEALER / DPS


@dataclass
class Heroes:
    boss: str
    dia: str
    hora: str
    mastery: str
    criador_id: int
    criador_nome: str
    agendada_para: str                      # ISO 8601 com timezone
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    channel_id: int = 0
    message_id: int = 0
    dm_message_id: int = 0                  # DM "posso finalizar?" enviada ao criador
    participantes: list = field(default_factory=list)  # list[Participante]
    # Flags de eventos já disparados (para não repetir após restart)
    lembretes_enviados: list = field(default_factory=list)  # ex: [15, 5]
    # Mensagens de lembrete enviadas: [{message_id, channel_id, apagar_em}]
    # (o delete_after do discord.py morre se o bot reiniciar; com o registro
    # aqui, o relógio apaga as vencidas mesmo depois de um restart)
    lembretes_mensagens: list = field(default_factory=list)
    puxada_automatica_feita: bool = False
    aviso_criador_enviado: bool = False

    # ---------- participantes ----------

    def participante(self, user_id: int):
        for p in self.participantes:
            if p.user_id == user_id:
                return p
        return None

    def por_classe(self, classe: str) -> list:
        return [p for p in self.participantes if p.classe == classe]

    def adicionar(self, user_id: int, nome: str, cargos_ids: list, role_ids: dict):
        """Retorna (sucesso, mensagem). `role_ids` = {"DPS": id, ...} vindo do config."""
        classe = None
        for nome_classe, role_id in role_ids.items():
            if role_id in cargos_ids:
                classe = nome_classe
                break
        if not classe:
            return False, "Você precisa ter um dos cargos: DPS, TANK ou HEALER para participar."
        if self.participante(user_id):
            return False, "Você já está participando!"
        if len(self.por_classe(classe)) >= LIMITES_POR_CLASSE[classe]:
            return False, f"Todos os slots de {classe} já estão preenchidos!"
        self.participantes.append(Participante(user_id, nome, classe))
        return True, f"Você entrou como {classe}!"

    def remover(self, user_id: int):
        p = self.participante(user_id)
        if not p:
            return False, "Você não estava participando."
        self.participantes.remove(p)
        return True, "Você saiu do alistamento!"

    # ---------- linha do tempo ----------

    @property
    def inicio(self) -> datetime:
        return datetime.fromisoformat(self.agendada_para)

    def acoes_pendentes(self, agora: datetime) -> list:
        """
        Decide o que o bot deve fazer AGORA para esta heroes.
        Retorna uma lista como ["lembrete_15"] ou ["auto_finalizar"].

        Regras:
        - No máximo UM lembrete por vez: o mais próximo do início cuja janela
          [inicio-N, inicio) contém agora. Se o bot estava desligado e a janela
          passou, o lembrete é pulado (não spamamos atrasado).
        - O aviso ao criador dispara a partir de inicio+30min, mas é suprimido
          se o prazo de auto-finalizar já passou (perguntar e finalizar no
          mesmo segundo não faz sentido).
        - Auto-finalizar dispara a partir de inicio+5h.
        """
        acoes = []
        candidatos = [
            m for m in LEMBRETE_ANTECEDENCIAS_MIN
            if m not in self.lembretes_enviados
            and self.inicio - timedelta(minutes=m) <= agora < self.inicio
        ]
        if candidatos:
            acoes.append(f"lembrete_{min(candidatos)}")
        # Puxada automática da fila: UMA tentativa no horário da heroes (o cog
        # marca como feita na primeira execução, esteja o shot caller na call
        # ou não; atrasados usam /puxar)
        if (
            not self.puxada_automatica_feita
            and self.inicio <= agora < self.inicio + AUTO_PUXAR_JANELA
        ):
            acoes.append("auto_puxar")
        if (
            not self.aviso_criador_enviado
            and self.inicio + AVISO_CRIADOR_APOS <= agora < self.inicio + AUTO_FINALIZAR_APOS
        ):
            acoes.append("aviso_criador")
        if agora >= self.inicio + AUTO_FINALIZAR_APOS:
            acoes.append("auto_finalizar")
        return acoes

    def marcar_lembrete(self, minutos: int):
        """Marca o lembrete enviado E os de antecedência maior (se o de 5 min
        saiu, o de 15 não deve mais disparar depois dele)."""
        novos = {m for m in LEMBRETE_ANTECEDENCIAS_MIN if m >= minutos}
        self.lembretes_enviados = sorted(set(self.lembretes_enviados) | novos, reverse=True)

    # ---------- persistência JSON ----------

    def _caminho(self) -> str:
        return os.path.join(HEROES_DIR, f"{self.id}.json")

    def salvar(self):
        # Escrita atômica: grava num .tmp e troca pelo definitivo com os.replace.
        # Se o bot morrer no meio da escrita, o JSON antigo continua intacto.
        os.makedirs(HEROES_DIR, exist_ok=True)
        temporario = self._caminho() + ".tmp"
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        os.replace(temporario, self._caminho())

    def apagar_json(self):
        try:
            os.remove(self._caminho())
        except FileNotFoundError:
            pass

    @classmethod
    def de_dict(cls, dados: dict) -> "Heroes":
        dados = dict(dados)
        dados["participantes"] = [Participante(**p) for p in dados.get("participantes", [])]
        return cls(**dados)

    @classmethod
    def carregar_todas(cls) -> list:
        """Lê todos os JSONs de heroes ativas (usado na inicialização do bot)."""
        if not os.path.isdir(HEROES_DIR):
            return []
        ativas = []
        for nome in os.listdir(HEROES_DIR):
            if not nome.endswith(".json"):
                continue
            caminho = os.path.join(HEROES_DIR, nome)
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    ativas.append(cls.de_dict(json.load(f)))
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                # Quarentena em vez de só ignorar: o problema fica visível no disco
                print(f"[HEROES] JSON inválido movido para quarentena: {nome} ({e})")
                try:
                    os.replace(caminho, caminho + ".corrupt")
                except OSError:
                    pass
        return ativas
