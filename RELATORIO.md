# Relatório — Implementação de Serviços com Docker

**Aluna:** Geisbelly Victória
**Data:** 18 de setembro de 2026
**Repositório:** `notas-docker`

---

## 1. Ambiente utilizado

| Item | Versão / Configuração |
|---|---|
| Sistema operacional do host | Windows 11 Pro (build 10.0.26200) |
| Runtime Docker | Docker Engine 29.8.1 (Community) instalado nativamente no **WSL2 / Ubuntu** |
| containerd | v2.3.5 |
| runc | 1.5.1 |
| Imagem base | `python:3.12-slim` (Python 3.12.14, Debian trixie) |
| Framework | Flask 3.0.3 |
| Armazenamento | SQLite (`sqlite3` da biblioteca padrão) |

**Observação sobre o ambiente:** a atividade foi executada com o Docker Engine rodando diretamente dentro da distro Ubuntu do WSL2, e não pelo Docker Desktop. O Docker Desktop estava instalado, mas o serviço privilegiado `com.docker.service` não iniciava e a distro utilitária `docker-desktop` permanecia no estado `Stopped`, impedindo a conexão com o daemon. A instalação do Docker Engine nativo no WSL2 resolveu o problema e trouxe uma vantagem para a Etapa 7: o `Mountpoint` retornado pelo `docker volume inspect` é um caminho real e navegável no sistema de arquivos do Linux, o que permitiu inspecionar o volume diretamente no host.

---

## 2. O serviço implementado

Aplicação Flask com três rotas:

| Método | Rota | Comportamento |
|---|---|---|
| `GET` | `/health` | Retorna `{"status": "ok"}` |
| `POST` | `/notas` | Recebe `{"texto": "..."}`, grava com data/hora, retorna `201`. Retorna `400` se `texto` for ausente ou vazio |
| `GET` | `/notas` | Retorna todas as anotações |

O caminho do diretório de dados é lido da variável de ambiente `DATA_DIR`, com padrão `/app/data`:

```python
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "notas.db")
```

Esse contrato é o que permite testar a aplicação fora do Docker (apontando `DATA_DIR` para uma pasta local) sem alterar uma linha de código, e é o que torna o container descartável: todo o estado da aplicação está do outro lado dessa variável.

Duas decisões de implementação merecem destaque:

**Criação idempotente do esquema.** A função `init_db()` é chamada no nível do módulo e executa `CREATE TABLE IF NOT EXISTS`. Isso é o que faz a prova de persistência funcionar: quando um container novo é montado sobre um volume que já contém o banco, a instrução encontra a tabela existente e não faz nada. Sem a cláusula `IF NOT EXISTS`, o segundo container falharia ao subir.

**Consultas parametrizadas.** O `INSERT` usa placeholders `?` com os valores em tupla separada, e nunca interpolação de string. O driver do SQLite envia comando e dados por caminhos distintos, de modo que o conteúdo da anotação nunca é interpretado como SQL — prevenindo injeção de SQL.

---

## 3. Explicação linha a linha do Dockerfile

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_DIR=/app/data

EXPOSE 8000

VOLUME /app/data

