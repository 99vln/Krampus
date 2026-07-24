# dashboard/auth.py
# Login do dashboard via Flask-Login. Sem rota de cadastro: os únicos jeitos
# de existir uma linha em dashboard_users são o create_user.py (manual, você)
# ou uma inserção direta no banco.

from flask_login import LoginManager, UserMixin
from werkzeug.security import check_password_hash

from db import get_db

login_manager = LoginManager()
login_manager.login_view = "login"


class DashboardUser(UserMixin):
    def __init__(self, id, username, papel):
        self.id = str(id)
        self.username = username
        self.papel = papel


@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, papel, ativo FROM dashboard_users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if row is None or not row["ativo"]:
        return None
    return DashboardUser(row["id"], row["username"], row["papel"])


def verificar_login(username: str, password: str):
    """Devolve o DashboardUser se usuário/senha baterem e a conta estiver
    ativa, senão None. Não distingue "usuário não existe" de "senha errada"
    na mensagem de erro (evita confirmar pra quem está tentando adivinhar
    se um username existe)."""
    db = get_db()
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, username, password_hash, papel, ativo FROM dashboard_users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None or not row["ativo"]:
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return DashboardUser(row["id"], row["username"], row["papel"])
