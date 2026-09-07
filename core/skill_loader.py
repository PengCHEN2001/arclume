"""Read-only loader and selector for human-authored Agent Skills."""

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Iterable


logger = logging.getLogger(__name__)


class SkillError(RuntimeError):
    """Base error for invalid or unavailable Skill definitions."""


class SkillNotFoundError(SkillError):
    """Raised when a requested Skill file does not exist."""


class SkillFormatError(SkillError):
    """Raised when a Skill file contains no usable instructions."""


@dataclass(frozen=True)
class SkillDocument:
    """One normalized Skill loaded from Markdown, text, or JSON."""

    name: str                                      # Display name used in the prompt
    description: str                               # Short operational summary
    content: str                                   # Human-authored instructions
    path: str                                      # Source path for provenance
    keywords: tuple[str, ...] = field(default_factory=tuple)  # Trigger terms
    agents: tuple[str, ...] = field(default_factory=tuple)    # Allowed Agent names
    enabled: bool = True                           # Runtime availability switch

    def matches(self, message: str, agent_name: str | None = None) -> bool:
        """Return whether this Skill should be injected for one request."""

        if not self.enabled:
            return False
        if self.agents and agent_name and agent_name.lower() not in self.agents:
            return False
        if not self.keywords:
            return True
        lowered = (message or "").lower()
        return any(keyword.lower() in lowered for keyword in self.keywords)

    def to_prompt_block(self, *, max_chars: int = 3200) -> str:
        """Format one Skill and enforce its individual prompt limit."""

        body = self._strip_repeated_heading(self.content.strip())
        if len(body) > max_chars:
            body = body[:max_chars].rstrip() + "\n..."
        description = f"\nDescription: {self.description}" if self.description else ""
        return f"### {self.name}{description}\n{body}"

    def metadata(self) -> dict[str, object]:
        """Return a safe summary without exposing the full instruction body."""

        return {
            "name": self.name,
            "description": self.description,
            "path": self.path,
            "keywords": list(self.keywords),
            "agents": list(self.agents),
            "enabled": self.enabled,
            "content_chars": len(self.content),
        }

    def _strip_repeated_heading(self, body: str) -> str:
        """Remove a first heading when it only repeats the Skill display name."""

        lines = body.splitlines()
        if lines:
            first = lines[0].strip()
            if first.startswith("#") and first.lstrip("#").strip() == self.name:
                return "\n".join(lines[1:]).strip()
        return body