CMD ["python", "app.py"]
```

### `FROM python:3.12-slim`

Define a imagem base. A tag foi escolhida em duas partes:

- **`3.12`** fixa a versão principal do Python, em vez de `latest`. Usar `latest` faria a imagem mudar sozinha ao longo do tempo, quebrando justamente a reprodutibilidade que o Docker promete.
- **`slim`** é a variante enxuta: Debian mínimo, sem compiladores nem bibliotecas de desenvolvimento. Comparativo aproximado: `python:3.12` ≈ 1 GB, `python:3.12-slim` ≈ 130 MB, `python:3.12-alpine` ≈ 50 MB. A variante Alpine é menor, mas usa `musl` em vez de `glibc`, o que quebra pacotes que dependem de *wheels* compilados para glibc. A `slim` é o equilíbrio entre tamanho e compatibilidade.

### `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1`

Duas variáveis definidas em uma única instrução (com `\` continuando a linha), para gerar uma camada em vez de duas.

- **`PYTHONUNBUFFERED=1`** desativa o buffer da saída padrão. Quando o `stdout` não é um terminal — como acontece dentro de um container — o Python acumula a saída em blocos antes de liberá-la. Sem essa variável, `docker logs` viria vazio ou atrasado, dificultando o diagnóstico. Com ela, os logs do Flask apareceram instantaneamente na Etapa 4.
- **`PYTHONDONTWRITEBYTECODE=1`** impede a geração de `__pycache__` dentro do container. Em uma imagem imutável, esses arquivos são peso morto.

### `WORKDIR /app`

Define o diretório de trabalho para todas as instruções seguintes, criando-o se não existir. Equivale a `mkdir -p /app && cd /app`, porém persistido: o `CMD` também executa a partir dali. Não se usa `RUN cd /app` porque cada `RUN` roda em um processo próprio e o `cd` se perderia.

### `COPY requirements.txt .` e `RUN pip install --no-cache-dir -r requirements.txt`

Estas duas instruções, nesta ordem e separadas do restante do código, existem por causa do **cache de camadas**.

Cada instrução do Dockerfile gera uma camada, e o Docker só reexecuta uma camada quando alguma de suas dependências muda — invalidando também todas as camadas posteriores. Como o `COPY requirements.txt .` depende apenas desse arquivo, enquanto as dependências não mudarem o `pip install` — o passo mais lento do build — é reaproveitado do cache, mesmo que o código da aplicação tenha sido totalmente reescrito.

Se a ordem fosse invertida (`COPY . .` antes do `pip install`), qualquer alteração mínima no `app.py` invalidaria a instalação e obrigaria o download de todas as dependências a cada build. A evidência prática deste efeito está na seção 4.2.

A flag **`--no-cache-dir`** impede que o pip mantenha os pacotes baixados em `~/.cache/pip`. Dentro da imagem esse cache é inútil e ficaria gravado na camada permanentemente.

### `COPY . .`

Copia o restante do código. O primeiro `.` é o contexto de build no host (a pasta onde `docker build` foi executado); o segundo é o `WORKDIR` dentro da imagem. É nesta instrução que o `.dockerignore` atua, filtrando o que não deve entrar.

### `ENV DATA_DIR=/app/data`

Torna explícito na imagem o contrato que a aplicação espera. Tecnicamente é redundante, já que o código define o mesmo valor como padrão do `os.environ.get`. Mas documenta a variável para quem inspecionar a imagem com `docker inspect`, e permite sobrescrevê-la com `docker run -e DATA_DIR=/outro/caminho` sem tocar no código.

### `EXPOSE 8000`

**Não publica porta alguma.** É apenas metadado declarando em qual porta o serviço escuta. Quem efetivamente abre o caminho entre host e container é a flag `-p 8000:8000` do `docker run`. Sem `EXPOSE`, o `-p` continua funcionando normalmente; a instrução serve para documentar a intenção e para habilitar o modo `docker run -P` (maiúsculo), que publica automaticamente as portas declaradas. A prova de que não gera conteúdo está no `docker history`, onde a camada aparece com `0B`.

### `VOLUME /app/data`

Declara que esse caminho é um ponto de montagem para dados persistentes. Tem dois efeitos distintos:

1. Se um volume nomeado for montado com `-v notas-dados:/app/data`, ele é utilizado (Etapa 5).
2. Se **nada** for montado, o Docker cria automaticamente um **volume anônimo**. Os dados sobrevivem à remoção do container, mas ficam órfãos, identificados apenas por um hash (Etapa 6).

Por convenção, `VOLUME` deve vir depois de qualquer `RUN` que escreva nesse diretório, já que escritas feitas após a declaração em tempo de build são descartadas.

### `CMD ["python", "app.py"]`

Define o comando padrão do container, na **forma exec** (lista JSON), e não na forma shell.

Na forma shell (`CMD python app.py`), o Docker executaria `/bin/sh -c "python app.py"`: o shell se tornaria o PID 1 e o Python seria um processo filho. O `docker stop` envia `SIGTERM` ao PID 1, e o shell não repassa o sinal — o container só morreria após 10 segundos, pelo `SIGKILL` de timeout. Na forma exec, o Python é o PID 1 e recebe o sinal diretamente, encerrando imediatamente. Esse comportamento foi observado na Etapa 5, onde o `docker stop` retornou em menos de um segundo.

Optou-se por `CMD` e não `ENTRYPOINT` porque `CMD` permite sobrescrever o comando na linha de execução — recurso usado na Etapa 7 para inspecionar o conteúdo da imagem com `docker run --rm notas-api:1.0 ls -la /app`.

### O `.dockerignore`

```
__pycache__/
*.pyc
*.pyo
.git/
.gitignore
venv/
.venv/
env/
data/
.env
*.md
.vscode/
.history/
evidencias/
anota*.txt
```

A linha mais importante é **`data/`**. Sem ela, a pasta local criada nos testes fora do Docker seria copiada para dentro da imagem, e as anotações de teste apareceriam no container da Etapa 6 — o que invalidaria completamente a demonstração de efemeridade, já que os dados viriam da imagem e não de qualquer volume.

Um detalhe que exigiu atenção: usou-se `anota*.txt` e não `*.txt`. Um padrão genérico `*.txt` excluiria também o `requirements.txt`, e o build falharia na instrução `COPY requirements.txt .`.

---

## 4. Etapa 3 — Build

### 4.1 Comando e saída

```bash
docker build -t notas-api:1.0 .
```

Saída completa em [`evidencias/etapa3-build.txt`](evidencias/etapa3-build.txt).

### 4.2 Prova do cache de camadas

Trecho da saída de um build executado após alteração apenas no código da aplicação:

```
#6 [2/5] WORKDIR /app
#6 CACHED

