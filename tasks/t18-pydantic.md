# T18 - Pydantic en la frontera

> **Estado: implementado y verificado.** Los pasos 1-9 están hechos con TDD y el
> Paso 10 (documentación) cerrado. Alcance humano: **A**.
>
> Decisión humana (2026-10-05): **alcance A** - Pydantic valida los cuerpos de
> entrada y genera el documento OpenAPI. No se toca `config.py`, ni los puertos,
> ni los servicios, ni los repositorios.
>
> **Supersede** la parte de [T17](./todo.md) que escribía los schemas a mano, y
> reescribe SPEC §2.3. T17 queda como historia: su razonamiento fue correcto
> bajo §2.3 v2, que es la premisa que esta tarea cambia.

---

## 1. Por qué

SPEC §2.3 (v2) exigía no usar Pydantic en el contrato. Era una decisión
deliberada, y su precio está escrito en el propio SPEC:

- **~55 líneas de dicts a mano** en `app/api/schemas.py:57-126` (`_TEXT`,
  `_CREATE_TEXT`, `_UPDATE_TEXT`, `_ACKNOWLEDGEMENT`, `_PROBE`), que nadie
  derivaba de las reglas que el servicio realmente aplica.
- Validación con `isinstance` repartida en tres bloques
  (`app/api/validators/create_text.py:29-35`) que declaran las reglas sin
  dejar que la herramienta las ejecute.

Dos hechos cambian el balance:

1. **`pydantic` 2.13.5 ya está instalada**, como dependencia transitiva de
   FastAPI (`uv.lock:301`). Promoverla a dependencia directa no añade nada al
   entorno ni al lock: sólo hace explícita una dependencia que ya existía.
2. Los schemas a mano son **la parte del diseño que más deriva**: si mañana
   `name` pasa a admitir 200 caracteres, el `dict` de `_CREATE_TEXT` no se
   entera. Un modelo declara la regla una vez.

### Lo que Pydantic no aporta (honestidad primero)

Verificado empíricamente antes de decidir:

- **En `PUT`, Pydantic no mejora el modelo de dominio.** `model_fields_set`
  distingue ausente de `null`, pero `TextChanges` ya lo resuelve con
  `name is not None and metadata is not None`
  (`app/api/validators/update_text.py:49`). Son equivalentes; la dataclass
  sigue siendo la correcta porque es un tipo de Capa 2.
- **En los validadores, la ganancia es modesta.** `CreateTextBody` reemplaza
  tres bloques `isinstance` por cuatro declaraciones de campo. Lo que aporta
  sobre todo es que la declaración de tipos y la generación del esquema pasan
  a ser **la misma fuente**.

**El retorno real de esta tarea es el documento OpenAPI**, no los validadores.

---

## 2. Alcance

| Elemento | Antes (SPEC §2.3 v2) | Después (T18) |
|---|---|---|
| Cuerpo de entrada | `await request.json()` → `dict` + `isinstance` | `Model.model_validate(raw)` en `validators/common.py` |
| Schemas OpenAPI | dicts a mano en `schemas.py` | `model_json_schema()` de los mismos modelos |
| Comando de servicio | `@dataclass(frozen=True)` | **sin cambio** (`ports.py` sigue sin Pydantic) |
| Configuración | `dataclass` + `os.environ` | **sin cambio** |
| Cuerpo de error | `dict` plano en `problem.py` | **sin cambio** |
| Puertos | `Protocol` + dataclasses | **sin cambio** |

**Límite que esta tarea no cruza:** `app/api/` es la única capa que importa
Pydantic. `app/services/`, `app/use_cases/` y `app/repositories/` no lo
importan, igual que hoy no importan `pymongo`. La dependencia sigue apuntando
hacia adentro; el dominio no hereda la versión de la librería.

---

## 3. Los cinco modelos (`app/api/models.py`, nuevo)

| Modelo | Componente | Validado por | Notas |
|---|---|---|---|
| `CreateTextBody` | `CreateText` | `validators/create_text.py` | `text` y `checksum` obligatorios y no vacíos |
| `UpdateTextBody` | `UpdateText` | `validators/update_text.py` | `name` y `metadata` opcionales |
| `TextOut` | `Text` | - | **sólo esquema**; `created_at: datetime` para que salga `format: date-time` |
| `AcknowledgementOut` | `Acknowledgement` | - | **sólo esquema** |
| `ProbeOut` | `Probe` | - | **sólo esquema** |

