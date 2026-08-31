from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from typing import Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict


FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")
QUALIFICATION_RUN_ID = re.compile(r"p0-([0-9a-f]{32})")
QUALIFICATION_COMPOSE_PROJECT = re.compile(
    r"nf-p0-([0-9a-f]{32})(?:-[a-z0-9][a-z0-9-]{0,31})?"
)
RUN_DATABASE_NAME = re.compile(r"nf_p0_[0-9a-f]{32}_test")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
PROTECTED_DATABASE_NAMES = frozenset(
    {"postgres", "template0", "template1", "novel_forge"}
)


class ResourceOwnershipError(RuntimeError):
    pass


class DockerCommandError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout.strip()[-8_000:]
        self.stderr = stderr.strip()[-8_000:]


@dataclass(frozen=True)
class QualificationRunIdentity:
    commit_sha: str
    run_id: str
    compose_project: str
    database_name: str
    artifact_root: Path

    @classmethod
    def create(
        cls,
        *,
        commit_sha: str,
        artifact_parent: Path,
    ) -> "QualificationRunIdentity":
        tested_sha = commit_sha.strip().lower()
        if not FULL_GIT_SHA.fullmatch(tested_sha):
            raise ValueError("qualification identity requires a full lowercase Git SHA")
        token = uuid4().hex
        return cls(
            commit_sha=tested_sha,
            run_id=f"p0-{token}",
            compose_project=f"nf-p0-{token}",
            database_name=f"nf_p0_{token}_test",
            artifact_root=(
                artifact_parent.resolve()
                / f"novel-forge-p0-{tested_sha[:12]}-{token}"
            ),
        )

    @classmethod
    def bind(
        cls,
        *,
        commit_sha: str,
        run_id: str,
        compose_project: str,
        artifact_root: Path,
    ) -> "QualificationRunIdentity":
        """INVARIANT: every derived Compose phase reuses the originating run identity."""
        tested_sha = commit_sha.strip().lower()
        run_match = QUALIFICATION_RUN_ID.fullmatch(run_id.strip().lower())
        project_match = QUALIFICATION_COMPOSE_PROJECT.fullmatch(
            compose_project.strip().lower()
        )
        if not FULL_GIT_SHA.fullmatch(tested_sha):
            raise ValueError("qualification identity requires a full lowercase Git SHA")
        if (
            run_match is None
            or project_match is None
            or run_match.group(1) != project_match.group(1)
        ):
            raise ValueError(
                "qualification Compose project is not bound to the run-scoped identity"
            )
        token = run_match.group(1)
        return cls(
            commit_sha=tested_sha,
            run_id=f"p0-{token}",
            compose_project=compose_project.strip().lower(),
            database_name=f"nf_p0_{token}_test",
            artifact_root=artifact_root.resolve(),
        )


@dataclass(frozen=True, order=True)
class ComposeResource:
    kind: str
    resource_id: str
    project_name: str
    run_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"container", "network", "volume"}:
            raise ValueError(f"unsupported Compose resource kind: {self.kind}")
        if not self.resource_id:
            raise ValueError("Compose resource ID is required")


@dataclass(frozen=True)
class ComposeResourceSnapshot:
    resources: tuple[ComposeResource, ...]

    def __post_init__(self) -> None:
        identities = [(item.kind, item.resource_id) for item in self.resources]
        if len(set(identities)) != len(identities):
            raise ValueError("Compose resource snapshot contains duplicate IDs")

    @property
    def identities(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((item.kind, item.resource_id) for item in self.resources))

    def to_dict(self) -> dict[str, object]:
        return {
            "resources": [
                {
                    "kind": item.kind,
                    "resource_id": item.resource_id,
                    "project_name": item.project_name,
                    "run_id": item.run_id,
                }
                for item in sorted(self.resources)
            ]
        }


