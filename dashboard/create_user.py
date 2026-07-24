# dashboard/create_user.py
# Script de linha de comando pra criar login do dashboard manualmente — não
# existe (e não deve existir) rota de cadastro na aplicação web. Rode isso
# você mesmo e repasse usuário/senha pra Staff/Lead por fora.

import os
import sys
import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from werkzeug.security import generate_password_hash

import config


def main():
    if not config.DATABASE_URL:
        print("DATABASE_URL não encontrado no .env.")
        return

    username = input("Usuário: ").strip()
    if not username:
        print("Usuário não pode ser vazio.")
        return

    senha = getpass.getpass("Senha: ")
    confirmar = getpass.getpass("Confirme a senha: ")
    if not senha:
        print("Senha não pode ser vazia.")
        return
    if senha != confirmar:
        print("As senhas não conferem.")
        return

    papel = (input("Papel (staff/lead) [staff]: ").strip().lower() or "staff")
    if papel not in ("staff", "lead"):
        print("Papel inválido — use 'staff' ou 'lead'.")
        return

    conn = psycopg2.connect(config.DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO dashboard_users (username, password_hash, papel) VALUES (%s, %s, %s)",
                (username, generate_password_hash(senha), papel),
            )
    except psycopg2.errors.UniqueViolation:
        print(f"Já existe um usuário '{username}'.")
        return
    finally:
        conn.close()

    print(f"Usuário '{username}' ({papel}) criado com sucesso.")


if __name__ == "__main__":
    main()
