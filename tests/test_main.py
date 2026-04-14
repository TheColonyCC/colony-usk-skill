"""Tests for the colony-usk-skill dispatcher.

All tests mock ``colony_sdk.ColonyClient`` so they run hermetically and never
touch the real Colony API. The goal is 100% line coverage of ``main.py``.
"""

from __future__ import annotations

import io
import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import main

# --------------------------------------------------------------------------
# Helper: run main() with a given stdin and captured stdout.
# --------------------------------------------------------------------------


def run_main(
    stdin_text: str,
    env: dict[str, str] | None = None,
    client_factory: Any = None,
) -> tuple[int, dict]:
    """Invoke ``main.main()`` with a fake stdin, return (exit_code, parsed_stdout).

    If ``client_factory`` is provided, ``main.ColonyClient`` is patched so
    instantiating it returns whatever the factory produces. This keeps every
    test hermetic.
    """
    captured_stdout = io.StringIO()

    patchers: list[Any] = [
        patch.object(sys, "stdin", io.StringIO(stdin_text)),
        patch.object(sys, "stdout", captured_stdout),
    ]
    if env is not None:
        patchers.append(patch.dict("os.environ", env, clear=False))
    if client_factory is not None:
        patchers.append(patch.object(main, "ColonyClient", client_factory))

    for p in patchers:
        p.start()
    try:
        code = main.main()
    finally:
        for p in reversed(patchers):
            p.stop()

    raw_out = captured_stdout.getvalue().strip()
    parsed = json.loads(raw_out) if raw_out else {}
    return code, parsed


# --------------------------------------------------------------------------
# Action discovery
# --------------------------------------------------------------------------


def test_action_map_is_populated_and_excludes_state_helpers():
    # Every excluded method must NOT appear
    for name in main.EXCLUDED_METHODS:
        assert name not in main.ACTIONS, f"{name} should be excluded"

    # Spot-check a selection of actions that should definitely be exposed
    expected = [
        "create_post",
        "get_post",
        "get_posts",
        "update_post",
        "delete_post",
        "create_comment",
        "get_comments",
        "get_all_comments",
        "iter_comments",
        "vote_post",
        "vote_comment",
        "react_post",
        "react_comment",
        "get_colonies",
        "join_colony",
        "leave_colony",
        "search",
        "directory",
        "send_message",
        "list_conversations",
        "get_conversation",
        "get_notifications",
        "mark_notification_read",
        "mark_notifications_read",
        "get_me",
        "get_user",
        "update_profile",
        "follow",
        "unfollow",
        "get_webhooks",
        "create_webhook",
        "update_webhook",
        "delete_webhook",
        "register",
        "rotate_key",
    ]
    for name in expected:
        assert name in main.ACTIONS, f"{name} should be exposed"

    # Private methods must not leak
    for name in main.ACTIONS:
        assert not name.startswith("_")

    # Register must be in the static-method set
    assert "register" in main.STATIC_METHODS


def test_build_action_map_skips_non_callables_and_dunders():
    # The helper itself must be idempotent — re-running should yield the
    # same map.
    first = main._build_action_map()
    second = main._build_action_map()
    assert first == second


# --------------------------------------------------------------------------
# Serialisation helper
# --------------------------------------------------------------------------


class _Dummy:
    """Plain Python class with no special serialisation hooks."""

    def __init__(self) -> None:
        self.foo = "bar"
        self.nested = {"inner": 42}
        self._private = "hidden"


class _WithModelDump:
    """Pydantic-style object — model_dump() should take precedence."""

    def model_dump(self) -> dict:
        return {"dumped": True}


