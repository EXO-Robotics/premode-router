from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any

from .default_plugin import get_literal_symbol_plugin

ENTRY_POINT_GROUP = "premode.plugins"
BUILTIN_PLUGIN_LOADERS = {"literal_symbol": get_literal_symbol_plugin}


class PluginAliasError(ValueError):
    """Raised when a Pre-mode plugin alias cannot be resolved safely."""


@dataclass(frozen=True)
class ResolvedPacketPlugin:
    plugin_name: str
    plugin_package: str | None
    packet_version: str
    packet_variant: str
    packet_strategy: str

    def as_compile_kwargs(self) -> dict[str, str]:
        return {
            "packet_version": self.packet_version,
            "packet_variant": self.packet_variant,
            "packet_strategy": self.packet_strategy,
        }

    def as_dict(self) -> dict[str, str | None]:
        return {
            "plugin_name": self.plugin_name,
            "plugin_package": self.plugin_package,
            "packet_version": self.packet_version,
            "packet_variant": self.packet_variant,
            "packet_strategy": self.packet_strategy,
        }


def _entry_points(group: str = ENTRY_POINT_GROUP) -> list[Any]:
    eps = metadata.entry_points()
    if hasattr(eps, "select"):
        return list(eps.select(group=group))
    if isinstance(eps, dict):
        return list(eps.get(group, []))
    return [ep for ep in eps if getattr(ep, "group", None) == group]


def available_plugin_aliases() -> list[str]:
    discovered = {str(ep.name) for ep in _entry_points() if getattr(ep, "name", None)}
    return sorted(discovered | set(BUILTIN_PLUGIN_LOADERS))


def _available_suffix() -> str:
    aliases = available_plugin_aliases()
    if not aliases:
        return " No Pre-mode plugin aliases are installed."
    return " Available aliases: " + ", ".join(aliases)


def _load_metadata(entry_point: Any) -> dict[str, Any]:
    try:
        loaded = entry_point.load()
        plugin = loaded() if callable(loaded) else loaded
    except Exception as exc:  # pragma: no cover - exercised through CLI failure paths
        raise PluginAliasError(f"Could not load Pre-mode plugin alias '{entry_point.name}': {exc}") from exc
    if not isinstance(plugin, dict):
        raise PluginAliasError(f"Pre-mode plugin alias '{entry_point.name}' returned invalid metadata; expected a dict.")
    return plugin


def _text_field(plugin: dict[str, Any], key: str, *, alias: str) -> str:
    value = plugin.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginAliasError(f"Pre-mode plugin alias '{alias}' is missing required metadata field '{key}'.")
    return value.strip()


def resolve_packet_plugin(
    alias: str,
    *,
    packet_version: str | None = None,
    packet_variant: str | None = None,
    packet_strategy: str | None = None,
) -> ResolvedPacketPlugin:
    alias = str(alias or "").strip()
    if not alias:
        raise PluginAliasError("Pre-mode plugin alias cannot be empty." + _available_suffix())

    matches = [ep for ep in _entry_points() if getattr(ep, "name", None) == alias]
    if len(matches) > 1:
        raise PluginAliasError(f"Duplicate Pre-mode plugin alias '{alias}' found; refusing to choose one.")
    builtin = BUILTIN_PLUGIN_LOADERS.get(alias)
    if not matches:
        if builtin is None:
            raise PluginAliasError(f"Unknown Pre-mode plugin alias '{alias}'." + _available_suffix())
        plugin = builtin()
    else:
        plugin = _load_metadata(matches[0])
        if builtin is not None:
            bundled = builtin()
            fields = ("packet_version", "packet_variant", "packet_strategy")
            conflicts = [field for field in fields if plugin.get(field) != bundled.get(field)]
            if conflicts:
                raise PluginAliasError(
                    f"Installed legacy plugin alias '{alias}' conflicts with the bundled stable default: "
                    + ", ".join(conflicts)
                )
            plugin = bundled
    if not (plugin.get("strategy_id") or plugin.get("name")):
        raise PluginAliasError(f"Pre-mode plugin alias '{alias}' is missing required metadata field 'strategy_id' or 'name'.")

    resolved = ResolvedPacketPlugin(
        plugin_name=alias,
        plugin_package=str(plugin.get("name") or "") or None,
        packet_version=_text_field(plugin, "packet_version", alias=alias),
        packet_variant=_text_field(plugin, "packet_variant", alias=alias),
        packet_strategy=_text_field(plugin, "packet_strategy", alias=alias),
    )

    conflicts = []
    if packet_version and packet_version != resolved.packet_version:
        conflicts.append(f"packet_version={packet_version!r} conflicts with plugin value {resolved.packet_version!r}")
    if packet_variant and packet_variant != resolved.packet_variant:
        conflicts.append(f"packet_variant={packet_variant!r} conflicts with plugin value {resolved.packet_variant!r}")
    if packet_strategy and packet_strategy != resolved.packet_strategy:
        conflicts.append(f"packet_strategy={packet_strategy!r} conflicts with plugin value {resolved.packet_strategy!r}")
    if conflicts:
        raise PluginAliasError(f"Pre-mode plugin alias '{alias}' conflicts with explicit packet options: " + "; ".join(conflicts))

    return resolved


def apply_packet_plugin(
    alias: str | None,
    *,
    packet_version: str | None = None,
    packet_variant: str | None = None,
    packet_strategy: str | None = None,
) -> tuple[str | None, str | None, str | None, dict[str, str | None] | None]:
    if not alias:
        return packet_version, packet_variant, packet_strategy, None
    resolved = resolve_packet_plugin(
        alias,
        packet_version=packet_version,
        packet_variant=packet_variant,
        packet_strategy=packet_strategy,
    )
    return resolved.packet_version, resolved.packet_variant, resolved.packet_strategy, resolved.as_dict()
