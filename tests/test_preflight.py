import httpx

from heya.config import Profile
from heya.preflight import check_profile, OK, UNREACHABLE, MODEL_MISSING, NO_KEY


def _local(model="m"):
    return Profile(name="local", base_url="http://x/v1", model=model, provider_type="local")


def _client_returning(payload):
    def handler(request):
        return httpx.Response(200, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_local_ok_when_model_listed():
    c = _client_returning({"data": [{"id": "m"}, {"id": "other"}]})
    assert check_profile(_local("m"), client=c) == OK


def test_local_model_missing():
    c = _client_returning({"data": [{"id": "other"}]})
    assert check_profile(_local("m"), client=c) == MODEL_MISSING


def test_local_unreachable_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("nope")
    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert check_profile(_local("m"), client=c) == UNREACHABLE


def test_cloud_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HEYA_TEST_KEY", raising=False)
    p = Profile(name="cloud", base_url="u", model="m",
                provider_type="api_key", api_key_env="HEYA_TEST_KEY")
    assert check_profile(p, credentials_path=tmp_path / "c.toml") == NO_KEY


def test_cloud_ok_with_env_key(monkeypatch):
    monkeypatch.setenv("HEYA_TEST_KEY", "k")
    p = Profile(name="cloud", base_url="u", model="m",
                provider_type="api_key", api_key_env="HEYA_TEST_KEY")
    assert check_profile(p) == OK
