import os
import sqlite3
from datetime import datetime

from flask import Flask, jsonify, request

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "notas.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notas (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            texto     TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

app = Flask(__name__)

init_db()

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.post("/notas")
def criar_nota():
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()

    if not texto:
        return jsonify({"erro": "o campo 'texto' e obrigatorio"}), 400

    criado_em = datetime.now().isoformat(timespec="seconds")

    conn = get_conn()
    cursor = conn.execute(
        "INSERT INTO notas (texto, criado_em) VALUES (?, ?)",
        (texto, criado_em),
    )
    conn.commit()
    nota_id = cursor.lastrowid
    conn.close()

    return jsonify({"id": nota_id, "texto": texto, "criado_em": criado_em}), 201

@app.get("/notas")
def listar_notas():
    conn = get_conn()
    linhas = conn.execute(
        "SELECT id, texto, criado_em FROM notas ORDER BY id"
    ).fetchall()
    conn.close()

    return jsonify([dict(linha) for linha in linhas])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)

