from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from premode.openclaw_contracts import (
    MAX_DANGEROUS_ZONES,
    MAX_EXACT_TASK_LENGTH,
    MAX_LIKELY_PATHS,
    MAX_VALIDATION_SURFACES,
    OpenClawDangerousMutationZoneV1,
    OpenClawLikelyPathV1,
    OpenClawPreflightContractError,
    OpenClawPreflightRequestV1,
    OpenClawPreflightResultV1,
    OpenClawValidationSurfaceV1,
    canonical_json_bytes,
    derive_openclaw_preflight_receipt_id,
    openclaw_preflight_receipt_from_dict,
    openclaw_preflight_request_from_dict,
    openclaw_preflight_result_from_dict,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDENS = ROOT / "contracts/goldens"
SCHEMAS = ROOT / "schemas"
CONTRACTS = {
    "openclaw-preflight-request-v1.json": (
        "pcodex.openclaw-preflight-request.v1.schema.json",
        openclaw_preflight_request_from_dict,
    ),
    "openclaw-preflight-result-v1.json": (
        "pcodex.openclaw-preflight-result.v1.schema.json",
        openclaw_preflight_result_from_dict,
    ),
    "openclaw-preflight-receipt-v1.json": (
        "pcodex.openclaw-preflight-receipt.v1.schema.json",
        openclaw_preflight_receipt_from_dict,
    ),
}


def _golden(name: str) -> dict[str, object]:
    return json.loads((GOLDENS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(("golden_name", "contract"), CONTRACTS.items())
def test_openclaw_preflight_goldens_are_strict_draft_2020_12_contracts(
    golden_name: str, contract: tuple[str, object]
) -> None:
    schema_name, parser = contract
    payload = _golden(golden_name)
    schema = json.loads((SCHEMAS / schema_name).read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    parsed = parser(payload)  # type: ignore[operator]
    assert parsed.to_dict() == payload


def test_request_preserves_exact_task_once_and_defaults_only_supported_profile() -> (
    None
):
    payload = _golden("openclaw-preflight-request-v1.json")
    without_profile = {key: value for key, value in payload.items() if key != "profile"}

    request = openclaw_preflight_request_from_dict(without_profile)

    assert request.profile == "openclaw"
    assert request.exact_task == payload["exact_task"]
    assert request.to_dict()["exact_task"] == payload["exact_task"]
    assert request.canonical_bytes().count(str(payload["exact_task"]).encode()) == 1


def test_request_rejects_caller_root_task_echo_fields_and_unknown_versions() -> None:
    payload = _golden("openclaw-preflight-request-v1.json")

    for field, value in (
        ("root", "/tmp/repository"),
        ("cwd", "/tmp/repository"),
        ("command", "pytest"),
        ("snippet", "file contents"),
        ("config", {"secret": True}),
        ("candidate_id", "candidate-a"),
    ):
        with pytest.raises(OpenClawPreflightContractError, match="unsupported fields"):
            openclaw_preflight_request_from_dict({**payload, field: value})

    with pytest.raises(OpenClawPreflightContractError, match="unsupported.*request"):
        openclaw_preflight_request_from_dict(
            {**payload, "schema_version": "pcodex.openclaw-preflight-request.v2"}
        )
    with pytest.raises(OpenClawPreflightContractError, match="unsupported.*profile"):
        openclaw_preflight_request_from_dict({**payload, "profile": "general"})


def test_request_enforces_character_and_utf8_byte_bounds() -> None:
    assert (
        len(OpenClawPreflightRequestV1("a" * MAX_EXACT_TASK_LENGTH).exact_task) == 32768
    )
    assert (
        len(OpenClawPreflightRequestV1("é" * 16_384).exact_task.encode("utf-8"))
        == 32768
    )

    with pytest.raises(OpenClawPreflightContractError, match="32768"):
        OpenClawPreflightRequestV1("a" * (MAX_EXACT_TASK_LENGTH + 1))
    with pytest.raises(OpenClawPreflightContractError, match="32768"):
        OpenClawPreflightRequestV1("é" * 16_385)
    with pytest.raises(OpenClawPreflightContractError, match="non-empty"):
        OpenClawPreflightRequestV1("")


def test_result_and_receipt_are_deterministic_content_free_and_exactly_bound() -> None:
    request = openclaw_preflight_request_from_dict(
        _golden("openclaw-preflight-request-v1.json")
    )
    result = openclaw_preflight_result_from_dict(
        _golden("openclaw-preflight-result-v1.json")
    )
    receipt = openclaw_preflight_receipt_from_dict(
        _golden("openclaw-preflight-receipt-v1.json")
    )

    assert (
        result.exact_task_sha256
        == hashlib.sha256(request.exact_task.encode("utf-8")).hexdigest()
    )
    receipt.validate_against_result(result)
    assert result.canonical_bytes() == canonical_json_bytes(result.to_dict())
    assert receipt.canonical_bytes() == canonical_json_bytes(receipt.to_dict())

    result_text = result.canonical_bytes().decode("utf-8")
    receipt_text = receipt.canonical_bytes().decode("utf-8")
    assert request.exact_task not in result_text
    assert request.exact_task not in receipt_text
    assert "tools/gamebot/task_queue.py" not in receipt_text
    for prohibited in (
        '"command"',
        '"snippet"',
        '"config"',
        '"root"',
        '"candidate_id"',
        '"experiment_id"',
        '"observer"',
        '"qwen"',
    ):
        assert prohibited not in receipt_text


def test_receipt_id_is_domain_separated_and_binds_every_receipt_core_field() -> None:
    payload = _golden("openclaw-preflight-receipt-v1.json")
    receipt = openclaw_preflight_receipt_from_dict(payload)
    assert receipt.receipt_id == derive_openclaw_preflight_receipt_id(
        exact_task_sha256=receipt.exact_task_sha256,
        workspace_binding_id=receipt.workspace_binding_id,
        provider_decision_sha256=receipt.provider_decision_sha256,
        routing_mode=receipt.routing_mode,
        path_count=receipt.path_count,
        dangerous_zone_count=receipt.dangerous_zone_count,
        validation_surface_count=receipt.validation_surface_count,
        ordered_paths_sha256=receipt.ordered_paths_sha256,
        dangerous_zones_sha256=receipt.dangerous_zones_sha256,
        validation_surfaces_sha256=receipt.validation_surfaces_sha256,
    )

    for field, value in (
        ("provider_decision_sha256", "e" * 64),
        ("path_count", 3),
        ("ordered_paths_sha256", "d" * 64),
    ):
        with pytest.raises(OpenClawPreflightContractError, match="receipt_id"):
            openclaw_preflight_receipt_from_dict({**payload, field: value})

    undomained = (
        "ocpr_"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in payload.items() if key != "receipt_id"}
            )
        ).hexdigest()
    )
    assert undomained != receipt.receipt_id


def test_unknown_result_and_receipt_versions_and_fields_fail_closed() -> None:
    result = _golden("openclaw-preflight-result-v1.json")
    receipt = _golden("openclaw-preflight-receipt-v1.json")

    with pytest.raises(OpenClawPreflightContractError, match="unsupported.*result"):
        openclaw_preflight_result_from_dict(
            {**result, "schema_version": "pcodex.openclaw-preflight-result.v2"}
        )
    with pytest.raises(OpenClawPreflightContractError, match="unsupported fields"):
        openclaw_preflight_result_from_dict({**result, "packet": "forbidden"})
    with pytest.raises(OpenClawPreflightContractError, match="unsupported.*receipt"):
        openclaw_preflight_receipt_from_dict(
            {**receipt, "schema_version": "pcodex.openclaw-preflight-receipt.v2"}
        )
    with pytest.raises(OpenClawPreflightContractError, match="unsupported fields"):
        openclaw_preflight_receipt_from_dict({**receipt, "timestamp": "now"})


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.py",
        "../escape.py",
        "nested/../../escape.py",
        "C:/absolute.py",
        "nested\\windows.py",
        "nested//double.py",
        "nested/./dot.py",
        "trailing/",
        "glob/*.py",
        "e\u0301/decomposed.py",
    ],
)
def test_likely_paths_require_normalized_unique_relative_posix_paths(path: str) -> None:
    with pytest.raises(OpenClawPreflightContractError, match="path"):
        OpenClawLikelyPathV1(
            path=path,
            selection_role="primary",
            authority_class="authored_source",
            surface="general",
            mutation_policy="eligible",
            explicitly_task_named=False,
            reason_codes=(),
        )


