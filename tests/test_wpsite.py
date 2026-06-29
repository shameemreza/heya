from heya.config import WPSiteConfig
from heya.wpsite import WPClient, build_wp_connector, encode_ability_name


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    """Records requests and returns scripted responses keyed by method."""
    def __init__(self, responses):
        self._responses = responses  # list of _Resp, popped in order
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(("GET", url, params, None))
        return self._responses.pop(0)

    def post(self, url, json=None):
        self.calls.append(("POST", url, None, json))
        return self._responses.pop(0)

    def request(self, method, url, json=None):
        self.calls.append((method, url, None, json))
        return self._responses.pop(0)


def test_encode_ability_name():
    assert encode_ability_name("woocommerce/orders-query") == "woocommerce~1orders-query"
    assert encode_ability_name("a~b/c") == "a~0b~1c"


def test_list_abilities_formats_names():
    fake = _FakeClient([_Resp(200, {"abilities": [
        {"name": "woocommerce/orders-query", "label": "Query orders", "description": "Find orders."}]})])
    wp = WPClient("http://s.test", "u", "p", client=fake)
    out = wp.list_abilities()
    assert "woocommerce/orders-query" in out and "Query orders" in out
    assert fake.calls[0][1] == "http://s.test/wp-json/wp/v2/abilities"


def test_run_ability_posts_encoded_name_and_input():
    fake = _FakeClient([_Resp(200, {"orders": [{"id": 5}]})])
    wp = WPClient("http://s.test", "u", "p", client=fake)
    out = wp.run_ability("woocommerce/orders-query", {"status": "completed"})
    method, url, _, body = fake.calls[0]
    assert method == "POST"
    assert url == "http://s.test/wp-json/wp/v2/abilities/woocommerce~1orders-query/run"
    assert body == {"input": {"status": "completed"}}
    assert "orders" in out


def test_error_response_becomes_error_string():
    fake = _FakeClient([_Resp(404, {"code": "rest_ability_not_found", "message": "No such ability."})])
    wp = WPClient("http://s.test", "u", "p", client=fake)
    out = wp.run_ability("nope/x", {})
    assert out.startswith("Error")
    assert "rest_ability_not_found" in out or "No such ability" in out


def test_network_error_is_caught():
    class _Boom:
        def post(self, *a, **k):
            raise RuntimeError("connection refused")
    wp = WPClient("http://s.test", "u", "p", client=_Boom())
    out = wp.run_ability("x/y", {})
    assert out.startswith("Error")


def test_rest_builds_method_and_url():
    fake = _FakeClient([_Resp(200, {"ok": True})])
    wp = WPClient("http://s.test", "u", "p", client=fake)
    wp.rest("GET", "/wc/v3/orders")
    method, url, _, _ = fake.calls[0]
    assert method == "GET" and url == "http://s.test/wp-json/wc/v3/orders"


def test_build_wp_connector_refuses_production():
    cfg = WPSiteConfig(url="http://s.test", user="u", env="production")
    assert build_wp_connector(cfg, "secret", client=_FakeClient([])) is None


def test_build_wp_connector_needs_password():
    cfg = WPSiteConfig(url="http://s.test", user="u", env="dev")
    assert build_wp_connector(cfg, None, client=_FakeClient([])) is None


def test_build_wp_connector_ok():
    cfg = WPSiteConfig(url="http://s.test", user="u", env="dev")
    wp = build_wp_connector(cfg, "secret", client=_FakeClient([]))
    assert isinstance(wp, WPClient)
