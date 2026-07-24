# dashboard/db.py
# Conexão com o mesmo Postgres do sistema /board (config.DATABASE_URL), mas
# via psycopg2 (síncrono) em vez de asyncpg: o Flask aqui é síncrono, e ter
# dois drivers diferentes acessando o mesmo Postgres é normal (bot e
# dashboard são processos separados).

import os
import sys

# Permite "import config" a partir da raiz do repo, independente de onde o
# processo do Flask for iniciado (ex: Render com Root Directory = dashboard/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
from flask import g

import config


def get_db():
    """Uma conexão por request, guardada em flask.g. Fechada automaticamente
    no teardown_appcontext registrado em app.py."""
    if "db" not in g:
        g.db = psycopg2.connect(config.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db


def close_db(_exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