#7 [3/5] COPY requirements.txt .
#7 CACHED

#8 [4/5] RUN pip install --no-cache-dir -r requirements.txt
#8 CACHED

#9 [5/5] COPY . .
#9 DONE 0.0s
```

As três primeiras etapas foram reaproveitadas do cache e apenas o `COPY . .` foi reexecutado. O build completo levou cerca de 1 segundo, contra 12 segundos do build inicial. Essa é a confirmação prática da ordenação adotada no Dockerfile.

### 4.3 Tamanho final da imagem

```
IMAGE           ID             DISK USAGE   CONTENT SIZE   EXTRA
notas-api:1.0   bea37fea7e08        195MB         47.8MB
```

Arquivo: [`evidencias/etapa3-image-ls.txt`](evidencias/etapa3-image-ls.txt).

O Docker 29 substituiu a antiga coluna `SIZE` por duas métricas distintas:

- **DISK USAGE (195 MB)** — o espaço real ocupado no disco, descompactado. Equivale ao antigo `SIZE`.
- **CONTENT SIZE (47.8 MB)** — o tamanho compactado, que seria transferido em um `docker push` ou `docker pull`.

A distinção é relevante: uma representa o custo de armazenamento local, a outra o custo de distribuição.

### 4.4 Camadas da imagem

Saída completa em [`evidencias/etapa3-history.txt`](evidencias/etapa3-history.txt). Resumo:

| Origem | Camada | Tamanho |
|---|---|---|
| Base | `debian trixie` (rootfs) | 87.5 MB |
| Base | `apt-get` (ca-certificates, netbase, tzdata) | 13.2 MB |
| Base | compilação do CPython 3.12.14 | 41.4 MB |
| Base | links simbólicos (`idle3`, `pip3`, `python3`…) | 16.4 kB |
| Base | `CMD ["python3"]` | 0 B |
| **Própria** | `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1` | **0 B** |
| **Própria** | `WORKDIR /app` | 8.19 kB |
| **Própria** | `COPY requirements.txt .` | 12.3 kB |
| **Própria** | `RUN pip install --no-cache-dir -r requirements.txt` | **5.64 MB** |
| **Própria** | `COPY . .` | 20.5 kB |
| **Própria** | `ENV DATA_DIR=/app/data` | **0 B** |
| **Própria** | `EXPOSE 8000` | **0 B** |
| **Própria** | `VOLUME [/app/data]` | **0 B** |
| **Própria** | `CMD ["python" "app.py"]` | **0 B** |

Três conclusões:

1. **Cerca de 142 MB dos 195 MB — aproximadamente 73% — vêm da imagem base.** A aplicação inteira, Flask incluído, custa menos de 6 MB. Isso demonstra que a escolha da tag base é a decisão de maior impacto no tamanho final da imagem, muito mais do que qualquer otimização no código da aplicação.
2. **`ENV`, `EXPOSE`, `VOLUME` e `CMD` aparecem com `0 B`.** Elas gravam metadados no *manifest* da imagem, não arquivos no sistema de arquivos. É a evidência concreta de que `EXPOSE` não abre porta alguma: se abrisse, teria custo.
3. **`COPY requirements.txt .` (12.3 kB) está em uma camada separada de `COPY . .` (20.5 kB)** — é essa separação que preserva o cache do `pip install`.

### 4.5 Efeito do `.dockerignore`

Uma versão inicial do `.dockerignore` não excluía a pasta `.history/` (extensão *Local History* do VS Code), o diretório `evidencias/` nem o arquivo de anotações pessoais. A comparação entre os dois builds:

| Build | Contexto transferido | Camada `COPY . .` |
|---|---|---|
| `.dockerignore` incompleto | 40.32 kB | 168 kB |
| `.dockerignore` completo | **1.90 kB** | **20.5 kB** |

A camada caiu de 168 kB para 20.5 kB. A verificação do conteúdo final da imagem confirma que apenas os arquivos da aplicação foram copiados:

```
$ docker run --rm notas-api:1.0 ls -la /app
total 28
drwxr-xr-x 1 root root 4096 Sep 18 21:05 .
drwxr-xr-x 1 root root 4096 Sep 18 21:05 ..
-rwxrwxrwx 1 root root  119 Sep 18 20:09 .dockerignore
-rwxrwxrwx 1 root root  264 Sep 18 19:47 Dockerfile
-rwxrwxrwx 1 root root 1639 Sep 18 20:39 app.py
drwxr-xr-x 2 root root 4096 Sep 18 21:05 data
-rwxrwxrwx 1 root root   14 Sep 18 20:08 requirements.txt
```

O diretório `data` que aparece na listagem não veio do `COPY`: foi criado pelo Docker como ponto de montagem, em decorrência da instrução `VOLUME /app/data`. Como este `docker run` não recebeu `-v`, trata-se de um volume anônimo — o mesmo mecanismo demonstrado na Etapa 6.

---

## 5. Etapa 4 — Execução com volume nomeado

### 5.1 Criação do volume

```bash
$ docker volume create notas-dados
notas-dados

