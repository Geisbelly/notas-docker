"""Coleta o estado de execucao do servico: container, runtime, montagem e banco.

Tudo aqui e somente leitura e obtido de dentro do proprio container, sem
acesso ao socket do Docker. A informacao mais relevante vem de
/proc/self/mountinfo, que expone qual dispositivo esta montado em cada
caminho e qual o diretorio de origem no host -- e e o que permite dizer, em
tempo de execucao, se os dados estao em um volume ou na camada gravavel.

Separado de app.py para manter a API com apenas as rotas.
"""

import os
import platform
import re
import socket
import sqlite3
import time
from datetime import datetime

INICIO = time.monotonic()

# Volumes do Docker sao montados a partir de <data-root>/volumes/<nome>/_data
PADRAO_VOLUME = re.compile(r"/volumes/(?P<nome>[^/]+)/_data/?$")

# Volumes anonimos recebem um hash de 64 caracteres hexadecimais como nome
PADRAO_ANONIMO = re.compile(r"^[0-9a-f]{64}$")


def _desescapar(campo):
    """mountinfo escapa espacos e tabs em octal."""
    for octal, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        campo = campo.replace(octal, char)
    return campo


def _montagem_de(caminho):
    """Retorna a montagem mais especifica que cobre `caminho`, ou None."""
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as arquivo:
            linhas = arquivo.read().splitlines()
    except OSError:
        return None

    melhor = None
    for linha in linhas:
        partes = linha.split(" - ", 1)
        if len(partes) != 2:
            continue

        campos = partes[0].split(" ")
        if len(campos) < 6:
            continue

        ponto = _desescapar(campos[4])
        if caminho != ponto and not caminho.startswith(ponto.rstrip("/") + "/"):
            continue

        if melhor is not None and len(ponto) <= len(melhor["ponto"]):
            continue

        direita = partes[1].split(" ")
        melhor = {
            "raiz": _desescapar(campos[3]),
            "ponto": ponto,
            "opcoes": campos[5],
            "fstype": direita[0] if direita else "",
            "origem": _desescapar(direita[1]) if len(direita) > 1 else "",
        }

    return melhor


def _classificar_montagem(data_dir):
    """Diz se DATA_DIR e um volume nomeado, anonimo, bind mount ou efemero."""
    montagem = _montagem_de(data_dir)

    if montagem is None:
        return {
            "tipo": "desconhecido",
            "persistente": None,
            "descricao": "Nao foi possivel ler /proc/self/mountinfo.",
        }

    # Se a montagem mais especifica nao e o proprio DATA_DIR, o diretorio faz
    # parte do sistema de arquivos do container -- ou seja, da camada gravavel.
    if montagem["ponto"] != data_dir:
        return {
            "tipo": "camada gravavel",
            "persistente": False,
            "nome": None,
            "origem_host": None,
            "fstype": montagem["fstype"],
            "somente_leitura": "ro" in montagem["opcoes"].split(","),
            "descricao": (
                "Os dados estao na camada gravavel do container e serao "
                "perdidos no docker rm."
            ),
        }

    raiz = montagem["raiz"]
    correspondencia = PADRAO_VOLUME.search(raiz)

    if correspondencia:
        nome = correspondencia.group("nome")
        anonimo = bool(PADRAO_ANONIMO.match(nome))
        return {
            "tipo": "volume anonimo" if anonimo else "volume nomeado",
            "persistente": True,
            "reencontravel": not anonimo,
            "nome": nome,
            "origem_host": raiz,
            "fstype": montagem["fstype"],
            "somente_leitura": "ro" in montagem["opcoes"].split(","),
            "descricao": (
                "Volume anonimo: os dados sobrevivem ao docker rm, mas ficam "
                "orfaos e sao inviaveis de reencontrar."
                if anonimo
                else "Volume nomeado: os dados sobrevivem a destruicao do "
                "container e podem ser remontados pelo nome."
            ),
        }

    return {
        "tipo": "bind mount",
        "persistente": True,
        "reencontravel": True,
        "nome": None,
        "origem_host": raiz,
        "fstype": montagem["fstype"],
        "somente_leitura": "ro" in montagem["opcoes"].split(","),
        "descricao": "Diretorio do host montado diretamente no container.",
    }


def _sistema_operacional():
    try:
        with open("/etc/os-release", encoding="utf-8") as arquivo:
            for linha in arquivo:
                if linha.startswith("PRETTY_NAME="):
                    return linha.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def _versao_flask():
    try:
        from importlib.metadata import version

        return version("flask")
    except Exception:
        return "desconhecida"


def _limite_memoria():
    """Limite de memoria imposto pelo cgroup, se houver."""
    for caminho in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(caminho, encoding="utf-8") as arquivo:
                valor = arquivo.read().strip()
        except OSError:
            continue
        if valor == "max":
            return None
        try:
            bytes_ = int(valor)
        except ValueError:
            continue
        # Sem limite, o cgroup v1 reporta um numero absurdamente grande
        return None if bytes_ > (1 << 62) else bytes_
    return None


def _info_banco(db_path):
    info = {
        "caminho": db_path,
        "existe": os.path.exists(db_path),
        "bytes": None,
        "modificado_em": None,
        "sqlite": sqlite3.sqlite_version,
        "total_notas": None,
        "primeira_em": None,
        "ultima_em": None,
        "erro": None,
    }

    if not info["existe"]:
        return info

    try:
        stat = os.stat(db_path)
        info["bytes"] = stat.st_size
        info["modificado_em"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    except OSError as erro:
        info["erro"] = str(erro)
        return info

    try:
        conexao = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            linha = conexao.execute(
                "SELECT COUNT(*), MIN(criado_em), MAX(criado_em) FROM notas"
            ).fetchone()
            info["total_notas"], info["primeira_em"], info["ultima_em"] = linha
            info["pagina_bytes"] = conexao.execute("PRAGMA page_size").fetchone()[0]
            info["paginas"] = conexao.execute("PRAGMA page_count").fetchone()[0]
        finally:
            conexao.close()
    except sqlite3.Error as erro:
        info["erro"] = str(erro)

    return info


def coletar(data_dir, db_path):
    """Monta o retrato completo do estado atual do servico."""
    pid = os.getpid()

    return {
        "container": {
            # O Docker define o hostname como o ID curto do container
            "hostname": socket.gethostname(),
            "pid": pid,
            "e_pid_1": pid == 1,
            "uptime_s": round(time.monotonic() - INICIO, 1),
            "hora_local": datetime.now().isoformat(timespec="seconds"),
            "fuso": time.tzname[0],
            "cpus_visiveis": os.cpu_count(),
            "limite_memoria_bytes": _limite_memoria(),
        },
        "runtime": {
            "python": platform.python_version(),
            "flask": _versao_flask(),
            "sistema": _sistema_operacional(),
            "arquitetura": platform.machine(),
        },
        "armazenamento": {
            "data_dir": data_dir,
            "data_dir_existe": os.path.isdir(data_dir),
            "origem_variavel": "ambiente" if "DATA_DIR" in os.environ else "padrao do codigo",
            "montagem": _classificar_montagem(data_dir),
        },
        "banco": _info_banco(db_path),
    }
