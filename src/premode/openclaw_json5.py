"""Lossless, receipt-bound JSON5 edits for ``mcp.servers.pcodex``.

OpenClaw accepts JSON5 but its native configuration writer serializes the
complete document.  This module deliberately has a much smaller authority: it
parses enough JSON5 to prove the target structure, then inserts or removes one
member while retaining every unrelated character verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping


OWNERSHIP_SCHEMA_VERSION = "pcodex.openclaw-json5-ownership.v1"
TARGET_PATH = ("mcp", "servers", "pcodex")
_ENV_REFERENCE = re.compile(r"\$\{[^}]*\}")
_NUMBER = re.compile(
    r"[+-]?(?:Infinity|NaN|0[xX][0-9a-fA-F]+|"
    r"(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))\Z"
)


def _identifier_start(character: str) -> bool:
    return character == "$" or character == "_" or character.isidentifier()


def _identifier_continue(character: str) -> bool:
    return (
        character in {"$", "_", "\u200c", "\u200d"} or ("_" + character).isidentifier()
    )


class OpenClawJson5Error(ValueError):
    """The JSON5 document cannot be edited without weakening authority."""


class OpenClawJson5ConflictError(OpenClawJson5Error):
    """The pCodex target exists, is duplicated, or differs from ownership."""


@dataclass(frozen=True)
class Json5SpanEdit:
    """One exact character-span replacement."""

    start: int
    end: int
    before: str
    after: str


@dataclass(frozen=True)
class OpenClawJson5Ownership:
    """Non-sensitive authority needed to remove an installed member."""

    schema_version: str
    target_path: tuple[str, ...]
    target_value_sha256: str
    created_containers: tuple[str, ...]


@dataclass(frozen=True)
class Json5EditPlan:
    """A deterministic edit plan bound to the complete source document."""

    operation: str
    source_sha256: str
    edits: tuple[Json5SpanEdit, ...]
    ownership: OpenClawJson5Ownership


@dataclass(frozen=True)
class OpenClawJson5Inspection:
    """Content-free status for the one supported target path."""

    document_sha256: str
    target_present: bool
    target_value_sha256: str | None
    mcp_present: bool
    servers_present: bool


@dataclass(frozen=True)
class _Member:
    key: str
    start: int
    end: int
    value: "_Node"
    comma_start: int | None
    comma_end: int | None


@dataclass(frozen=True)
class _Node:
    kind: str
    start: int
    end: int
    members: tuple[_Member, ...] = ()
    items: tuple["_Node", ...] = ()
    string_value: str | None = None


@dataclass(frozen=True)
class _Authority:
    root: _Node
    mcp_member: _Member | None
    mcp: _Node | None
    servers_member: _Member | None
    servers: _Node | None
    target_member: _Member | None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OpenClawJson5Error("OpenClaw configuration must be valid UTF-8") from exc


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.position = 1 if text.startswith("\ufeff") else 0

    def parse(self) -> _Node:
        self._trivia()
        node = self._value()
        self._trivia()
        if self.position != self.length:
            self._fail("unexpected content after root value")
        if node.kind != "object":
            self._fail("OpenClaw configuration root must be an object", node.start)
        return node

    def _fail(self, message: str, position: int | None = None) -> None:
        offset = self.position if position is None else position
        raise OpenClawJson5Error(f"{message} at character {offset}")

    def _trivia(self) -> None:
        while self.position < self.length:
            character = self.text[self.position]
            if character.isspace():
                self.position += 1
                continue
            if self.text.startswith("//", self.position):
                newline = self.text.find("\n", self.position + 2)
                self.position = self.length if newline < 0 else newline + 1
                continue
            if self.text.startswith("/*", self.position):
                close = self.text.find("*/", self.position + 2)
                if close < 0:
                    self._fail("unterminated block comment")
                self.position = close + 2
                continue
            return

    def _value(self) -> _Node:
        if self.position >= self.length:
            self._fail("expected JSON5 value")
        character = self.text[self.position]
        if character == "{":
            return self._object()
        if character == "[":
            return self._array()
        if character in {"'", '"'}:
            start = self.position
            value = self._string()
            return _Node("string", start, self.position, string_value=value)
        return self._primitive()

    def _object(self) -> _Node:
        start = self.position
        self.position += 1
        members: list[_Member] = []
        self._trivia()
        if self._take("}"):
            return _Node("object", start, self.position, members=())

        while True:
            self._trivia()
            member_start = self.position
            key = self._key()
            self._trivia()
            if not self._take(":"):
                self._fail("expected ':' after object key")
            self._trivia()
            value = self._value()
            member_end = value.end
            self._trivia()
            comma_start: int | None = None
            comma_end: int | None = None
            if self._take(","):
                comma_start = self.position - 1
                comma_end = self.position
            members.append(
                _Member(
                    key=key,
                    start=member_start,
                    end=member_end,
                    value=value,
                    comma_start=comma_start,
                    comma_end=comma_end,
                )
            )
            self._trivia()
            if self._take("}"):
                return _Node("object", start, self.position, members=tuple(members))
            if comma_end is None:
                self._fail("expected ',' or '}' after object member")

    def _array(self) -> _Node:
        start = self.position
        self.position += 1
        items: list[_Node] = []
        self._trivia()
        if self._take("]"):
            return _Node("array", start, self.position, items=())
        while True:
            self._trivia()
            items.append(self._value())
            self._trivia()
            comma = self._take(",")
            self._trivia()
            if self._take("]"):
                return _Node("array", start, self.position, items=tuple(items))
            if not comma:
                self._fail("expected ',' or ']' after array item")

    def _key(self) -> str:
        if self.position >= self.length:
            self._fail("expected object key")
        if self.text[self.position] in {"'", '"'}:
            return self._string()
        start = self.position
        first = self.text[self.position]
        if not _identifier_start(first):
            self._fail("unsupported unquoted object key")
        self.position += 1
        while self.position < self.length:
            character = self.text[self.position]
            if _identifier_continue(character):
                self.position += 1
                continue
            break
        return self.text[start : self.position]

    def _string(self) -> str:
        quote = self.text[self.position]
        self.position += 1
        decoded: list[str] = []
        while self.position < self.length:
            character = self.text[self.position]
            self.position += 1
            if character == quote:
                return "".join(decoded)
            if character in {"\n", "\r"}:
                self._fail("unescaped newline in string", self.position - 1)
            if character != "\\":
                decoded.append(character)
                continue
            if self.position >= self.length:
                self._fail("unterminated string escape")
            escaped = self.text[self.position]
            self.position += 1
            if escaped == "\r":
                if self.position < self.length and self.text[self.position] == "\n":
                    self.position += 1
                continue
            if escaped == "\n":
                continue
            simple = {
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "v": "\v",
                "0": "\0",
            }
            if escaped in simple:
                decoded.append(simple[escaped])
                continue
            if escaped in {"x", "u"}:
                count = 2 if escaped == "x" else 4
                digits = self.text[self.position : self.position + count]
                if len(digits) != count or not all(
                    item in "0123456789abcdefABCDEF" for item in digits
                ):
                    self._fail("invalid hexadecimal string escape")
                decoded.append(chr(int(digits, 16)))
                self.position += count
                continue
            decoded.append(escaped)
        self._fail("unterminated string")
        raise AssertionError("unreachable")

    def _primitive(self) -> _Node:
        start = self.position
        while self.position < self.length:
            if self.text.startswith(("//", "/*"), self.position):
                break
            character = self.text[self.position]
            if character.isspace() or character in {",", "]", "}"}:
                break
            self.position += 1
        raw = self.text[start : self.position]
        if raw in {"true", "false", "null", "Infinity", "NaN"} or _NUMBER.fullmatch(
            raw
        ):
            return _Node("primitive", start, self.position)
        self._fail("unsupported or malformed JSON5 primitive", start)
        raise AssertionError("unreachable")

    def _take(self, expected: str) -> bool:
        if self.text.startswith(expected, self.position):
            self.position += len(expected)
            return True
        return False


def _parse(raw: bytes) -> tuple[str, _Node]:
    text = _decode(raw)
    return text, _Parser(text).parse()


def _members(node: _Node, key: str) -> tuple[_Member, ...]:
    return tuple(member for member in node.members if member.key == key)


def _unique_member(node: _Node, key: str, label: str) -> _Member | None:
    found = _members(node, key)
    if len(found) > 1:
        raise OpenClawJson5ConflictError(f"duplicate {label} keys are unsafe")
    return found[0] if found else None


def _contains_environment_reference(node: _Node) -> bool:
    if node.kind == "string" and node.string_value is not None:
        return bool(_ENV_REFERENCE.search(node.string_value))
    return any(
        _contains_environment_reference(member.value) for member in node.members
    ) or any(_contains_environment_reference(item) for item in node.items)


def _reject_include(node: _Node, label: str) -> None:
    if _members(node, "$include"):
        raise OpenClawJson5Error(f"$include authority at {label} is unsupported")


def _authority(root: _Node) -> _Authority:
    _reject_include(root, "the configuration root")
    mcp_member = _unique_member(root, "mcp", "mcp")
    if mcp_member is None:
        return _Authority(root, None, None, None, None, None)
    mcp = mcp_member.value
    if mcp.kind != "object":
        raise OpenClawJson5Error("mcp must be an object")
    _reject_include(mcp, "mcp")
    if _contains_environment_reference(mcp):
        raise OpenClawJson5Error(
            "environment-derived authority inside mcp is unsupported"
        )

    servers_member = _unique_member(mcp, "servers", "servers")
    if servers_member is None:
        return _Authority(root, mcp_member, mcp, None, None, None)
    servers = servers_member.value
    if servers.kind != "object":
        raise OpenClawJson5Error("mcp.servers must be an object")
    _reject_include(servers, "mcp.servers")
    target_member = _unique_member(servers, "pcodex", "pcodex")
    return _Authority(root, mcp_member, mcp, servers_member, servers, target_member)


def inspect_pcodex_document(raw: bytes) -> OpenClawJson5Inspection:
    """Validate authority and return content-free target status."""

    text, root = _parse(raw)
    authority = _authority(root)
    target_hash = None
    if authority.target_member is not None:
        target = authority.target_member.value
        if _contains_environment_reference(target):
            raise OpenClawJson5Error(
                "environment-derived authority inside mcp.servers.pcodex is unsupported"
            )
        target_hash = _sha256_text(text[target.start : target.end])
    return OpenClawJson5Inspection(
        document_sha256=_sha256_bytes(raw),
        target_present=authority.target_member is not None,
        target_value_sha256=target_hash,
        mcp_present=authority.mcp_member is not None,
        servers_present=authority.servers_member is not None,
    )


def _canonical_value(value: Mapping[str, object]) -> str:
    if not isinstance(value, Mapping):
        raise OpenClawJson5Error("pcodex registration must be an object")
    try:
        rendered = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise OpenClawJson5Error("pcodex registration is not JSON-compatible") from exc
    value_node = _Parser(rendered).parse()
    if value_node.kind != "object" or _contains_environment_reference(value_node):
        raise OpenClawJson5Error("pcodex registration contains unsupported authority")
    return rendered


def _insertion(parent: _Node, member_text: str) -> Json5SpanEdit:
    position = parent.start + 1
    suffix = "," if parent.members else ""
    return Json5SpanEdit(position, position, "", member_text + suffix)


def plan_install_pcodex(raw: bytes, value: Mapping[str, object]) -> Json5EditPlan:
    """Plan insertion of the one supported registration into an absent target."""

    _, root = _parse(raw)
    authority = _authority(root)
    if authority.target_member is not None:
        raise OpenClawJson5ConflictError("mcp.servers.pcodex already exists")
    rendered = _canonical_value(value)
    created: tuple[str, ...]
    if authority.mcp is None:
        edit = _insertion(root, f'"mcp":{{"servers":{{"pcodex":{rendered}}}}}')
        created = ("mcp", "mcp.servers")
    elif authority.servers is None:
        edit = _insertion(authority.mcp, f'"servers":{{"pcodex":{rendered}}}')
        created = ("mcp.servers",)
    else:
        edit = _insertion(authority.servers, f'"pcodex":{rendered}')
        created = ()
    ownership = OpenClawJson5Ownership(
        schema_version=OWNERSHIP_SCHEMA_VERSION,
        target_path=TARGET_PATH,
        target_value_sha256=_sha256_text(rendered),
        created_containers=created,
    )
    return Json5EditPlan(
        operation="install",
        source_sha256=_sha256_bytes(raw),
        edits=(edit,),
        ownership=ownership,
    )


def _validate_ownership(ownership: OpenClawJson5Ownership) -> None:
    if ownership.schema_version != OWNERSHIP_SCHEMA_VERSION:
        raise OpenClawJson5Error("unsupported OpenClaw JSON5 ownership schema")
    if ownership.target_path != TARGET_PATH:
        raise OpenClawJson5Error("ownership does not target mcp.servers.pcodex")
    allowed = {(), ("mcp.servers",), ("mcp", "mcp.servers")}
    if ownership.created_containers not in allowed:
        raise OpenClawJson5Error("ownership contains invalid created containers")
    if not re.fullmatch(r"[0-9a-f]{64}", ownership.target_value_sha256):
        raise OpenClawJson5Error("ownership target hash is invalid")


def _member_removal(text: str, parent: _Node, member: _Member) -> Json5SpanEdit:
    if len(parent.members) == 1:
        if member.comma_end is not None:
            raise OpenClawJson5Error(
                "cannot remove an owned sole member after its separator changed"
            )
        return Json5SpanEdit(
            member.start, member.end, text[member.start : member.end], ""
        )
    if member.comma_end is not None:
        if text[member.end : member.comma_start] != "":
            raise OpenClawJson5Error(
                "cannot remove an owned member across unrelated trailing trivia"
            )
        return Json5SpanEdit(
            member.start,
            member.comma_end,
            text[member.start : member.comma_end],
            "",
        )
    index = parent.members.index(member)
    if index == 0:
        raise OpenClawJson5Error("cannot safely identify the owned member separator")
    previous = parent.members[index - 1]
    if previous.comma_start is None:
        raise OpenClawJson5Error("cannot safely identify the preceding separator")
    between = text[previous.comma_end : member.start]
    if between != "":
        raise OpenClawJson5Error(
            "cannot remove an owned member across unrelated leading trivia"
        )
    return Json5SpanEdit(
        previous.comma_start,
        member.end,
        text[previous.comma_start : member.end],
        "",
    )


def _is_pristine_created_container(node: _Node, only_member: _Member) -> bool:
    """Return true only when no bytes were added around the created member."""

    return (
        len(node.members) == 1
        and node.members[0] is only_member
        and only_member.start == node.start + 1
        and only_member.comma_end is None
        and only_member.end == node.end - 1
    )


def _has_canonical_member_prefix(
    text: str, member: _Member, value: _Node, key: str
) -> bool:
    return text[member.start : value.start] == json.dumps(key) + ":"


def plan_remove_pcodex(raw: bytes, ownership: OpenClawJson5Ownership) -> Json5EditPlan:
    """Plan removal of an exact receipt-owned registration."""

    _validate_ownership(ownership)
    text, root = _parse(raw)
    authority = _authority(root)
    target_member = authority.target_member
    if target_member is None or authority.servers is None:
        raise OpenClawJson5ConflictError("receipt-owned mcp.servers.pcodex is absent")
    target = target_member.value
    current_hash = _sha256_text(text[target.start : target.end])
    if current_hash != ownership.target_value_sha256:
        raise OpenClawJson5ConflictError(
            "receipt-owned mcp.servers.pcodex was modified"
        )
    if not _has_canonical_member_prefix(text, target_member, target, "pcodex"):
        raise OpenClawJson5ConflictError(
            "receipt-owned mcp.servers.pcodex member syntax was modified"
        )

    servers_only_target = _is_pristine_created_container(
        authority.servers, target_member
    )
    mcp_only_servers = (
        authority.mcp is not None
        and authority.servers_member is not None
        and _is_pristine_created_container(authority.mcp, authority.servers_member)
    )
    if (
        "mcp" in ownership.created_containers
        and "mcp.servers" in ownership.created_containers
        and servers_only_target
        and mcp_only_servers
        and authority.mcp_member is not None
        and authority.mcp is not None
        and _has_canonical_member_prefix(
            text, authority.mcp_member, authority.mcp, "mcp"
        )
        and authority.servers_member is not None
        and _has_canonical_member_prefix(
            text, authority.servers_member, authority.servers, "servers"
        )
    ):
        edit = _member_removal(text, root, authority.mcp_member)
    elif (
        "mcp.servers" in ownership.created_containers
        and servers_only_target
        and authority.mcp is not None
        and authority.servers_member is not None
        and _has_canonical_member_prefix(
            text, authority.servers_member, authority.servers, "servers"
        )
    ):
        edit = _member_removal(text, authority.mcp, authority.servers_member)
    else:
        edit = _member_removal(text, authority.servers, target_member)
    return Json5EditPlan(
        operation="remove",
        source_sha256=_sha256_bytes(raw),
        edits=(edit,),
        ownership=ownership,
    )


def apply_json5_edit_plan(raw: bytes, plan: Json5EditPlan) -> bytes:
    """Apply a plan only to the exact document and exact before spans."""

    if plan.operation not in {"install", "remove"}:
        raise OpenClawJson5Error("unsupported JSON5 edit operation")
    _validate_ownership(plan.ownership)
    if _sha256_bytes(raw) != plan.source_sha256:
        raise OpenClawJson5ConflictError(
            "OpenClaw configuration changed after planning"
        )
    text = _decode(raw)
    ordered = sorted(plan.edits, key=lambda item: (item.start, item.end))
    previous_end = 0
    for edit in ordered:
        if (
            edit.start < previous_end
            or edit.start < 0
            or edit.end < edit.start
            or edit.end > len(text)
        ):
            raise OpenClawJson5Error("JSON5 edit spans overlap or are out of bounds")
        if text[edit.start : edit.end] != edit.before:
            raise OpenClawJson5ConflictError("JSON5 edit before span no longer matches")
        previous_end = edit.end
    for edit in reversed(ordered):
        text = text[: edit.start] + edit.after + text[edit.end :]
    result = text.encode("utf-8")
    inspection = inspect_pcodex_document(result)
    if plan.operation == "install":
        if (
            not inspection.target_present
            or inspection.target_value_sha256 != plan.ownership.target_value_sha256
        ):
            raise OpenClawJson5Error("installed JSON5 target failed verification")
    elif inspection.target_present:
        raise OpenClawJson5Error("removed JSON5 target remains present")
    return result
