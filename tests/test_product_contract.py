import argparse
import json
import pathlib
import shutil
import sys
import tomllib

import premode
from premode.cli import build_parser
from premode.pcodex_bootstrap import LOCAL_STATE_CLEANUP_TARGETS, _parser as build_pcodex_parser
from premode.product_contract import validate_installed_product_contract


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _validate(instance, schema, path="$") -> None:
    if "const" in schema:
        assert instance == schema["const"], f"{path}: wrong constant"
    expected = schema.get("type")
    if expected == "object":
        assert isinstance(instance, dict), f"{path}: expected object"
        required = set(schema.get("required", []))
        assert required <= set(instance), f"{path}: missing required fields"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(instance) <= set(properties), f"{path}: unexpected fields"
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], f"{path}.{key}")
    elif expected == "array":
        assert isinstance(instance, list), f"{path}: expected array"
        assert len(instance) >= schema.get("minItems", 0), f"{path}: too few items"
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True) for item in instance]
            assert len(encoded) == len(set(encoded)), f"{path}: duplicate items"
        for index, value in enumerate(instance):
            _validate(value, schema.get("items", {}), f"{path}[{index}]")
    elif expected == "string":
        assert isinstance(instance, str), f"{path}: expected string"
        assert len(instance) >= schema.get("minLength", 0), f"{path}: string too short"


def _choices(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("parser has no subcommands")


def test_product_manifest_shape_without_network_dependencies() -> None:
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/premode.product.schema.json").read_text(encoding="utf-8"))
    _validate(manifest, schema)
    assert manifest["canonical_packet_authority"] == {
        "version": "v5",
        "variant": "tool_assisted_anchors_internal",
        "strategy": "literal_symbol",
        "public_renderer": "canonical_core_v1",
        "model_facing_sections": ["TASK", "LIKELY FILES", "PRIMARY", "VERIFY", "SUPPORT"],
        "internal_anchors_model_facing": False,
    }


def test_installed_product_manifest_and_schema_validator(tmp_path: pathlib.Path) -> None:
    share = tmp_path / "share" / "premode-router"
    (share / "schemas").mkdir(parents=True)
    shutil.copy2(ROOT / "premode.product.json", share / "premode.product.json")
    shutil.copy2(ROOT / "schemas" / "premode.product.schema.json", share / "schemas" / "premode.product.schema.json")
    result = validate_installed_product_contract(tmp_path)
    assert result == {
        "status": "valid",
        "schema_version": "premode.product.v2",
        "product_name": "pCodex",
        "release_target": "0.3.0b1",
    }


def test_public_commands_exist_in_active_parsers() -> None:
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    premode_commands = _choices(build_parser())
    pcodex_commands = _choices(build_pcodex_parser())
    for command in manifest["public_commands"]:
        program, name, *rest = command.split()
        if program == "premode":
            assert name in premode_commands
        else:
            assert name in pcodex_commands
        if rest:
            parser = build_pcodex_parser() if program == "pcodex" else build_parser()
            action = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
            nested = action.choices[name]
            assert rest[0] in _choices(nested)


def test_bounded_uninstall_is_a_public_command() -> None:
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    assert "pcodex uninstall" in manifest["public_commands"]
    assert "review" in _choices(build_pcodex_parser())
    assert "uninstall" in _choices(build_pcodex_parser())


def test_manifest_covers_every_active_cleanup_target() -> None:
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    locations = "\n".join(entry["location"] for entry in manifest["stateful_surface_inventory"])
    for target in LOCAL_STATE_CLEANUP_TARGETS:
        component = "/".join(target.strip("/").split("/")[:2])
        assert component in locations, target


def test_core_version_has_one_declared_authority_and_matching_runtime_mirror() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "premode.__version__"}
    assert premode.__version__ == "0.3.0b1"


def test_production_modules_do_not_import_observer_modules() -> None:
    production = ["cli.py", "compiler.py", "locator.py", "pcodex_bootstrap.py", "routing_contract.py", "production_ranking.py", "production_ranking_incumbent.py", "managed_state.py"]
    combined = "\n".join((ROOT / "src" / "premode" / name).read_text(encoding="utf-8") for name in production)
    assert "from .lab73" not in combined
    assert "import premode.lab73" not in combined


def test_contract_and_manifest_agree_on_claim_boundaries() -> None:
    contract = (ROOT / "docs/PRODUCT_CONTRACT.md").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "premode.product.json").read_text(encoding="utf-8"))
    for command in manifest["public_commands"]:
        assert command in contract
    assert "not production-supported" in contract
    assert manifest["integration_status"]["openclaw"] == "advanced_experimental_not_production_supported"