def test_cross_item_path_uniqueness_is_casefolded() -> None:
    item = OpenClawLikelyPathV1(
        path="Source/Game.cpp",
        selection_role="primary",
        authority_class="authored_source",
        surface="unreal_source",
        mutation_policy="eligible",
        explicitly_task_named=False,
        reason_codes=(),
    )
    duplicate = OpenClawLikelyPathV1(
        path="source/game.cpp",
        selection_role="support",
        authority_class="authored_source",
        surface="unreal_source",
        mutation_policy="eligible",
        explicitly_task_named=False,
        reason_codes=(),
    )

    with pytest.raises(OpenClawPreflightContractError, match="duplicate paths"):
        OpenClawPreflightResultV1(
            routing_mode="narrow",
            abstention_reason=None,
            exact_task_sha256="a" * 64,
            workspace_binding_id="ocwb_" + "b" * 32,
            ordered_likely_paths=(item, duplicate),
            dangerous_mutation_zones=(),
            expected_validation_surfaces=(),
            receipt_id="ocpr_" + "c" * 64,
        )


def test_historical_and_generated_paths_can_only_be_read_only() -> None:
    for authority_class in ("historical_evidence", "generated_evidence"):
        with pytest.raises(OpenClawPreflightContractError, match="read_only"):
            OpenClawLikelyPathV1(
                path=f"proof/{authority_class}.json",
                selection_role="support",
                authority_class=authority_class,
                surface="control_plane",
                mutation_policy="eligible",
                explicitly_task_named=True,
                reason_codes=("exact_task_path",),
            )


