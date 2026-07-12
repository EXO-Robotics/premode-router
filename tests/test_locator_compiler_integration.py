from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _prepare(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _paths(files) -> list[str]:
    return [str(item.get("path")) for item in files if isinstance(item, dict)]


def _all_context_paths(result: dict) -> set[str]:
    paths: set[str] = set()
    for key in ("candidate_edit_files", "likely_edit_files", "read_only_support_files", "related_tests", "suggested_tests"):
        paths.update(_paths(result.get(key) or []))
    for key in ("full_text_files", "summarized_files", "manifest_only_files"):
        paths.update(_paths((result.get("context_tiers") or {}).get(key) or []))
    return paths


def test_compiler_recovers_generic_ui_file_from_locator(repo: Path) -> None:
    _write(
        repo / "src" / "app" / "page.tsx",
        'export function HomeScreen() { return <main aria-label="Home Screen"><button>Start</button></main> }\n',
    )
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = ({children}) => <button>{children}</button>\n")
    _prepare(repo)

    result = compile_prompt(repo, 'Move the "Start" button on the Home Screen.', "lite", record=False)

    assert "src/app/page.tsx" in _paths(result["candidate_edit_files"])
    assert "src/components/Button.tsx" not in _paths(result["candidate_edit_files"][:1])
    locator_primary = result["locator_evidence"]["primary_files"]
    assert locator_primary[0]["path"] == "src/app/page.tsx"
    signals = locator_primary[0]["matched_signals"]
    assert 'quoted_literal:"Start"' in signals
    assert any("home" in signal for signal in signals)
    assert any("screen" in signal for signal in signals)
    assert any("button" in signal for signal in signals)


def test_compiler_manifest_includes_locator_dependency_relations(repo: Path) -> None:
    _write(
        repo / "src" / "app" / "page.tsx",
        """
        import { useHomeActions } from "./useHomeActions"
        export function HomeScreen() {
          const actions = useHomeActions()
          return <main aria-label="Home Screen"><button onClick={actions.start}>Start</button></main>
        }
        """,
    )
    _write(repo / "src" / "app" / "useHomeActions.ts", "export function useHomeActions() { return { start() {} } }\n")
    _prepare(repo)

    result = compile_prompt(repo, 'Move the "Start" button on the Home Screen.', "lite", record=False)

    assert "src/app/page.tsx" in _paths(result["candidate_edit_files"])
    assert "src/app/useHomeActions.ts" in _all_context_paths(result)
    relations = result["locator_evidence"]["dependency_relations"]
    assert {
        "source": "src/app/page.tsx",
        "target": "src/app/useHomeActions.ts",
        "relation": "imports",
        "strength": 86,
    } in relations


def test_compiler_uses_symbol_content_for_generic_filename(repo: Path) -> None:
    _write(
        repo / "src" / "main.py",
        """
        class ReplayRunner:
            def timeout_handling(self):
                return "timeout handling"
        """,
    )
    _write(repo / "src" / "replay.py", "def replay_helper(): return True\n")
    _prepare(repo)

    result = compile_prompt(repo, "Fix ReplayRunner timeout handling.", "lite", record=False)

    assert "src/main.py" in _paths(result["candidate_edit_files"])
    assert _paths(result["candidate_edit_files"]).index("src/main.py") < len(result["candidate_edit_files"])
    locator_primary = result["locator_evidence"]["primary_files"]
    assert locator_primary[0]["path"] == "src/main.py"
    assert "symbol:ReplayRunner" in locator_primary[0]["matched_signals"]
    assert "content:timeout" in locator_primary[0]["matched_signals"]


def test_compiler_allows_config_primary_when_prompt_asks_config(repo: Path) -> None:
    _write(repo / "pyproject.toml", "[project.scripts]\nrobotriage = 'src.cli:main'\n")
    _write(repo / "src" / "cli.py", "def main(): pass\n")
    _prepare(repo)

    result = compile_prompt(repo, "Fix the console script entry point.", "lite", record=False)

    assert "pyproject.toml" in _paths(result["candidate_edit_files"])
    assert "src/cli.py" in _all_context_paths(result)
    assert result["locator_evidence"]["primary_files"][0]["path"] == "pyproject.toml"


def test_compiler_keeps_test_file_available_when_prompt_asks_test(repo: Path) -> None:
    _write(repo / "tests" / "test_checkout_flow.py", "def test_checkout_flow(): assert checkout_total() == 10\n")
    _write(repo / "src" / "checkout.py", "def checkout_total(): return 0\n")
    _prepare(repo)

    result = compile_prompt(repo, "Fix the failing checkout flow test.", "lite", record=False)

    all_paths = _all_context_paths(result)
    assert "tests/test_checkout_flow.py" in all_paths
    assert result["locator_evidence"]["primary_files"][0]["path"] == "tests/test_checkout_flow.py"


def test_compiler_does_not_transport_secret_file_from_locator(repo: Path) -> None:
    _write(repo / ".env", "API_TOKEN=literal-secret-token\n")
    _write(repo / "src" / "config.py", "API_TOKEN_ENV = 'API_TOKEN'\ndef load_api_token(): return API_TOKEN_ENV\n")
    _prepare(repo)

    result = compile_prompt(repo, "Update API token config loading.", "lite", record=False)

    assert ".env" not in _all_context_paths(result)
    assert ".env" not in {
        item["path"]
        for bucket in ("primary_files", "support_files", "verification_files")
        for item in result["locator_evidence"][bucket]
    }
    rejected = [
        item
        for item in result["locator_evidence"]["candidate_provenance"]
        if item["normalized_path"] == ".env"
    ]
    assert rejected and rejected[0]["final_disposition"] == "REJECT"
    assert "literal-secret-token" not in str(result["locator_evidence"])
    assert "src/config.py" in _all_context_paths(result)


def test_low_confidence_locator_does_not_force_weak_files_to_candidates(repo: Path) -> None:
    _write(repo / "src" / "a.py", "# telemetry helper\n")
    _write(repo / "src" / "b.py", "# inventory helper\n")
    _write(repo / "src" / "c.py", "# timeout helper\n")
    _prepare(repo)

    result = compile_prompt(repo, "Fix telemetry inventory timeout behavior.", "lite", record=False)

    assert result["locator_evidence"]["confidence"] in {"low", "medium"}
    assert "terms_split_across_many_files" in result["locator_evidence"]["ambiguity_reasons"]
    weak_paths = {"src/a.py", "src/b.py", "src/c.py"}
    assert not (weak_paths & set(_paths(result["candidate_edit_files"])))
    fit = result["evidence_summary"]["locator_context_fit"]
    assert fit["confidence"] in {"low", "medium"}
