from pathlib import Path
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_APP_ENV_NAMES = (
    "EVENT_CARDS_PATH",
    "RETRIEVER_BACKEND",
    "REVIEW_CONFIDENCE_THRESHOLD",
    "ENABLE_OFFLINE_DEMO_REVIEWER",
)
_ORIGINAL_APP_ENV = {name: os.environ.get(name) for name in _APP_ENV_NAMES}
import app as demo_app  # noqa: E402
for _name, _value in _ORIGINAL_APP_ENV.items():
    if _value is None:
        os.environ.pop(_name, None)
    else:
        os.environ[_name] = _value


def test_exact_preset_keeps_standard_policy() -> None:
    assert (
        demo_app.resolve_review_policy(
            demo_app.STANDARD_MODE,
            demo_app.DEMO_TARGET,
            demo_app.DEMO_CONTEXT,
            demo_app.DEMO_TEXT,
        )
        == "standard"
    )


def test_changed_comment_automatically_enables_strict_policy() -> None:
    assert (
        demo_app.resolve_review_policy(
            demo_app.STANDARD_MODE,
            demo_app.DEMO_TARGET,
            demo_app.DEMO_CONTEXT,
            "面试官临时输入的一条新评论",
        )
        == "strict_live_test"
    )


def test_explicit_strict_mode_routes_even_the_preset() -> None:
    assert (
        demo_app.resolve_review_policy(
            demo_app.STRICT_MODE,
            demo_app.DEMO_TARGET,
            demo_app.DEMO_CONTEXT,
            demo_app.DEMO_TEXT,
        )
        == "strict_live_test"
    )