$ docker volume ls
DRIVER    VOLUME NAME
local     notas-dados
```

### 5.2 Execução do container

```bash
$ docker run -d --name notas -p 8000:8000 -v notas-dados:/app/data notas-api:1.0
919a24c32c74c1bece6bcf0fe8a5ef70b2860172480aa033f6b930aedcae324f

$ docker ps
CONTAINER ID   IMAGE           COMMAND           CREATED          STATUS          PORTS                                         NAMES
919a24c32c74   notas-api:1.0   "python app.py"   10 seconds ago   Up 10 seconds   0.0.0.0:8000->8000/tcp, [::]:8000->8000/tcp   notas
```

Significado das flags:

| Flag | Função |
|---|---|
| `-d` | *detached* — executa em segundo plano |
| `--name notas` | nome fixo, em vez do nome aleatório gerado pelo Docker |
| `-p 8000:8000` | publica a porta no formato `hostPort:containerPort`. **É esta flag que abre o caminho**, não o `EXPOSE` |
| `-v notas-dados:/app/data` | monta o volume nomeado. Como o lado esquerdo é um nome e não um caminho iniciado por `/` ou `.`, o Docker interpreta como volume nomeado e não como *bind mount* |

### 5.3 Logs do container

```bash
$ docker logs notas
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:8000
 * Running on http://172.17.0.2:8000
Press CTRL+C to quit
```

Três observações:

- **`Running on all addresses (0.0.0.0)`** confirma a decisão tomada no código. Se a aplicação escutasse no padrão do Flask (`127.0.0.1`), o `-p` entregaria o tráfego na interface de rede do container e o Flask o ignoraria: o `curl` no host retornaria "empty reply" enquanto o `docker ps` mostraria o container perfeitamente saudável.
- **`Running on http://172.17.0.2:8000`** é o endereço do container na rede bridge `docker0`, evidenciando que ele possui pilha de rede própria, isolada do host.
- O **`WARNING`** do Flask é pertinente: o servidor embutido não é adequado para produção. A correção seria trocar o `CMD` por um servidor WSGI como Gunicorn. Para o escopo desta atividade, cujo foco é empacotamento e persistência, o servidor de desenvolvimento é suficiente.

### 5.4 Inserção das anotações

```bash
curl -X POST http://localhost:8000/notas -H "Content-Type: application/json" -d '{"texto": "primeira nota"}'
curl -X POST http://localhost:8000/notas -H "Content-Type: application/json" -d '{"texto": "segunda nota"}'
curl -X POST http://localhost:8000/notas -H "Content-Type: application/json" -d '{"texto": "terceira nota"}'
```

Listagem resultante ([`evidencias/etapa4-notas.txt`](evidencias/etapa4-notas.txt)):

```json
[{"criado_em":"2026-09-18T21:08:12","id":1,"texto":"primeira nota"},
 {"criado_em":"2026-09-18T21:08:18","id":2,"texto":"segunda nota"},
 {"criado_em":"2026-09-18T21:08:21","id":3,"texto":"terceira nota"}]
```

**Nota sobre o horário:** os timestamps `21:08` estão em UTC, fuso padrão da imagem `python:3.12-slim`, enquanto o relógio do host estava em `18:08` (BRT, UTC−03). Não é um erro: o container possui configuração de fuso independente do host. Essa diferença reaparece de forma útil na Etapa 7.

---

## 6. Etapa 5 — Prova de persistência

### 6.1 Destruição completa do container

```bash
$ docker stop notas
$ docker rm notas

$ docker ps -a
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
```

Arquivo: [`evidencias/etapa5-1-container-removido.txt`](evidencias/etapa5-1-container-removido.txt). Nenhum container existe mais. A camada gravável foi destruída junto.

O `docker stop` retornou em menos de um segundo — consequência direta do `CMD` na forma exec, conforme explicado na seção 3.

### 6.2 O volume sobreviveu

```bash
$ docker volume ls
DRIVER    VOLUME NAME
local     notas-dados
```

```bash
$ docker volume inspect notas-dados
[
    {
        "CreatedAt": "2026-09-18T18:05:58-03:00",
        "Driver": "local",
        "Labels": null,
        "Mountpoint": "/var/lib/docker/volumes/notas-dados/_data",
        "Name": "notas-dados",
        "Options": null,
        "Scope": "local"
    }
]
```

