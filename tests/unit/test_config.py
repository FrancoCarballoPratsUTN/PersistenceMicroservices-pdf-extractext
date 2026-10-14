"""Tests de la configuracion operativa de :mod:`app.config`.

La configuracion es la ultima linea de defensa antes de que el servicio arranque
sin proteccion, asi que los tests enuncian dos cosas con rotundo: cada valor por
defecto documentado de SPEC 2.5 se respeta exactamente, y un token ausente, vacio
o formado solo por espacios detiene el proceso en lugar de dejarlo arrancar.

El orquestador nombra el secreto compartido ``PERSISTENCE_API_TOKEN``, asi que ese
es el nombre canonico que este servicio lee; ``SERVICE_API_TOKEN`` se conserva
como nombre heredado para no romper arranques ya desplegados.

El entorno es real aqui a proposito. ``monkeypatch`` fija y elimina variables de
proceso reales, asi que estos tests ejercitan las mismas lecturas de ``os.environ``
que hara la raiz de composicion en produccion, y no un sustituto.
"""

import pytest

from app.config import ConfigurationError, Settings, get_settings

ALL_VARIABLES = (
    "APP_NAME",
    "PERSISTENCE_API_TOKEN",
    "SERVICE_API_TOKEN",
    "MONGO_URI",
    "MONGO_DATABASE",
    "MONGO_TEXTS_COLLECTION",
    "MONGO_TIMEOUT_MS",
    "MAX_TEXT_BODY_BYTES",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Empezar cada test desde un entorno sin ninguna de nuestras variables puestas.

    Aqui el aislamiento importa mas que la comodidad: un ``SERVICE_API_TOKEN``
    fugado de otro test haria que los tests de variable obligatoria pasaran por el
    motivo equivocado.
    """
    for name in ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def token(clean_environment):
    """Un token valido, para los tests que tratan de otra cosa y no de la ausencia."""
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    return "s3cr3t-token"


def test_the_documented_defaults_apply_when_only_the_token_is_set(token):
    settings = get_settings()

    assert settings.app_name == "Persistence Microservice"
    assert settings.mongo_uri == "mongodb://localhost:27017"
    assert settings.mongo_database == "pdf_extractext"
    assert settings.mongo_texts_collection == "texts"
    assert settings.mongo_timeout_ms == 5000
    assert settings.max_text_body_bytes == 10485760
    assert settings.log_level == "INFO"


def test_the_token_is_read_from_the_environment(token):
    assert get_settings().service_api_token == "s3cr3t-token"


def test_the_persistence_api_token_is_read_from_the_environment(clean_environment):
    clean_environment.setenv("PERSISTENCE_API_TOKEN", "orch-token")

    assert get_settings().service_api_token == "orch-token"


def test_the_persistence_api_token_wins_over_the_legacy_name(clean_environment):
    clean_environment.setenv("PERSISTENCE_API_TOKEN", "orch-token")
    clean_environment.setenv("SERVICE_API_TOKEN", "legacy-token")

    assert get_settings().service_api_token == "orch-token"


def test_the_legacy_service_api_token_is_still_accepted(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "legacy-token")

    assert get_settings().service_api_token == "legacy-token"


def test_every_documented_default_matches_the_spec_table(token):
    """Los valores por defecto son contrato, asi que se afirman en bloque.

    Escrito como comparacion de tablas porque quien compruebe SPEC 2.5 quiere ver
    las dos columnas una junto a otra.
    """
    settings = get_settings()

    documented = {
        "APP_NAME": settings.app_name,
        "MONGO_URI": settings.mongo_uri,
        "MONGO_DATABASE": settings.mongo_database,
        "MONGO_TEXTS_COLLECTION": settings.mongo_texts_collection,
        "MONGO_TIMEOUT_MS": settings.mongo_timeout_ms,
        "MAX_TEXT_BODY_BYTES": settings.max_text_body_bytes,
        "LOG_LEVEL": settings.log_level,
    }

    assert documented == {
        "APP_NAME": "Persistence Microservice",
        "MONGO_URI": "mongodb://localhost:27017",
        "MONGO_DATABASE": "pdf_extractext",
        "MONGO_TEXTS_COLLECTION": "texts",
        "MONGO_TIMEOUT_MS": 5000,
        "MAX_TEXT_BODY_BYTES": 10485760,
        "LOG_LEVEL": "INFO",
    }


def test_no_token_in_the_environment_stops_the_service(clean_environment):
    with pytest.raises(ConfigurationError):
        get_settings()


def test_an_empty_token_in_the_environment_stops_the_service(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "")

    with pytest.raises(ConfigurationError):
        get_settings()


def test_a_whitespace_only_token_stops_the_service(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "   \t  ")

    with pytest.raises(ConfigurationError):
        get_settings()


def test_the_failure_names_the_variable_that_is_missing(clean_environment):
    with pytest.raises(ConfigurationError, match="PERSISTENCE_API_TOKEN"):
        get_settings()


def test_the_failure_echoes_neither_the_variable_value_nor_its_whitespace(
    clean_environment,
):
    """Un token en blanco sigue teniendo valor; el mensaje no debe llevarlo.

    Afirmar sobre los propios espacios es lo que convierte esto en una proteccion
    de verdad: un mensaje construido con ``{raw!r}`` apareceria aqui como un tab y
    una racha de espacios.
    """
    clean_environment.setenv("PERSISTENCE_API_TOKEN", "  \t  ")

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    message = str(raised.value)
    assert "PERSISTENCE_API_TOKEN" in message
    assert "\t" not in message
    assert "  " not in message


def test_settings_are_frozen(token):
    settings = get_settings()

    with pytest.raises(AttributeError):
        settings.mongo_database = "otra"  # type: ignore[misc]


def test_the_int_variables_are_parsed_as_integers(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("MONGO_TIMEOUT_MS", "250")
    clean_environment.setenv("MAX_TEXT_BODY_BYTES", "2048")

    settings = get_settings()

    assert settings.mongo_timeout_ms == 250
    assert settings.max_text_body_bytes == 2048


def test_a_blank_numeric_variable_falls_back_to_its_default(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("MONGO_TIMEOUT_MS", "  ")
    clean_environment.setenv("MAX_TEXT_BODY_BYTES", "")

    settings = get_settings()

    assert settings.mongo_timeout_ms == 5000
    assert settings.max_text_body_bytes == 10485760


def test_a_non_numeric_timeout_is_reported_as_a_configuration_error(
    clean_environment,
):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("MONGO_TIMEOUT_MS", "cinco milisegundos")

    with pytest.raises(ConfigurationError, match="MONGO_TIMEOUT_MS"):
        get_settings()


def test_a_non_numeric_body_limit_is_reported_as_a_configuration_error(
    clean_environment,
):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("MAX_TEXT_BODY_BYTES", "diez MiB")

    with pytest.raises(ConfigurationError, match="MAX_TEXT_BODY_BYTES"):
        get_settings()


def test_a_non_positive_body_limit_is_rejected(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("MAX_TEXT_BODY_BYTES", "0")

    with pytest.raises(ConfigurationError, match="MAX_TEXT_BODY_BYTES"):
        get_settings()


def test_a_non_positive_timeout_is_rejected(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("MONGO_TIMEOUT_MS", "-1")

    with pytest.raises(ConfigurationError, match="MONGO_TIMEOUT_MS"):
        get_settings()


def test_the_token_surrounding_whitespace_is_removed(token, clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "  s3cr3t-token  ")

    assert get_settings().service_api_token == "s3cr3t-token"


def test_two_successive_reads_return_equal_settings(token):
    assert get_settings() == get_settings()


def test_a_settings_instance_can_be_built_without_reading_the_environment(token):
    """El dataclass es usable por si solo, lo que mantiene simples los tests y las
    herramientas."""

    assert Settings(service_api_token="direct").service_api_token == "direct"


def test_settings_expose_exactly_the_documented_variables(token):
    assert set(Settings.__dataclass_fields__) == {
        "app_name",
        "service_api_token",
        "mongo_uri",
        "mongo_database",
        "mongo_texts_collection",
        "mongo_timeout_ms",
        "max_text_body_bytes",
        "log_level",
    }


def test_the_log_level_defaults_to_info(token):
    assert get_settings().log_level == "INFO"


def test_the_log_level_is_read_from_the_environment(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("LOG_LEVEL", "debug")

    assert get_settings().log_level == "DEBUG"


def test_a_blank_log_level_falls_back_to_its_default(clean_environment):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("LOG_LEVEL", "   ")

    assert get_settings().log_level == "INFO"


def test_an_unknown_log_level_is_reported_as_a_configuration_error(
    clean_environment,
):
    clean_environment.setenv("SERVICE_API_TOKEN", "s3cr3t-token")
    clean_environment.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        get_settings()
