"""Read-only loader for human-authored Agent Skills."""

from dataclasses import dataclass
import os
from pathlib import Path
import re


class SkillError(RuntimeError):
    """Base error for invalid or unavailable Skill definitions."""


class SkillNotFoundError(SkillError):
    """Raised when a requested Skill directory or file does not exist."""


class SkillFormatError(SkillError):
    """Raised when a Skill file exists but contains no usable instructions."""


@dataclass(frozen=True)
class SkillDocument:
    """One immutable Skill loaded from a local SKILL.md file."""

    name: str                 # Stable name used by the future Router
    content: str              # Instructions injected into one Context
    path: str                 # Source path used for debugging and provenance


class SkillLoader:
    """Load Skills from a controlled directory without modifying them."""

    SKILL_FILENAME = "SKILL.md"
    NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

    def __init__(self, skills_dir: str | Path = "skills") -> None:
        self.skills_dir = Path(skills_dir)  # Root directory containing Skill folders

    @classmethod
    def from_environment(cls) -> "SkillLoader":
        """Create a loader using the configured Skill directory."""

        return cls(os.getenv("ARCLUME_SKILLS_DIR", "skills").strip() or "skills")

    def list_available(self) -> list[str]:
        """Return valid Skill directory names in stable alphabetical order."""

        if not self.skills_dir.exists():
            return []
        return sorted(
            path.name
            for path in self.skills_dir.iterdir()
            if path.is_dir()
            and self.NAME_PATTERN.fullmatch(path.name)
            and (path / self.SKILL_FILENAME).is_file()
        )

    def load(self, name: str) -> SkillDocument:
        """Load one Skill file and return its normalized instructions."""

        self._validate_name(name)
        skill_path = self.skills_dir / name / self.SKILL_FILENAME
        if not skill_path.is_file():
            raise SkillNotFoundError(f"Skill file does not exist: {skill_path}")

        content = skill_path.read_text(encoding="utf-8").strip()
        if not content:
            raise SkillFormatError(f"Skill file is empty: {skill_path}")

        return SkillDocument(name=name, content=content, path=str(skill_path))

    def load_many(self, names: list[str]) -> list[SkillDocument]:
        """Load multiple Skills in the requested order without changing files."""

        return [self.load(name) for name in names]

    @classmethod
    def _validate_name(cls, name: str) -> None:
        """Reject path traversal and ambiguous Skill names."""

        if not name or not cls.NAME_PATTERN.fullmatch(name):
            raise SkillError(
                "Skill names may contain only letters, numbers, underscores, and hyphens"
            )
