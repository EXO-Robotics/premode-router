from __future__ import annotations

import subprocess
from pathlib import Path

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.review_patch import review_patch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _init_commit(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")


def _paths(items: list[dict]) -> set[str]:
    return {str(item.get("path")) for item in items if item.get("path")}


def _write_bound_evidence(repo: Path, packet_sha: str, command: str) -> None:
    out_dir = repo / ".premode" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "test.log").write_text(
        f"packet_sha256: {packet_sha}\n{command}\n1 passed in 0.01s\n",
        encoding="utf-8",
    )


def _make_dotnet(repo: Path) -> tuple[str, str, str]:
    (repo / "MyApp.sln").write_text("Microsoft Visual Studio Solution File\n", encoding="utf-8")
    (repo / "src" / "MyApp" / "Services").mkdir(parents=True)
    (repo / "src" / "MyApp" / "MyApp.csproj").write_text("<Project Sdk=\"Microsoft.NET.Sdk\" />\n", encoding="utf-8")
    (repo / "src" / "MyApp" / "Services" / "InvoiceService.cs").write_text(
        "namespace MyApp.Services;\npublic class InvoiceService { public int Total() => 1; }\n",
        encoding="utf-8",
    )
    (repo / "tests" / "MyApp.Tests").mkdir(parents=True)
    (repo / "tests" / "MyApp.Tests" / "MyApp.Tests.csproj").write_text("<Project Sdk=\"Microsoft.NET.Sdk\" />\n", encoding="utf-8")
    (repo / "tests" / "MyApp.Tests" / "InvoiceServiceTests.cs").write_text(
        "public class InvoiceServiceTests { }\n",
        encoding="utf-8",
    )
    return (
        "src/MyApp/Services/InvoiceService.cs",
        "tests/MyApp.Tests/InvoiceServiceTests.cs",
        "Change invoice total validation in src/MyApp/Services/InvoiceService.cs. Do not touch project files or package files.",
    )


def test_dotnet_csharp_routes_source_tests_commands_and_allowed_contract(repo: Path) -> None:
    source_path, test_path, prompt = _make_dotnet(repo)
    _init_commit(repo)

    result = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, save=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "dotnet_csharp"
    assert source_path in _paths(result["likely_edit_files"])
    assert source_path in _paths(result["likely_files"])
    assert test_path in _paths(result["related_tests"])
    assert source_path in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert source_path in (result["review_contract"].get("allowed_edit_files") or [])
    assert "MyApp.sln" not in (result["review_contract"].get("allowed_edit_files") or [])
    assert "src/MyApp/MyApp.csproj" not in (result["review_contract"].get("allowed_edit_files") or [])
    commands = result["commands"]["commands"]
    assert commands["test"]["command"] == "dotnet test"
    assert commands["build"]["command"] == "dotnet build"
    assert commands["test_project"]["command"] == "dotnet test tests/MyApp.Tests/MyApp.Tests.csproj"


def test_dotnet_allowed_source_patch_passes_review_with_bound_evidence(repo: Path) -> None:
    source_path, _test_path, prompt = _make_dotnet(repo)
    _init_commit(repo)
    compiled = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, save=True)

    source = repo / source_path
    source.write_text(source.read_text(encoding="utf-8") + "\n// reviewed change\n", encoding="utf-8")
    _write_bound_evidence(repo, compiled["compiled_packet_sha256"], "dotnet test tests/MyApp.Tests/MyApp.Tests.csproj")

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "pass"
    assert source_path in result["allowed_files_changed"]
    assert result["unexpected_files_changed"] == []
    assert result["verification"]["verification_status"] == "evidence_found"


def test_zig_routes_source_tests_commands_and_allowed_contract(repo: Path) -> None:
    (repo / "build.zig").write_text("pub fn build() void {}\n", encoding="utf-8")
    (repo / "build.zig.zon").write_text(".{}\n", encoding="utf-8")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "main.zig").write_text("pub fn main() void {}\n", encoding="utf-8")
    (repo / "test").mkdir()
    (repo / "test" / "main_test.zig").write_text("test \"main\" {}\n", encoding="utf-8")
    _init_commit(repo)

    result = compile_prompt(repo, "Change CLI argument validation in src/main.zig. Do not touch build metadata.", "lite", use_repo_map=True, cache_optimized=True, save=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "zig"
    assert "src/main.zig" in _paths(result["likely_edit_files"])
    assert "src/main.zig" in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert "test/main_test.zig" in _paths(result["related_tests"])
    assert "build.zig" not in (result["review_contract"].get("allowed_edit_files") or [])
    commands = result["commands"]["commands"]
    assert commands["test"]["command"] == "zig build test"
    assert commands["test_file"]["command"] == "zig test test/main_test.zig"


def test_haskell_stack_cabal_routes_source_tests_commands_and_allowed_contract(repo: Path) -> None:
    (repo / "stack.yaml").write_text("resolver: lts-22.0\n", encoding="utf-8")
    (repo / "myapp.cabal").write_text("cabal-version: 3.0\nname: myapp\n", encoding="utf-8")
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "Parser.hs").write_text("module Parser where\nparse = id\n", encoding="utf-8")
    (repo / "app").mkdir()
    (repo / "app" / "Main.hs").write_text("module Main where\nmain = pure ()\n", encoding="utf-8")
    (repo / "test").mkdir()
    (repo / "test" / "ParserSpec.hs").write_text("module ParserSpec where\n", encoding="utf-8")
    _init_commit(repo)

    result = compile_prompt(repo, "Change parser validation in src/Parser.hs. Do not touch package metadata.", "lite", use_repo_map=True, cache_optimized=True, save=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "haskell_stack_cabal"
    assert "src/Parser.hs" in _paths(result["likely_edit_files"])
    assert "src/Parser.hs" in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert "test/ParserSpec.hs" in _paths(result["related_tests"])
    assert "stack.yaml" not in (result["review_contract"].get("allowed_edit_files") or [])
    assert "myapp.cabal" not in (result["review_contract"].get("allowed_edit_files") or [])
    commands = result["commands"]["commands"]
    assert commands["test"]["command"] == "stack test"
    assert commands["build"]["command"] == "stack build"
