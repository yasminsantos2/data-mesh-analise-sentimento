#!/usr/bin/env python3
"""S2-04 - Validacao E2E da integridade das particoes no Athena.

Executa 6 checks de qualidade na tabela customer_sentiment_by_age via workgroup
marketing_wg e grava o relatorio em logs/validation_report.json.

Uso:
    python scripts/validate_e2e.py
    python scripts/validate_e2e.py --workgroup marketing_wg --database customer_sentiment

Requer simulacao completa (run_simulation.py) para todos os checks PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "logs" / "validation_report.json"
DEFAULT_REGION = "us-east-1"
DEFAULT_WORKGROUP = "marketing_wg"
DEFAULT_DATABASE = "customer_sentiment"
DEFAULT_TABLE = "customer_sentiment_by_age"
EXPECTED_PARTITIONS = 235
EXPECTED_MIN_DT = "2024-01-01"
EXPECTED_AGE_BANDS = frozenset({"Jovem", "Adulto", "Madura", "Sênior"})
EXPECTED_SENTIMENTS = frozenset({"Positivo", "Neutro", "Negativo"})


@dataclass
class CheckResult:
    id: int
    name: str
    status: str
    expected: Any
    actual: Any
    sql: str
    detail: str = ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validacao E2E do data product no Athena.")
    parser.add_argument("--workgroup", default=DEFAULT_WORKGROUP, help="Workgroup Athena.")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help="Database Glue.")
    parser.add_argument("--table", default=DEFAULT_TABLE, help="Tabela do data product.")
    parser.add_argument(
        "--expected-partitions",
        type=int,
        default=EXPECTED_PARTITIONS,
        help=f"Numero esperado de particoes dt distintas (default: {EXPECTED_PARTITIONS}).",
    )
    parser.add_argument(
        "--expected-min-dt",
        default=EXPECTED_MIN_DT,
        help=f"Data minima esperada (default: {EXPECTED_MIN_DT}).",
    )
    parser.add_argument(
        "--expected-max-dt",
        default=None,
        help="Data maxima esperada (default: min + N-1 dias das particoes).",
    )
    parser.add_argument("--region", default=DEFAULT_REGION, help="Regiao AWS.")
    parser.add_argument(
        "--report-path",
        default=str(REPORT_PATH),
        help="Caminho do relatorio JSON de saida.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=2,
        help="Intervalo de polling das queries Athena.",
    )
    return parser.parse_args(argv)


def table_ref(database: str, table: str) -> str:
    return f"{database}.{table}"


def expected_max_dt(min_dt: str, partition_count: int) -> str:
    start = datetime.strptime(min_dt, "%Y-%m-%d").date()
    return (start + timedelta(days=partition_count - 1)).isoformat()


def poll_query(athena, query_execution_id: str, poll_seconds: int) -> dict:
    while True:
        resp = athena.get_query_execution(QueryExecutionId=query_execution_id)
        state = resp["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            if state != "SUCCEEDED":
                reason = resp["QueryExecution"]["Status"].get("StateChangeReason", state)
                raise RuntimeError(f"Query Athena falhou: {reason}")
            return resp
        time.sleep(poll_seconds)


def fetch_scalar(athena, query_execution_id: str) -> str | None:
    results = athena.get_query_results(QueryExecutionId=query_execution_id)
    rows = results["ResultSet"]["Rows"]
    if len(rows) < 2:
        return None
    return rows[1]["Data"][0].get("VarCharValue")


def fetch_column_values(athena, query_execution_id: str) -> list[str]:
    results = athena.get_query_results(QueryExecutionId=query_execution_id)
    rows = results["ResultSet"]["Rows"]
    values: list[str] = []
    for row in rows[1:]:
        cell = row["Data"][0].get("VarCharValue")
        if cell is not None:
            values.append(cell)
    return values


def fetch_two_columns(athena, query_execution_id: str) -> tuple[str | None, str | None]:
    results = athena.get_query_results(QueryExecutionId=query_execution_id)
    rows = results["ResultSet"]["Rows"]
    if len(rows) < 2:
        return None, None
    data = rows[1]["Data"]
    left = data[0].get("VarCharValue") if data else None
    right = data[1].get("VarCharValue") if len(data) > 1 else None
    return left, right


def run_query(
    athena,
    sql: str,
    database: str,
    workgroup: str,
    poll_seconds: int,
) -> str:
    started = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
    )
    poll_query(athena, started["QueryExecutionId"], poll_seconds)
    return started["QueryExecutionId"]


def normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:10]


def build_checks(args: argparse.Namespace) -> list[dict[str, str]]:
    ref = table_ref(args.database, args.table)
    return [
        {
            "id": 1,
            "name": "COUNT DISTINCT dt",
            "sql": f"SELECT CAST(COUNT(DISTINCT dt) AS VARCHAR) FROM {ref}",
            "kind": "scalar",
            "expected": args.expected_partitions,
        },
        {
            "id": 2,
            "name": "DISTINCT age_band",
            "sql": f"SELECT DISTINCT age_band FROM {ref} ORDER BY age_band",
            "kind": "set",
            "expected": sorted(EXPECTED_AGE_BANDS),
        },
        {
            "id": 3,
            "name": "DISTINCT sentiment",
            "sql": f"SELECT DISTINCT sentiment FROM {ref} ORDER BY sentiment",
            "kind": "set",
            "expected": sorted(EXPECTED_SENTIMENTS),
        },
        {
            "id": 4,
            "name": "age_band IS NULL",
            "sql": f"SELECT CAST(COUNT(*) AS VARCHAR) FROM {ref} WHERE age_band IS NULL",
            "kind": "scalar",
            "expected": 0,
        },
        {
            "id": 5,
            "name": "sentiment IS NULL",
            "sql": f"SELECT CAST(COUNT(*) AS VARCHAR) FROM {ref} WHERE sentiment IS NULL",
            "kind": "scalar",
            "expected": 0,
        },
        {
            "id": 6,
            "name": "MIN/MAX dt",
            "sql": f"SELECT CAST(MIN(dt) AS VARCHAR), CAST(MAX(dt) AS VARCHAR) FROM {ref}",
            "kind": "range",
            "expected": {
                "min": args.expected_min_dt,
                "max": args.expected_max_dt
                or expected_max_dt(args.expected_min_dt, args.expected_partitions),
            },
        },
    ]


def evaluate_check(
    athena,
    spec: dict[str, Any],
    database: str,
    workgroup: str,
    poll_seconds: int,
) -> CheckResult:
    qid = run_query(athena, spec["sql"], database, workgroup, poll_seconds)
    kind = spec["kind"]
    expected = spec["expected"]

    if kind == "scalar":
        raw = fetch_scalar(athena, qid)
        actual = int(raw) if raw is not None else None
        passed = actual == expected
        detail = f"count={actual}"
    elif kind == "set":
        actual_list = fetch_column_values(athena, qid)
        actual = sorted(actual_list)
        passed = set(actual_list) == set(expected)
        detail = f"values={actual_list}"
    elif kind == "range":
        min_raw, max_raw = fetch_two_columns(athena, qid)
        actual = {"min": normalize_date(min_raw), "max": normalize_date(max_raw)}
        passed = actual == expected
        detail = f"min={actual['min']} max={actual['max']}"
    else:
        raise ValueError(f"kind desconhecido: {kind}")

    return CheckResult(
        id=spec["id"],
        name=spec["name"],
        status="PASS" if passed else "FAIL",
        expected=expected,
        actual=actual,
        sql=spec["sql"],
        detail=detail,
    )


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_validation(args: argparse.Namespace, athena=None) -> tuple[list[CheckResult], int]:
    if args.expected_max_dt is None:
        args.expected_max_dt = expected_max_dt(args.expected_min_dt, args.expected_partitions)

    athena = athena or boto3.client("athena", region_name=args.region)
    checks: list[CheckResult] = []

    for spec in build_checks(args):
        try:
            checks.append(
                evaluate_check(
                    athena,
                    spec,
                    args.database,
                    args.workgroup,
                    args.poll_seconds,
                )
            )
        except (ClientError, RuntimeError, ValueError) as exc:
            checks.append(
                CheckResult(
                    id=spec["id"],
                    name=spec["name"],
                    status="FAIL",
                    expected=spec["expected"],
                    actual=None,
                    sql=spec["sql"],
                    detail=str(exc),
                )
            )

    failed = sum(1 for c in checks if c.status == "FAIL")
    report = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "workgroup": args.workgroup,
        "database": args.database,
        "table": args.table,
        "checks": [asdict(c) for c in checks],
        "summary": {
            "pass": len(checks) - failed,
            "fail": failed,
            "overall": "PASS" if failed == 0 else "FAIL",
        },
    }

    report_path = Path(args.report_path)
    write_report(report_path, report)

    print(f"Relatorio: {report_path}")
    print(f"{'CHECK':<6} {'STATUS':<6} NOME")
    print("-" * 50)
    for check in checks:
        print(f"{check.id:<6} {check.status:<6} {check.name}")
        if check.detail:
            print(f"       -> {check.detail}")

    print("-" * 50)
    print(f"Resumo: {report['summary']['pass']} PASS, {report['summary']['fail']} FAIL")
    return checks, 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _, exit_code = run_validation(args)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