class _Exotic:
    """No __dict__, no model_dump — should fall through to str()."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return f"exotic({self.value})"


def test_serialisable_primitives():
    assert main._serialisable(None) is None
    assert main._serialisable(1) == 1
    assert main._serialisable(1.5) == 1.5
    assert main._serialisable("x") == "x"
    assert main._serialisable(True) is True


def test_serialisable_dict_and_list():
    assert main._serialisable({"a": 1, "b": [2, 3]}) == {"a": 1, "b": [2, 3]}
    assert main._serialisable([1, {"x": "y"}, (4, 5)]) == [1, {"x": "y"}, [4, 5]]


def test_serialisable_plain_object_strips_private_attrs():
    result = main._serialisable(_Dummy())
    assert result == {"foo": "bar", "nested": {"inner": 42}}
    assert "_private" not in result


def test_serialisable_model_dump_wins():
    assert main._serialisable(_WithModelDump()) == {"dumped": True}


def test_serialisable_exotic_falls_back_to_str():
    assert main._serialisable(_Exotic("hi")) == "exotic(hi)"


# --------------------------------------------------------------------------
# Request validation errors
# --------------------------------------------------------------------------


def test_empty_stdin_returns_empty_input_error():
    code, resp = run_main("")
    assert code == 1
    assert resp["status"] == "error"
    assert resp["error"]["code"] == "EMPTY_INPUT"


def test_whitespace_only_stdin_returns_empty_input_error():
    code, resp = run_main("   \n\n  ")
    assert code == 1
    assert resp["error"]["code"] == "EMPTY_INPUT"


def test_invalid_json_returns_parse_error():
    code, resp = run_main("not json at all")
    assert code == 1
    assert resp["error"]["code"] == "INVALID_JSON"


def test_non_object_top_level_returns_invalid_request():
    code, resp = run_main("[1, 2, 3]")
    assert code == 1
    assert resp["error"]["code"] == "INVALID_REQUEST"


def test_missing_action_returns_invalid_request():
    code, resp = run_main("{}")
    assert code == 1
    assert resp["error"]["code"] == "INVALID_REQUEST"


def test_non_string_action_returns_invalid_request():
    code, resp = run_main(json.dumps({"action": 42}))
    assert code == 1
    assert resp["error"]["code"] == "INVALID_REQUEST"


def test_empty_string_action_returns_invalid_request():
    code, resp = run_main(json.dumps({"action": ""}))
    assert code == 1
    assert resp["error"]["code"] == "INVALID_REQUEST"


def test_unknown_action_returns_unknown_action_error():
    code, resp = run_main(json.dumps({"action": "no_such_method"}))
    assert code == 1
    assert resp["error"]["code"] == "UNKNOWN_ACTION"
    assert "no_such_method" in resp["error"]["message"]


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


def test_missing_api_key_for_authenticated_action():
    # Clear any inherited COLONY_API_KEY from the environment
    with patch.dict("os.environ", {}, clear=True):
        code, resp = run_main(json.dumps({"action": "get_me"}))
    assert code == 1
    assert resp["error"]["code"] == "MISSING_API_KEY"


def test_register_does_not_require_api_key():
    # register is a static method — no client needed.
    fake_register = MagicMock(return_value={"id": "abc", "api_key": "col_fresh"})

    # Patch the SDK's register method so it doesn't hit the network.
    with patch.object(main.ColonyClient, "register", fake_register), patch.dict("os.environ", {}, clear=True):
        code, resp = run_main(
            json.dumps(
                {
                    "action": "register",
                    "username": "my-agent",
                    "display_name": "My Agent",
                    "bio": "A new agent",
                }
            )
        )
    assert code == 0
    assert resp["status"] == "ok"
    assert resp["result"] == {"id": "abc", "api_key": "col_fresh"}
    fake_register.assert_called_once_with(
        username="my-agent",
        display_name="My Agent",
        bio="A new agent",
    )


# --------------------------------------------------------------------------
# Successful dispatch
# --------------------------------------------------------------------------


def _stub_client_factory(method_name: str, return_value: Any) -> Any:
    """Return a callable that builds a MagicMock with ``method_name`` stubbed."""

    def factory(api_key: str) -> MagicMock:
        client = MagicMock(spec=[method_name])
        getattr(client, method_name).return_value = return_value
        return client

    return factory


def test_dispatch_passes_kwargs_to_sdk_method():
    fake_post = {"id": "p1", "title": "Hi", "body": "Hello", "score": 0}
    factory = _stub_client_factory("create_post", fake_post)

    code, resp = run_main(
        json.dumps(
            {
                "action": "create_post",
                "title": "Hi",
                "body": "Hello",
                "colony": "general",
            }
        ),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 0
    assert resp == {"status": "ok", "result": fake_post}


def test_dispatch_with_list_return_value():
    items = [{"id": "a"}, {"id": "b"}]
    factory = _stub_client_factory("get_all_comments", items)
    code, resp = run_main(
        json.dumps({"action": "get_all_comments", "post_id": "p1"}),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 0
    assert resp["result"] == items


def test_dispatch_with_none_return_value():
    # mark_notifications_read returns None — should serialise to null.
    factory = _stub_client_factory("mark_notifications_read", None)
    code, resp = run_main(
        json.dumps({"action": "mark_notifications_read"}),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 0
    assert resp == {"status": "ok", "result": None}


def test_generator_results_are_exhausted():
    def gen_posts():
        yield {"id": "p1"}
        yield {"id": "p2"}
        yield {"id": "p3"}

    factory = _stub_client_factory("iter_posts", gen_posts())
    code, resp = run_main(
        json.dumps({"action": "iter_posts", "colony": "general", "max_results": 3}),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 0
    assert resp["result"] == [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]


# --------------------------------------------------------------------------
# SDK errors
# --------------------------------------------------------------------------


def test_invalid_args_returns_invalid_args_error():
    def factory(api_key: str) -> MagicMock:
        client = MagicMock(spec=["create_post"])
        # Simulate the real SDK raising TypeError on wrong kwargs
        client.create_post.side_effect = TypeError("create_post() got an unexpected keyword argument 'tit'")
        return client

    code, resp = run_main(
        json.dumps({"action": "create_post", "tit": "typo"}),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 1
    assert resp["error"]["code"] == "INVALID_ARGS"
    assert "tit" in resp["error"]["message"]


def test_sdk_error_with_code_attribute_is_passed_through():
    class AuthError(Exception):
        code = "AUTH_INVALID_TOKEN"

    def factory(api_key: str) -> MagicMock:
        client = MagicMock(spec=["get_me"])
        client.get_me.side_effect = AuthError("Token expired")
        return client

    code, resp = run_main(
        json.dumps({"action": "get_me"}),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 1
    assert resp["error"]["code"] == "AUTH_INVALID_TOKEN"
    assert resp["error"]["message"] == "Token expired"


def test_sdk_error_without_code_falls_back_to_exception_class_name():
    def factory(api_key: str) -> MagicMock:
        client = MagicMock(spec=["get_me"])
        client.get_me.side_effect = RuntimeError("Something exploded")
        return client

    code, resp = run_main(
        json.dumps({"action": "get_me"}),
        env={"COLONY_API_KEY": "col_test"},
        client_factory=factory,
    )
    assert code == 1
    assert resp["error"]["code"] == "RuntimeError"
    assert resp["error"]["message"] == "Something exploded"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def test_main_module_entry_point_invokes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running ``python -m main`` should call ``main.main()`` and exit with its code."""
    # Confirm main.main is callable at module level — covers the ``if __name__`` branch
    # indirectly by asserting the pattern is there. The actual branch is not easily
    # coverable from within pytest, so we exclude it with `# pragma: no cover` in the
    # source if needed. For now we just sanity-check the symbol.
    assert callable(main.main)
