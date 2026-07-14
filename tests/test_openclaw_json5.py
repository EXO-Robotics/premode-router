from __future__ import annotations

from dataclasses import replace

import pytest

from premode.openclaw_json5 import (
    Json5SpanEdit,
    OpenClawJson5ConflictError,
    OpenClawJson5Error,
    OpenClawJson5Ownership,
    apply_json5_edit_plan,
    inspect_pcodex_document,
    plan_install_pcodex,
    plan_remove_pcodex,
)


VALUE = {
    "args": ["-m", "premode.pcodex_bootstrap", "mcp-server"],
    "command": "/installed/python",
    "cwd": "/workspace with spaces/ユニコード",
}


def _install(raw: bytes, value: dict[str, object] | None = None):
    plan = plan_install_pcodex(raw, value or VALUE)
    return apply_json5_edit_plan(raw, plan), plan.ownership


@pytest.mark.parametrize(
    "raw",
    (
        b"{}",
        b"{}\n",
        b"{root:'single-quoted',unquoted:[.5,+1,0xFF,Infinity,NaN,],}",
        b'{"double":"// not a comment","block":"/* not a comment */"}',
        (
            b"\xef\xbb\xbf{\r\n"
            b"  // keep CRLF and comments\r\n"
            b"  unquoted: 'value',\r\n"
            b"  nested: { trailing: true, },\r\n"
            b"}"
        ),
        "{emoji:'🌲',路径:'保持'}".encode(),
    ),
)
def test_install_then_remove_restores_every_original_byte(raw: bytes) -> None:
    installed, ownership = _install(raw)

    assert installed != raw
    assert apply_json5_edit_plan(
        installed, plan_remove_pcodex(installed, ownership)
    ) == raw


@pytest.mark.parametrize(
    ("raw", "created"),
    (
        (b"{}", ("mcp", "mcp.servers")),
        (b"{mcp:{/*keep*/}}", ("mcp.servers",)),
        (b"{mcp:{servers:{/*keep*/}}}", ()),
    ),
)
def test_install_uses_the_narrowest_existing_object(
    raw: bytes, created: tuple[str, ...]
) -> None:
    installed, ownership = _install(raw)
    inspection = inspect_pcodex_document(installed)

    assert ownership.created_containers == created
    assert inspection.target_present is True
    assert inspection.target_value_sha256 == ownership.target_value_sha256
    assert apply_json5_edit_plan(
        installed, plan_remove_pcodex(installed, ownership)
    ) == raw


def test_escaped_authority_keys_are_decoded_and_not_duplicated() -> None:
    raw = b'{"m\\u0063p":{"serv\\x65rs":{}}}'

    installed, ownership = _install(raw)

    assert ownership.created_containers == ()
    assert installed.count(b'"pcodex"') == 1
    assert apply_json5_edit_plan(
        installed, plan_remove_pcodex(installed, ownership)
    ) == raw


def test_unrelated_root_edit_after_install_is_preserved_exactly() -> None:
    original = b"{root:'before', formatting : [1, 2,],}"
    installed, ownership = _install(original, {"command": "python"})
    changed = installed.replace(b"'before'", b"'after'", 1)

    removed = apply_json5_edit_plan(
        changed, plan_remove_pcodex(changed, ownership)
    )

    assert removed == b"{root:'after', formatting : [1, 2,],}"


def test_sibling_server_addition_preserves_created_containers() -> None:
    installed, ownership = _install(b"{}", {"command": "python"})
    changed = installed.replace(
        b'{"pcodex":{"command":"python"}}',
        b'{"pcodex":{"command":"python"},"other":{url:\'stdio://x\'}}',
    )

    removed = apply_json5_edit_plan(
        changed, plan_remove_pcodex(changed, ownership)
    )

    assert removed == b'{"mcp":{"servers":{"other":{url:\'stdio://x\'}}}}'


def test_sibling_mcp_addition_collapses_only_created_empty_servers() -> None:
    installed, ownership = _install(b"{}", {"command": "python"})
    changed = installed.replace(
        b'{"servers":{"pcodex":{"command":"python"}}}',
        b'{"servers":{"pcodex":{"command":"python"}}, timeout : 5}',
    )

    removed = apply_json5_edit_plan(
        changed, plan_remove_pcodex(changed, ownership)
    )

    assert removed == b'{"mcp":{ timeout : 5}}'