Los tres últimos no validan nada: existen para que el documento se genere de
una fuente y no de una transcripción. Su docstring lo dice explícitamente, y
es la razón por la que el docstring del módulo existe.

### `Problem` NO se modela

Su `enum` de `code` sale de `ServiceError.__subclasses__()` en runtime
(`schemas.py:54`). Un `Literal` estático no puede derivarse de una
introspección, así que `_PROBLEM` sigue escrito a mano. Es la excepción
justificada dentro de la tarea.

---

## 4. Traducción de errores: Pydantic → vocabulario RFC 9457

`app/api/validators/common.py` gana `checked(model, raw)`, que llama a
`model_validate` y convierte el `ValidationError` de Pydantic en el nuestro,
mapeando el `loc` del primer error a un `detail` **propio**:

| `loc` | `detail` | Origen |
|---|---|---|
| `()` | `invalid body` | el body no es un objeto JSON |
| `("text",)` | `invalid text` | falta, vacío o no es `str` |
| `("checksum",)` | `invalid checksum` | idem |
| `("name",)` | `invalid name` | presente y no es `str` |
| `("metadata",)` | `invalid metadata` | presente y no es objeto |

El `detail` se construye con nombres de campo nuestros, **nunca** con la prosa
inglesa de Pydantic (`"String should have at least 1 character"`): el `detail`
es parte del contrato de cable y no debe cambiar con una versión de la librería.

Guarda obligatoria: si el primer elemento del `loc` no es un campo conocido, el
`detail` cae a `"invalid body"`. Sin esa guarda, el primer modelo anidado
futuro provocaría un `KeyError` **dentro del manejador de errores**.

`require_str` **se queda**: lo usan `routers/texts.py:76,154,188` para el query
param, y un query param no pasa por un modelo. `require_mapping` desaparece —
`loc == ()` cubre exactamente su caso.

---

## 5. Pasos (TDD: RED → GREEN en cada uno)

### Paso 1 — Dependencia

- [x] `"pydantic>=2.13.5"` en `[project].dependencies` de `pyproject.toml`
- [x] `uv lock` — el diff promueve `pydantic` a dependencia directa
      del proyecto, sin cambiar ninguna versión

### Paso 2 — RED: `tests/unit/api/test_models.py` (nuevo)

Tests que **no pueden pasar** porque `app/api/models.py` no existe:

- [x] `CreateTextBody` exige `text` y `checksum`, y `required` es exactamente
      `["text", "checksum"]`
- [x] `checksum` publica `minLength: 1`; `text` también
- [x] `TextOut` publica los 6 `required` y `format: date-time` en las fechas
- [x] `UpdateTextBody` no publica ningún `required`
- [x] el esquema **no contiene ninguna clave `title`**, ni en la raíz ni en las
      propiedades (Pydantic las añade; son ruido cuando el componente ya tiene nombre)

### Paso 3 — GREEN: `app/api/models.py`

Los cinco modelos + `schema_of(model, description)`.

`schema_of` quita los `title` recursivamente y pone la `description` **desde
`schemas.py`**, no desde el docstring: los docstrings Google-style con `Args:`
se volcarían enteros en `/docs`.

### Paso 4 — RED: `tests/unit/api/validators/test_common.py`

- [x] `checked(CreateTextBody, [1, 2])` lanza `ValidationError` con
      `detail == "invalid body"`
- [x] `checked(CreateTextBody, {"text": "t"})` → `detail == "invalid checksum"`
- [x] `checked(CreateTextBody, {"text": "t", "checksum": "c", "metadata": []})`
      → `detail == "invalid metadata"`
- [x] `checked(CreateTextBody, {"text": "", "checksum": "c"})` → `"invalid text"`
- [x] **un `loc` anidado** (`{"metadata": {1: "x"}}` → `("metadata", 1, "[key]")`)
      nombra `metadata`, no el camino de Pydantic
- [x] un body escalar o `null` (`"hola"`, `7`, `None`) → `"invalid body"`
- [x] `require_str` sigue funcionando (no se toca)

