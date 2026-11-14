"""Edge routes for Keycloak and the Keycloak-backed logins.

``_matching`` evaluates Traefik rules (Host, Path, PathPrefix, HeaderRegexp,
``&&``, ``||``, ``!`` and parentheses) so the tests can ask which routers can
match a request and which one wins. The real binary is checked separately.
"""

import re

import pytest

from llmaven.infrastructure.config.schema import LLMavenConfig
from llmaven.infrastructure.resources.traefik import (
    LITELLM_UI_PATHS,
    LOGIN_COOKIE,
    build_edge_dynamic_config,
)

from . import PINNED_KEYCLOAK_IMAGE
from .test_edge_config import LITELLM_HOST, MLFLOW_HOST, _data

KEYCLOAK_HOST = "auth.example.org"
KEYCLOAK_ADMIN = "198.51.100.0/24"
BACKENDS = {
    "litellm": "https://litellm.internal.env.test",
    "mlflow": "https://mlflow.internal.env.test",
    "keycloak": "https://keycloak.internal.env.test",
    "mlflow-auth": "https://ml-auth.internal.env.test",
    "litellm-auth": "https://li-auth.internal.env.test",
}
LITELLM_COOKIE_RULE = "HeaderRegexp(`Cookie`, `(^|;\\s*)_llmoxie_litellm(_\\d+)?=`)"
BEARER_RULE = "HeaderRegexp(`Authorization`, `^Bearer `)"


def _config(*, keycloak=True, mlflow_login=True, litellm_login=True, kc_ips=None):
    data = _data(litellm={"admin_allowed_ips": ["203.0.113.0/24"]})
    domains = data["edge"]["custom_domains"]
    domains.append({"name": KEYCLOAK_HOST, "certificate_name": "cert-kc"})
    if keycloak:
        data["keycloak"] = {
            "enabled": True,
            "image": PINNED_KEYCLOAK_IMAGE,
            "hostname": KEYCLOAK_HOST,
            "admin_allowed_ips": [KEYCLOAK_ADMIN] if kc_ips is None else kc_ips,
        }
    data["mlflow"]["login"] = {"enabled": mlflow_login}
    data["litellm"]["login"] = {"enabled": litellm_login}
    return LLMavenConfig.model_validate(data)


def _http(config=None, backends=None) -> dict:
    return build_edge_dynamic_config(config or _config(), backends or BACKENDS)["http"]


# --- a small Traefik rule evaluator -----------------------------------------

_TOKEN = re.compile(r"\s*(&&|\|\||!|\(|\)|,|`[^`]*`|\w+)")


def _tokens(rule: str) -> list[str]:
    out, pos = [], 0
    while pos < len(rule):
        match = _TOKEN.match(rule, pos)
        assert match, f"cannot tokenize {rule!r} at {pos}"
        out.append(match.group(1))
        pos = match.end()
    return out


def _evaluate(rule: str, host: str, path: str, headers: dict) -> bool:
    """``headers`` maps a name to one value or a list (a repeated header).

    Names are case-insensitive and a regexp matches if any value does, as in
    Traefik. ``path`` is the routing path (reserved characters stay encoded).
    """
    tokens, pos = _tokens(rule), 0
    folded: dict[str, list[str]] = {}
    for name, value in headers.items():
        values = [value] if isinstance(value, str) else list(value)
        folded.setdefault(name.lower(), []).extend(values)

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def or_expr():
        value = and_expr()
        while peek() == "||":
            take()
            value = and_expr() or value  # evaluate both: always consume
        return value

    def and_expr():
        value = not_expr()
        while peek() == "&&":
            take()
            value = not_expr() and value
        return value

    def not_expr():
        if peek() == "!":
            take()
            return not not_expr()
        return atom()

    def atom():
        if peek() == "(":
            take()
            value = or_expr()
            assert take() == ")"
            return value
        name = take()
        assert take() == "("
        args = []
        while peek() != ")":
            token = take()
            if token != ",":
                args.append(token.strip("`"))
        take()
        if name == "Host":
            return host == args[0]
        if name == "Path":
            return path == args[0]
        if name == "PathPrefix":
            return path.startswith(args[0])
        if name == "HeaderRegexp":
            values = folded.get(args[0].lower(), [])
            return any(re.search(args[1], v) for v in values)
        if name == "PathRegexp":
            return re.search(args[0], path) is not None
        raise AssertionError(f"unsupported matcher {name}")

    value = or_expr()
    assert pos == len(tokens), f"trailing tokens in {rule!r}"
    return value


def _priority(rule: str, router: dict) -> int:
    return router.get("priority", len(rule))


