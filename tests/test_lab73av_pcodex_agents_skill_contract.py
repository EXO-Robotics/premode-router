from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / "AGENTS.md"
SKILL = REPO_ROOT / ".codex" / "skills" / "pcodex-subagent-routing" / "SKILL.md"
DOC = REPO_ROOT / "docs" / "pcodex" / "SUBAGENT_ROUTING_CONTRACT.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_agents_md_exists_and_mentions_pcodex_routing() -> None:
    assert AGENTS.exists()
    text = _text(AGENTS)

    assert "## pCodex Routing" in text
    assert "pcodex" in text
    assert "premode compile --plugin literal_symbol" in text


def test_agents_md_routes_codex_created_prompts_before_dispatch() -> None:
    text = _text(AGENTS)

    assert "exact raw subagent prompt Codex intends to send" in text
    assert "Codex-created subagent prompt through pCodex before dispatch" in text
    assert "transform_subagent_prompt" in text


def test_agents_md_documents_preserve_and_fallback_boundaries() -> None:
    text = _text(AGENTS)

    assert "send the raw prompt unchanged" in text
    assert "pCodex is disabled or transformation fails" in text
    assert "report the fallback out of band" in text


def test_agents_md_avoids_hosted_overclaims() -> None:
    text = _text(AGENTS)

    assert "Do not claim it controls hosted/internal Codex subagents" in text
    assert "Do not patch hosted Codex/Web UI" in text
    assert "controls all hosted/internal subagents" not in text
    assert "hosted Codex/Web UI is patchable" not in text


def test_skill_file_exists_and_references_transform_contract() -> None:
    assert SKILL.exists()
    text = _text(SKILL)

    assert text.startswith("---\n")
    assert "name: pcodex-subagent-routing" in text
    assert "description: pCodex instruction-level routing guidance for local alpha testing." in text
    assert "# pCodex Subagent Routing" in text
    assert "transform_subagent_prompt" in text
    assert "raw_subagent_prompt" in text
    assert "dispatch_prompt = result.prompt" in text


def test_skill_file_includes_forbidden_content_boundaries() -> None:
    text = _text(SKILL)

    assert "Forbidden in model-facing subagent prompts" in text
    assert "TASK_CLASS" in text
    assert "SUPPORT_RELATIONS" in text
    assert "snippets or file blocks" in text
    assert "diagnostics" in text
    assert "secrets or full environment dumps" in text


def test_source_doc_exists_and_explains_adapter_readiness() -> None:
    assert DOC.exists()
    text = _text(DOC)

    assert "Soft layer" in text
    assert "Medium layer" in text
    assert "Future hard layer" in text
    assert "instruction-level behavior guidance" in text
    assert "not a hard guarantee for hosted/internal Codex subagents" in text


def test_source_doc_requires_hook_or_extension_for_real_integration() -> None:
    text = _text(DOC)

    assert "local Codex dispatch hook" in text
    assert "local source patch" in text
    assert "official extension point" in text
    assert "Hosted Codex/Web UI should not be patched" in text


def test_source_instruction_files_do_not_include_lab_or_user_paths() -> None:
    combined = "\n".join(_text(path) for path in (AGENTS, SKILL, DOC))

    assert "/private/tmp" not in combined
    assert "/Users/" not in combined
    assert "premode_labs" not in combined


def test_source_instruction_files_do_not_include_secret_like_placeholders() -> None:
    combined = "\n".join(_text(path) for path in (AGENTS, SKILL, DOC))

    for forbidden in ("OPENAI_API_KEY", "GITHUB_TOKEN", "SECRET_TOKEN", "PASSWORD="):
        assert forbidden not in combined


def test_task_class_and_support_relations_are_not_allowed_model_facing_output() -> None:
    text = _text(DOC)

    assert "Do not include `TASK_CLASS` or `SUPPORT_RELATIONS` as allowed model-facing output" in text
    assert "Allowed model-facing packet sections are TASK, PRIMARY_FILES, RELATED_TESTS, and END" in text
