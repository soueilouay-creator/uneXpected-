from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import re


class SkillRegistryError(RuntimeError):
    """A local workflow-skill manifest or pinned source failed validation."""


@dataclass(frozen=True)
class SkillSpec:
    id: str
    version: str
    path: str
    sha256: str
    agent_ids: tuple[str, ...]
    trigger_terms: tuple[str, ...]
    source_ref: str
    status: str


class SkillRegistry:
    """Loads only locally reviewed, hash-pinned workflow context."""

    def __init__(self, package_root: Path, skills: list[SkillSpec]):
        self.package_root = package_root.resolve()
        self._skills = tuple(skills)
        self._by_id = {skill.id: skill for skill in skills}
        if len(self._by_id) != len(skills):
            raise SkillRegistryError('Duplicate skill IDs in skill manifest.')

    @classmethod
    def load(cls, manifest_path: str | Path | None = None,
             package_root: str | Path | None = None) -> 'SkillRegistry':
        root = Path(package_root) if package_root is not None else Path(__file__).resolve().parent.parent
        root = root.resolve()
        manifest = Path(manifest_path) if manifest_path is not None else root / 'skill_manifest.json'
        if not manifest.is_absolute():
            manifest = (root / manifest).resolve()
        try:
            manifest.resolve().relative_to(root)
        except ValueError as exc:
            raise SkillRegistryError('Skill manifest must reside inside the package root.') from exc
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillRegistryError(f'Cannot read skill manifest: {type(exc).__name__}.') from None
        if data.get('schema_version') != 1 or not isinstance(data.get('skills'), list):
            raise SkillRegistryError('Unsupported or malformed skill manifest schema.')
        skills: list[SkillSpec] = []
        for raw in data['skills']:
            try:
                skill = SkillSpec(
                    id=str(raw['id']), version=str(raw['version']), path=str(raw['path']),
                    sha256=str(raw['sha256']).lower(),
                    agent_ids=tuple(str(x) for x in raw['agent_ids']),
                    trigger_terms=tuple(str(x).lower() for x in raw['trigger_terms']),
                    source_ref=str(raw['source_ref']), status=str(raw['status']),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SkillRegistryError(f'Malformed skill record: {type(exc).__name__}.') from None
            if (not skill.id or not skill.version or not skill.agent_ids or not skill.trigger_terms
                    or not skill.source_ref or skill.status != 'active'
                    or not re.fullmatch(r'[0-9a-f]{64}', skill.sha256)):
                raise SkillRegistryError(f'Invalid or inactive skill record: {skill.id!r}.')
            cls._safe_path(root, skill.path)
            cls._verify_file(root, skill)
            skills.append(skill)
        return cls(root, skills)

    @staticmethod
    def _safe_path(root: Path, relative: str) -> Path:
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise SkillRegistryError(f'Skill path escapes package root: {relative!r}.') from exc
        return path

    @classmethod
    def _read_verified_bytes(cls, root: Path, skill: SkillSpec) -> bytes:
        path = cls._safe_path(root, skill.path)
        if not path.is_file():
            raise SkillRegistryError(f'Skill source file is missing: {skill.path!r}.')
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SkillRegistryError(f'Cannot read skill source: {type(exc).__name__}.') from None
        digest = hashlib.sha256(data).hexdigest()
        if digest != skill.sha256:
            raise SkillRegistryError(f'Skill source hash mismatch: {skill.id}.')
        return data

    @classmethod
    def _verify_file(cls, root: Path, skill: SkillSpec) -> Path:
        cls._read_verified_bytes(root, skill)
        return cls._safe_path(root, skill.path)

    def resolve(self, agent_id: str, objective: str) -> SkillSpec | None:
        text = f' {re.sub(r"[^a-z0-9]+", " ", objective.lower()).strip()} '
        for skill in self._skills:
            if skill.status != 'active' or agent_id not in skill.agent_ids:
                continue
            for term in skill.trigger_terms:
                normalized = f' {re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()} '
                if normalized.strip() and normalized in text:
                    return skill
        return None

    def read_context(self, skill: SkillSpec) -> str:
        registered = self._by_id.get(skill.id)
        if registered != skill:
            raise SkillRegistryError(f'Skill is not part of this registry: {skill.id}.')
        data = self._read_verified_bytes(self.package_root, skill)
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise SkillRegistryError(f'Cannot decode skill source: {type(exc).__name__}.') from None

    def list(self) -> list[SkillSpec]:
        return list(self._skills)
