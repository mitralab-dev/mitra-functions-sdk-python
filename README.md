# Mitra Functions SDK for Python

SDK Python para Server Functions da Mitra: dá acesso a usuário atual, entidades, custom queries, Functions, integrações e arquivos do app em que a Function roda. App de browser usa outro pacote, o `@mitralab.io/platform-sdk`.

## Instalação

```bash
pip install mitra-functions-sdk
```

Requer Python 3.11 ou mais novo. O pacote é importado como `mitra_functions_sdk` e depende só do `httpx`. A API é síncrona, como o runner de Functions Python.

## Início rápido

Dentro de uma Server Function invocada por um usuário, `create_client()` sem argumento lê a configuração que o runtime injeta. Use o client como context manager para que as conexões sejam fechadas no fim:

```python
from mitra_functions_sdk import MitraApiError, create_client


def handler(event: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    with create_client() as mitra:
        orders = mitra.entities.table("Order")
        created = orders.create({"customerId": event["customerId"], "status": "pending"})
        try:
            execution = mitra.functions.execute("notify-order", {"orderId": created["id"]})
        except MitraApiError as error:
            return {"order": created, "notification": None, "error": error.code}
        return {"order": created, "notification": execution}
```

Execução sem usuário que invoca, como passo de workflow, não recebe essas variáveis, e `create_client()` lança `MitraConfigError`. Nesse caso, e fora do runtime, passe a configuração explícita com `create_client(MitraClientConfig(...))`, ou um mapping com `create_client_from_environment(env)`, útil em teste.

## O que dá para fazer