def _matching(http, host, path, **headers) -> list[str]:
    """Routers that match, highest priority first."""
    hits = [
        (name, router)
        for name, router in http["routers"].items()
        if _evaluate(router["rule"], host, path, headers)
    ]
    hits.sort(key=lambda hit: -_priority(hit[1]["rule"], hit[1]))
    return [name for name, _ in hits]


def _winner(http, host, path, **headers) -> str | None:
    hits = _matching(http, host, path, **headers)
    return hits[0] if hits else None


def _carries(http, name, middleware) -> bool:
    return middleware in http["routers"][name].get("middlewares", [])


# --- tests --------------------------------------------------------------------


def test_matcher_sanity():
    rule = "Host(`a`) && (Path(`/x`) || PathPrefix(`/y/`)) && !HeaderRegexp(`H`, `^z`)"
    assert _evaluate(rule, "a", "/x", {})
    assert _evaluate(rule, "a", "/y/q", {"H": "k"})
    assert not _evaluate(rule, "a", "/y/q", {"H": "zz"})
    assert not _evaluate(rule, "b", "/x", {})


def test_login_cookie_names():
    assert LOGIN_COOKIE == {"mlflow": "_llmoxie_mlflow", "litellm": "_llmoxie_litellm"}


def test_keycloak_host_routes():
    http = _http()
    host = f"Host(`{KEYCLOAK_HOST}`)"
    routers = {k: v for k, v in http["routers"].items() if host in v["rule"]}
    assert len(routers) == 3
    by_prefix = {
        prefix: router
        for router in routers.values()
        for prefix in ("/realms/", "/resources/", "/admin/")
        if router["rule"] == f"{host} && PathPrefix(`{prefix}`)"
    }
    assert set(by_prefix) == {"/realms/", "/resources/", "/admin/"}
    for prefix in ("/realms/", "/resources/"):
        assert by_prefix[prefix]["middlewares"] == ["client-rate-limit"]
        assert by_prefix[prefix]["service"] == "keycloak"
    admin = by_prefix["/admin/"]
    assert "keycloak-admin-ip-allowlist" in admin["middlewares"]
    allow = http["middlewares"]["keycloak-admin-ip-allowlist"]["ipAllowList"]
    assert allow["sourceRange"] == [KEYCLOAK_ADMIN]
    assert allow["ipStrategy"] == {"depth": 1}
    assert http["services"]["keycloak"]["loadBalancer"]["servers"] == [
        {"url": BACKENDS["keycloak"]}
    ]

    for path in ("/", "/metrics", "/health", "/q/metrics", "/realm", "/adminx"):
        assert _matching(http, KEYCLOAK_HOST, path) == [], path
    for path in ("/realms/master/x", "/resources/a.css", "/admin/realms"):
        assert len(_matching(http, KEYCLOAK_HOST, path)) == 1, path


def test_keycloak_admin_allowlist_is_closed_without_ips():
    http = _http(_config(kc_ips=[]))
    allow = http["middlewares"]["keycloak-admin-ip-allowlist"]["ipAllowList"]
    assert allow["sourceRange"] == ["127.0.0.1/32"]


def test_mlflow_login_routes():
    http = _http()
    oauth = _winner(http, MLFLOW_HOST, "/oauth2/callback")
    assert http["routers"][oauth]["service"] == "mlflow-auth"
    assert http["services"]["mlflow-auth"]["loadBalancer"]["servers"] == [
        {"url": BACKENDS["mlflow-auth"]}
    ]
    mlflow_routers = [
        (name, router)
        for name, router in http["routers"].items()
        if name != oauth and MLFLOW_HOST in router["rule"]
    ]
    assert mlflow_routers
    login = http["middlewares"]["mlflow-login"]["forwardAuth"]
    assert login["address"] == f"{BACKENDS['mlflow-auth']}/"
    assert login["trustForwardHeader"] is True
    for name, router in mlflow_routers:
        assert "mlflow-login" in router["middlewares"], name
    # the app is only reachable through a login router
    assert _winner(http, MLFLOW_HOST, "/api/2.0/mlflow/x") in dict(mlflow_routers)


def test_mlflow_login_off_keeps_stage_1_open_router():
    http = _http(_config(mlflow_login=False))
    assert http["routers"]["mlflow"] == {
        "entryPoints": ["web"],
        "rule": f"Host(`{MLFLOW_HOST}`)",
        "service": "mlflow",
    }
    assert "mlflow-auth" not in http["services"]
    assert "mlflow-login" not in http["middlewares"]