Arquivos: [`evidencias/etapa5-2-volume-ls.txt`](evidencias/etapa5-2-volume-ls.txt) e [`evidencias/etapa5-3-volume-inspect.txt`](evidencias/etapa5-3-volume-inspect.txt).

O ponto conceitual: o volume aparece na listagem **mesmo sem nenhum container existir**. Ele não pertence a container algum — tem ciclo de vida próprio, gerenciado pelo Docker Engine.

### 6.3 Conteúdo do volume sem a aplicação

Montando o volume em um container descartável de Alpine, apenas para leitura:

```bash
$ docker run --rm -v notas-dados:/v alpine ls -la /v
total 20
drwxr-xr-x    2 root     root          4096 Sep 18 21:08 .
drwxr-xr-x    1 root     root          4096 Sep 18 21:10 ..
-rw-r--r--    1 root     root         12288 Sep 18 21:08 notas.db
```

Arquivo: [`evidencias/etapa5-4-conteudo-volume.txt`](evidencias/etapa5-4-conteudo-volume.txt).

O `notas.db` existe independentemente da imagem `notas-api`, do container destruído e da própria aplicação Python — foi lido por um container Alpine que não tem Python instalado.

### 6.4 Novo container, mesmo volume

```bash
docker run -d --name notas2 -p 8000:8000 -v notas-dados:/app/data notas-api:1.0
```

Container novo, com identificador diferente do anterior (`919a24c32c74`) e sistema de arquivos criado do zero a partir da mesma imagem.

### 6.5 Resultado

```bash
$ curl -s http://localhost:8000/notas
[{"criado_em":"2026-09-18T21:08:12","id":1,"texto":"primeira nota"},
 {"criado_em":"2026-09-18T21:08:18","id":2,"texto":"segunda nota"},
 {"criado_em":"2026-09-18T21:08:21","id":3,"texto":"terceira nota"}]
```

Arquivo: [`evidencias/etapa5-5-notas-apos-recriar.txt`](evidencias/etapa5-5-notas-apos-recriar.txt).

As três anotações reapareceram com os mesmos `id` e os mesmos `criado_em`. A comparação byte a byte confirma:

```bash
$ diff evidencias/etapa4-notas.txt evidencias/etapa5-5-notas-apos-recriar.txt && echo "IDENTICOS - PERSISTENCIA COMPROVADA"
IDENTICOS - PERSISTENCIA COMPROVADA
```

### 6.6 O que foi destruído e o que sobreviveu

| Destruído com `docker rm` | Sobreviveu |
|---|---|
| Camada gravável do container | Volume `notas-dados` |
| Processo e PID | Arquivo `notas.db` (12288 bytes) |
| Endereço `172.17.0.2` e interfaces de rede | Os três registros, com `id` e timestamps intactos |
| Qualquer escrita fora de `/app/data` | |

O mecanismo que torna isso possível, do lado da aplicação, é o `CREATE TABLE IF NOT EXISTS`: o `init_db()` do container novo encontra a tabela já existente no arquivo do volume e não faz nada, de modo que a aplicação se reconecta a um banco que já possui estado.

---

## 7. Etapa 6 — Contraexemplo (efemeridade)

### 7.1 Estado inicial dos volumes

```bash
$ docker volume ls -f dangling=true
DRIVER    VOLUME NAME
local     notas-dados
```

Arquivo: [`evidencias/etapa6-0-orfaos-antes.txt`](evidencias/etapa6-0-orfaos-antes.txt).

Observação terminológica: o filtro `dangling=true` significa "não utilizado por nenhum container no momento", e não "anônimo". Por isso o `notas-dados` aparece aqui — ele estava ocioso, já que o `notas2` havia sido removido.

### 7.2 Container sem `-v`

```bash
$ docker run -d --name efemero -p 8000:8000 notas-api:1.0
$ curl -s http://localhost:8000/notas
[]
```

Primeira constatação: as três notas da Etapa 5 **não aparecem**, embora o volume `notas-dados` ainda exista no host. Um volume só é alcançável se for explicitamente montado.

### 7.3 Onde os dados vão parar

A inspeção dos *mounts* do container revela que o Docker criou um **volume anônimo**, em decorrência da instrução `VOLUME /app/data` do Dockerfile:

```bash
$ docker volume ls
DRIVER    VOLUME NAME
local     ab7a09a5fd79866ad81885efc1b90af4e3fc30881bcc3f6257896afd6f9a2cca
local     notas-dados
```

### 7.4 Inserção, destruição e recriação

```bash
$ curl -s http://localhost:8000/notas
[{"criado_em":"2026-09-18T21:16:00","id":1,"texto":"nota efemera A"},
 {"criado_em":"2026-09-18T21:16:06","id":2,"texto":"nota efemera B"}]
```

