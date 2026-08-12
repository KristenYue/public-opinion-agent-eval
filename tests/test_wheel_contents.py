from pathlib import Path
from zipfile import ZipFile
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_wheel_contents import inspect_wheel  # noqa: E402


def test_wheel_inspection_accepts_required_package_and_static_files(tmp_path: Path) -> None:
    wheel = tmp_path / "package.whl"
    required = {
        "opinion_agent/__init__.py": "",
        "opinion_agent/api.py": "",
        "opinion_agent/mcp_server.py": "",
        "opinion_agent/agent/graph.py": "",
        "opinion_agent/static/index.html": "",
        "opinion_agent/static/app.js": "",
        "opinion_agent/static/styles.css": "",
    }
    with ZipFile(wheel, "w") as archive:
        for name, content in required.items():
            archive.writestr(name, content)

    assert inspect_wheel(wheel) == {"passed": True, "missing": [], "forbidden": []}


def test_wheel_inspection_rejects_private_or_unlicensed_assets(tmp_path: Path) -> None:
    wheel = tmp_path / "package.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("data/raw_private/comment.csv", "private")

    result = inspect_wheel(wheel)

    assert result["passed"] is False
    assert result["missing"]
    assert result["forbidden"] == ["data/raw_private/comment.csv"]
