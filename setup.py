"""Positive production-module allowlist for release wheels."""

from setuptools import setup
from setuptools.command.build_py import build_py


PRODUCTION_MODULES = frozenset(
    {
        "__init__", "__main__", "adapters", "audit", "backbone", "cache_manifest",
        "candidate_evidence", "candidate_materializer", "candidate_policy", "cli", "codex_exec", "command_discovery",
        "compiler", "config", "context_constraints", "core_packet", "doctor",
        "evidence_snippets", "fixture", "git_state", "hook", "ignore", "indexer",
        "install_manifest", "intake", "inventory", "launch_safety", "live_ledger", "locator",
        "lockfile", "log_scanner", "mcp_server", "metrics", "packet_schema", "paths",
        "pcodex_bootstrap", "pcodex_mcp", "pcodex_mcp_server", "pcodex_state",
        "pcodex_subagent", "plugin", "plugins", "profiles", "ranker_protocol", "redaction",
        "repo_map", "repo_summary", "review_patch", "role_core", "role_model", "router",
        "routing_base", "routing_decision", "routing_safety", "safe_reader", "stress",
        "task_intent", "timeutil", "topology", "tuning", "write_policy",
    }
)


class PositiveAllowlistBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if package != "premode":
            return modules
        return [item for item in modules if item[1] in PRODUCTION_MODULES]


setup(cmdclass={"build_py": PositiveAllowlistBuildPy})