def test_litellm_login_routes():
    config = _config()
    http = _http(config)
    routers = http["routers"]

    # stage 1's health and public routers are unchanged
    host = f"Host(`{LITELLM_HOST}`)"
    for name, paths, priority in (
        ("litellm-health", config.litellm.health_paths, 300),
        ("litellm-public", config.litellm.public_paths, 200),
    ):
        expected = " || ".join(f"Path(`{p}`)" for p in paths)
        assert routers[name]["rule"] == f"{host} && ({expected})"
        assert routers[name]["priority"] == priority
    assert "middlewares" not in routers["litellm-health"]
    assert routers["litellm-public"]["middlewares"] == ["client-rate-limit"]

    oauth = routers["litellm-oauth2"]
    assert oauth["rule"] == f"{host} && PathPrefix(`/oauth2/`)"
    assert oauth["service"] == "litellm-auth"

    session = routers["litellm-session"]
    assert LITELLM_COOKIE_RULE in session["rule"]
    assert "litellm-login" in session["middlewares"]
    assert session["service"] == "litellm"

    bearer = routers["litellm-bearer"]
    assert BEARER_RULE in bearer["rule"]
    assert f"!{LITELLM_COOKIE_RULE}" in bearer["rule"]
    for path in LITELLM_UI_PATHS:
        assert f"Path(`{path}`)" in bearer["rule"]
    assert "litellm-login" not in bearer["middlewares"]
    assert "litellm-admin-ip-allowlist" in bearer["middlewares"]
    assert "client-rate-limit" in bearer["middlewares"]
    allow = http["middlewares"]["litellm-admin-ip-allowlist"]["ipAllowList"]
    assert allow["sourceRange"] == ["203.0.113.0/24"]

    catch_all = routers["litellm-admin"]
    assert catch_all["rule"] == host
    assert "litellm-login" in catch_all["middlewares"]
    assert "client-rate-limit" in catch_all["middlewares"]
    assert "litellm-admin-ip-allowlist" not in catch_all["middlewares"]

    login = http["middlewares"]["litellm-login"]["forwardAuth"]
    assert login["address"] == f"{BACKENDS['litellm-auth']}/"
    assert login["trustForwardHeader"] is True

    order = [
        routers[n]["priority"]
        for n in (
            "litellm-public",
            "litellm-oauth2",
            "litellm-session",
            "litellm-bearer",
            "litellm-admin",
        )
    ]
    assert order == sorted(order, reverse=True)
    assert len(set(order)) == len(order)
    assert routers["litellm-health"]["priority"] > routers["litellm-public"]["priority"]


COOKIE = f"a=b; {LOGIN_COOKIE['litellm']}=xyz"


def test_litellm_requests_resolve_to_the_right_router():
    http = _http()
    h = LITELLM_HOST
    assert _winner(http, h, "/health/liveliness") == "litellm-health"
    assert _winner(http, h, "/v1/chat/completions", Authorization="Bearer k") == (
        "litellm-public"
    )
    assert _winner(http, h, "/oauth2/start") == "litellm-oauth2"
    assert _winner(http, h, "/key/list") == "litellm-admin"
    assert _winner(http, h, "/key/list", Cookie=COOKIE) == "litellm-session"
    assert _winner(http, h, "/key/list", Cookie=COOKIE, Authorization="Bearer k") == (
        "litellm-session"
    )
    assert _winner(http, h, "/key/list", Authorization="Bearer k") == "litellm-bearer"
    # a cookie that merely contains the name does not count as the session
    fake = "x_llmoxie_litellm=1"
    assert _winner(http, h, "/key/list", Authorization="Bearer k", Cookie=fake) == (
        "litellm-bearer"
    )


def test_litellm_bearer_key_needs_allowlisted_ip():
    http = _http()
    hits = _matching(http, LITELLM_HOST, "/key/generate", Authorization="Bearer sk-1")
    # the catch-all also matches, but the bearer router outranks it
    assert hits[0] == "litellm-bearer"
    assert set(hits) == {"litellm-bearer", "litellm-admin"}
    assert _carries(http, "litellm-bearer", "litellm-admin-ip-allowlist")
    assert _carries(http, "litellm-bearer", "client-rate-limit")


@pytest.mark.parametrize("ui_path", LITELLM_UI_PATHS)
def test_litellm_ui_paths_always_need_a_session(ui_path):
    http = _http()
    for path in (ui_path, f"{ui_path}/sub/page"):
        for headers in (
            {"Authorization": "Bearer x"},
            {"Authorization": "Bearer x", "Cookie": "other=1"},
            {},
        ):
            hits = _matching(http, LITELLM_HOST, path, **headers)
            assert hits, (path, headers)
            for name in hits:
                assert _carries(http, name, "litellm-login"), (path, headers, name)


def test_litellm_ui_prefix_does_not_exempt_unrelated_paths():
    """Entries match their own path and sub-paths, not look-alike management paths."""
    http = _http()
    for path in ("/loginx", "/uis", "/ssox", "/get_image2", "/user/new", "/key/login"):
        assert (
            _winner(http, LITELLM_HOST, path, Authorization="Bearer x")
            == "litellm-bearer"
        ), path


