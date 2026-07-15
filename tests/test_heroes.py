# Testes do modelo Heroes (roda sem Discord e sem token):
#   C:\Users\pmath\.venvs\krampus\Scripts\python.exe -m unittest tests.test_heroes -v
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from heroes import Heroes, proxima_ocorrencia

TZ = ZoneInfo("America/Sao_Paulo")
ROLE_IDS = {"DPS": 111, "TANK": 222, "HEALER": 333}


def heroes_de_teste(inicio: datetime) -> Heroes:
    return Heroes(
        boss="GUILD BOSS 10 PLAYERS",
        dia="DOMINGO",
        hora="18:00",
        mastery="9000",
        criador_id=1,
        criador_nome="Criador",
        agendada_para=inicio.isoformat(),
    )


class TestProximaOcorrencia(unittest.TestCase):
    # terça-feira, 14h
    AGORA = datetime(2026, 7, 14, 14, 0, tzinfo=TZ)

    def test_agendar_para_domingo(self):
        alvo = proxima_ocorrencia("DOMINGO", "18:00", self.AGORA)
        self.assertEqual(alvo.weekday(), 6)
        self.assertEqual((alvo.hour, alvo.minute), (18, 0))
        self.assertEqual(alvo.date().isoformat(), "2026-07-19")

    def test_mesmo_dia_horario_futuro(self):
        alvo = proxima_ocorrencia("TERÇA", "20:00", self.AGORA)
        self.assertEqual(alvo.date(), self.AGORA.date())

    def test_mesmo_dia_horario_passado_vai_para_proxima_semana(self):
        alvo = proxima_ocorrencia("TERÇA", "10:00", self.AGORA)
        self.assertEqual(alvo.date(), self.AGORA.date() + timedelta(days=7))


class TestParticipantes(unittest.TestCase):
    def setUp(self):
        self.h = heroes_de_teste(datetime(2026, 7, 19, 18, 0, tzinfo=TZ))

    def test_entrar_com_classe(self):
        ok, msg = self.h.adicionar(10, "Fulano", [222], ROLE_IDS)
        self.assertTrue(ok)
        self.assertEqual(self.h.participante(10).classe, "TANK")

    def test_sem_cargo_de_classe(self):
        ok, msg = self.h.adicionar(10, "Fulano", [999], ROLE_IDS)
        self.assertFalse(ok)

    def test_nao_entra_duas_vezes(self):
        self.h.adicionar(10, "Fulano", [111], ROLE_IDS)
        ok, msg = self.h.adicionar(10, "Fulano", [111], ROLE_IDS)
        self.assertFalse(ok)

    def test_limite_de_tank_eh_1(self):
        self.h.adicionar(10, "A", [222], ROLE_IDS)
        ok, msg = self.h.adicionar(11, "B", [222], ROLE_IDS)
        self.assertFalse(ok)
        self.assertIn("TANK", msg)

    def test_limite_de_dps_eh_6(self):
        for i in range(6):
            ok, _ = self.h.adicionar(100 + i, f"D{i}", [111], ROLE_IDS)
            self.assertTrue(ok)
        ok, _ = self.h.adicionar(200, "D7", [111], ROLE_IDS)
        self.assertFalse(ok)

    def test_sair(self):
        self.h.adicionar(10, "Fulano", [333], ROLE_IDS)
        ok, _ = self.h.remover(10)
        self.assertTrue(ok)
        self.assertIsNone(self.h.participante(10))


