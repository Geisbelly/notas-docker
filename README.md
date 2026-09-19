# notas-docker

Serviço de anotações em Python empacotado em imagem Docker própria, com persistência de dados em volume nomeado.

Atividade Prática — Implementação de Serviços com Docker.

O relatório completo da atividade, com as evidências de cada etapa, está em [RELATORIO.md](RELATORIO.md).

## Descrição

API HTTP que registra anotações de texto com data e hora. Os dados são gravados em um banco SQLite dentro do diretório apontado pela variável de ambiente `DATA_DIR`, cujo padrão é `/app/data` — o ponto de montagem do volume.

Acompanha uma interface web que consome a própria API e exibe, em tempo de execução, o estado da montagem de dados, do banco e do contêiner.

## Rotas

| Método | Rota | Corpo | Resposta |
|---|---|---|---|
| `GET` | `/health` | — | `200` `{"status": "ok"}` |
| `POST` | `/notas` | `{"texto": "..."}` | `201` com a nota criada, ou `400` se `texto` estiver ausente ou vazio |
| `GET` | `/notas` | — | `200` com a lista completa de anotações |
| `GET` | `/info` | — | `200` com o estado de execução: montagem de `DATA_DIR`, banco, contêiner e runtime |
| `GET` | `/` | — | Página HTML para criar e consultar anotações pelo navegador |

Resposta do `POST /notas`:

```json
{"id": 1, "texto": "primeira nota", "criado_em": "2026-09-18T21:08:12"}
```

Trecho da resposta do `GET /info`:

```json
{
  "armazenamento": {
    "data_dir": "/app/data",
    "origem_variavel": "ambiente",
    "montagem": {
      "tipo": "volume nomeado",
      "nome": "notas-dados",
      "origem_host": "/var/lib/docker/volumes/notas-dados/_data",
      "fstype": "ext4",
      "persistente": true,
      "reencontravel": true
    }
  },
  "banco": { "bytes": 12288, "total_notas": 3, "sqlite": "3.46.1" },
  "container": { "hostname": "6856699d9cc3", "pid": 1, "e_pid_1": true, "fuso": "UTC" },
  "runtime": { "python": "3.12.14", "flask": "3.0.3", "sistema": "Debian GNU/Linux 13 (trixie)" }
}
```

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `DATA_DIR` | `/app/data` | Diretório onde o arquivo `notas.db` é criado |

## Stack

- Python 3.12 (imagem base `python:3.12-slim`)
- Flask 3.0.3 — única dependência externa
- SQLite (módulo `sqlite3` da biblioteca padrão)
- Interface web em HTML, CSS e JavaScript puros, sem CDN nem framework

## Estrutura

```
notas-docker/
├── app.py              # aplicação Flask: as cinco rotas
├── estado.py           # coleta do estado de execução, consumida por GET /info
├── templates/
│   └── index.html      # interface web servida em GET /
├── requirements.txt    # dependências (Flask)
├── Dockerfile          # receita da imagem
├── .dockerignore       # filtro do contexto de build
├── compose.yaml        # alternativa declarativa: serviço, porta, volume e healthcheck
├── README.md
├── RELATORIO.md        # relatório da atividade
└── evidencias/         # saídas de terminal das etapas 3 a 7 e do Compose
```

## Versões da imagem

| Tag | Conteúdo |
|---|---|
| `notas-api:1.0` | Escopo da atividade: as três rotas da API. É a versão documentada nas evidências do relatório |
| `notas-api:1.1` | Acrescenta a interface web (`GET /`) e a rota de estado (`GET /info`) |

Os comandos abaixo usam `1.1`. Para reproduzir exatamente o que está no relatório, troque a tag por `1.0`.

## Como executar

### Build da imagem

```bash
docker build -t notas-api:1.1 .
```

### Criar o volume e subir o contêiner

```bash
docker volume create notas-dados
docker run -d --name notas -p 8000:8000 -v notas-dados:/app/data notas-api:1.1
```

Interface web em <http://localhost:8000> e API na mesma porta.

### Testar pela linha de comando

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/notas \
  -H "Content-Type: application/json" \
  -d '{"texto": "primeira nota"}'