def test_sibling_root_addition_still_collapses_owned_mcp() -> None:
    installed, ownership = _install(b"{}", {"command": "python"})
    changed = installed[:-1] + b", root : 'keep'}"

    removed = apply_json5_edit_plan(
        changed, plan_remove_pcodex(changed, ownership)
    )

    assert removed == b"{ root : 'keep'}"


@pytest.mark.parametrize(
    ("changed", "expected"),
    (
        (
            b'{"mcp":{/* user mcp comment */"servers":{"pcodex":{"command":"python"}}}}',
            b'{"mcp":{/* user mcp comment */}}',
        ),
        (
            b'{"mcp":{"servers":{/* user server comment */"pcodex":{"command":"python"}}}}',
            b'{"mcp":{"servers":{/* user server comment */}}}',
        ),
        (
            b'{"mcp":{"servers":{"pcodex":{"command":"python"}/* after target */}}}',
            b'{"mcp":{"servers":{/* after target */}}}',
        ),
    ),
)
def test_comments_added_inside_created_wrappers_prevent_unsafe_collapse(
    changed: bytes, expected: bytes
) -> None:
    _, ownership = _install(b"{}", {"command": "python"})

    removed = apply_json5_edit_plan(
        changed, plan_remove_pcodex(changed, ownership)
    )

    assert removed == expected


def test_user_added_trailing_comma_on_sole_target_fails_closed() -> None:
    _, ownership = _install(b"{}", {"command": "python"})
    changed = b'{"mcp":{"servers":{"pcodex":{"command":"python"},}}}'

    with pytest.raises(OpenClawJson5Error):
        plan_remove_pcodex(changed, ownership)


def test_existing_servers_wrapper_is_never_claimed_or_collapsed() -> None:
    original = b"{mcp:{servers:{/* owned by user */}}}"
    installed, ownership = _install(original, {"command": "python"})

    removed = apply_json5_edit_plan(
        installed, plan_remove_pcodex(installed, ownership)
    )

    assert ownership.created_containers == ()
    assert removed == original


@pytest.mark.parametrize(
    "raw",
    (
        b"{mcp:{},mcp:{}}",
        b"{mcp:{servers:{},servers:{}}}",
        b"{mcp:{servers:{pcodex:{},pcodex:{}}}}",
        b'{"mcp":{},"m\\u0063p":{}}',
    ),
)
def test_duplicate_authority_keys_fail_closed(raw: bytes) -> None:
    with pytest.raises(OpenClawJson5ConflictError):
        inspect_pcodex_document(raw)
    with pytest.raises(OpenClawJson5ConflictError):
        plan_install_pcodex(raw, VALUE)


@pytest.mark.parametrize(
    "raw",
    (
        b"{mcp:null}",
        b"{mcp:'${OPENCLAW_MCP}'}",
        b"{mcp:{servers:false}}",
        b"{$include:'other.json'}",
        b"{mcp:{$include:'other.json'}}",
        b"{mcp:{servers:{$include:'servers.json'}}}",
        b"{mcp:{servers:{pcodex:{command:'${COMMAND}'}}}}",
        b"{mcp:{servers:{other:{token:'${TOKEN}'}}}}",
    ),
)
def test_ambiguous_or_environment_derived_authority_fails_closed(raw: bytes) -> None:
    with pytest.raises(OpenClawJson5Error):
        inspect_pcodex_document(raw)
    with pytest.raises(OpenClawJson5Error):
        plan_install_pcodex(raw, VALUE)


@pytest.mark.parametrize(
    "raw",
    (
        b"[]",
        b"{",
        b"{mcp}",
        b"{mcp:,}",
        b"{mcp:{servers:{pcodex:@bad}}}",
        b"{/* unterminated",
        b"{'unterminated: 1}",
        b"{a:[1 2]}",
        b"{a:1,,b:2}",
        "{💩:1}".encode(),
        b"\xff{}",
    ),
)
def test_malformed_or_unsupported_documents_are_rejected(raw: bytes) -> None:
    with pytest.raises(OpenClawJson5Error):
        inspect_pcodex_document(raw)


def test_existing_target_is_a_conflict_and_is_never_adopted() -> None:
    raw = b"{mcp:{servers:{pcodex:{command:'user-owned'}}}}"

    with pytest.raises(OpenClawJson5ConflictError):
        plan_install_pcodex(raw, VALUE)


