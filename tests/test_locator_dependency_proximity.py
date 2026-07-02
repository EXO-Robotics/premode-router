from __future__ import annotations

from pathlib import Path

from premode.locator import locate_files


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _paths(files) -> list[str]:
    return [file.path for file in files]


def _all_paths(result) -> list[str]:
    return _paths(result.primary_files + result.support_files + result.verification_files)


def _signals(result, path: str) -> list[str]:
    for file in result.primary_files + result.support_files + result.verification_files:
        if file.path == path:
            return file.matched_signals
    return []


def test_checkout_page_imports_totals_helper_cluster(repo: Path) -> None:
    _write(
        repo / "src" / "pages" / "CheckoutPage.tsx",
        """
        import { useCheckoutTotals } from "../hooks/useCheckoutTotals"
        export function CheckoutPage() {
          const total = useCheckoutTotals()
          return <span>{total}</span>
        }
        """,
    )
    _write(
        repo / "src" / "hooks" / "useCheckoutTotals.ts",
        """
        import { applyDiscount } from "../lib/pricing"
        export function useCheckoutTotals() {
          return calculateTotal(applyDiscount())
        }
        export function calculateTotal(value = 0) { return value }
        """,
    )
    _write(repo / "src" / "lib" / "pricing.ts", "export function applyDiscount() { return taxDiscountMath() }\n")
    _write(
        repo / "tests" / "checkout-flow.test.ts",
        'import { useCheckoutTotals } from "../src/hooks/useCheckoutTotals"\ntest("checkout total", () => {})\n',
    )

    result = locate_files(repo, "Fix checkout total calculation.")
    all_paths = _all_paths(result)

    assert "src/hooks/useCheckoutTotals.ts" in _paths(result.primary_files + result.support_files)
    assert "src/pages/CheckoutPage.tsx" in _paths(result.support_files + result.primary_files)
    assert "tests/checkout-flow.test.ts" in _paths(result.verification_files + result.support_files)
    assert any("import" in signal or "proximity_to_primary:" in signal for signal in _signals(result, "src/pages/CheckoutPage.tsx"))
    assert any(path in all_paths for path in ["src/lib/pricing.ts", "src/hooks/useCheckoutTotals.ts"])
    assert result.dependency_relations


def test_start_button_page_keeps_literal_primary_and_action_helper_support(repo: Path) -> None:
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
    _write(repo / "src" / "components" / "Button.tsx", "export const Button = ({children}) => <button>{children}</button>\n")

    result = locate_files(repo, 'Move the "Start" button on the Home Screen.')

    assert result.primary_files[0].path == "src/app/page.tsx"
    assert "src/app/useHomeActions.ts" in _paths(result.support_files + result.verification_files)
    assert "src/components/Button.tsx" not in _paths(result.primary_files[:1])
    assert any(signal.startswith("imported_by:src/app/page.tsx") for signal in _signals(result, "src/app/useHomeActions.ts"))


def test_python_cli_imports_exporter_writer_cluster(repo: Path) -> None:
    _write(
        repo / "tools" / "export_csv.py",
        """
        import argparse
        from src.exporter.csv_writer import write_csv
        parser = argparse.ArgumentParser(description="CSV export")
        def main(output_folder):
            return write_csv(output_folder)
        """,
    )
    _write(
        repo / "src" / "exporter" / "csv_writer.py",
        """
        def write_csv(output_folder):
            if not output_folder:
                raise ValueError("output folder is missing")
        """,
    )
    _write(repo / "tools" / "build_html_report.py", "import argparse\nparser = argparse.ArgumentParser()\n")
    _write(repo / "tests" / "test_csv_export.py", "from src.exporter.csv_writer import write_csv\n")

    result = locate_files(repo, "Improve the CSV export error message when the output folder is missing.")
    all_paths = _all_paths(result)

    assert "tools/export_csv.py" in all_paths
    assert "src/exporter/csv_writer.py" in all_paths
    assert "tools/build_html_report.py" not in _paths(result.primary_files[:1])
    assert "tests/test_csv_export.py" in _paths(result.verification_files + result.support_files)
    assert any(
        relation.source == "tools/export_csv.py" and relation.target == "src/exporter/csv_writer.py"
        for relation in result.dependency_relations
    )


