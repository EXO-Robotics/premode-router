from premode.config import init_project
from premode.codex_exec import CodexOptions, build_codex_args


def test_schema_created_by_init(repo):
    paths = init_project(repo)
    assert (repo / ".premode" / "schemas" / "codex_final_report.schema.json").exists()


def test_structured_final_report_uses_default_schema(repo):
    init_project(repo)
    args = build_codex_args(repo, CodexOptions(structured_final_report=True))
    assert "--output-schema" in args
    i = args.index("--output-schema")
    assert args[i + 1].endswith(".premode/schemas/codex_final_report.schema.json")


def test_explicit_output_schema_overrides_default(repo):
    init_project(repo)
    args = build_codex_args(repo, CodexOptions(structured_final_report=True, output_schema="custom.schema.json"))
    i = args.index("--output-schema")
    assert args[i + 1] == "custom.schema.json"


def test_codex_passthrough_options(repo):
    init_project(repo)
    args = build_codex_args(repo, CodexOptions(codex_profile="fast", add_dir=["../SharedPackage"], skip_git_repo_check=True, model="qwen3.6", oss=True))
    assert "--profile" in args and "fast" in args
    assert args.count("--add-dir") == 1
    assert "--skip-git-repo-check" in args
    assert "--model" in args and "qwen3.6" in args
    assert "--oss" in args
    assert args[-1] == "-"