class ComposeClient(Protocol):
    def discover(self, project_name: str) -> ComposeResourceSnapshot: ...

    def down(
        self,
        *,
        project_name: str,
        compose_files: Sequence[Path],
        environment: dict[str, str],
    ) -> None: ...


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class DockerComposeClient:
    @classmethod
    def from_environment(
        cls,
        *,
        repo_root: Path,
        environment: Mapping[str, str],
        runner: CommandRunner = subprocess.run,
        docker_command: Sequence[str] = ("docker",),
    ) -> "DockerComposeClient":
        raw_command = str(
            environment.get("NOVEL_FORGE_DOCKER_COMPOSE_BIN") or "docker compose"
        )
        try:
            compose_command = tuple(shlex.split(raw_command))
        except ValueError as exc:
            raise ValueError(
                "NOVEL_FORGE_DOCKER_COMPOSE_BIN must be a valid shell command"
            ) from exc
        if not compose_command or not compose_command[0].strip():
            raise ValueError(
                "NOVEL_FORGE_DOCKER_COMPOSE_BIN must be a valid shell command"
            )
        return cls(
            repo_root=repo_root,
            runner=runner,
            docker_command=docker_command,
            compose_command=compose_command,
        )

    def __init__(
        self,
        *,
        repo_root: Path,
        runner: CommandRunner = subprocess.run,
        docker_command: Sequence[str] = ("docker",),
        compose_command: Sequence[str] = ("docker", "compose"),
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.runner = runner
        self.docker_command = tuple(docker_command)
        self.compose_command = tuple(compose_command)
        if any(
            token == "--env-file" or token.startswith("--env-file=")
            for token in self.compose_command
        ):
            raise ValueError(
                "qualification Compose command cannot use an explicit env-file"
            )

    def _run(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        timeout: float = 120,
    ) -> str:
        try:
            completed = self.runner(
                list(command),
                cwd=self.repo_root,
                env=None if environment is None else dict(environment),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerCommandError(
                "Docker command timed out before trustworthy resource evidence was available"
            ) from exc
        except OSError as exc:
            raise DockerCommandError(
                "Docker command could not start; resource state is unknown"
            ) from exc
        if completed.returncode:
            raise DockerCommandError(
                "Docker command failed without yielding trustworthy resource evidence: "
                + " ".join(command[:4]),
                returncode=completed.returncode,
                stdout=str(completed.stdout or ""),
                stderr=str(completed.stderr or ""),
            )
        return str(completed.stdout or "").strip()

    def _list_ids(self, kind: str, project_name: str) -> tuple[str, ...]:
        command = [*self.docker_command, kind, "ls"]
        if kind == "container":
            command.append("--all")
        command.extend(
            [
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
            ]
        )
        output = self._run(command)
        identifiers = tuple(line.strip() for line in output.splitlines() if line.strip())
        if any(any(character.isspace() for character in value) for value in identifiers):
            raise DockerCommandError("Docker resource list emitted an invalid identifier")
        if len(set(identifiers)) != len(identifiers):
            raise DockerCommandError("Docker resource list emitted duplicate identifiers")
        return identifiers

    def _inspect(self, kind: str, identifiers: Sequence[str]) -> list[object]:
        if not identifiers:
            return []
        output = self._run(
            [*self.docker_command, kind, "inspect", *identifiers]
        )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise DockerCommandError("Docker inspect did not emit JSON") from exc
        if not isinstance(payload, list) or len(payload) != len(identifiers):
            raise DockerCommandError("Docker inspect result count differs from resource IDs")
        return payload

    def discover(self, project_name: str) -> ComposeResourceSnapshot:
        resources: list[ComposeResource] = []
        for kind in ("container", "volume", "network"):
            identifiers = self._list_ids(kind, project_name)
            payload = self._inspect(kind, identifiers)
            for item in payload:
                if not isinstance(item, dict):
                    raise DockerCommandError("Docker inspect item is not an object")
                labels = (
                    (item.get("Config") or {}).get("Labels")
                    if kind == "container" and isinstance(item.get("Config"), dict)
                    else item.get("Labels")
                )
                if not isinstance(labels, dict):
                    labels = {}
                resource_id = str(
                    item.get("Name") if kind == "volume" else item.get("Id") or ""
                )
                resources.append(
                    ComposeResource(
                        kind=kind,
                        resource_id=resource_id,
                        project_name=str(
                            labels.get("com.docker.compose.project") or ""
                        ),
                        run_id=str(
                            labels.get("novel-forge.qualification.run-id") or ""
                        ),
                    )
                )
        return ComposeResourceSnapshot(tuple(sorted(resources)))

    def run_compose(
        self,
        *,
        project_name: str,
        compose_files: Sequence[Path],
        environment: Mapping[str, str],
        arguments: Sequence[str],
        timeout: float,
    ) -> str:
        file_arguments = [
            value
            for path in compose_files
            for value in ("-f", str(path))
        ]
        compose_environment = {
            key: value
            for key, value in environment.items()
            if key != "COMPOSE_ENV_FILES"
        }
        compose_environment["COMPOSE_DISABLE_ENV_FILE"] = "1"
        return self._run(
            [
                *self.compose_command,
                "-p",
                project_name,
                *file_arguments,
                *arguments,
            ],
            environment=compose_environment,
            timeout=timeout,
        )

    def down(
        self,
        *,
        project_name: str,
        compose_files: Sequence[Path],
        environment: dict[str, str],
    ) -> None:
        self.run_compose(
            project_name=project_name,
            compose_files=compose_files,
            environment=environment,
            arguments=("down", "--volumes", "--remove-orphans", "--timeout", "45"),
            timeout=180,
        )

    def published_port(
        self,
        *,
        project_name: str,
        compose_files: Sequence[Path],
        environment: Mapping[str, str],
        service: str,
        container_port: int,
    ) -> int:
        container_id = self.run_compose(
            project_name=project_name,
            compose_files=compose_files,
            environment=environment,
            arguments=("ps", "--quiet", service),
            timeout=30,
        )
        identifiers = tuple(
            line.strip() for line in container_id.splitlines() if line.strip()
        )
        if len(identifiers) != 1:
            raise DockerCommandError(
                f"Compose service {service} does not resolve to exactly one container"
            )
        payload = self._inspect("container", identifiers)
        return published_loopback_port(payload, container_port=container_port)

    def container_lifecycle(
        self,
        *,
        project_name: str,
        compose_files: Sequence[Path],
        environment: Mapping[str, str],
        service: str,
    ) -> dict[str, str]:
        container_id = self.run_compose(
            project_name=project_name,
            compose_files=compose_files,
            environment=environment,
            arguments=("ps", "--quiet", service),
            timeout=30,
        )
        identifiers = tuple(
            line.strip() for line in container_id.splitlines() if line.strip()
        )
        if len(identifiers) != 1:
            raise DockerCommandError(
                f"Compose service {service} does not resolve to exactly one container"
            )
        payload = self._inspect("container", identifiers)
        item = payload[0]
        if not isinstance(item, dict) or str(item.get("Id") or "") != identifiers[0]:
            raise DockerCommandError(
                f"Compose service {service} returned an inconsistent container identity"
            )
        state = item.get("State")
        started_at = (
            str(state.get("StartedAt") or "") if isinstance(state, dict) else ""
        )
        if not started_at:
            raise DockerCommandError(
                f"Compose service {service} has no container start identity"
            )
        return {"container_id": identifiers[0], "started_at": started_at}


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


class OwnedComposeProject:
    """SECURITY: cleanup is permitted only for the captured run-labeled resource set."""

    def __init__(
        self,
        *,
        identity: QualificationRunIdentity,
        repo_root: Path,
        compose_files: Sequence[Path],
        environment: Mapping[str, str],
        client: ComposeClient,
    ) -> None:
        self.identity = identity
        self.repo_root = repo_root.resolve()
        self.compose_files = tuple(Path(path) for path in compose_files)
        self.environment = dict(environment)
        self.client = client
        self.receipt_path = (
            identity.artifact_root
            / f"compose-resource-ownership-{identity.compose_project}.json"
        )
        self._claim_asserted = False
        self._captured: ComposeResourceSnapshot | None = None

    def assert_unclaimed(self) -> None:
        snapshot = self.client.discover(self.identity.compose_project)
        if snapshot.resources:
            raise ResourceOwnershipError(
                "qualification Compose project already has resources; refusing ownership"
            )
        self._claim_asserted = True

    def _assert_labels(self, snapshot: ComposeResourceSnapshot) -> None:
        for resource in snapshot.resources:
            if resource.project_name != self.identity.compose_project:
                raise ResourceOwnershipError(
                    "Compose resource project label does not match the qualification run"
                )
            if resource.run_id != self.identity.run_id:
                raise ResourceOwnershipError(
                    "Compose resource run label does not match the qualification run"
                )

    def capture(self) -> dict[str, object]:
        if not self._claim_asserted:
            raise ResourceOwnershipError(
                "qualification Compose ownership was not preflighted"
            )
        snapshot = self.client.discover(self.identity.compose_project)
        if not snapshot.resources:
            raise ResourceOwnershipError(
                "qualification Compose project created no discoverable resources"
            )
        self._assert_labels(snapshot)
        self._captured = snapshot
        receipt = {
            "schema_version": "novel-forge.compose-resource-ownership.v1",
            "run_id": self.identity.run_id,
            "compose_project": self.identity.compose_project,
            **snapshot.to_dict(),
        }
        _atomic_json(self.receipt_path, receipt)
        return receipt

    def assert_owned(self) -> dict[str, object]:
        if self._captured is None:
            raise ResourceOwnershipError(
                "qualification Compose resources have no in-process ownership receipt"
            )
        current = self.client.discover(self.identity.compose_project)
        self._assert_labels(current)
        if current.identities != self._captured.identities:
            raise ResourceOwnershipError(
                "qualification Compose resource set changed after ownership capture"
            )
        return {
            "status": "PASS",
            "run_id": self.identity.run_id,
            "compose_project": self.identity.compose_project,
            "resource_count": len(current.resources),
            "receipt": self.receipt_path.name,
        }

    def cleanup(self) -> dict[str, object]:
        ownership = self.assert_owned()
        self.client.down(
            project_name=self.identity.compose_project,
            compose_files=self.compose_files,
            environment=self.environment,
        )
        remaining = self.client.discover(self.identity.compose_project)
        if remaining.resources:
            raise ResourceOwnershipError(
                "qualification Compose cleanup left owned resources behind"
            )
        self._captured = None
        return {**ownership, "status": "PASS", "remaining_resource_count": 0}

    def cleanup_discovered(self) -> dict[str, object]:
        current = self.client.discover(self.identity.compose_project)
        if not current.resources:
            self._captured = None
            return {
                "status": "PASS",
                "run_id": self.identity.run_id,
                "compose_project": self.identity.compose_project,
                "resource_count": 0,
                "remaining_resource_count": 0,
                "ownership_capture": "NO_RESOURCES_PRESENT",
            }
        if self._captured is None:
            if not self._claim_asserted:
                raise ResourceOwnershipError(
                    "refusing cleanup without a successful empty-project preflight"
                )
            self.capture()
        return self.cleanup()


def validate_disposable_database_url(
    database_url: str,
    *,
    expected_database: str,
) -> dict[str, object]:
    """SECURITY: qualification writes only to its loopback run-owned database."""
    if not RUN_DATABASE_NAME.fullmatch(expected_database):
        raise ValueError("expected database is not a run-owned database identity")
    try:
        parameters = conninfo_to_dict(database_url)
    except (TypeError, ValueError) as exc:
        raise ValueError("qualification database URL is invalid") from exc
    database_name = str(parameters.get("dbname") or "")
    if database_name != expected_database:
        raise ValueError(
            "qualification database URL does not target the run-owned database"
        )
    host = str(parameters.get("host") or "").strip().lower()
    if host not in LOOPBACK_HOSTS:
        raise ValueError("qualification database URL must use one loopback host")
    raw_port = str(parameters.get("port") or "")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("qualification database URL requires an explicit port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("qualification database port is outside the TCP range")
    user = str(parameters.get("user") or "").strip()
    if not user:
        raise ValueError("qualification database URL requires an explicit user")
    identity = {
        "host": "localhost" if host == "localhost" else host,
        "port": port,
        "database": database_name,
        "user": user,
    }
    digest = "sha256:" + hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "database_name": database_name,
        "host_class": "LOOPBACK",
        "port": port,
        "server_identity_digest": digest,
    }


def require_disposable_database_name(database_name: object) -> str:
    if not isinstance(database_name, str) or not database_name:
        raise ValueError(
            "database safety preflight returned an invalid name; refusing writes"
        )
    if database_name in PROTECTED_DATABASE_NAMES:
        raise ValueError(
            f"database safety preflight resolved a protected name; refusing writes for {database_name!r}"
        )
    if not database_name.endswith("_test"):
        raise ValueError(
            f"database safety requires an _test suffix; refusing writes for {database_name!r}"
        )
    return database_name


def published_loopback_port(
    inspect_payload: object,
    *,
    container_port: int,
) -> int:
    if (
        not isinstance(inspect_payload, list)
        or len(inspect_payload) != 1
        or not isinstance(inspect_payload[0], dict)
    ):
        raise ValueError("Docker inspect must describe exactly one container")
    network = inspect_payload[0].get("NetworkSettings")
    if not isinstance(network, dict):
        raise ValueError("Docker inspect lacks container network settings")
    ports = network.get("Ports")
    if not isinstance(ports, dict):
        raise ValueError("Docker inspect lacks published ports")
    bindings = ports.get(f"{container_port}/tcp")
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise ValueError("Docker inspect requires one published TCP port")
    binding = bindings[0]
    if not isinstance(binding, dict):
        raise ValueError("Docker published port binding is invalid")
    host_ip = str(binding.get("HostIp") or "").lower()
    if host_ip not in {"127.0.0.1", "::1"}:
        raise ValueError("Docker qualification port must bind to loopback")
    try:
        port = int(str(binding.get("HostPort") or ""))
    except ValueError as exc:
        raise ValueError("Docker published host port is invalid") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Docker published host port is outside the TCP range")
    return port


__all__ = [
    "ComposeClient",
    "ComposeResource",
    "ComposeResourceSnapshot",
    "DockerCommandError",
    "DockerComposeClient",
    "OwnedComposeProject",
    "QualificationRunIdentity",
    "ResourceOwnershipError",
    "published_loopback_port",
    "require_disposable_database_name",
    "validate_disposable_database_url",
]