class TestLinhaDoTempo(unittest.TestCase):
    INICIO = datetime(2026, 7, 19, 18, 0, tzinfo=TZ)

    def setUp(self):
        self.h = heroes_de_teste(self.INICIO)

    def test_nada_pendente_muito_antes(self):
        self.assertEqual(self.h.acoes_pendentes(self.INICIO - timedelta(hours=2)), [])

    def test_lembrete_15_na_janela(self):
        acoes = self.h.acoes_pendentes(self.INICIO - timedelta(minutes=14))
        self.assertEqual(acoes, ["lembrete_15"])

    def test_dentro_da_janela_de_5_dispara_so_o_mais_proximo(self):
        # Heroes criada faltando 3 min: NÃO pode mandar dois pings seguidos
        acoes = self.h.acoes_pendentes(self.INICIO - timedelta(minutes=3))
        self.assertEqual(acoes, ["lembrete_5"])

    def test_lembrete_nao_repete(self):
        self.h.lembretes_enviados = [15]
        acoes = self.h.acoes_pendentes(self.INICIO - timedelta(minutes=10))
        self.assertEqual(acoes, [])

    def test_marcar_lembrete_5_suprime_o_de_15(self):
        # Se o ping de 5 min saiu, o de 15 não pode disparar DEPOIS dele
        self.h.marcar_lembrete(5)
        self.assertIn(15, self.h.lembretes_enviados)
        self.assertIn(5, self.h.lembretes_enviados)
        acoes = self.h.acoes_pendentes(self.INICIO - timedelta(minutes=2))
        self.assertEqual(acoes, [])

    def test_marcar_lembrete_15_nao_suprime_o_de_5(self):
        self.h.marcar_lembrete(15)
        acoes = self.h.acoes_pendentes(self.INICIO - timedelta(minutes=4))
        self.assertEqual(acoes, ["lembrete_5"])

    def test_lembrete_perdido_nao_dispara_depois_do_inicio(self):
        acoes = self.h.acoes_pendentes(self.INICIO + timedelta(minutes=1))
        self.assertNotIn("lembrete_15", acoes)
        self.assertNotIn("lembrete_5", acoes)

    def test_puxada_automatica_no_horario(self):
        acoes = self.h.acoes_pendentes(self.INICIO)
        self.assertEqual(acoes, ["auto_puxar"])
        # a janela curta existe só para o tick de 60s não perder o início
        acoes = self.h.acoes_pendentes(self.INICIO + timedelta(minutes=2))
        self.assertEqual(acoes, ["auto_puxar"])

    def test_puxada_automatica_nao_dispara_antes_nem_depois_da_janela(self):
        self.assertNotIn("auto_puxar", self.h.acoes_pendentes(self.INICIO - timedelta(minutes=1)))
        # bot desligado no horário = tentativa perdida, ninguém é puxado atrasado
        self.assertNotIn("auto_puxar", self.h.acoes_pendentes(self.INICIO + timedelta(minutes=4)))

    def test_puxada_automatica_nao_repete_depois_de_feita(self):
        self.h.puxada_automatica_feita = True
        self.assertEqual(self.h.acoes_pendentes(self.INICIO + timedelta(minutes=2)), [])

    def test_aviso_criador_30_min_depois(self):
        acoes = self.h.acoes_pendentes(self.INICIO + timedelta(minutes=30))
        self.assertEqual(acoes, ["aviso_criador"])

    def test_aviso_criador_nao_repete(self):
        self.h.aviso_criador_enviado = True
        acoes = self.h.acoes_pendentes(self.INICIO + timedelta(minutes=45))
        self.assertEqual(acoes, [])

    def test_auto_finalizar_5_horas_depois_do_horario_marcado(self):
        acoes = self.h.acoes_pendentes(self.INICIO + timedelta(hours=5))
        self.assertIn("auto_finalizar", acoes)
        acoes_antes = self.h.acoes_pendentes(self.INICIO + timedelta(hours=4, minutes=59))
        self.assertNotIn("auto_finalizar", acoes_antes)

    def test_aviso_suprimido_quando_auto_finalizar_ja_venceu(self):
        # Bot ficou fora do ar de antes do +30min até depois do +5h:
        # não faz sentido perguntar "posso finalizar?" e finalizar no mesmo tick
        acoes = self.h.acoes_pendentes(self.INICIO + timedelta(hours=6))
        self.assertEqual(acoes, ["auto_finalizar"])


class TestJsonRoundtrip(unittest.TestCase):
    def test_vira_dict_e_volta_igual(self):
        h = heroes_de_teste(datetime(2026, 7, 19, 18, 0, tzinfo=TZ))
        h.adicionar(10, "Fulano", [222], ROLE_IDS)
        h.adicionar(11, "Sicrana", [333], ROLE_IDS)
        h.lembretes_enviados = [15]

        from dataclasses import asdict
        copia = Heroes.de_dict(asdict(h))

        self.assertEqual(asdict(copia), asdict(h))
        self.assertEqual(copia.participante(11).classe, "HEALER")
        self.assertEqual(copia.inicio, h.inicio)


class TestPersistenciaEmDisco(unittest.TestCase):
    def setUp(self):
        import tempfile
        import heroes as heroes_mod
        self._mod = heroes_mod
        self._dir_original = heroes_mod.HEROES_DIR
        heroes_mod.HEROES_DIR = tempfile.mkdtemp()

    def tearDown(self):
        self._mod.HEROES_DIR = self._dir_original

    def test_salvar_e_carregar(self):
        h = heroes_de_teste(datetime(2026, 7, 19, 18, 0, tzinfo=TZ))
        h.adicionar(10, "Fulano", [222], ROLE_IDS)
        h.salvar()
        carregadas = self._mod.Heroes.carregar_todas()
        self.assertEqual(len(carregadas), 1)
        self.assertEqual(carregadas[0].id, h.id)
        self.assertEqual(carregadas[0].participante(10).classe, "TANK")

    def test_json_corrompido_vai_para_quarentena(self):
        import os
        lixo = os.path.join(self._mod.HEROES_DIR, "quebrado.json")
        os.makedirs(self._mod.HEROES_DIR, exist_ok=True)
        with open(lixo, "w", encoding="utf-8") as f:
            f.write("{ nem json isso")
        carregadas = self._mod.Heroes.carregar_todas()
        self.assertEqual(carregadas, [])
        self.assertFalse(os.path.exists(lixo))
        self.assertTrue(os.path.exists(lixo + ".corrupt"))


if __name__ == "__main__":
    unittest.main()
