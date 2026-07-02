from __future__ import annotations

from pathlib import Path

from premode.locator import locate_files


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _paths(files) -> list[str]:
    return [file.path for file in files]


def test_high_confidence_preserved_by_quoted_literal(repo: Path) -> None:
    _write(
        repo / "src" / "app" / "page.tsx",
        'export function HomeScreen() { return <main><button>Start</button></main> }\n',
    )
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = () => <button />\n")

    result = locate_files(repo, 'Change the "Start" button label on the Home Screen.')

    assert result.confidence == "high"
    assert result.primary_files[0].path == "src/app/page.tsx"
    assert 'quoted_literal:"Start"' in result.primary_files[0].matched_signals


def test_high_confidence_preserved_by_symbol_in_generic_filename(repo: Path) -> None:
    _write(
        repo / "main.py",
        """
        class ReplayRunner:
            def timeout_handling(self):
                return "timeout handling"
        """,
    )
    _write(repo / "replay.py", "from main import ReplayRunner\n")

    result = locate_files(repo, "Fix ReplayRunner timeout handling.")

    assert result.confidence == "high"
    assert result.primary_files[0].path == "main.py"
    assert "symbol:ReplayRunner" in result.primary_files[0].matched_signals
    assert "content:timeout" in result.primary_files[0].matched_signals


def test_broad_coherent_activity_feedback_downgrades_to_medium(repo: Path) -> None:
    _write(repo / "src" / "activity" / "session.py", "class ActivitySession: pass\n")
    _write(repo / "src" / "activity" / "result.py", 'class ActivityResult:\n    feedback = "result feedback"\n')
    _write(repo / "src" / "activity" / "receipt.py", 'def render_receipt(result): return "useful feedback"\n')
    _write(repo / "src" / "ui" / "activity_view.py", 'def show_activity_result(): return "activity result"\n')

    result = locate_files(repo, "Improve the activity feedback so the result feels clearer and more useful.")

    assert result.confidence == "medium"
    assert "src/activity/result.py" in _paths(result.primary_files + result.support_files)
    assert "multiple_related_helpers" in result.ambiguity_reasons
    assert "confidence_downgraded_by_ambiguity" in result.ambiguity_reasons


def test_multi_file_cli_wording_is_not_low_when_targets_are_selected(repo: Path) -> None:
    _write(
        repo / "tools" / "run_diagnostic_batch.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Command-line diagnostic output helper")
        def main():
            print("Success: diagnostic command complete")
        """,
    )
    _write(
        repo / "tools" / "create_demo_outputs.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Create command-line demo output")
        def main():
            print("Success: demo outputs created")
        """,
    )
    _write(
        repo / "cpp" / "src" / "main.cpp",
        'int main(){ std::cout << "Usage: robotriage command-line output"; std::cerr << "error: missing input"; }\n',
    )
    _write(
        repo / "ros2" / "robotriage_ros" / "tools" / "export_scenarios_to_csv.py",
        """
        import argparse
        parser = argparse.ArgumentParser(description="Export command-line CSV output")
        def main():
            print("success: export complete")
        """,
    )
    _write(repo / "tests" / "test_cli.py", "def test_cli(): pass\n")
    _write(repo / "setup.py", "setup()\n")

    result = locate_files(
        repo,
        "Make the command-line output easier to understand: clarify one help message, one error message, and one success message. Do not change tests or packaging.",
    )
    selected = set(_paths(result.primary_files + result.support_files + result.verification_files))

    assert result.confidence in {"medium", "high"}
    assert "tools/run_diagnostic_batch.py" in selected
    assert "tools/create_demo_outputs.py" in selected
    assert "cpp/src/main.cpp" in selected
    assert "ros2/robotriage_ros/tools/export_scenarios_to_csv.py" in selected
    assert "setup.py" not in _paths(result.primary_files)
    assert "tests/test_cli.py" not in _paths(result.primary_files)


def test_weak_split_terms_do_not_report_high(repo: Path) -> None:
    _write(repo / "src" / "a.py", "# telemetry helper\n")
    _write(repo / "src" / "b.py", "# inventory helper\n")
    _write(repo / "src" / "c.py", "# timeout helper\n")

    result = locate_files(repo, "Fix telemetry inventory timeout behavior.")

    assert result.confidence in {"low", "medium"}
    assert result.confidence != "high"
    assert "terms_split_across_many_files" in result.ambiguity_reasons or any(
        reason.startswith("uncovered_core_terms:") for reason in result.ambiguity_reasons
    )


def test_generic_quality_words_do_not_pollute_uncovered_core_terms(repo: Path) -> None:
    _write(repo / "src" / "activity" / "result.py", 'class ActivityResult:\n    feedback = "activity result feedback"\n')
    _write(repo / "src" / "activity" / "session.py", "class ActivitySession: pass\n")

    result = locate_files(
        repo,
        "Make the next result clearer and easier to understand after the player finishes an activity so it feels useful and tells them what happened.",
    )

    uncovered = set(result.uncovered_prompt_terms)
    assert not {
        "clearer",
        "understand",
        "useful",
        "finishes",
        "tell",
        "tells",
        "next",
    } & uncovered
    assert not any(
        reason in {f"uncovered_core_terms:{term}" for term in {"clearer", "understand", "useful", "finishes", "tell", "tells", "next"}}
        for reason in result.ambiguity_reasons
    )
