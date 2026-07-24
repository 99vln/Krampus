# dashboard/app.py
# Dashboard web do sistema /board: login restrito (Staff/Lead, sem cadastro),
# listagem de boards, detalhe do roster e encerramento de board. Lê e
# escreve no MESMO Postgres que o bot (config.DATABASE_URL), via psycopg2.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import CSRFProtect

import config
from board_constants import ROLES, STATUSES, ROLE_LABELS, STATUS_LABELS
from db import get_db, close_db
from auth import login_manager, verificar_login


def create_app():
    app = Flask(__name__)

    if not config.FLASK_SECRET_KEY:
        raise ValueError(
            "FLASK_SECRET_KEY não encontrado no .env — gere com "
            "'python -c \"import secrets; print(secrets.token_hex(32))\"'"
        )
    app.secret_key = config.FLASK_SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not config.DASHBOARD_DEBUG

    login_manager.init_app(app)
    CSRFProtect(app)
    app.teardown_appcontext(close_db)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("boards"))
        if request.method == "POST":
            user = verificar_login(request.form.get("username", ""), request.form.get("password", ""))
            if user is None:
                flash("Usuário ou senha inválidos.", "error")
                return render_template("login.html")
            login_user(user)
            db = get_db()
            with db.cursor() as cur:
                cur.execute("UPDATE dashboard_users SET ultimo_login = now() WHERE id = %s", (user.id,))
            db.commit()
            return redirect(url_for("boards"))
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def boards():
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT * FROM boards ORDER BY data_evento DESC")
            todos = cur.fetchall()
        return render_template("boards.html", boards=todos)

    @app.route("/board/<int:board_id>")
    @login_required
    def board_detail(board_id):
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT * FROM boards WHERE id = %s", (board_id,))
            board = cur.fetchone()
            if board is None:
                flash("Board não encontrado.", "error")
                return redirect(url_for("boards"))

            cur.execute("SELECT role, max_vagas FROM board_vagas WHERE board_id = %s", (board_id,))
            vagas = {r["role"]: r["max_vagas"] for r in cur.fetchall()}

            cur.execute(
                "SELECT discord_user_id, discord_display_name, role, status "
                "FROM board_inscricoes WHERE board_id = %s ORDER BY atualizado_em",
                (board_id,),
            )
            inscricoes = cur.fetchall()

        por_role = {r: [] for r in ROLES}
        por_status = {s: [] for s in STATUSES}
        for i in inscricoes:
            if i["role"]:
                por_role[i["role"]].append(i)
            elif i["status"]:
                por_status[i["status"]].append(i)

        return render_template(
            "board_detail.html",
            board=board,
            vagas=vagas,
            por_role=por_role,
            por_status=por_status,
            roles=ROLES,
            statuses=STATUSES,
            role_labels=ROLE_LABELS,
            status_labels=STATUS_LABELS,
        )

    @app.route("/board/<int:board_id>/fechar", methods=["POST"])
    @login_required
    def fechar_board_route(board_id):
        db = get_db()
        with db.cursor() as cur:
            cur.execute(
                "UPDATE boards SET status = 'fechado', fechado_em = now() "
                "WHERE id = %s AND status = 'aberto'",
                (board_id,),
            )
        db.commit()
        flash("Board encerrado.", "success")
        return redirect(url_for("board_detail", board_id=board_id))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=config.DASHBOARD_DEBUG)
