from __future__ import annotations

from pathlib import Path

from premode.adapters import detect_projects
from premode.command_discovery import discover_commands
from premode.compiler import compile_prompt
from premode.config import init_project
from premode.indexer import index_project


def _init(repo: Path) -> None:
    init_project(repo)
    index_project(repo, "lite")


def _paths(items: list[dict]) -> set[str]:
    return {str(item.get("path")) for item in items if item.get("path")}


def test_phoenix_assets_folder_does_not_trigger_unity(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "mix.exs").write_text("defmodule Demo.MixProject do\nend\n", encoding="utf-8")
    (repo / "assets").mkdir()
    (repo / "assets" / "app.js").write_text("console.log('phoenix')\n", encoding="utf-8")
    (repo / "lib" / "phoenix").mkdir(parents=True)
    (repo / "lib" / "phoenix" / "router.ex").write_text("defmodule Phoenix.Router do\nend\n", encoding="utf-8")
    (repo / "test" / "phoenix").mkdir(parents=True)
    (repo / "test" / "phoenix" / "router_test.exs").write_text("defmodule Phoenix.RouterTest do\nend\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Fix routing behavior in lib/phoenix/router.ex.", "lite", use_repo_map=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "elixir_phoenix"
    assert result["project_detection"]["active_project"]["project_kind"] != "unity"
    assert "lib/phoenix/router.ex" in _paths(result["likely_edit_files"])
    assert "test/phoenix/router_test.exs" in _paths(result["related_tests"])
    assert result["commands"]["commands"]["test"]["command"] == "mix test"
    assert any(item["command"] == "mix test test/phoenix/router_test.exs" for item in result["verification_order"])


def test_php_composer_outranks_package_json_and_maps_phpunit(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "composer.json").write_text('{"scripts":{"test":"phpunit"}}\n', encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "plugins" / "Goals").mkdir(parents=True)
    (repo / "plugins" / "Goals" / "Controller.php").write_text("<?php class Controller {}\n", encoding="utf-8")
    (repo / "tests" / "PHPUnit" / "Plugins" / "Goals").mkdir(parents=True)
    (repo / "tests" / "PHPUnit" / "Plugins" / "Goals" / "ControllerTest.php").write_text("<?php class ControllerTest {}\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Fix plugins/Goals/Controller.php behavior.", "lite", use_repo_map=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "php_composer"
    assert "plugins/Goals/Controller.php" in _paths(result["likely_edit_files"])
    assert "tests/PHPUnit/Plugins/Goals/ControllerTest.php" in _paths(result["related_tests"])
    assert "composer.json" not in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert result["commands"]["commands"]["test"]["command"] == "composer test"


def test_ruby_rails_outranks_package_json_and_maps_rspec(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "Gemfile").write_text("source 'https://rubygems.org'\n", encoding="utf-8")
    (repo / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "routes.rb").write_text("Rails.application.routes.draw do\nend\n", encoding="utf-8")
    (repo / "app" / "models").mkdir(parents=True)
    (repo / "app" / "models" / "account.rb").write_text("class Account\nend\n", encoding="utf-8")
    (repo / "spec" / "models").mkdir(parents=True)
    (repo / "spec" / "models" / "account_spec.rb").write_text("RSpec.describe Account do\nend\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Fix app/models/account.rb validation.", "lite", use_repo_map=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "ruby_rails"
    assert "app/models/account.rb" in _paths(result["likely_edit_files"])
    assert "spec/models/account_spec.rb" in _paths(result["related_tests"])
    assert "Gemfile" not in (result["patch_boundary"].get("allowed_edit_files") or [])
    assert result["commands"]["commands"]["test"]["command"] == "bundle exec rspec"


def test_terraform_target_is_editable_but_state_and_lock_are_not(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "modules" / "s3").mkdir(parents=True)
    (repo / "modules" / "s3" / "variables.tf").write_text('variable "bucket_name" { type = string }\n', encoding="utf-8")
    (repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (repo / "terraform.tfstate").write_text("{}\n", encoding="utf-8")
    (repo / ".terraform.lock.hcl").write_text("# lock\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Change Terraform validation for modules/s3/variables.tf.", "lite", use_repo_map=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "terraform"
    assert "modules/s3/variables.tf" in _paths(result["likely_edit_files"])
    assert "terraform.tfstate" not in _paths(result["likely_edit_files"])
    assert ".terraform.lock.hcl" not in (result["patch_boundary"].get("allowed_edit_files") or [])
    commands = result["commands"]["commands"]
    assert commands["fmt"]["command"] == "terraform fmt -check"
    assert commands["validate"]["command"] == "terraform validate"


def test_android_kotlin_maps_app_tests_and_module_gradle_commands(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "settings.gradle").write_text("pluginManagement {}\n", encoding="utf-8")
    (repo / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "app").mkdir()
    (repo / "app" / "build.gradle").write_text("plugins { id 'com.android.application' }\n", encoding="utf-8")
    main = repo / "app" / "src" / "main" / "java" / "com" / "example"
    test = repo / "app" / "src" / "test" / "java" / "com" / "example"
    android_test = repo / "app" / "src" / "androidTest" / "java" / "com" / "example"
    main.mkdir(parents=True)
    test.mkdir(parents=True)
    android_test.mkdir(parents=True)
    (main / "MainActivity.kt").write_text("class MainActivity\n", encoding="utf-8")
    (test / "MainActivityTest.kt").write_text("class MainActivityTest\n", encoding="utf-8")
    (android_test / "MainActivityDeviceTest.kt").write_text("class MainActivityDeviceTest\n", encoding="utf-8")
    _init(repo)

    result = compile_prompt(repo, "Fix app/src/main/java/com/example/MainActivity.kt.", "lite", use_repo_map=True)

    assert result["project_detection"]["active_project"]["project_kind"] == "java_kotlin"
    assert "app/src/main/java/com/example/MainActivity.kt" in _paths(result["likely_edit_files"])
    assert "app/src/test/java/com/example/MainActivityTest.kt" in _paths(result["related_tests"])
    commands = result["commands"]["commands"]
    assert commands["test"]["command"] == "./gradlew :app:testDebugUnitTest"
    assert commands["build"]["command"] == "./gradlew :app:assembleDebug"
    assert "build.gradle" not in (result["patch_boundary"].get("allowed_edit_files") or [])


def test_lowercase_assets_without_unity_markers_is_not_unity(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "mix.exs").write_text("defmodule Demo.MixProject do\nend\n", encoding="utf-8")
    (repo / "assets").mkdir()
    (repo / "assets" / "README.md").write_text("web assets\n", encoding="utf-8")
    _init(repo)
    detection = detect_projects(repo, entries=index_project(repo, "lite")["entries"])
    assert detection["active_project"]["project_kind"] == "elixir_phoenix"
    assert all(item["project_kind"] != "unity" for item in detection["detected_projects"])