> **Desvío de D-T18.5, cerrado durante la implementación.** El paso preveía una
> tabla `{("text",): "invalid text", ...}` y una guarda que cayera a
> `"invalid body"` ante un `loc` desconocido. La tabla se eliminó: `_detail`
> interpola `location[0]`, que es siempre un nombre de campo nuestro, así que
> no hay `KeyError` que temer y **la guarda sobre loc desconocido sobra** — un
> `loc` desconocido solo puede aparecer dentro de un modelo que aún no existe.
> El comportamiento que sí importa quedó fijado con tests que mutan: sin la
> guarda de `loc == ()` caen 2 tests; usando `location[-1]` en vez de
> `location[0]` cae el del `loc` anidado. La tabla habría sido un segundo sitio
> donde olvidar un nombre.

### Paso 5 — GREEN: `app/api/validators/common.py`

`checked()` + `require_str`. Fuera `require_mapping`.

### Paso 6 — RED: validadores de create y update

- [x] `validate_create({"text": "t", "checksum": "c", "name": 5})` →
      `detail == "invalid name"`
- [x] `validate_create([1, 2])` → `"invalid body"`
- [x] `validate_update` sigue dando `ImmutableFieldError` **antes** de validar
      tipos: `{"text": "x", "name": 5}` → `IMMUTABLE_FIELD`, no `VALIDATION_ERROR`
- [x] `validate_update({})` → `"no changes requested"` (sigue siendo un no-op rechazado)
- [x] `validate_update({"name": ""})` y `{"metadata": {}}` → cambio real, no "sin cambio"

### Paso 7 — GREEN: `create_text.py` (42 → ~25) y `update_text.py` (57 → ~35)

- [x] `_refuse_immutable_fields` se ejecuta **antes** de `checked()` en `update_text.py`
- [x] `extra` se queda en el default (`ignore`): una clave desconocida hoy se
      ignora y no debe empezar a dar `400`

### Paso 8 — RED: `tests/integration/api/test_openapi.py`

- [x] El componente `CreateText` publicado lleva `minLength: 1` en `text` y `checksum`
- [x] El componente `Text` publicado lleva `format: date-time` en `created_at`
- [x] Ningún componente publicado contiene `title`

### Paso 9 — GREEN: `app/api/schemas.py`

- [x] Fuera `_TEXT`, `_CREATE_TEXT`, `_UPDATE_TEXT`, `_ACKNOWLEDGEMENT`, `_PROBE`
- [x] `_PROBLEM`, `_FAILURES`, `accepts`, `answered_with`, `failing_with`,
      `_require_the_checksum`, `_drop_pydantic_validation` y `publish` **no se tocan**:
      los tres "errores de FastAPI" que arregla este módulo los sigue
      cometiendo, porque el `checksum: str | None = None` de la firma sigue ahí

### Paso 10 — REFACTOR / documentación

Ocho lugares afirman hoy que no hay Pydantic. Si no se corrigen, el código miente:

| Fichero | Línea | Afirmación |
|---|---|---|
| `SPEC.md` | 275-301 | §2.3 completo, "Sin Pydantic — cómo y con qué coste" |
| `SPEC.md` | 743-753 | §7 diagrama: "SIN Pydantic", "isinstance + TypedDict" |
| `SPEC.md` | 873 | riesgo "OpenAPI degrada al no usar Pydantic" |
| `SPEC.md` | 2.4 | árbol: añadir `app/api/models.py` |
| `tasks/plan.md` | 14, 77-80, 643, 686 | D-decisión y tabla de riesgos |
| `tasks/todo.md` | 258 | nota de T17 |
| `app/config.py` | 5 | "No Pydantic is involved (SPEC 2.3)" |
| `app/api/problem.py` | 8-11 | "Why a dict and not a model" |
| `app/api/schemas.py` | 1-27 | docstring entero |
| `validators/create_text.py`, `update_text.py` | 3-4 | "No Pydantic: …" |

- [x] §2.3 se reescribe como **"Pydantic en la frontera, no en el dominio"**
- [x] Aviso de versión de `SPEC.md` subido a v3, como ya hace la v2
- [x] T18 resumida en `tasks/todo.md`; la nota de T17 se marca como superada
- [x] `README.md` no menciona Pydantic: **no requiere cambio** (verificado)

---

## 6. Criterios de aceptación

- [x] Los 5 component schemas se generan desde los modelos
- [x] Ningún componente publicado contiene `title`
- [x] `required` exacto: `["text", "checksum"]` en `CreateText`, los 6 en `Text`,
      ninguno en `UpdateText`