```bash
$ docker stop efemero && docker rm efemero
$ docker run -d --name efemero2 -p 8000:8000 notas-api:1.0
$ curl -s http://localhost:8000/notas
[]
```

Arquivos: [`evidencias/etapa6-1-antes-de-destruir.txt`](evidencias/etapa6-1-antes-de-destruir.txt) e [`evidencias/etapa6-2-apos-destruir.txt`](evidencias/etapa6-2-apos-destruir.txt).

O `diff` entre os dois acusa divergência — exatamente o inverso do resultado da Etapa 5.

### 7.5 Volumes órfãos acumulados

```bash
$ docker volume ls -f dangling=true
DRIVER    VOLUME NAME
local     ab7a09a5fd79866ad81885efc1b90af4e3fc30881bcc3f6257896afd6f9a2cca
local     notas-dados
```

Arquivo: [`evidencias/etapa6-3-orfaos-depois.txt`](evidencias/etapa6-3-orfaos-depois.txt). Comparando com o estado inicial (seção 7.1), o volume anônimo `ab7a09a5fd79…` foi deixado para trás pelo ciclo de subir-e-destruir sem `-v`.

### 7.6 Explicação do motivo

A explicação usual é que "os dados ficam na camada gravável do container e morrem com o `docker rm`". Isso é verdadeiro em geral, mas **não descreve com precisão o que aconteceu neste caso** — e a diferença é instrutiva.

Como o Dockerfile declara `VOLUME /app/data`, os dados **nunca chegaram à camada gravável**. O Docker criou automaticamente um volume anônimo e montou ali. Ao executar `docker rm`, o container foi destruído, mas **o volume anônimo permaneceu no disco, órfão** — identificado apenas por um hash de 64 caracteres, sem nome, praticamente impossível de reencontrar na operação do dia a dia.

O container seguinte, por sua vez, recebeu um volume anônimo **diferente e vazio**. Do ponto de vista da aplicação, o efeito é idêntico à perda total: os dados são inacessíveis. Do ponto de vista do disco, a situação é pior que a perda — é lixo acumulando silenciosamente a cada ciclo.

Disso decorre a conclusão precisa: **o que garante a persistência não é a instrução `VOLUME` no Dockerfile, e sim a flag `-v nome:/caminho` no `docker run`.** A instrução apenas declara a intenção de que aquele diretório guarde estado; o nome é o que torna o dado reencontrável.

| Cenário | Onde os dados ficam | Sobrevive ao `rm`? | Reencontrável? |
|---|---|---|---|
| `-v notas-dados:/app/data` | Volume nomeado | Sim | **Sim** |
| Sem `-v`, com `VOLUME` no Dockerfile | Volume anônimo | Sim, mas órfão | **Não** |
| Sem `-v` e sem `VOLUME` | Camada gravável | **Não** | Não |

---

## 8. Etapa 7 — Inspeção

### Pergunta 1 — Onde, no host, o Docker armazena fisicamente o volume `notas-dados`?

```bash
$ docker volume inspect notas-dados
[
    {
        "CreatedAt": "2026-09-18T18:05:58-03:00",
        "Driver": "local",
        "Labels": null,
        "Mountpoint": "/var/lib/docker/volumes/notas-dados/_data",
        "Name": "notas-dados",
        "Options": null,
        "Scope": "local"
    }
]
```

Arquivo: [`evidencias/etapa7-1-inspect.txt`](evidencias/etapa7-1-inspect.txt).

**Resposta:** em `/var/lib/docker/volumes/notas-dados/_data`, seguindo a estrutura `<data-root>/volumes/<nome>/_data`. O driver `local` indica armazenamento no disco da própria máquina, e o escopo `local` indica que o volume existe apenas nesta instalação do Docker.

Verificação direta no sistema de arquivos do host:

```bash
$ sudo ls -la /var/lib/docker/volumes/notas-dados/_data
total 20
drwxr-xr-x 2 root root  4096 Sep 18 18:08 .
drwx-----x 3 root root  4096 Sep 18 18:05 ..
-rw-r--r-- 1 root root 12288 Sep 18 18:08 notas.db
```

Arquivo: [`evidencias/etapa7-2-mountpoint-host.txt`](evidencias/etapa7-2-mountpoint-host.txt).

O `sudo` é necessário porque `/var/lib/docker` pertence ao root — o acesso aos dados de volumes é privilegiado, o que constitui uma característica de segurança.

