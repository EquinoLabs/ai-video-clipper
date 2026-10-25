"""Architecture boundary enforcement and regression prevention tests.

Enforces:
- Rule A: Domain purity (domain modules must not import services, CLI, or API)
- Rule B: Canonical Clipper imports (canonical Clipper code must not import legacy shims)
- Rule C: Product isolation (Clipper and Animation Studio cannot cross-import)
- Rule D: Shared infrastructure independence (common/core cannot import products)
- Rule E: Central API composition (central router may compose, products cannot import router)
- Rule F: Legacy compatibility-shim integrity (shims remain valid forwarding proxies)
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
        # Central API composition exemption:
        # backend/app/api/v1/api.py is authorized to compose product routes.
        if src_mod == "app.api.v1.api":
            return None

        # Root CLI entrypoint rule
        # root.app (app.py) must not import legacy Clipper paths or Animation Studio.
        if src_mod == "root.app":
            for forbidden in ("app.domain", "app.services", "app.cli", "app.api"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule B: Canonical Clipper Imports (Root CLI)",
                        message=(
                            f"Root CLI '{src_mod}' cannot depend on legacy path '{imp}'. "
                            f"Use canonical 'app.ai_clipper.*' imports."
                        ),
                    )
            if self._matches_or_submodule(imp, "app.ai_animation"):
                return Violation(
                    file_path=str(file_path),
                    lineno=lineno,
                    imported_module=imp,
                    rule="Rule C: Product Isolation (Root CLI)",
                    message=f"Root CLI '{src_mod}' cannot import AI Animation module '{imp}'.",
                )

        # Rule E: Central API composition
        # Product implementation packages must not import the central router back into themselves.
        if self._matches_or_submodule(src_mod, "app.ai_clipper") or self._matches_or_submodule(
            src_mod, "app.ai_animation"
        ):
            if self._matches_or_submodule(imp, "app.api.v1.api") or imp == "app.api.v1":
                return Violation(
                    file_path=str(file_path),
                    lineno=lineno,
                    imported_module=imp,
                    rule="Rule E: Central API Composition",
                    message=(
                        f"Product module '{src_mod}' cannot import central router '{imp}'. "
                        f"The central router composes products; products must not depend backward on central composition."
                    ),
                )

        # Rule A: Domain purity
        # app.ai_clipper.domain must not depend on services, cli, or api layers.
        if self._matches_or_submodule(src_mod, "app.ai_clipper.domain"):
            for forbidden in (
                "app.ai_clipper.services",
                "app.ai_clipper.cli",
                "app.ai_clipper.api",
                "app.services",
                "app.cli",
                "app.api",
            ):
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

        # Rule B: Canonical Clipper imports
        # Canonical Clipper implementation code must not depend on legacy shims.
        if self._matches_or_submodule(src_mod, "app.ai_clipper"):
            for forbidden in ("app.domain", "app.services", "app.cli", "app.api"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule B: Canonical Clipper Imports",
                        message=(
                            f"Canonical Clipper module '{src_mod}' cannot depend on legacy path '{imp}'. "
                            f"Use canonical 'app.ai_clipper.*' imports."
                        ),
                    )

        # Rule C: Product isolation
        # Clipper must not import Animation, and Animation must not import Clipper.
        if self._matches_or_submodule(src_mod, "app.ai_clipper"):
            if self._matches_or_submodule(imp, "app.ai_animation"):
                return Violation(
                    file_path=str(file_path),
                    lineno=lineno,
                    imported_module=imp,
                    rule="Rule C: Product Isolation",
                    message=(
                        f"AI Clipper module '{src_mod}' cannot import AI Animation module '{imp}'. "
                        f"Products must remain completely isolated."
                    ),
                )

        if self._matches_or_submodule(src_mod, "app.ai_animation"):
            for forbidden in ("app.ai_clipper", "app.domain", "app.services", "app.cli"):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule C: Product Isolation",
                        message=(
                            f"AI Animation module '{src_mod}' cannot import AI Clipper module '{imp}'. "
                            f"Products must remain completely isolated."
                        ),
                    )

        # Rule D: Shared infrastructure independence
        # app.common and app.core must not depend on product packages.
        if self._matches_or_submodule(src_mod, "app.common") or self._matches_or_submodule(
            src_mod, "app.core"
        ):
            for forbidden in (
                "app.ai_clipper",
                "app.ai_animation",
                "app.domain",
                "app.services",
                "app.cli",
                "app.api",
            ):
                if self._matches_or_submodule(imp, forbidden):
                    return Violation(
                        file_path=str(file_path),
                        lineno=lineno,
                        imported_module=imp,
                        rule="Rule D: Shared Infrastructure Independence",
                        message=(
                            f"Shared infrastructure module '{src_mod}' cannot import product module '{imp}'. "
                            f"Shared utilities must remain generic and independent of products."
                        ),
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
    src = "from app.ai_clipper.domain.timeline.models import TimeRange\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "domain" / "candidates" / "models.py"
    )
    assert len(v) == 0


def test_rule_a_prohibited_domain_to_service_import(checker: ArchitectureBoundaryChecker):
    """Rule A: Domain modules must not import services."""
    src = "from app.ai_clipper.services.storage.staging import StagingManager\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "domain" / "candidates" / "scoring.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule A: Domain Purity"
    assert "Domain module" in v[0].message
    assert v[0].imported_module == "app.ai_clipper.services.storage.staging"


def test_rule_a_prohibited_domain_to_legacy_service_import(checker: ArchitectureBoundaryChecker):
    """Rule A: Domain modules must not import legacy services."""
    src = "import app.services.pipeline.orchestrator\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "domain" / "candidates" / "models.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule A: Domain Purity"


def test_rule_b_prohibited_clipper_to_legacy_import(checker: ArchitectureBoundaryChecker):
    """Rule B: Canonical Clipper code must not import legacy shims."""
    src = "from app.domain.candidates.models import CandidateClip\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "services" / "candidates" / "ranking.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule B: Canonical Clipper Imports"
    assert "legacy path" in v[0].message


def test_rule_c_prohibited_clipper_to_animation_import(checker: ArchitectureBoundaryChecker):
    """Rule C: Clipper must not import Animation Studio."""
    src = "from app.ai_animation.config import get_animation_settings\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "services" / "pipeline" / "orchestrator.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule C: Product Isolation"
    assert "cannot import AI Animation" in v[0].message


def test_rule_c_prohibited_animation_to_clipper_import(checker: ArchitectureBoundaryChecker):
    """Rule C: Animation Studio must not import Clipper."""
    src = "from app.ai_clipper.services.rendering.short_clip_renderer import ShortClipRenderer\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_animation" / "services" / "renderer.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule C: Product Isolation"
    assert "cannot import AI Clipper" in v[0].message


def test_rule_d_prohibited_common_to_product_import(checker: ArchitectureBoundaryChecker):
    """Rule D: Shared infrastructure (common/core) must not import products."""
    src = "from app.ai_clipper.services.media.ffmpeg import run_ffmpeg\n"
    v = checker.check_source(
        src, checker.app_dir / "common" / "media" / "probing.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule D: Shared Infrastructure Independence"
    assert "cannot import product module" in v[0].message


def test_rule_d_permitted_shared_imports(checker: ArchitectureBoundaryChecker):
    """Rule D: Products are permitted to import shared common and core infrastructure."""
    src = (
        "from app.core.config import get_settings\n"
        "from app.common.media.probing import probe_media_file\n"
        "from app.common.llm.structured import generate_json\n"
    )
    # Both Clipper and Animation may import common/core
    v_clipper = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "services" / "storage" / "staging.py"
    )
    assert len(v_clipper) == 0

    v_anim = checker.check_source(
        src, checker.app_dir / "ai_animation" / "services" / "stubs.py"
    )
    assert len(v_anim) == 0


def test_rule_e_central_api_composition_permitted(checker: ArchitectureBoundaryChecker):
    """Rule E: Central API composition is permitted to register both product routers."""
    src = (
        "from fastapi import APIRouter\n"
        "from app.ai_clipper.api.routes import review\n"
        "from app.ai_animation.api import routes as animation_routes\n"
    )
    v = checker.check_source(src, checker.app_dir / "api" / "v1" / "api.py")
    assert len(v) == 0


def test_rule_e_product_importing_central_api_prohibited(checker: ArchitectureBoundaryChecker):
    """Rule E: Product modules cannot import back into central API composition."""
    src = "from app.api.v1.api import api_router\n"
    v = checker.check_source(
        src, checker.app_dir / "ai_clipper" / "api" / "routes" / "review.py"
    )
    assert len(v) == 1
    assert v[0].rule == "Rule E: Central API Composition"
    assert "cannot import central router" in v[0].message


def test_rule_f_legacy_shims_not_misclassified(checker: ArchitectureBoundaryChecker):
    """Rule F: Legacy compatibility shims are allowed forwarding proxies outside ai_clipper."""
    src = (
        "import sys\n"
        "from app.ai_clipper.domain.candidates import models as _impl\n"
        "sys.modules[__name__] = _impl\n"
    )
    v = checker.check_source(
        src, checker.app_dir / "domain" / "candidates" / "models.py"
    )
    assert len(v) == 0


def test_relative_imports_resolution(checker: ArchitectureBoundaryChecker):
    """Relative imports within a product resolve correctly and detect violations."""
    # Valid intra-package relative import
    src_valid = "from .base import StorageService\n"
    v_valid = checker.check_source(
        src_valid, checker.app_dir / "ai_clipper" / "services" / "storage" / "staging.py"
    )
    assert len(v_valid) == 0

    # Prohibited relative import from domain jumping into services
    src_invalid_domain = "from ...services.storage import base\n"
    v_domain = checker.check_source(
        src_invalid_domain,
        checker.app_dir / "ai_clipper" / "domain" / "candidates" / "scoring.py",
    )
    assert len(v_domain) == 1
    assert v_domain[0].rule == "Rule A: Domain Purity"

    # Prohibited relative import from Clipper crossing into Animation
    src_cross = "from ....ai_animation import config\n"
    v_cross = checker.check_source(
        src_cross,
        checker.app_dir / "ai_clipper" / "services" / "storage" / "staging.py",
    )
    assert len(v_cross) == 1
    assert v_cross[0].rule == "Rule C: Product Isolation"


def test_diagnostic_message_quality(checker: ArchitectureBoundaryChecker):
    """Verify diagnostic message format includes file, line, rule, and message."""
    src = "import app.services.storage.staging\n"
    target_file = checker.app_dir / "ai_clipper" / "domain" / "candidates" / "models.py"
    v = checker.check_source(src, target_file)
    assert len(v) == 1
    item = v[0]
    assert item.lineno == 1
    assert "Rule A" in item.rule
    assert "app.services.storage.staging" in item.imported_module
    assert str(target_file) in item.file_path
    assert "Domain module" in item.message


# ==============================================================================
# Root CLI Entrypoint Boundary Tests
# ==============================================================================

def test_root_cli_uses_canonical_imports(checker: ArchitectureBoundaryChecker):
    """Root app.py entrypoint must have zero architectural violations using canonical imports."""
    root_cli = checker.backend_dir.parent / "app.py"
    assert root_cli.exists(), f"Root app.py not found at {root_cli}"
    violations = checker.check_file(root_cli)
    assert len(violations) == 0, f"Root CLI has violations: {violations}"


def test_root_cli_prohibits_legacy_imports(checker: ArchitectureBoundaryChecker):
    """Root app.py must not import legacy compatibility shim modules."""
    root_cli = checker.backend_dir.parent / "app.py"
    src = "from app.services.pipeline.batch_runner import BatchSummary\n"
    violations = checker.check_source(src, root_cli)
    assert len(violations) == 1
    assert "Rule B" in violations[0].rule
    assert violations[0].imported_module == "app.services.pipeline.batch_runner"
    assert "Root CLI" in violations[0].message


def test_root_cli_prohibits_animation_imports(checker: ArchitectureBoundaryChecker):
    """Root app.py is Clipper-only and must not import AI Animation Studio modules."""
    root_cli = checker.backend_dir.parent / "app.py"
    src = "from app.ai_animation.domain.models import AnimationJob\n"
    violations = checker.check_source(src, root_cli)
    assert len(violations) == 1
    assert "Rule C" in violations[0].rule
    assert violations[0].imported_module == "app.ai_animation.domain.models"
    assert "AI Animation" in violations[0].message


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


# ==============================================================================
# Legacy Compatibility Shim Integrity Tests
# ==============================================================================

def test_legacy_shim_module_identities():
    """Verify representative legacy compatibility shims share module identity with canonical modules."""
    import app.api.v1.schemas.candidates as legacy_schema
    import app.ai_clipper.api.schemas.candidates as canonical_schema

    assert legacy_schema is canonical_schema


def test_legacy_shim_monkeypatch_bidirectional(monkeypatch):
    """Verify monkeypatching a shim attribute is reflected on canonical module and vice versa."""
    import app.api.v1.schemas.candidates as legacy_schema
    import app.ai_clipper.api.schemas.candidates as canonical_schema

    monkeypatch.setattr(legacy_schema, "_test_marker_stage5", "sentinel_value", raising=False)
    assert getattr(canonical_schema, "_test_marker_stage5", None) == "sentinel_value"


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
