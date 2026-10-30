"""Architecture boundary enforcement and regression prevention tests.

Enforces:
- Rule A: Domain Purity (app.domain must not import services, cli, or api)
- Rule B: Core Independence (app.core must not import domain, services, cli, or api)
- Rule C: Service Layer Independence (app.services must not import cli or api)
- Rule D: Application Layer Direction (app.cli and app.api must not cross-import)
- Rule E: Prohibited Retired Namespaces (no imports of app.ai_clipper or app.ai_animation)
- Rule F: Root CLI Independence (root app.py must not import retired namespaces)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterator, List, Optional
import pytest


@dataclass(frozen=True)
class Violation:
    file_path: str
    lineno: int
    imported_module: str
    rule: str
    message: str


class ArchitectureBoundaryChecker:
    """AST-based static import scanner and architecture boundary validator."""

    def __init__(self, backend_dir: Optional[Path] = None):
        if backend_dir is None:
            # Deterministic resolution relative to this test file location:
            # __file__ = backend/tests/unit/test_architecture_boundaries.py -> parents[2] = backend/
            self.backend_dir = Path(__file__).resolve().parents[2]
        else:
            self.backend_dir = backend_dir.resolve()
        self.app_dir = self.backend_dir / "app"

    def file_to_module(self, path: Path) -> str:
        """Resolve a Path to its Python module dot-notation string."""
        resolved = path.resolve()
        try:
            rel = resolved.relative_to(self.backend_dir)
        except ValueError:
            # Handle root app.py or virtual/temporary test paths
            if resolved == (self.backend_dir.parent / "app.py").resolve() or path.name == "app.py":
                return "root.app"
            rel = path
        parts = list(rel.parts)
        if parts and parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def file_to_package(self, path: Path) -> str:
        """Resolve the enclosing Python package for relative import calculations."""
        mod = self.file_to_module(path)
        if path.name == "__init__.py":
            return mod
        parts = mod.split(".")
        return ".".join(parts[:-1]) if len(parts) > 1 else ""

    def extract_imports(self, source: str, file_path: Path) -> Iterator[tuple[int, str]]:
        """Parse source via AST and yield (lineno, resolved_imported_module)."""
        tree = ast.parse(source, filename=str(file_path))
        pkg = self.file_to_package(file_path)
        pkg_parts = [p for p in pkg.split(".") if p]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield node.lineno, alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    # Relative import
                    if node.level <= len(pkg_parts):
                        base_parts = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                        if node.module:
                            resolved = ".".join(base_parts + [node.module])
                            yield node.lineno, resolved
                        else:
                            for alias in node.names:
                                yield node.lineno, ".".join(base_parts + [alias.name])
                    else:
                        yield node.lineno, f"<invalid_relative_level_{node.level}>"
                else:
                    # Absolute import
                    if node.module:
                        yield node.lineno, node.module
                        # Also check if importing sub-package from top-level: from app import domain
                        if node.module == "app":
                            for alias in node.names:
                                yield node.lineno, f"app.{alias.name}"

    @staticmethod
    def _matches_or_submodule(target: str, prefix: str) -> bool:
        return target == prefix or target.startswith(prefix + ".")

    def check_source(self, source: str, file_path: Path) -> List[Violation]:
        """Check source code of a file against all architectural rules."""
        src_mod = self.file_to_module(file_path)
        violations: List[Violation] = []

        for lineno, imp in self.extract_imports(source, file_path):
            v = self._check_import(file_path, src_mod, lineno, imp)
            if v:
                violations.append(v)
        return violations

    def check_file(self, file_path: Path) -> List[Violation]:
        """Read and check a single Python file."""
        source = file_path.read_text(encoding="utf-8")
        return self.check_source(source, file_path)

    def scan_repository(self) -> List[Violation]:
        """Scan all Python files under backend/app/ and the root CLI entrypoint."""
        all_violations: List[Violation] = []
        for py_file in sorted(self.app_dir.rglob("*.py")):
            all_violations.extend(self.check_file(py_file))
        root_cli = self.backend_dir.parent / "app.py"
        if root_cli.exists():
            all_violations.extend(self.check_file(root_cli))
        return all_violations

    def _check_import(
        self, file_path: Path, src_mod: str, lineno: int, imp: str
    ) -> Optional[Violation]:
        # Rule E: Prohibited Retired Namespaces (app.ai_clipper and app.ai_animation)
        for retired in ("app.ai_clipper", "app.ai_animation", "app.common"):
            if self._matches_or_submodule(imp, retired):
                return Violation(
                    file_path=str(file_path),
                    lineno=lineno,
                    imported_module=imp,
                    rule="Rule E: Prohibited Retired Namespaces",
                    message=(
                        f"Module '{src_mod}' imports retired namespace '{imp}'. "
                        f"Use canonical top-level packages (app.domain, app.services, app.cli, app.api)."
                    ),
                )

        # Rule F: Root CLI Independence
        if src_mod == "root.app":
            for forbidden in ("app.ai_clipper", "app.ai_animation", "app.common"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule F: Root CLI Independence",
                        message=f"Root CLI '{src_mod}' cannot import retired module '{imp}'.",
                    )

        # Rule A: Domain Purity
        # app.domain must not depend on services, cli, or api layers.
        if self._matches_or_submodule(src_mod, "app.domain"):
            for forbidden in ("app.services", "app.cli", "app.api"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule A: Domain Purity",
                        message=(
                            f"Domain module '{src_mod}' cannot import application/service/API module '{imp}'. "
                            f"Domain entities must remain decoupled from implementation services."
                        ),
                    )

        # Rule B: Core Independence
        # app.core must not depend on domain, services, cli, or api layers.
        if self._matches_or_submodule(src_mod, "app.core"):
            for forbidden in ("app.domain", "app.services", "app.cli", "app.api"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule B: Core Independence",
                        message=(
                            f"Core module '{src_mod}' cannot import module '{imp}'. "
                            f"Core configuration and utilities must remain foundational and independent."
                        ),
                    )

        # Rule C: Service Layer Independence
        # app.services must not depend on cli or api layers.
        if self._matches_or_submodule(src_mod, "app.services"):
            for forbidden in ("app.cli", "app.api"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule C: Service Layer Independence",
                        message=(
                            f"Service module '{src_mod}' cannot import presentation module '{imp}'. "
                            f"Services must not depend on CLI or API layers."
                        ),
                    )

        # Rule D: Application Layer Direction
        # app.cli cannot import app.api; app.api cannot import app.cli
        if self._matches_or_submodule(src_mod, "app.cli"):
            if self._matches_or_submodule(imp, "app.api"):
                return Violation(
                    file_path=str(file_path),
                    lineno=lineno,
                    imported_module=imp,
                    rule="Rule D: Application Layer Direction",
                    message=f"CLI module '{src_mod}' cannot import API module '{imp}'.",
                )
        if self._matches_or_submodule(src_mod, "app.api"):
            if self._matches_or_submodule(imp, "app.cli"):
                return Violation(
                    file_path=str(file_path),
                    lineno=lineno,
                    imported_module=imp,
                    rule="Rule D: Application Layer Direction",
                    message=f"API module '{src_mod}' cannot import CLI module '{imp}'.",
                )

        return None


# ==============================================================================
# Unit Tests for Architecture Checker Rules
# ==============================================================================

@pytest.fixture
def checker() -> ArchitectureBoundaryChecker:
    return ArchitectureBoundaryChecker()


def test_rule_a_valid_domain_to_domain_import(checker: ArchitectureBoundaryChecker):
    """Rule A: Domain modules may import other domain entities."""
    src = "from app.domain.timeline.models import TimeRange\n"
    v = checker.check_source(
        src, checker.app_dir / "domain" / "candidates" / "models.py"
    )
    assert len(v) == 0


def test_rule_a_prohibited_domain_to_service_import(checker: ArchitectureBoundaryChecker):
    """Rule A: Domain modules must not import services."""
    src = "from app.services.storage.staging import StagingManager\n"
    v = checker.check_source(
        src, checker.app_dir / "domain" / "candidates" / "scoring.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule A: Domain Purity"
    assert "Domain module" in v[0].message
    assert v[0].imported_module == "app.services.storage.staging"


def test_rule_b_prohibited_core_to_domain_import(checker: ArchitectureBoundaryChecker):
    """Rule B: Core modules must not import domain."""
    src = "from app.domain.candidates.models import CandidateClip\n"
    v = checker.check_source(
        src, checker.app_dir / "core" / "config.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule B: Core Independence"
    assert "Core module" in v[0].message


def test_rule_c_prohibited_service_to_cli_or_api_import(checker: ArchitectureBoundaryChecker):
    """Rule C: Service modules must not import CLI or API."""
    src_cli = "from app.cli.process_local import build_parser\n"
    v_cli = checker.check_source(
        src_cli, checker.app_dir / "services" / "candidates" / "ranking.py"
    )
    assert len(v_cli) == 1
    assert v_cli[0].rule == "Rule C: Service Layer Independence"

    src_api = "from app.api.v1.routes import review\n"
    v_api = checker.check_source(
        src_api, checker.app_dir / "services" / "pipeline" / "orchestrator.py"
    )
    assert len(v_api) == 1
    assert v_api[0].rule == "Rule C: Service Layer Independence"


def test_rule_d_prohibited_cli_to_api_cross_import(checker: ArchitectureBoundaryChecker):
    """Rule D: CLI must not import API, and API must not import CLI."""
    src_cli_to_api = "from app.api.v1.routes.review import router\n"
    v1 = checker.check_source(
        src_cli_to_api, checker.app_dir / "cli" / "orchestrate.py"
    )
    assert len(v1) == 1
    assert v1[0].rule == "Rule D: Application Layer Direction"

    src_api_to_cli = "from app.cli.orchestrate import run\n"
    v2 = checker.check_source(
        src_api_to_cli, checker.app_dir / "api" / "v1" / "routes" / "review.py"
    )
    assert len(v2) == 1
    assert v2[0].rule == "Rule D: Application Layer Direction"


def test_rule_e_prohibited_retired_namespaces(checker: ArchitectureBoundaryChecker):
    """Rule E: Prohibit any import of app.ai_clipper or app.ai_animation or app.common."""
    src = "from app.ai_clipper.domain.models import VideoMetadata\n"
    v = checker.check_source(
        src, checker.app_dir / "services" / "storage" / "staging.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule E: Prohibited Retired Namespaces"
    assert "retired namespace" in v[0].message


def test_rule_f_root_cli_uses_canonical_imports(checker: ArchitectureBoundaryChecker):
    """Rule F: Root app.py entrypoint must have zero architectural violations using canonical imports."""
    root_cli = checker.backend_dir.parent / "app.py"
    assert root_cli.exists(), f"Root app.py not found at {root_cli}"
    violations = checker.check_file(root_cli)
    assert len(violations) == 0, f"Root CLI has violations: {violations}"


def test_rule_f_root_cli_prohibits_retired_imports(checker: ArchitectureBoundaryChecker):
    """Rule F: Root app.py must not import retired modules."""
    root_cli = checker.backend_dir.parent / "app.py"
    src = "from app.ai_clipper.services.pipeline.batch_runner import BatchSummary\n"
    violations = checker.check_source(src, root_cli)
    assert len(violations) >= 1
    assert violations[0].imported_module == "app.ai_clipper.services.pipeline.batch_runner"


def test_relative_imports_resolution(checker: ArchitectureBoundaryChecker):
    """Relative imports resolve correctly and detect boundary violations."""
    # Valid intra-package relative import
    src_valid = "from .base import StorageService\n"
    v_valid = checker.check_source(
        src_valid, checker.app_dir / "services" / "storage" / "staging.py"
    )
    assert len(v_valid) == 0

    # Prohibited relative import from domain jumping into services
    src_invalid_domain = "from ...services.storage import base\n"
    v_domain = checker.check_source(
        src_invalid_domain,
        checker.app_dir / "domain" / "candidates" / "scoring.py",
    )
    assert len(v_domain) == 1
    assert v_domain[0].rule == "Rule A: Domain Purity"


# ==============================================================================
# Full Live Codebase Integration Test
# ==============================================================================

def test_live_codebase_has_zero_architecture_violations(checker: ArchitectureBoundaryChecker):
    """Scan all Python modules across the active codebase and enforce zero violations."""
    violations = checker.scan_repository()
    if violations:
        report = "\n".join(
            f"[{v.rule}] {v.file_path}:{v.lineno} -> {v.imported_module} ({v.message})"
            for v in violations
        )
        pytest.fail(f"Found {len(violations)} architectural boundary violation(s):\n{report}")
    assert len(violations) == 0


if __name__ == "__main__":
    checker_instance = ArchitectureBoundaryChecker()
    results = checker_instance.scan_repository()
    if results:
        print(f"FAILED: Found {len(results)} architecture violation(s):")
        for violation in results:
            print(f"  [{violation.rule}] {violation.file_path}:{violation.lineno} -> {violation.imported_module}")
        sys.exit(1)
    else:
        print("SUCCESS: 0 architecture violations found across active repository.")
        sys.exit(0)