def test_modified_owned_target_is_preserved() -> None:
    installed, ownership = _install(b"{}", {"a": 1, "b": 2})
    reformatted = installed.replace(b'{"a":1,"b":2}', b'{"a": 1, "b": 2}')

    with pytest.raises(OpenClawJson5ConflictError):
        plan_remove_pcodex(reformatted, ownership)


def test_remove_refuses_to_cross_an_unrelated_comment() -> None:
    installed, ownership = _install(b"{}", {"command": "python"})
    moved = b'{"mcp":{"servers":{"other":1, /* keep */ "pcodex":{"command":"python"}}}}'
    assert inspect_pcodex_document(moved).target_value_sha256 == ownership.target_value_sha256

    with pytest.raises(OpenClawJson5Error):
        plan_remove_pcodex(moved, ownership)


def test_remove_last_owned_member_without_trivia_preserves_sibling_value() -> None:
    _, ownership = _install(b"{}", {"command": "python"})
    moved = b'{"mcp":{"servers":{"other":1,"pcodex":{"command":"python"}}}}'

    removed = apply_json5_edit_plan(
        moved, plan_remove_pcodex(moved, ownership)
    )

    assert removed == b'{"mcp":{"servers":{"other":1}}}'


@pytest.mark.parametrize(
    "changed",
    (
        b'{"mcp":{"servers":{"other":1,  "pcodex":{"command":"python"}}}}',
        b'{"mcp":{"servers":{"pcodex":{"command":"python"} /* keep */,"other":1}}}',
        b'{"mcp":{"servers":{"pcodex" /* keep */:{"command":"python"}}}}',
    ),
)
def test_modified_member_trivia_is_preserved_by_failing_closed(changed: bytes) -> None:
    _, ownership = _install(b"{}", {"command": "python"})

    with pytest.raises(OpenClawJson5Error):
        plan_remove_pcodex(changed, ownership)


def test_created_wrapper_with_modified_member_prefix_is_not_collapsed() -> None:
    _, ownership = _install(b"{}", {"command": "python"})
    changed = b'{"mcp" /* keep */:{"servers":{"pcodex":{"command":"python"}}}}'

    removed = apply_json5_edit_plan(
        changed, plan_remove_pcodex(changed, ownership)
    )

    assert removed == b'{"mcp" /* keep */:{}}'


def test_stale_plan_and_before_span_mismatch_are_rejected() -> None:
    raw = b"{}"
    plan = plan_install_pcodex(raw, {"command": "python"})
    with pytest.raises(OpenClawJson5ConflictError):
        apply_json5_edit_plan(b"{ }", plan)

    edit = plan.edits[0]
    tampered = replace(
        plan,
        edits=(Json5SpanEdit(edit.start, edit.end, "not-empty", edit.after),),
    )
    with pytest.raises(OpenClawJson5ConflictError):
        apply_json5_edit_plan(raw, tampered)


def test_planning_is_deterministic() -> None:
    raw = b"\xef\xbb\xbf{/*keep*/root:'x',}\r\n"

    assert plan_install_pcodex(raw, VALUE) == plan_install_pcodex(raw, VALUE)


@pytest.mark.parametrize(
    "ownership",
    (
        OpenClawJson5Ownership("future", ("mcp", "servers", "pcodex"), "0" * 64, ()),
        OpenClawJson5Ownership(
            "pcodex.openclaw-json5-ownership.v1", ("other",), "0" * 64, ()
        ),
        OpenClawJson5Ownership(
            "pcodex.openclaw-json5-ownership.v1",
            ("mcp", "servers", "pcodex"),
            "invalid",
            (),
        ),
        OpenClawJson5Ownership(
            "pcodex.openclaw-json5-ownership.v1",
            ("mcp", "servers", "pcodex"),
            "0" * 64,
            ("servers",),
        ),
    ),
)
def test_invalid_or_future_ownership_fails_closed(
    ownership: OpenClawJson5Ownership,
) -> None:
    with pytest.raises(OpenClawJson5Error):
        plan_remove_pcodex(b"{}", ownership)


def test_registration_value_must_be_safe_json_without_environment_authority() -> None:
    with pytest.raises(OpenClawJson5Error):
        plan_install_pcodex(b"{}", {"command": float("nan")})
    with pytest.raises(OpenClawJson5Error):
        plan_install_pcodex(b"{}", {"command": "${COMMAND}"})