class SkillLoader:
    """Discover, parse, select, and hot-reload human-authored Skills."""

    SKILL_FILENAME = "SKILL.md"
    SUPPORTED_SUFFIXES = {".md", ".txt", ".json"}
    FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
    DEFAULT_MAX_PROMPT_CHARS = 5000
    DEFAULT_SKILL_MAX_CHARS = 3200

    def __init__(
        self,
        skills_dir: str | Path = "skills",
        *,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        skill_max_chars: int = DEFAULT_SKILL_MAX_CHARS,
    ) -> None:
        if max_prompt_chars < 1 or skill_max_chars < 1:
            raise ValueError("Skill prompt limits must be greater than zero")
        self.skills_dir = Path(skills_dir).expanduser()  # Root directory for Skills
        self.max_prompt_chars = max_prompt_chars            # Total Context budget
        self.skill_max_chars = skill_max_chars              # Per-Skill safety limit
        self._cache: dict[str, tuple[int, SkillDocument]] = {}  # Mtime-aware cache
        self._errors: list[str] = []                       # Non-blocking load errors

    @classmethod
    def from_environment(cls) -> "SkillLoader":
        """Create a loader from the configured directory and prompt budget."""

        try:
            max_prompt_chars = int(
                os.getenv(
                    "ARCLUME_SKILLS_MAX_PROMPT_CHARS",
                    str(cls.DEFAULT_MAX_PROMPT_CHARS),
                )
            )
        except ValueError:
            max_prompt_chars = cls.DEFAULT_MAX_PROMPT_CHARS
        return cls(
            os.getenv("ARCLUME_SKILLS_DIR", "skills").strip() or "skills",
            max_prompt_chars=max_prompt_chars,
        )

    @property
    def errors(self) -> list[str]:
        """Return Skill files that failed during the latest directory scan."""

        return list(self._errors)

    def list_available(self) -> list[str]:
        """Return loaded Skill display names in stable order."""

        return [document.name for document in self.list_skills()]

    def load(self, name: str) -> SkillDocument:
        """Load one Skill by directory name, file name, or metadata name."""

        path = self._find_path(name)
        if path is None:
            raise SkillNotFoundError(f"Skill does not exist: {name}")
        return self._load_path(path)

    def load_many(self, names: list[str]) -> list[SkillDocument]:
        """Load multiple Skills in the requested order."""

        return [self.load(name) for name in names]

    def list_skills(self) -> list[SkillDocument]:
        """Scan all supported files while isolating malformed Skill files."""

        if not self.skills_dir.exists():
            self._errors = []
            return []

        loaded: list[SkillDocument] = []
        errors: list[str] = []
        for path in self._discover_files(self.skills_dir):
            try:
                loaded.append(self._load_path(path))
            except Exception as exc:
                message = f"{path}: {exc}"
                errors.append(message)
                logger.warning("Skill loading failed: %s", message)
        self._errors = errors
        return sorted(loaded, key=lambda item: item.name.lower())

    def select_for_agent(
        self,
        agent_name: str,
        query: str,
        names: list[str] | None = None,
        *,
        max_skills: int | None = None,
    ) -> list[SkillDocument]:
        """Select enabled Skills by Agent scope, keywords, and an optional allowlist."""

        candidates = self.load_many(names) if names else self.list_skills()
        selected = [
            document
            for document in candidates
            if document.matches(query, agent_name)
        ]
        if max_skills is not None:
            return selected[: max(0, max_skills)]
        return selected

    def render(self, documents: Iterable[SkillDocument]) -> str:
        """Render matched Skills within a total prompt budget."""

        blocks: list[str] = []
        remaining = self.max_prompt_chars
        for document in documents:
            if remaining <= 0:
                break
            block = document.to_prompt_block(max_chars=min(self.skill_max_chars, remaining))
            if len(block) > remaining:
                block = block[:remaining].rstrip() + "\n..."
            blocks.append(block)
            remaining -= len(block)
        return "\n\n".join(blocks)

    def prompt_for(
        self,
        message: str,
        agent_name: str | None = None,
        names: list[str] | None = None,
    ) -> str:
        """Select and render Skills for one request."""

        return self.render(self.select_for_agent(agent_name or "", message, names))

    def reload(self) -> list[str]:
        """Clear the cache, rescan the directory, and return loaded names."""

        self._cache.clear()
        return [document.name for document in self.list_skills()]

    def summary(self) -> dict[str, object]:
        """Return the management summary used by diagnostics and the API."""

        documents = self.list_skills()
        return {
            "root_dir": str(self.skills_dir),
            "count": len(documents),
            "skills": [document.metadata() for document in documents],
            "errors": self.errors,
        }

    def _find_path(self, name: str) -> Path | None:
        """Find a Skill without allowing path traversal."""

        if not name or Path(name).name != name or name in {".", ".."}:
            raise SkillError("Invalid Skill name")
        direct_candidates = [
            self.skills_dir / name / self.SKILL_FILENAME,
            self.skills_dir / f"{name}.md",
            self.skills_dir / f"{name}.txt",
            self.skills_dir / f"{name}.json",
        ]
        for path in direct_candidates:
            if path.is_file():
                return path
        for path in self._discover_files(self.skills_dir):
            if path.parent.name == name or path.stem == name:
                return path
            try:
                if self._load_path(path).name == name:
                    return path
            except Exception:
                continue
        return None

    def _load_path(self, path: Path) -> SkillDocument:
        """Load one path with mtime-aware caching."""

        cache_key = str(path.resolve())
        modified_at = path.stat().st_mtime_ns
        cached = self._cache.get(cache_key)
        if cached and cached[0] == modified_at:
            return cached[1]

        if path.suffix.lower() == ".json":
            document = self._load_json(path)
        else:
            document = self._load_text(path)
        self._cache[cache_key] = (modified_at, document)
        return document

    def _load_json(self, path: Path) -> SkillDocument:
        """Load the compatible JSON Skill representation."""

        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SkillFormatError("JSON Skill must be an object")
        content = str(raw.get("content") or raw.get("instructions") or "").strip()
        if not content:
            raise SkillFormatError("JSON Skill requires content or instructions")
        return self._build_document(
            path=path,
            name=str(raw.get("name") or path.parent.name or path.stem),
            description=str(raw.get("description") or ""),
            content=content,
            keywords=self._as_list(raw.get("keywords")),
            agents=self._as_list(raw.get("agents")),
            enabled=self._as_bool(raw.get("enabled"), default=True),
        )

    def _load_text(self, path: Path) -> SkillDocument:
        """Load Markdown or text with optional simple front matter."""

        raw = path.read_text(encoding="utf-8")
        metadata, body = self._split_front_matter(raw)
        content = body.strip()
        if not content:
            raise SkillFormatError("Skill file contains no instructions")
        default_name = path.parent.name if path.name == self.SKILL_FILENAME else path.stem
        name = str(metadata.get("name") or self._first_heading(content) or default_name)
        content = self._strip_first_heading(content, name)
        return self._build_document(
            path=path,
            name=name,
            description=str(metadata.get("description") or ""),
            content=content,
            keywords=self._as_list(metadata.get("keywords")),
            agents=self._as_list(metadata.get("agents")),
            enabled=self._as_bool(metadata.get("enabled"), default=True),
        )

    def _build_document(
        self,
        *,
        path: Path,
        name: str,
        description: str,
        content: str,
        keywords: list[str],
        agents: list[str],
        enabled: bool,
    ) -> SkillDocument:
        """Normalize one parsed Skill without restricting display-name language."""

        normalized_name = name.strip()
        if not normalized_name:
            raise SkillFormatError("Skill name cannot be empty")
        return SkillDocument(
            name=normalized_name,
            description=description.strip(),
            content=content.strip(),
            path=str(path),
            keywords=tuple(item.lower() for item in keywords),
            agents=tuple(item.lower() for item in agents),
            enabled=enabled,
        )

    def _discover_files(self, root_dir: Path) -> Iterable[Path]:
        """Discover SKILL.md first, then compatible standalone files."""

        skill_md_files = sorted(root_dir.rglob(self.SKILL_FILENAME))
        yielded = {path.resolve() for path in skill_md_files}
        for path in skill_md_files:
            yield path
        for path in sorted(root_dir.rglob("*")):
            resolved = path.resolve()
            if resolved in yielded or not path.is_file():
                continue
            if path.name.startswith(".") or path.name.upper() == "README.MD":
                continue
            if path.suffix.lower() in self.SUPPORTED_SUFFIXES:
                yield path

    @staticmethod
    def _split_front_matter(raw: str) -> tuple[dict[str, str], str]:
        """Parse simple key-value front matter without adding PyYAML."""

        text = raw.lstrip()
        match = SkillLoader.FRONT_MATTER_PATTERN.match(text)
        if not match:
            return {}, raw
        metadata: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip("\"'")
        return metadata, text[match.end() :]

    @staticmethod
    def _first_heading(body: str) -> str | None:
        """Return the first Markdown heading as a fallback display name."""

        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or None
        return None

    @staticmethod
    def _strip_first_heading(body: str, name: str) -> str:
        """Remove a duplicated first heading from prompt content."""

        lines = body.splitlines()
        if lines:
            first = lines[0].strip()
            if first.startswith("#") and first.lstrip("#").strip() == name:
                return "\n".join(lines[1:]).strip()
        return body

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        """Normalize list metadata and both English and Chinese commas."""

        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        normalized = str(value).replace("，", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        """Parse the supported boolean values used by Skill metadata."""

        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}
