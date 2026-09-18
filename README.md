# notas-docker

Serviço de anotações em Python empacotado em imagem Docker própria, com persistência de dados em volume nomeado.

Atividade Prática — Implementação de Serviços com Docker.

## Descrição

API HTTP mínima que registra anotações de texto com data e hora. Os dados são gravados em um banco SQLite dentro do diretório apontado pela variável de ambiente `DATA_DIR`, que por padrão é `/app/data` — o ponto de montagem do volume.

## Rotas

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| `GET` | `/health` | — | `200` `{"status": "ok"}` |
| `POST` | `/notas` | `{"texto": "..."}` | `201` com a nota criada, ou `400` se `texto` estiver ausente ou vazio |
| `GET` | `/notas` | — | `200` com a lista completa de anotações |

Exemplo de resposta do `POST /notas`:

```json
{"id": 1, "texto": "primeira nota", "criado_em": "2026-09-18T21:08:12"}
```

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `DATA_DIR` | `/app/data` | Diretório onde o arquivo `notas.db` é criado |

## Stack

- Python 3.12 (imagem base `python:3.12-slim`)
- Flask 3.0.3
- SQLite (módulo `sqlite3` da biblioteca padrão)

## Estrutura

```
notas-docker/
├── app.py              # aplicação Flask
├── requirements.txt    # dependências (Flask)
├── Dockerfile          # receita da imagem
├── .dockerignore       # filtro do contexto de build
├── README.md
├── RELATORIO.md        # relatório da atividade
└── evidencias/         # saídas de terminal das etapas 3 a 7
```

## Como executar

### Build da imagem

```bash
docker build -t notas-api:1.0 .
```

### Criar o volume e subir o container

```bash
docker volume create notas-dados
docker run -d --name notas -p 8000:8000 -v notas-dados:/app/data notas-api:1.0
```

A API fica disponível em `http://localhost:8000`.

### Testar

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/notas \
  -H "Content-Type: application/json" \
  -d '{"texto": "primeira nota"}'

curl http://localhost:8000/notas
```

### Verificar a persistência

Destrua o container e suba outro apontando para o mesmo volume — as anotações continuam lá:

```bash
docker stop notas && docker rm notas
docker run -d --name notas2 -p 8000:8000 -v notas-dados:/app/data notas-api:1.0
curl http://localhost:8000/notas
```

### Parar e limpar

```bash
docker stop notas2 && docker rm notas2
docker volume rm notas-dados      # remove os dados permanentemente
docker image rm notas-api:1.0
```

## Execução local (sem Docker)

```bash
pip install -r requirements.txt
DATA_DIR=./data python app.py
```

No PowerShell:

```powershell
pip install -r requirements.txt
$env:DATA_DIR=".\data"; python app.py
```

## Observações

- O servidor embutido do Flask é usado por simplicidade didática. Em produção, o `CMD` deveria apontar para um servidor WSGI como Gunicorn ou uWSGI.
- A aplicação escuta em `0.0.0.0` e não em `127.0.0.1`: dentro de um contêiner, o endereço de loopback não é alcançável pelo mapeamento de portas do host.
