# Mitra Functions SDK for Python

SDK Python para Server Functions da Mitra: dá acesso a usuário atual, entidades, custom queries, Functions e integrações do app em que a Function roda. App de browser usa outro pacote, o `@mitralab.io/platform-sdk`.

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

ID vazio, `.` ou `..` e `delete_many({})` lançam `ValueError` antes de qualquer requisição.

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