def test_public_reason_identifiers_reject_experiment_identity() -> None:
    with pytest.raises(OpenClawPreflightContractError, match="public-safe"):
        OpenClawDangerousMutationZoneV1(
            path_pattern="Content/**",
            surface="unreal_asset",
            mutation_policy="forbidden",
            reason_code="candidate_d3_winner",
        )


def test_routing_modes_enforce_abstention_and_raw_fallback_boundaries() -> None:
    result = _golden("openclaw-preflight-result-v1.json")
    with pytest.raises(OpenClawPreflightContractError, match="abstention_reason"):
        openclaw_preflight_result_from_dict(
            {**result, "routing_mode": "abstain", "abstention_reason": None}
        )
    with pytest.raises(OpenClawPreflightContractError, match="cannot contain"):
        openclaw_preflight_result_from_dict(
            {**result, "routing_mode": "fallback", "abstention_reason": None}
        )
    with pytest.raises(OpenClawPreflightContractError, match="only for abstain"):
        openclaw_preflight_result_from_dict(
            {
                **result,
                "routing_mode": "narrow",
                "abstention_reason": "provider_declined",
            }
        )


def test_collection_bounds_are_enforced_by_typed_contracts() -> None:
    paths = tuple(
        OpenClawLikelyPathV1(
            path=f"src/path_{index}.py",
            selection_role="support",
            authority_class="authored_source",
            surface="general",
            mutation_policy="eligible",
            explicitly_task_named=False,
            reason_codes=(),
        )
        for index in range(MAX_LIKELY_PATHS + 1)
    )
    zones = tuple(
        OpenClawDangerousMutationZoneV1(
            path_pattern=f"generated/zone_{index}/**",
            surface="general",
            mutation_policy="forbidden",
            reason_code="generated_zone",
        )
        for index in range(MAX_DANGEROUS_ZONES + 1)
    )
    validation = tuple(
        OpenClawValidationSurfaceV1(f"tests/test_{index}.py", "test")
        for index in range(MAX_VALIDATION_SURFACES + 1)
    )

    base = dict(
        routing_mode="narrow",
        abstention_reason=None,
        exact_task_sha256="a" * 64,
        workspace_binding_id="ocwb_" + "b" * 32,
        receipt_id="ocpr_" + "c" * 64,
    )
    with pytest.raises(OpenClawPreflightContractError, match="20"):
        OpenClawPreflightResultV1(
            **base,
            ordered_likely_paths=paths,
            dangerous_mutation_zones=(),
            expected_validation_surfaces=(),
        )
    with pytest.raises(OpenClawPreflightContractError, match="32"):
        OpenClawPreflightResultV1(
            **base,
            ordered_likely_paths=(),
            dangerous_mutation_zones=zones,
            expected_validation_surfaces=(),
        )
    with pytest.raises(OpenClawPreflightContractError, match="12"):
        OpenClawPreflightResultV1(
            **base,
            ordered_likely_paths=(),
            dangerous_mutation_zones=(),
            expected_validation_surfaces=validation,
        )


def test_schemas_reject_prohibited_fields_and_bad_relative_paths() -> None:
    request = _golden("openclaw-preflight-request-v1.json")
    result = _golden("openclaw-preflight-result-v1.json")
    request_schema = json.loads(
        (SCHEMAS / "pcodex.openclaw-preflight-request.v1.schema.json").read_text()
    )
    result_schema = json.loads(
        (SCHEMAS / "pcodex.openclaw-preflight-result.v1.schema.json").read_text()
    )

    with pytest.raises(ValidationError):
        Draft202012Validator(request_schema).validate({**request, "root": "/tmp"})
    escaped = json.loads(json.dumps(result))
    escaped["ordered_likely_paths"][0]["path"] = "../escape.py"
    with pytest.raises(ValidationError):
        Draft202012Validator(result_schema).validate(escaped)
