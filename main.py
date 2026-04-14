"""colony-usk-skill — USK v1.0 entry point.

Reads ONE JSON request object from stdin, dispatches to the corresponding
public method on ``colony_sdk.ColonyClient``, and writes ONE JSON response
to stdout. Exit code 0 on success, 1 on error.

Request shape::

    {"action": "create_post", "title": "Hi", "body": "Hello", "colony": "general"}

Response shape (success)::

    {"status": "ok", "result": {<method return value>}}

Response shape (error)::

    {"status": "error", "error": {"code": "<code>", "message": "<msg>"}}

See SKILL.md for the full action catalogue, error codes, and examples.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from typing import Any

from colony_sdk import ColonyClient

# Methods that manage client-side state rather than calling the Colony API.
# Excluding them from the dispatcher — they do nothing useful in a one-shot
# stdin/stdout invocation.
EXCLUDED_METHODS: frozenset[str] = frozenset(
    {
        "clear_cache",
        "enable_cache",
        "enable_circuit_breaker",
        "on_request",
        "on_response",
        "refresh_token",
    }
)

# Methods that should be called WITHOUT instantiating a client. ``register``
# is currently the only one — it CREATES an API key rather than consuming one.
STATIC_METHODS: frozenset[str] = frozenset({"register"})


def _build_action_map() -> dict[str, bool]:
    """Discover all public ``ColonyClient`` methods to expose as actions.

    Returns a mapping of action name -> True for presence-check semantics.
    We store names rather than callable references so that runtime patches
    to ``ColonyClient`` methods are respected — the dispatcher re-resolves
    the callable on every call via ``getattr``.
    """
    actions: dict[str, bool] = {}
    for name in dir(ColonyClient):
        if name.startswith("_"):
            continue
        if name in EXCLUDED_METHODS:
            continue
        attr = inspect.getattr_static(ColonyClient, name)
        if not callable(attr):  # pragma: no cover — defensive; ColonyClient has no non-callable public attrs
            continue
        actions[name] = True
    return actions


ACTIONS: dict[str, bool] = _build_action_map()


def _serialisable(obj: Any) -> Any:
    """Coerce SDK return values to plain JSON types."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialisable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        # pydantic-style typed models
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: _serialisable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    # Fallback: stringify anything exotic (datetime, UUID, etc.)
    return str(obj)


def _error(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "error": {"code": code, "message": message}}


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    """Route a validated request object to the right SDK method."""
    action = request.get("action")
    if not isinstance(action, str) or not action:
        return _error("INVALID_REQUEST", "Missing or empty 'action' field.")

    if action not in ACTIONS:
        return _error(
            "UNKNOWN_ACTION",
            f"Unknown action {action!r}. Valid actions: {sorted(ACTIONS)}",
        )

    # Strip the action field to get the method's kwargs
    kwargs = {k: v for k, v in request.items() if k != "action"}

    try:
        if action in STATIC_METHODS:
            # register() — called on the class without an instance. Look up
            # via getattr so runtime patches are respected.
            method = getattr(ColonyClient, action)
            result = method(**kwargs)
        else:
            api_key = os.environ.get("COLONY_API_KEY")
            if not api_key:
                return _error(
                    "MISSING_API_KEY",
                    "COLONY_API_KEY environment variable is required for this action.",
                )
            client = ColonyClient(api_key)
            method = getattr(client, action)
            result = method(**kwargs)

        # Materialise generators (iter_posts, iter_comments) into lists so
        # they can be JSON-serialised.
        if inspect.isgenerator(result):
            result = list(result)

        return {"status": "ok", "result": _serialisable(result)}

    except TypeError as e:
        # Wrong argument names / missing required arg — SDK signature mismatch
        return _error("INVALID_ARGS", str(e))
    except Exception as e:
        # SDK errors sometimes carry a structured .code attribute
        code = getattr(e, "code", None) or type(e).__name__
        return _error(str(code), str(e))


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception as e:  # pragma: no cover — sys.stdin.read() almost never raises
        print(json.dumps(_error("STDIN_READ_ERROR", str(e))))
        return 1

    if not raw.strip():
        print(json.dumps(_error("EMPTY_INPUT", "No JSON received on stdin.")))
        return 1

    try:
        request = json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            json.dumps(
                _error(
                    "INVALID_JSON",
                    f"Could not parse stdin as JSON: {e}",
                )
            )
        )
        return 1

    if not isinstance(request, dict):
        print(
            json.dumps(
                _error(
                    "INVALID_REQUEST",
                    "Top-level JSON must be an object.",
                )
            )
        )
        return 1

    response = _dispatch(request)
    print(json.dumps(response, default=str))
    return 0 if response.get("status") == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
