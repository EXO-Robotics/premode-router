from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project
from premode.review_patch import review_patch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=30)


def _commit_baseline(repo: Path) -> None:
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


def _make_phoenix(repo: Path) -> tuple[str, str, str, str]:
    (repo / "mix.exs").write_text("defmodule Demo.MixProject do\nend\n", encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "assets").mkdir()
    (repo / "assets" / "app.js").write_text("console.log('phoenix')\n", encoding="utf-8")
    (repo / "lib" / "phoenix").mkdir(parents=True)
    (repo / "lib" / "phoenix" / "router.ex").write_text("defmodule Phoenix.Router do\nend\n", encoding="utf-8")
    (repo / "test" / "phoenix").mkdir(parents=True)
    (repo / "test" / "phoenix" / "router_test.exs").write_text("defmodule Phoenix.RouterTest do\nend\n", encoding="utf-8")
    return (
        "elixir_phoenix",
        "lib/phoenix/router.ex",
        "test/phoenix/router_test.exs",
        "Change Phoenix router behavior in lib/phoenix/router.ex. Do not touch assets, package.json, or generated files.",
    )


def _make_php(repo: Path) -> tuple[str, str, str, str]:
    (repo / "composer.json").write_text('{"scripts":{"test":"phpunit"}}\n', encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "src" / "Illuminate" / "Routing").mkdir(parents=True)
    (repo / "src" / "Illuminate" / "Routing" / "Router.php").write_text("<?php class Router {}\n", encoding="utf-8")
    (repo / "tests" / "Routing").mkdir(parents=True)
    (repo / "tests" / "Routing" / "RouterTest.php").write_text("<?php class RouterTest {}\n", encoding="utf-8")
    return (
        "php_composer",
        "src/Illuminate/Routing/Router.php",
        "tests/Routing/RouterTest.php",
        "Change routing validation in src/Illuminate/Routing/Router.php. Do not touch package.json or frontend assets.",
    )


def _make_rails(repo: Path) -> tuple[str, str, str, str]:
    (repo / "Gemfile").write_text("source 'https://rubygems.org'\n", encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "routes.rb").write_text("Rails.application.routes.draw do\nend\n", encoding="utf-8")
    (repo / "app" / "models").mkdir(parents=True)
    (repo / "app" / "models" / "account.rb").write_text("class Account\nend\n", encoding="utf-8")
    (repo / "spec" / "models").mkdir(parents=True)
    (repo / "spec" / "models" / "account_spec.rb").write_text("RSpec.describe Account do\nend\n", encoding="utf-8")
    return (
        "ruby_rails",
        "app/models/account.rb",
        "spec/models/account_spec.rb",
        "Change account model validation in app/models/account.rb. Do not touch package.json, Gemfile, or frontend assets.",
    )


def _make_terraform(repo: Path) -> tuple[str, str, str, str]:
    (repo / "modules" / "s3").mkdir(parents=True)
    (repo / "modules" / "s3" / "variables.tf").write_text('variable "bucket_name" { type = string }\n', encoding="utf-8")
    (repo / "main.tf").write_text('module "s3" { source = "./modules/s3" }\n', encoding="utf-8")
    (repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (repo / "terraform.tfstate").write_text("{}\n", encoding="utf-8")
    (repo / ".terraform.lock.hcl").write_text("# lock\n", encoding="utf-8")
    return (
        "terraform",
        "modules/s3/variables.tf",
        "",
        "Change Terraform validation for modules/s3/variables.tf bucket_name. Do not touch terraform.tfstate, .terraform.lock.hcl, .env, or root module wiring.",
    )


@pytest.mark.parametrize("factory", [_make_phoenix, _make_php, _make_rails, _make_terraform])
def test_new_adapter_likely_edit_files_are_allowed_by_review_contract(repo: Path, factory) -> None:
    project_kind, source_path, test_path, prompt = factory(repo)
    _commit_baseline(repo)

    result = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, save=True)

    assert result["project_detection"]["active_project"]["project_kind"] == project_kind
    assert source_path in _paths(result["likely_edit_files"])
    assert source_path in _paths(result["likely_files"])
    assert source_path in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert source_path in (result["review_contract"].get("allowed_edit_files") or [])
    if test_path:
        assert test_path in _paths(result["related_tests"])
    for forbidden in ("assets/app.js", "package.json", "Gemfile", "composer.json", ".env", "terraform.tfstate", ".terraform.lock.hcl"):
        assert forbidden not in (result["patch_boundary"].get("allowed_edit_files") or [])
        assert forbidden not in (result["review_contract"].get("allowed_edit_files") or [])


@pytest.mark.parametrize(
    ("factory", "evidence_command"),
    [
        (_make_phoenix, "mix test test/phoenix/router_test.exs"),
        (_make_php, "composer test"),
        (_make_rails, "bundle exec rspec spec/models/account_spec.rb"),
        (_make_terraform, "terraform validate"),
    ],
)
def test_new_adapter_allowed_source_patch_passes_review_with_bound_evidence(repo: Path, factory, evidence_command: str) -> None:
    _project_kind, source_path, _test_path, prompt = factory(repo)
    _commit_baseline(repo)
    compiled = compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, save=True)

    source = repo / source_path
    source.write_text(source.read_text(encoding="utf-8") + "\n# reviewed change\n", encoding="utf-8")
    _write_bound_evidence(repo, compiled["compiled_packet_sha256"], evidence_command)

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "pass"
    assert source_path in result["allowed_files_changed"]
    assert result["unexpected_files_changed"] == []
    assert result["verification"]["verification_status"] == "evidence_found"


@pytest.mark.parametrize(
    ("factory", "forbidden_path"),
    [
        (_make_phoenix, "assets/app.js"),
        (_make_phoenix, "package.json"),
        (_make_php, "package.json"),
        (_make_rails, "Gemfile"),
        (_make_rails, "package.json"),
        (_make_terraform, ".env"),
        (_make_terraform, "terraform.tfstate"),
    ],
)
def test_new_adapter_forbidden_patch_paths_block_review(repo: Path, factory, forbidden_path: str) -> None:
    _project_kind, _source_path, _test_path, prompt = factory(repo)
    _commit_baseline(repo)
    compile_prompt(repo, prompt, "lite", use_repo_map=True, cache_optimized=True, save=True)

    target = repo / forbidden_path
    target.write_text(target.read_text(encoding="utf-8") + "\nforbidden change\n", encoding="utf-8")

    result = review_patch(repo, since_compile=True)

    assert result["merge_readiness"] == "blocked"
    assert forbidden_path in (
        result["prompt_forbidden_files_touched"]
        + result["secret_like_paths_touched"]
        + result["generated_or_state_mutation"]
    )
