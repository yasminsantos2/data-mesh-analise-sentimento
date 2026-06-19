#!/usr/bin/env python3
"""Validacao automatizada dos criterios de aceite do S2-04 (validate_e2e.py).

Testa a logica dos 6 checks com cliente Athena fake — sem AWS real.

Uso:
    python tests/validate_s2_04.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_e2e.py"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


spec = importlib.util.spec_from_file_location("validate_e2e", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules["validate_e2e"] = mod
spec.loader.exec_module(mod)  # type: ignore[union-attr]


class FakeAthena:
    def __init__(self, mode: str = "pass"):
        self.mode = mode
        self.queries: list[str] = []

    def start_query_execution(self, QueryString: str, QueryExecutionContext: dict, WorkGroup: str):  # noqa: N803
        self.queries.append(QueryString)
        return {"QueryExecutionId": f"q-{len(self.queries)}"}

    def get_query_execution(self, QueryExecutionId: str):  # noqa: N803
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId: str):  # noqa: N803
        sql = self.queries[int(QueryExecutionId.split("-")[1]) - 1]
        if self.mode == "pass":
            if "COUNT(DISTINCT dt)" in sql:
                return _rows([["235"]])
            if "DISTINCT age_band" in sql:
                return _rows([["Adulto"], ["Jovem"], ["Madura"], ["Sênior"]])
            if "DISTINCT sentiment" in sql:
                return _rows([["Negativo"], ["Neutro"], ["Positivo"]])
            if "age_band IS NULL" in sql:
                return _rows([["0"]])
            if "sentiment IS NULL" in sql:
                return _rows([["0"]])
            if "MIN(dt)" in sql:
                return _rows([["2024-01-01", "2024-08-22"]])
        return _rows([["0"]])


def _rows(values: list[list[str]]) -> dict:
    header = [{"VarCharValue": f"col{i}"} for i in range(len(values[0]))]
    body = [[{"VarCharValue": v} for v in row] for row in values]
    return {
        "ResultSet": {
            "Rows": [{"Data": header}] + [{"Data": row} for row in body],
        }
    }


def check_pass_scenario() -> None:
    with TemporaryDirectory() as tmp:
        report = Path(tmp) / "validation_report.json"
        args = mod.parse_args([
            "--report-path", str(report),
            "--poll-seconds", "0",
        ])
        _, code = mod.run_validation(args, athena=FakeAthena("pass"))

        payload = json.loads(report.read_text(encoding="utf-8"))
        record("validate_e2e.py executa 6 checks", len(payload["checks"]) == 6, f"n={len(payload['checks'])}")
        record(
            "Gera logs/validation_report.json com PASS/FAIL por check",
            report.exists() and all("status" in c for c in payload["checks"]),
            str(report.name),
        )
        record(
            "Exit code 0 quando todos PASS",
            code == 0 and payload["summary"]["overall"] == "PASS",
            f"code={code}, overall={payload['summary']['overall']}",
        )


def check_fail_scenario() -> None:
    class BadAthena(FakeAthena):
        def get_query_results(self, QueryExecutionId: str):  # noqa: N803
            sql = self.queries[int(QueryExecutionId.split("-")[1]) - 1]
            if "COUNT(DISTINCT dt)" in sql:
                return _rows([["100"]])
            return super().get_query_results(QueryExecutionId)

    with TemporaryDirectory() as tmp:
        report = Path(tmp) / "validation_report.json"
        args = mod.parse_args(["--report-path", str(report), "--poll-seconds", "0"])
        _, code = mod.run_validation(args, athena=BadAthena("pass"))
        payload = json.loads(report.read_text(encoding="utf-8"))

        record(
            "Exit code 1 quando algum FAIL",
            code == 1 and payload["summary"]["fail"] >= 1,
            f"code={code}, fail={payload['summary']['fail']}",
        )


def check_expected_max_dt() -> None:
    got = mod.expected_max_dt("2024-01-01", 235)
    record(
        "CHECK 6 usa max derivado de 235 particoes a partir de 2024-01-01",
        got == "2024-08-22",
        f"max={got}",
    )


def check_gitignore() -> None:
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    checks = [
        ("logs/ consta no .gitignore", "logs/" in text),
        ("data/ consta no .gitignore", "data/" in text),
        ("*.tfvars ignorado com excecao de example", "*.tfvars" in text and "!*.tfvars.example" in text),
        (".env.example versionado existe", (REPO_ROOT / ".env.example").exists()),
        (
            "terraform.tfvars.example versionado existe",
            (REPO_ROOT / "terraform/environments/dev/terraform.tfvars.example").exists(),
        ),
    ]
    for name, ok in checks:
        record(name, ok, "ok" if ok else "ausente")


def check_readme() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    checks = [
        ("README possui diagrama Mermaid flowchart TD", "flowchart TD" in readme),
        ("README documenta estrutura de pastas", "├── modules/" in readme and "athena/" in readme),
        ("README documenta upload_partitions -> run_simulation -> validate_e2e", "validate_e2e.py" in readme and "run_simulation.py" in readme),
        ("README documenta schema customer_sentiment_by_age", "customer_sentiment_by_age" in readme and "review_count" in readme),
        ("README documenta regras de negocio", "Jovem" in readme and "Positivo" in readme),
        ("README troubleshooting com 5+ erros", readme.lower().count("###") >= 5 or readme.count("**Causa:**") >= 5),
    ]
    for name, ok in checks:
        record(name, ok, "ok" if ok else "ausente no README")


def main() -> int:
    print("Validando criterios S2-04 (validate_e2e + README)\n")
    check_pass_scenario()
    check_fail_scenario()
    check_expected_max_dt()
    check_gitignore()
    check_readme()

    print(f"{'RESULTADO':<8} CRITERIO")
    print("-" * 70)
    failed = 0
    for name, passed, detail in results:
        tag = "[PASS]" if passed else "[FAIL]"
        if not passed:
            failed += 1
        print(f"{tag:<8} {name}")
        if detail:
            print(f"         -> {detail}")

    total = len(results)
    print("-" * 70)
    print(f"{total - failed}/{total} criterios aprovados")
    if failed:
        return 1
    print("\nTodos os criterios de aceite do S2-04 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