- [x] `checksum` y `text` con `minLength: 1`; fechas con `format: date-time`
- [x] El `detail` de un `400` nombra el campo, no dice `"invalid string"`
- [x] Un body no-objeto da `"invalid body"` sin `KeyError` en el manejador
- [x] `text`/`checksum` en `PUT` → `IMMUTABLE_FIELD` antes de validar tipos
- [x] `pymongo` sigue ausente de `app/api/` y `app/services/` (AC de T9/T10)
- [x] `pydantic` ausente de `app/services/`, `app/use_cases/`, `app/repositories/`, `app/config.py`
- [x] Sin `xfail` ni `skip`
- [x] Cobertura de `app` no baja

## 7. Verificación

```bash
uv sync
uv run pytest --cov=app --cov-fail-under=85    # base: 332 passed, cobertura 100%
uv run ruff check .
uv run ruff format --check .
```

Manual, porque el documento es el único artefacto que cambia de forma:

```bash
uv run uvicorn app.main:create_app --factory --port 8082
curl -s -H "Authorization: Bearer $SERVICE_API_TOKEN" localhost:8082/openapi.json > before.json
# ... aplicar la tarea ...
curl -s -H "Authorization: Bearer $SERVICE_API_TOKEN" localhost:8082/openapi.json > after.json
# diff de components.schemas.CreateText / UpdateText / Text
```

## 8. Diffs de cable asumidos

Los tres son documentos o texto de error, ninguno es un status ni un cuerpo
de éxito:

1. **`name`/`metadata` pasan a documentarse como `anyOf: [T, null]` con
   `default: null`**, en vez de `type: string`. Es más cierto: `null` es legal
   en el contrato. El cliente Go es a mano, no hay generación de cliente.
2. **El `detail` de un `400` nombra el campo** (`"invalid text"`) en vez del
   genérico `"invalid string"`. El orquestador nunca lee `detail`: SPEC §1.6
   punto 4 dice que sólo comprueba `status`.
3. **Desaparecen los `title` por propiedad** que Pydantic añade.

Ningún status cambia. Ningún `code` cambia. Ningún body de éxito cambia.

## 9. Decisiones

| # | Decisión | Cerrada como |
|---|---|---|
| D-T18.1 | Alcance | **A**: validación de entrada + generación OpenAPI. `config`, `ports`, `services` y `repositories` no se tocan |
| D-T18.2 | Modelos de respuesta | **Los 5 desde Pydantic**, aunque 3 no validen nada: el contrato de cable queda escrito en un solo sitio |
| D-T18.3 | `Problem` | **Se queda a mano**: su `enum` es derivado en runtime, no declarable |
| D-T18.4 | `extra` | **`ignore`** (default): una clave desconocida hoy se ignora y no debe empezar a dar `400` |
| D-T18.5 | `detail` de un `400` | **Nombra el campo**, con vocabulario propio; nunca la prosa de Pydantic. **Revisión en el Paso 4:** sin tabla, interpolando `location[0]` |
| D-T18.6 | `_refuse_immutable_fields` | **Sigue antes** del modelo: regla estructural, y un `text` en el body nunca debe pasar desapercibido (razón de T13) |
| D-T18.7 | `require_str` | **Se queda**: el query param no pasa por un modelo, y `checksum: str \| None = None` debe seguir dando `400` y no `422` |
| D-T18.8 | `response_model` de FastAPI | **No**: Pydantic serializa `datetime` con microsegundos (`.789000Z`) y rompería el RFC 3339 con milisegundos que el SPEC fija |

## 10. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El documento OpenAPI cambia de forma | Bajo | Verificación manual con diff antes/después; único cambio observable |
| Prosa inglesa de Pydantic filtrándose al `detail` | Medio | El `detail` se construye con nombres de campo nuestros (D-T18.5); test que lo fija |
| `KeyError` en el manejador de errores si un `loc` es inesperado | Alto | **Cerrado**: no hay tabla, `_detail` interpola `location[0]` y no puede lanzar `KeyError`. Fijado por los 2 tests que caen al quitar la guarda de `loc == ()` |
| Un modelo anidado futuro rompe el mapeo de `loc` | Medio | today ya existe el caso (`metadata` con clave no `str` → `loc` de 3 niveles) y nombra `metadata`; un campo nuevo debe añadir su nombre a un modelo, no a una tabla |
| Modelos que "no se usan" (los 3 de respuesta) leídos como código muerto | Bajo | Docstring de `models.py` que declara el reparto; es contract-first |
| `pydantic` filtrándose a `app/services/` | Medio | AC explícito en §6 + el grep que T9/T10 ya usan para `pymongo` |
