# Mitra Functions SDK for Python

SDK Python síncrono para código que roda dentro de Server Functions: usuário atual, entidades, custom queries, execuções de Function e integrações, no escopo de um app. Usa um access token de curta duração, sem login, refresh nem API key. A API é síncrona porque o runner de Functions Python é síncrono.

## Instalação

```bash
pip install mitra-functions-sdk
```

Python 3.11 ou mais novo. Importado como `mitra_functions_sdk`; a única dependência é `httpx`.

## Configuração

`create_client()` sem argumento lê o ambiente; `create_client_from_environment(env)` lê de um mapping, útil em teste. `create_client(MitraClientConfig(...))` usa só o que for passado, sem cair no ambiente.

| Variável | Campo | Obrigatória | Uso |
|---|---|---|---|
| `MITRA_API_URL` | `api_url` | sim | URL base HTTP(S) do API gateway, sem credencial, query ou fragmento; os serviços saem dela (`/iam`, `/data-manager`, `/functions`, `/integration`, `/code-studio`) |
| `MITRA_PLATFORM_ACCESS_TOKEN` | `access_token` | sim | token da invocação atual, enviado como `Bearer` |
| `MITRA_APP_ID` | `app_id` | sim | escopo do app, enviado em `X-App-Id` |
| `MITRA_DATA_SOURCE_ID` | `data_source_id` | não | data source das custom queries; sem ele, chame `init()` |
| | `timeout_seconds` | não | timeout por requisição, padrão `10.0` |
| | `http_client` | não | `httpx.Client` próprio; o SDK não fecha um client que não criou |

`access_token` e `http_client` ficam fora do `repr` da configuração.

## Uso

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

## Contratos e armadilhas

- O runtime de Functions hoje injeta `MITRA_TOKEN`, `MITRA_BASE_URL` e `MITRA_PROJECT_ID`, os nomes do SDK legado, e este SDK não lê esses nomes: sem as variáveis da tabela, `create_client()` falha com `MitraConfigError`. Nesse caso, monte o `MitraClientConfig` explicitamente.
- Custom query sem data source falha com `MitraConfigError`. `init()` busca o valor em `/code-studio/api/v1/apps/{appId}/info` só quando ele ainda não existe, e lança `MitraResponseError` se o app não tem data source. A requisição envia `dataSourceId` e `parameters`.
- Use o client como context manager ou chame `close()`: sem isso, o pool de conexões do `httpx` fica aberto até o fim do processo.
- O SDK faz uma única tentativa por requisição e nunca repete, para não reexecutar escrita. `retryable` é só diagnóstico.
- `functions.execute` envia `X-Invocation-Type: sync` e espera a execução terminar; `execute_async` envia `async` e devolve o registro para acompanhar com `get_execution`. `integration.execute` sempre envia `source: "SDK"`.
- Redirect não é seguido: a resposta 3xx vira `MitraApiError` com o status recebido. O token é mascarado na mensagem, no código, no `request_id` e nos detalhes do erro.

## Contrato com o Core

Os testes executam o corpus SDK-PARITY-001 do `mitra-core-sdk` a partir de uma cópia em `tests/fixtures/`, para rodarem offline. O manifest ao lado fixa a versão (hoje `0.1.0`), o commit de origem e o SHA-256. O CI baixa o arquivo original nesse commit e compara byte a byte. Para conferir a cópia localmente:

```bash
python scripts/check_contract_fixture.py
```

## Erros

Todas herdam de `MitraSdkError`. As três de requisição trazem `status`, `code`, `details`, `request_id` e `retryable`.

| Classe | Quando |
|---|---|
| `MitraConfigError` | configuração ausente ou inválida, query sem data source; também é `ValueError` |
| `MitraApiError` | resposta HTTP de erro; `retryable` vem do corpo ou é `True` só para 5xx |
| `MitraNetworkError` | `REQUEST_TIMEOUT` ou `NETWORK_ERROR`, com `status=0` e `retryable=True` |
| `MitraResponseError` | resposta de sucesso vazia, nula, com JSON inválido ou fora do contrato (`INVALID_RESPONSE`, `status=200`) |

ID vazio, `.` ou `..` no path e `delete_many({})` lançam `ValueError` puro, antes da requisição.

## Desenvolvimento

```bash
python -m pip install -e '.[test]'
ruff format --check . && ruff check . && mypy && pytest
```

O `pytest` exige cobertura mínima de 80%.
