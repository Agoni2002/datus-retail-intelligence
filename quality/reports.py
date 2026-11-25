"""JSON quality records use counts and check names without raw business data."""

from dataclasses import asdict, dataclass, field


@dataclass
class Result:
    name: str
    severity: str
    violations: int
    detail: str = ""


@dataclass
class Report:
    version: str
    checks: list[Result] = field(default_factory=list)
    reference_date: str | None = None

    def add(self, name, violations, severity="error", detail=""):
        self.checks.append(Result(name, severity, int(violations), detail))

    @property
    def passed(self):
        return not any(check.violations for check in self.checks if check.severity == "error")

    def to_dict(self):
        return {
            "version": self.version, "passed": self.passed, "reference_date": self.reference_date,
            "checks": [asdict(c) | {"passed": c.violations == 0} for c in self.checks],
        }

    def require_pass(self):
        if not self.passed:
            raise QualityFailure(", ".join(c.name for c in self.checks if c.severity == "error" and c.violations))


class QualityFailure(RuntimeError):
    pass