**Ressalva importante sobre o Windows:** como esta atividade usou o Docker Engine nativo no WSL2, esse caminho existe no sistema de arquivos da distro Ubuntu e é acessível, como o comando acima demonstra. Caso o Docker Desktop estivesse em uso, o `Mountpoint` reportaria o mesmo caminho Linux, porém ele estaria dentro da máquina virtual utilitária do Docker Desktop, **invisível a partir do `C:\`**. Essa é uma fonte frequente de confusão sobre volumes no Windows.

### Pergunta 2 — Qual é o conteúdo do diretório `/app/data` dentro do container?

```bash
$ docker exec notas2 ls -la /app/data
total 20
drwxr-xr-x 2 root root  4096 Sep 18 21:08 .
drwxr-xr-x 1 root root  4096 Sep 18 21:18 ..
-rw-r--r-- 1 root root 12288 Sep 18 21:08 notas.db
```

Arquivo: [`evidencias/etapa7-3-conteudo-container.txt`](evidencias/etapa7-3-conteudo-container.txt).

**Resposta:** um único arquivo, `notas.db`, com 12288 bytes — o banco SQLite contendo a tabela `notas` e os três registros.

Comparando esta listagem com a do host (Pergunta 1), nota-se que o **tamanho é idêntico (12288 bytes)** e que apenas a representação do horário difere: `18:08` no host e `21:08` no container. Essa diferença de três horas é justamente o fuso — o host em BRT (UTC−03) e o container em UTC. Não são duas cópias sincronizadas: **é o mesmo arquivo, o mesmo inode, visto de dentro do namespace de montagem do container**. Essa é a essência técnica de um volume.

### Pergunta 3 — O que acontece com os dados ao executar `docker volume rm notas-dados` com o container parado e removido?

A resposta se divide em três constatações, cada uma verificada experimentalmente.

**3a. Com um container ainda existindo, o Docker recusa a remoção.**

A tentativa de remover o volume enquanto o container `notas2` existia (mesmo parado) retornou erro informando que o volume está em uso, acompanhado do ID do container. Existe, portanto, uma trava de integridade referencial: o Docker não permite remover um volume referenciado por um container existente.

**3b. Com o container removido, a remoção é executada sem confirmação.**

```bash
$ docker stop notas2 && docker rm notas2
$ docker volume rm notas-dados
$ docker volume ls
DRIVER    VOLUME NAME
```

Arquivo: [`evidencias/etapa7-4-volume-removido.txt`](evidencias/etapa7-4-volume-removido.txt). A listagem ficou vazia.

**3c. Os dados são irrecuperáveis, e o Docker não sinaliza a perda.**

```bash
$ docker run -d --name notas3 -p 8000:8000 -v notas-dados:/app/data notas-api:1.0
$ curl -s http://localhost:8000/notas
[]
```

Arquivo: [`evidencias/etapa7-5-apos-volume-rm.txt`](evidencias/etapa7-5-apos-volume-rm.txt).

Observe o comportamento: o Docker **não emitiu erro** ao receber a ordem de montar um volume inexistente. Ele simplesmente **criou um novo volume vazio** com aquele nome. Esse detalhe é traiçoeiro na operação real: é possível acreditar que se reconectou a uma base existente e, na verdade, ter começado do zero silenciosamente.

**Resposta consolidada:** a remoção é **permanente e imediata**. O diretório `_data` é apagado do disco do host. Não há lixeira, não há `undo`, e o comando não solicita confirmação. A única proteção existente é a trava descrita em 3a, que cobre apenas volumes referenciados por containers existentes — um volume ocioso é removido sem qualquer aviso. A recuperação só seria possível a partir de backup externo previamente realizado, por exemplo:

```bash
docker run --rm -v notas-dados:/v -v $(pwd):/backup alpine tar czf /backup/notas.tar.gz /v
```

### Tabela-resumo

| Pergunta | Resposta | Evidência |
|---|---|---|
| Onde fica no host? | `/var/lib/docker/volumes/notas-dados/_data`, driver `local`, gerenciado pelo Docker Engine | `docker volume inspect` + `ls` no caminho real |
| Conteúdo de `/app/data`? | O arquivo `notas.db` (12288 bytes); mesmo inode visto do host, diferindo apenas no fuso exibido | `docker exec ls -la` comparado ao `ls` do host |
| E o `docker volume rm`? | Apagamento permanente, sem lixeira nem confirmação. Bloqueado se houver container referenciando; um `run` posterior recria o volume vazio, sem erro | Erro de volume em uso + listagem vazia + `[]` no `curl` |

---

## 9. Dificuldades e aprendizados

> **Rascunho baseado no que efetivamente ocorreu durante a execução. Revise e reescreva na sua voz antes de entregar — esta seção vale mais quando soa como relato pessoal.**

A maior dificuldade não esteve no Docker em si, mas em colocá-lo para funcionar. O Docker Desktop estava instalado e o cliente `docker` respondia normalmente no PowerShell, o que dava a impressão de que tudo estava certo — mas toda tentativa de comando falhava com `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`. Levei um tempo até entender que cliente e servidor são componentes separados: o CLI estava lá, o daemon não. Investigando, descobri que o serviço `com.docker.service` permanecia parado e a distro utilitária `docker-desktop` do WSL2 nunca saía do estado `Stopped`. Mesmo iniciando a aplicação manualmente, ela subia os processos e encerrava sozinha depois de alguns minutos, sem mensagem de erro útil.

A saída foi instalar o Docker Engine nativamente dentro da distro Ubuntu que eu já tinha no WSL2. Funcionou de primeira e, no fim, foi melhor para a atividade: com o Engine rodando diretamente no Linux, o `Mountpoint` retornado pelo `docker volume inspect` é um caminho real que dá para abrir com `ls`, o que permitiu responder a Pergunta 1 da Etapa 7 com evidência concreta em vez de apenas citar a documentação. Se eu tivesse conseguido usar o Docker Desktop, esse caminho estaria escondido dentro de uma VM e eu não teria enxergado o arquivo.

Logo depois tropecei em outro detalhe: mesmo após rodar `sudo usermod -aG docker $USER`, todos os comandos continuavam retornando `permission denied` no socket. Passei a usar `sudo` em tudo, até perceber que mudanças de grupo só têm efeito em sessões novas — bastava sair e entrar de novo no WSL. Foi um aprendizado útil sobre como o Linux resolve permissões, e também sobre por que mascarar o problema com `sudo` é má ideia: o acesso ao `docker.sock` equivale a acesso root na máquina, coisa que o próprio script de instalação avisa na saída.

Houve ainda um conjunto de problemas causados por escrever arquivos no Windows e processá-los no Linux. Os arquivos criados com `Out-File -Encoding utf8` saíram com BOM, aquela sequência invisível de três bytes no início — o que teria quebrado o Dockerfile com um erro `unknown instruction`. E como as quebras de linha eram CRLF, comandos `sed` com âncora de fim de linha simplesmente não encontravam o que deveriam encontrar, porque havia um `\r` invisível antes do fim. Passei a verificar arquivos com `od -c` e `cat -A` em vez de confiar no que o editor mostrava.

No Docker propriamente dito, o conceito que mais mudou minha compreensão foi o de **camadas**. Ver na saída do `docker history` que `ENV`, `EXPOSE`, `VOLUME` e `CMD` ocupam `0 B` tornou concreto algo que eu tinha lido mas não havia assimilado: essas instruções são metadados, não conteúdo. Ficou claro, em particular, que `EXPOSE` não abre porta alguma — quem publica é o `-p` do `docker run`. E o teste de cache foi muito ilustrativo: alterar apenas o `app.py` e ver o `pip install` sair como `CACHED`, reduzindo o build de 12 segundos para 1, mostrou exatamente por que o `requirements.txt` é copiado separadamente.

O aprendizado mais importante, porém, veio da Etapa 6. Eu esperava que, sem a flag `-v`, os dados fossem parar na camada gravável e desaparecessem no `docker rm`. Mas como meu Dockerfile declara `VOLUME /app/data`, o que aconteceu foi diferente: o Docker criou um volume **anônimo** a cada execução. Os dados tecnicamente sobreviveram à remoção do container — só que identificados por um hash de 64 caracteres, sem nome, impossíveis de reencontrar na prática. Cada ciclo deixou mais lixo no disco. Isso me fez reformular a conclusão de forma mais precisa: **o que garante persistência não é a instrução `VOLUME` no Dockerfile, é o nome no `-v` do `docker run`**. A instrução declara a intenção; o nome é o que torna o dado recuperável.

Por fim, a Etapa 7 trouxe a constatação que mais me marcou. Ao comparar o `ls` do host com o `ls` de dentro do container, vi o mesmo arquivo de 12288 bytes aparecer com horários diferentes — `18:08` de um lado, `21:08` do outro. A princípio pensei em erro; era o fuso, com o container em UTC e o host em BRT. Percebi então que não se tratava de duas cópias sincronizadas, mas do mesmo arquivo visto de dois namespaces distintos. Foi o momento em que a ideia de volume deixou de ser uma regra decorada e passou a fazer sentido de verdade.

---

## 10. Conclusão

A atividade demonstrou, com evidências reproduzíveis, que:

1. Uma imagem própria construída a partir de `python:3.12-slim` empacota aplicação, dependências e configuração em um artefato imutável de 195 MB, dos quais cerca de 73% vêm da imagem base.
2. A ordenação das instruções do Dockerfile tem efeito mensurável: separar a cópia do `requirements.txt` reduziu um rebuild de 12 para 1 segundo.
3. O sistema de arquivos de um container é efêmero, mas volumes nomeados sobrevivem à sua destruição — comprovado por comparação byte a byte entre listagens obtidas antes e depois de destruir e recriar o container.
4. Sem montagem nomeada, os dados se tornam inacessíveis ainda que fisicamente sobrevivam em volumes anônimos órfãos.
5. Volumes possuem ciclo de vida independente e sua remoção é permanente, sem confirmação e sem recuperação.
