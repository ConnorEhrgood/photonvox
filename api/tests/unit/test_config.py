import pytest

from app.config import Settings

GOOD = dict(environment="production", oidc_issuer="https://id.photonind.com", oidc_audience="photonvox", directory_url="https://api.account.photonind.com",
            directory_client_id="pdc_vox", directory_client_secret="s" * 40, directory_notice_secret="n" * 40,
            system_database_url="postgresql+psycopg://vox_system:x@db/photonvox", cors_origins="https://vox.photonind.com",
            secrets_key="k" * 44)


def test_a_good_production_configuration_is_safe():
    assert Settings(**GOOD).production_safe() is None


def test_development_is_never_refused():
    assert Settings(environment="development").production_safe() is None


@pytest.mark.parametrize("over,word", [
    ({"oidc_issuer": ""}, "OIDC_ISSUER"),
    ({"oidc_audience": ""}, "OIDC_ISSUER"),
    ({"directory_url": "http://directory"}, "DIRECTORY_URL"),
    ({"directory_client_id": ""}, "DIRECTORY_CLIENT_ID"),
    ({"directory_client_secret": ""}, "DIRECTORY_CLIENT_ID"),
    ({"directory_notice_secret": ""}, "DIRECTORY_NOTICE_SECRET"),
    ({"directory_notice_secret": "short"}, "DIRECTORY_NOTICE_SECRET"),
    ({"system_database_url": ""}, "SYSTEM_DATABASE_URL"),
    ({"secrets_key": ""}, "SECRETS_KEY"),
    ({"cors_origins": ""}, "CORS_ORIGINS must list"),
    ({"cors_origins": "http://localhost:5183"}, "https://"),
])
def test_each_unsafe_production_setting_is_named(over, word):
    assert word in Settings(**{**GOOD, **over}).production_safe()


def test_lists_are_split_and_trimmed():
    s = Settings(cors_origins=" https://a , https://b ,", summary_origins="https://c, ", directory_notice_secret="one, two")
    assert s.cors_list == ["https://a", "https://b"] and s.summary_origin_list == ["https://c"] and s.notice_secrets == ["one", "two"]


def test_the_product_key_is_vox():
    assert Settings().directory_product == "vox"