curl http://localhost:8000/notas
```

### Verificar a persistência

Destrua o contêiner e suba outro apontando para o mesmo volume — as anotações continuam lá:

```bash
docker stop notas && docker rm notas
docker run -d --name notas2 -p 8000:8000 -v notas-dados:/app/data notas-api:1.1
curl http://localhost:8000/notas
```

### Parar e limpar

```bash
docker stop notas2 && docker rm notas2
docker volume rm notas-dados      # remove os dados permanentemente
docker image rm notas-api:1.1
```

## Interface web

Com o contêiner no ar, acesse <http://localhost:8000>. A página permite criar e listar anotações sem `curl`, acompanha o estado da rota `/health` e apresenta o painel descrito a seguir. Todo o HTML, CSS e JavaScript é servido pelo próprio Flask a partir de `templates/index.html`, o que mantém a imagem autossuficiente e funcional sem acesso à internet.

### Painel "Estado do serviço"

Quatro grupos de informação, obtidos da rota `GET /info`:

| Grupo | Conteúdo |
|---|---|
| Armazenamento | valor de `DATA_DIR` e se veio do ambiente ou do padrão do código, **tipo de montagem**, nome do volume, caminho de origem no host, sistema de arquivos, permissão de escrita |
| Banco de dados | caminho e tamanho do `notas.db`, número e tamanho das páginas, total de anotações, datas da primeira e da última, versão do SQLite |
| Contêiner | hostname (que é o ID curto do contêiner), PID do processo e se ele é o PID 1, tempo no ar, hora e fuso internos, CPUs visíveis, limite de memória do cgroup |
| Runtime | versões de Python e Flask, distribuição base, arquitetura |

No topo do painel aparece o **veredito de persistência**, colorido conforme o caso:

| Situação | Indicação |
|---|---|
| `-v notas-dados:/app/data` | verde — volume nomeado; os dados sobrevivem e são remontáveis pelo nome |
| Sem `-v` (volume anônimo criado pela instrução `VOLUME`) | amarelo — os dados sobrevivem, porém órfãos e inviáveis de reencontrar |
| `/app/data` na camada gravável | vermelho — os dados serão perdidos no `docker rm` |

Para ver o contraste lado a lado, suba um segundo contêiner sem `-v` em outra porta:

```bash
docker run -d --name sem-volume -p 8001:8000 notas-api:1.1
```

<http://localhost:8000> mostra o veredito verde e <http://localhost:8001> o amarelo. Depois:

```bash
docker rm -f sem-volume && docker volume prune -f
```

### Como a detecção funciona

A classificação é feita **de dentro do próprio contêiner**, sem acesso ao socket do Docker. O módulo `estado.py` lê `/proc/self/mountinfo` e localiza a montagem mais específica que cobre `DATA_DIR`:

| Achado | Conclusão |
|---|---|
| A montagem é o próprio `/app/data` e o campo *root* termina em `/volumes/<nome>/_data` | volume — anônimo se o nome tiver 64 caracteres hexadecimais, nomeado caso contrário |
| A montagem é o próprio `/app/data` e o *root* está fora de `/volumes/` | bind mount |
| A montagem mais específica **não** é `/app/data` | o diretório pertence ao sistema de arquivos do contêiner: camada gravável, portanto efêmero |

O campo *root* da entrada do `mountinfo` é o que revela o caminho de origem no host, por exemplo `/var/lib/docker/volumes/notas-dados/_data`.

## Alternativa: Docker Compose

O arquivo [compose.yaml](compose.yaml) declara o serviço, o mapeamento de porta, o volume nomeado e um *healthcheck* que consulta `/health`. Ele usa a tag `notas-api:1.0`, que é a documentada no relatório e nas evidências; para subir a versão com interface web, troque a linha `image:` para `notas-api:1.1`.

Build e execução em um comando:

```bash
docker compose up -d --build
```

```bash
docker compose ps        # estado do serviço, incluindo o healthcheck
docker compose logs -f   # logs em tempo real
```

Para encerrar preservando os dados:

```bash
docker compose down
```

Para encerrar removendo também o volume, o que apaga as anotações:

```bash
docker compose down -v
```

O bloco de volumes declara `name: notas-dados` explicitamente. Sem essa chave, o Compose prefixaria o nome com o do projeto e criaria `notas-docker_notas-dados` — um volume diferente do usado nos comandos manuais.

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

Fora do contêiner, o painel de estado indica que `/app/data` não é uma montagem dedicada — comportamento esperado, já que não há Docker envolvido.

## Observações

- O servidor embutido do Flask é usado por simplicidade didática. Em produção, o `CMD` deveria apontar para um servidor WSGI como Gunicorn ou uWSGI.
- A aplicação escuta em `0.0.0.0` e não em `127.0.0.1`: dentro de um contêiner, o endereço de loopback não é alcançável pelo mapeamento de portas do host.
- Os horários gravados usam o fuso do contêiner, que é UTC na imagem `python:3.12-slim`. É por isso que o mesmo arquivo aparece com horários diferentes quando listado de dentro do contêiner e a partir do host.
- A instrução `VOLUME /app/data` no Dockerfile apenas declara o ponto de montagem. O que garante persistência recuperável é a flag `-v nome:/app/data` no `docker run`.