- `mitra.auth.me()`: usuário atual e o tenant dele.
- `mitra.entities.table("Nome")`: `list`, `filter`, `get`, `create`, `bulk_create`, `update`, `delete` e `delete_many` sobre registros de uma tabela.
- `mitra.queries.execute(query_id, parameters)`: executa uma custom query do app.
- `mitra.functions`: `execute` espera o resultado, `execute_async` devolve a execução para acompanhar com `get_execution`, e `cancel_execution` cancela.
- `mitra.integration`: `execute_resource` chama um recurso de integração e `execute` chama uma configuração de template.
- `mitra.files`: `get`, `get_url`, `download`, `upload` e `delete` sobre arquivos do app; veja [Arquivos](#arquivos).

## Arquivos

A API de arquivos do Data Manager confere a permissão, registra o arquivo e assina um link; os bytes vão direto ao storage por esse link, que vale poucos minutos.

```python
with create_client() as mitra:
    report = mitra.files.upload(
        csv_bytes,
        name="vendas.csv",
        content_type="text/csv",
        kind="TEMPORARY",
        visibility="RESTRICTED",
    )
    content = mitra.files.download(report["id"])
```

| Método | Efeito |
|---|---|
| `get(file_id)` | metadado (`FileMetadata`), com o dono em `ownerUserId` |
| `get_url(file_id)` | link de leitura (`FileReadUrl`), que vale 5 minutos |
| `download(file_id)` | pede o link e devolve o conteúdo em `bytes` |
| `upload(content, *, name, kind, visibility, content_type="application/octet-stream", app_owned=False)` | pede o envio, manda os bytes ao link devolvido e confirma; devolve o arquivo `READY` |
| `delete(file_id)` | apaga o arquivo |

`kind` é `TEMPORARY`, que vence 7 dias depois do pedido de envio, ou `PERMANENT`. `visibility` é `PRIVATE` (só o dono), `RESTRICTED` (o dono ou uma Server Function do app que roda em nome de um usuário) ou `APP` (quem tem leitura de arquivos no app). `app_owned=True` cria arquivo do app, sem dono, e pede `visibility="APP"`. `content` precisa ser `bytes`, porque o tamanho vai assinado no link.

Garantias:

- O pedido ao storage vai ao endereço que a API devolveu, com o método e só os cabeçalhos que ela devolveu. Não leva o token nem o que o `http_client` acrescenta (cabeçalhos padrão, autenticação, cookies, event hooks), e um redirect é recusado.
- A URL do pedido ao storage nunca aparece em mensagem de erro, `repr`, exceção encadeada nem no log. Num erro de envio, de confirmação ou de leitura, ela também não fica nas variáveis locais que um traceback com `capture_locals` mostra (Sentry, `pytest --showlocals`). O `httpx.Client` registra em INFO a URL de cada pedido, por isso o pedido ao storage sai pelo transport do client, abaixo dessa camada. Em DEBUG, o httpcore registra o host, a porta e os cabeçalhos da resposta do storage, sem o caminho nem a query do pedido.
- Falha no envio dos bytes, inclusive `412` e erro de rede, apaga o arquivo `PENDING` antes de lançar `MitraFileTransferError` com `step="send"`, e `cleaned_up` diz se a exclusão funcionou.
- Falha na confirmação também lança `MitraFileTransferError`, com `step="confirm"` e o `file_id`. Nesse passo `cleaned_up` é sempre `False`, porque a SDK não apaga nada, e o erro da chamada de confirmação fica em `__cause__`; um `FILE_SIZE_MISMATCH` ali quer dizer que a API já descartou o arquivo. Para seguir, `get(file_id)` mostra se o arquivo ficou `READY`, o que acontece quando só a resposta se perdeu; se ele seguir `PENDING`, apague com `delete(file_id)` e envie de novo.

Erros da API, como `404 NOT_FOUND` para arquivo que não existe ou que o chamador não pode ver, `413 FILE_TOO_LARGE`, `409 FILE_QUOTA_REACHED` e `429`, chegam como `MitraApiError`. Com a feature de arquivos desligada no workspace, toda rota responde `404`. O `timeout_seconds` vale também no storage, por operação de rede (conectar, ler, escrever), e não pela transferência inteira.

Fora do escopo: envio em partes, retomada, cache de link e link de vários arquivos numa chamada.

## Configuração

Cada campo aceita dois nomes de variável. Quando os dois existem, vale o primeiro da coluna. No runtime de Functions, os nomes da direita já vêm preenchidos quando um usuário invoca a Function.

| Variável | Campo | Obrigatória | Uso |
|---|---|---|---|
| `MITRA_API_URL` ou `MITRA_BASE_URL` | `api_url` | sim | URL base HTTP(S) do API gateway, sem credencial, query ou fragmento; o `/legacy` no fim de `MITRA_BASE_URL` é removido |
| `MITRA_PLATFORM_ACCESS_TOKEN` ou `MITRA_TOKEN` | `access_token` | sim | token de acesso da execução, enviado como `Bearer` |
| `MITRA_APP_ID` ou `MITRA_PROJECT_ID` | `app_id` | sim | app em que as chamadas acontecem, enviado em `X-App-Id` |
| `MITRA_DATA_SOURCE_ID` | `data_source_id` | não | data source das custom queries |
| | `timeout_seconds` | não | prazo por requisição em segundos, padrão `10.0` |
| | `http_client` | não | `httpx.Client` próprio; o SDK não fecha um client que não criou |

O token e o `http_client` ficam fora do `repr` da configuração.

## Erros

Todas as exceções herdam de `MitraSdkError`. `MitraApiError`, `MitraNetworkError` e `MitraResponseError` trazem `status`, `code`, `details`, `request_id` e `retryable`. O token nunca aparece nesses campos nem na mensagem.

| Classe | Quando |
|---|---|
| `MitraConfigError` | configuração ausente ou inválida, ou custom query sem data source; também é `ValueError` |
| `MitraApiError` | a API respondeu com erro HTTP |
| `MitraNetworkError` | timeout (`REQUEST_TIMEOUT`) ou falha de rede (`NETWORK_ERROR`) |
| `MitraResponseError` | resposta de sucesso vazia, com JSON inválido ou fora do formato esperado |
| `MitraFileTransferError` | os bytes de um arquivo não chegaram ao storage ou não voltaram dele, ou o envio não foi confirmado; traz `file_id`, `step` (`send`, `confirm` ou `download`), `status` e `cleaned_up`, e não traz `code`, `retryable` nem `request_id`. `status` é a resposta do storage, `None` quando ele não respondeu ou quando o passo não envolve o storage (`confirm`) |

ID vazio, `.` ou `..` e `delete_many({})` lançam `ValueError` antes de qualquer requisição, e `files.upload` com `content` que não é `bytes` lança `TypeError`.

## Boas práticas

- Use `with create_client() as mitra:` ou chame `mitra.close()` no fim, para devolver as conexões.
- O SDK faz uma tentativa por requisição e não repete sozinho, para não executar uma escrita duas vezes. `retryable` indica falha possivelmente temporária, não que a escrita deixou de acontecer: um timeout ou 5xx pode chegar depois de a API gravar. Só repita uma escrita quando ela for idempotente.
- O prazo padrão é de 10 segundos por requisição. Quando uma chamada precisar de mais, ajuste mantendo a leitura do ambiente: `create_client(dataclasses.replace(MitraClientConfig.from_environment(), timeout_seconds=30))`.
- Custom query precisa de data source: defina `MITRA_DATA_SOURCE_ID` ou chame `mitra.init()` uma vez antes de `queries.execute`, que busca o data source do app.

## Desenvolvimento

```bash
python -m pip install -e '.[test]'
ruff format --check . && ruff check . && mypy && pytest
```

O `pytest` exige cobertura mínima de 80%. Os testes usam uma cópia do contrato de paridade com o `mitra-core-sdk` em `tests/fixtures/`; para conferir a cópia, rode `python scripts/check_contract_fixture.py`.
