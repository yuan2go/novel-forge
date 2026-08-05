"""Deterministic, read-only Capability Pack version resolution."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Iterable

from .artifacts import is_floating_version
from .schema import CapabilityPackManifest


_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_PROTOCOL = re.compile(r"^novelos\.capability_pack\.v([1-9][0-9]*)$")


def _semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value)
    if match is None:
        raise ValueError(f"version is not exact SemVer: {value}")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _protocol(value: str) -> int:
    match = _PROTOCOL.fullmatch(value)
    if match is None:
        raise ValueError(f"protocol is not governed: {value}")
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class PackDependency:
    pack_id: str
    version: str


@dataclass(frozen=True, slots=True)
class PackCatalogEntry:
    manifest: CapabilityPackManifest
    dependencies: tuple[PackDependency, ...] = ()


class ReadOnlyPackCatalog:
    def __init__(self, entries: Iterable[PackCatalogEntry]) -> None:
        values: dict[tuple[str, str], PackCatalogEntry] = {}
        for entry in entries:
            key = (str(entry.manifest.identity.pack_id), str(entry.manifest.identity.version))
            existing = values.get(key)
            if existing is not None:
                if (
                    existing.manifest.manifest_hash != entry.manifest.manifest_hash
                    or existing.dependencies != entry.dependencies
                ):
                    raise ValueError(
                        "pack identity is bound to different manifest or dependencies"
                    )
                continue
            values[key] = entry
        self._values = MappingProxyType(values)

    def resolve(self, pack_id: str, version: str) -> PackCatalogEntry:
        if is_floating_version(version):
            raise ValueError("floating Pack versions are forbidden")
        _semver(version)
        try:
            return self._values[(pack_id, version)]
        except KeyError as exc:
            raise KeyError(f"Pack not found: {pack_id}@{version}") from exc

    def entries(self) -> tuple[PackCatalogEntry, ...]:
        return tuple(self._values[key] for key in sorted(self._values))


@dataclass(frozen=True, slots=True)
class ResolvedPackSet:
    root_pack_id: str
    root_version: str
    dependency_order: tuple[str, ...]
    manifest_hashes: tuple[tuple[str, str], ...]
    dependency_edges: tuple[tuple[str, str], ...]


class CapabilityPackVersionResolver:
    def resolve(
        self,
        *,
        pack_id: str,
        pack_version: str,
        protocol_version: str,
        novel_forge_version: str,
        release_sha: str,
        runtime_profile: str,
        release_channel: str,
        catalog: ReadOnlyPackCatalog,
    ) -> ResolvedPackSet:
        if len(release_sha) != 40 or any(ch not in "0123456789abcdef" for ch in release_sha):
            raise ValueError("release_sha must be a full lowercase Git SHA")
        root = catalog.resolve(pack_id, pack_version)
        seen: set[tuple[str, str]] = set()
        visiting: set[tuple[str, str]] = set()
        order: list[str] = []
        hashes: list[tuple[str, str]] = []
        edges: list[tuple[str, str]] = []
        resolved_versions: dict[str, str] = {}

        def visit(entry: PackCatalogEntry) -> None:
            identity = (str(entry.manifest.identity.pack_id), str(entry.manifest.identity.version))
            existing_version = resolved_versions.get(identity[0])
            if existing_version is not None and existing_version != identity[1]:
                raise ValueError(
                    "resolved Pack set cannot contain multiple versions of one pack_id"
                )
            resolved_versions[identity[0]] = identity[1]
            if identity in visiting:
                raise ValueError("Capability Pack dependency graph contains a cycle")
            if identity in seen:
                return
            visiting.add(identity)
            self._validate_target(
                entry.manifest,
                protocol_version=protocol_version,
                novel_forge_version=novel_forge_version,
                runtime_profile=runtime_profile,
                release_channel=release_channel,
            )
            declared_upstream = {
                str(item) for item in entry.manifest.role.upstream_packs
            }
            resolved_upstream = {item.pack_id for item in entry.dependencies}
            if declared_upstream != resolved_upstream:
                raise ValueError(
                    "Manifest upstream Pack declarations require exact injected dependencies"
                )
            incompatible = set(str(item) for item in entry.manifest.compatibility.incompatible_packs)
            for dependency in sorted(entry.dependencies, key=lambda item: (item.pack_id, item.version)):
                if is_floating_version(dependency.version):
                    raise ValueError("floating dependency versions are forbidden")
                if dependency.pack_id in incompatible:
                    raise ValueError("Pack dependency is explicitly incompatible")
                child = catalog.resolve(dependency.pack_id, dependency.version)
                edges.append(
                    (
                        f"{identity[0]}@{identity[1]}",
                        f"{dependency.pack_id}@{dependency.version}",
                    )
                )
                visit(child)
            visiting.remove(identity)
            seen.add(identity)
            order.append(f"{identity[0]}@{identity[1]}")
            hashes.append((f"{identity[0]}@{identity[1]}", entry.manifest.manifest_hash))

        visit(root)
        resolved_ids = {item.split("@", 1)[0] for item in order}
        for entry in catalog.entries():
            if (str(entry.manifest.identity.pack_id), str(entry.manifest.identity.version)) in seen:
                conflicts = set(str(item) for item in entry.manifest.compatibility.incompatible_packs)
                if conflicts & resolved_ids:
                    raise ValueError("resolved Pack set contains an incompatibility conflict")
        return ResolvedPackSet(
            pack_id,
            pack_version,
            tuple(order),
            tuple(sorted(hashes)),
            tuple(sorted(set(edges))),
        )

    @staticmethod
    def _validate_target(
        manifest: CapabilityPackManifest,
        *,
        protocol_version: str,
        novel_forge_version: str,
        runtime_profile: str,
        release_channel: str,
    ) -> None:
        compatibility = manifest.compatibility
        current_protocol = _protocol(protocol_version)
        minimum_protocol = _protocol(str(compatibility.protocol_min_version))
        maximum_protocol = (
            _protocol(str(compatibility.protocol_max_version))
            if compatibility.protocol_max_version is not None
            else None
        )
        if current_protocol < minimum_protocol or (
            maximum_protocol is not None and current_protocol > maximum_protocol
        ):
            raise ValueError("Capability Pack protocol is incompatible")
        build = _semver(novel_forge_version)
        minimum_build = _semver(str(compatibility.novel_forge_min_version))
        maximum_build = (
            _semver(str(compatibility.novel_forge_max_version))
            if compatibility.novel_forge_max_version is not None
            else None
        )
        if build < minimum_build or (maximum_build is not None and build > maximum_build):
            raise ValueError("Novel Forge version is incompatible")
        if runtime_profile not in compatibility.compatible_runtime_profiles:
            raise ValueError("runtime profile is incompatible")
        if manifest.identity.status in {"DISABLED", "RETIRED"}:
            raise ValueError("disabled or retired Pack cannot be resolved")
        if str(manifest.governance.release_channel) != release_channel:
            raise ValueError("Pack is not available on the target release channel")


__all__ = [
    "CapabilityPackVersionResolver",
    "PackCatalogEntry",
    "PackDependency",
    "ReadOnlyPackCatalog",
    "ResolvedPackSet",
]