def test_api_route_imports_user_settings_service_cluster(repo: Path) -> None:
    _write(repo / "src" / "api" / "routes" / "index.py", 'ROUTES = ["/users", "/settings"]\n')
    _write(
        repo / "src" / "api" / "routes" / "user_handler.py",
        """
        from src.services.user_settings import update_user_settings
        ROUTE = "/users"
        def handler(payload):
            return update_user_settings(payload)
        """,
    )
    _write(
        repo / "src" / "services" / "user_settings.py",
        """
        def update_user_settings(payload):
            if payload is None:
                raise ValueError("missing update payload")
        """,
    )
    _write(repo / "tests" / "test_user_settings_api.py", "def test_missing_update_payload(): pass\n")

    result = locate_files(repo, "Fix the user settings API handler when the update payload is missing.")
    all_paths = _all_paths(result)

    assert "src/api/routes/user_handler.py" in _paths(result.primary_files + result.support_files)
    assert "src/services/user_settings.py" in _paths(result.primary_files + result.support_files)
    assert "src/api/routes/index.py" not in _paths(result.primary_files[:1])
    assert "tests/test_user_settings_api.py" in _paths(result.verification_files + result.support_files)
    assert any(
        relation.source == "src/api/routes/user_handler.py" and relation.target == "src/services/user_settings.py"
        for relation in result.dependency_relations
    )
    assert "src/api/routes/index.py" not in all_paths or result.primary_files[0].path != "src/api/routes/index.py"


def test_test_prompt_keeps_test_primary_and_source_support(repo: Path) -> None:
    _write(
        repo / "tests" / "test_replay_timeout.py",
        """
        from src.replay_runner import replay_timeout
        def test_replay_timeout_expectation():
            assert replay_timeout() == "expected timeout"
        """,
    )
    _write(repo / "src" / "replay_runner.py", "def replay_timeout(): return 'timeout'\n")

    result = locate_files(repo, "Fix the failing replay timeout test expectation.")

    assert result.primary_files[0].path == "tests/test_replay_timeout.py"
    assert "src/replay_runner.py" in _paths(result.support_files + result.verification_files)
    assert any(signal.startswith(("imports:", "adjacent_source:", "proximity_to_primary:")) for signal in _signals(result, "src/replay_runner.py"))


def test_proximity_does_not_promote_many_generic_utilities(repo: Path) -> None:
    imports = "\n".join(f'import {{ util{i} }} from "./utils/util{i}"' for i in range(6))
    _write(
        repo / "src" / "checkout" / "discount.ts",
        f"""
        {imports}
        export function fixCheckoutDiscountRounding() {{
          return "checkout discount rounding"
        }}
        """,
    )
    for index in range(6):
        _write(repo / "src" / "checkout" / "utils" / f"util{index}.ts", f"export function util{index}() {{ return {index} }}\n")

    result = locate_files(repo, "Fix checkout discount rounding.")
    primary_paths = _paths(result.primary_files)
    utility_primary = [path for path in primary_paths if "/utils/" in path]
    utility_support = [path for path in _paths(result.support_files) if "/utils/" in path]

    assert result.primary_files[0].path == "src/checkout/discount.ts"
    assert not utility_primary
    assert len(utility_support) <= 4
    assert "proximity_only_support" in result.ambiguity_reasons or utility_support


def test_low_confidence_split_dependency_cluster_does_not_overclaim(repo: Path) -> None:
    _write(repo / "src" / "telemetry.py", "from src.inventory import inventory_helper\n# telemetry helper\n")
    _write(repo / "src" / "inventory.py", "from src.timeout import timeout_helper\n# inventory helper\n")
    _write(repo / "src" / "timeout.py", "# timeout helper\n")

    result = locate_files(repo, "Fix telemetry inventory timeout behavior.")

    assert result.confidence in {"low", "medium"}
    assert result.confidence != "high"
    reasons = set(result.ambiguity_reasons)
    assert "dependency_cluster_split" in reasons or "terms_split_across_many_files" in reasons
    assert "proximity_only_support" in reasons or result.dependency_relations