def test_logins_off_render_stage_1_exactly():
    off = _config(keycloak=False, mlflow_login=False, litellm_login=False)
    plain = _data(litellm={"admin_allowed_ips": ["203.0.113.0/24"]})
    plain["edge"]["custom_domains"].append(
        {"name": KEYCLOAK_HOST, "certificate_name": "cert-kc"}
    )
    stage_1 = LLMavenConfig.model_validate(plain)
    stage_1_backends = {k: BACKENDS[k] for k in ("litellm", "mlflow")}
    expected = build_edge_dynamic_config(stage_1, stage_1_backends)
    assert build_edge_dynamic_config(off, BACKENDS) == expected
    assert build_edge_dynamic_config(off, stage_1_backends) == expected
    assert "keycloak" not in str(expected)


# --- fix round 1 ----------------------------------------------------------------

SPLIT_COOKIE = f"{LOGIN_COOKIE['litellm']}_0=aaa; {LOGIN_COOKIE['litellm']}_1=bbb"


def test_split_session_cookie_counts_as_a_session():
    http = _http()
    hits = _winner(
        http, LITELLM_HOST, "/key/list", Cookie=SPLIT_COOKIE, Authorization="Bearer k"
    )
    assert hits == "litellm-session"
    # a look-alike name is not a session
    for fake in ("x_llmoxie_litellm_0=1", f"{LOGIN_COOKIE['litellm']}_x=1"):
        assert (
            _winner(
                http, LITELLM_HOST, "/key/list", Cookie=fake, Authorization="Bearer k"
            )
            == "litellm-bearer"
        )


def test_header_names_are_case_insensitive():
    http = _http()
    assert _winner(http, LITELLM_HOST, "/key/list", authorization="Bearer k") == (
        "litellm-bearer"
    )
    assert _winner(http, LITELLM_HOST, "/key/list", COOKIE=COOKIE) == "litellm-session"


def test_repeated_cookie_headers_any_value_counts():
    http = _http()
    cookies = ["a=b", COOKIE]
    assert _winner(
        http, LITELLM_HOST, "/key/list", Cookie=cookies, Authorization="Bearer k"
    ) == ("litellm-session")


@pytest.mark.parametrize(
    "path", ["/ui%2F", "/ui%2f", "/v2%2Flogin", "/a%25b", "/ui\\", "/ui\x00"]
)
def test_encoded_reserved_characters_never_use_the_bearer_route(path):
    """The routing path keeps %2F/%25 encoded while LiteLLM decodes them."""
    http = _http()
    hits = _matching(http, LITELLM_HOST, path, Authorization="Bearer x")
    assert hits
    assert "litellm-bearer" not in hits
    for name in hits:
        assert _carries(http, name, "litellm-login"), name


def test_keycloak_on_with_litellm_login_off_leaves_litellm_as_stage_1():
    on = _http(_config(litellm_login=False))
    plain = _data(litellm={"admin_allowed_ips": ["203.0.113.0/24"]})
    plain["edge"]["custom_domains"].append(
        {"name": KEYCLOAK_HOST, "certificate_name": "cert-kc"}
    )
    stage_1 = build_edge_dynamic_config(
        LLMavenConfig.model_validate(plain),
        {k: BACKENDS[k] for k in ("litellm", "mlflow")},
    )["http"]
    for kind in ("routers", "services"):
        for name, value in stage_1[kind].items():
            if name.startswith("litellm"):
                assert on[kind][name] == value
    assert not [
        n
        for n in on["routers"]
        if n.startswith("litellm-")
        and n not in ("litellm-health", "litellm-public", "litellm-admin")
    ]
    assert "litellm-login" not in on["middlewares"]


def test_missing_keycloak_backend_raises():
    backends = {k: v for k, v in BACKENDS.items() if k != "keycloak"}
    with pytest.raises(KeyError, match="keycloak"):
        _http(backends=backends)


@pytest.mark.parametrize("path", ["/ui;x", "/v2/login;x", "/key;x/generate"])
def test_semicolon_paths_never_use_the_bearer_route(path):
    """A path parameter (;) may be dropped by the backend, so it needs a session."""
    http = _http()
    hits = _matching(http, LITELLM_HOST, path, Authorization="Bearer x")
    assert hits
    assert "litellm-bearer" not in hits
    for name in hits:
        assert _carries(http, name, "litellm-login"), name


def test_plain_key_path_still_takes_the_bearer_route():
    assert (
        _winner(_http(), LITELLM_HOST, "/key/generate", Authorization="Bearer x")
        == "litellm-bearer"
    )
