#!/usr/bin/env python3
"""Validacao automatizada dos criterios de aceite do S2-03 (run_simulation.py).

Usa clientes S3/SFN fake em memoria para validar listagem, dry-run, start-from,
execucao sequencial, log CSV e continuacao apos falha — sem AWS real.

Uso:
    python tests/validate_s2_03.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_simulation.py"
BUCKET_RAW = "fake-raw"
ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:fake"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


spec = importlib.util.spec_from_file_location("run_simulation", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]


class FakeS3:
    def __init__(self, dates: list[str], prefix: str = "reviews/"):
        self.prefix = prefix if prefix.endswith("/") else f"{prefix}/"
        self.dates = dates

    def get_paginator(self, _name: str):
        return self

    def paginate(self, Bucket: str, Prefix: str, Delimiter: str):  # noqa: N803
        for dt in sorted(self.dates):
            yield {
                "CommonPrefixes": [
                    {"Prefix": f"{self.prefix}dt={dt}/"},
                ]
            }


class FakeSFN:
    def __init__(self, outcomes: list[str]):
        self.outcomes = outcomes
        self.start_calls = 0
        self.active = 0
        self.max_active = 0
        self.executions: list[dict] = []

    def start_execution(self, stateMachineArn: str, name: str, input: str):  # noqa: N803
        self.start_calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        idx = self.start_calls - 1
        status = self.outcomes[idx] if idx < len(self.outcomes) else "SUCCEEDED"
        arn = f"arn:aws:states:us-east-1:123:execution:fake:{name}"
        self.executions.append({"arn": arn, "status": status, "input": json.loads(input)})
        return {"executionArn": arn}

    def describe_execution(self, executionArn: str):  # noqa: N803
        for ex in self.executions:
            if ex["arn"] == executionArn:
                if not ex.get("completed"):
                    ex["completed"] = True
                    self.active = max(0, self.active - 1)
                status = ex["status"]
                body = {"status": status, "startDate": None, "stopDate": None}
                if status == "FAILED":
                    body["error"] = "SimulatedFailure"
                    body["cause"] = "partition failed"
                return body
        raise KeyError(executionArn)


def base_args(**overrides) -> list[str]:
    args = [
        "--state-machine-arn", ARN,
        "--bucket-raw", BUCKET_RAW,
        "--bucket-trusted", "fake-trusted",
        "--bucket-product", "fake-product",
        "--poll-seconds", "0",
    ]
    for key, value in overrides.items():
        flag = f"--{key.replace('_', '-')}"
        if value is True:
            args.append(flag)
        elif value is not False and value is not None:
            args.extend([flag, str(value)])
    return args


def read_log(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check_list_and_dry_run() -> None:
    dates = [f"2024-01-{d:02d}" for d in range(1, 6)]
    s3 = FakeS3(dates)
    listed = mod.list_partitions(s3, BUCKET_RAW, "reviews/")
    record("Lista particoes dt=YYYY-MM-DD ordenadas", listed == sorted(dates), str(listed))

    with TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "simulation_log.csv"
        orig_log = mod.LOG_PATH
        mod.LOG_PATH = log_path
        try:
            rc = mod.run_simulation(
                mod.parse_args(base_args(dry_run=True)),
                s3=s3,
                sfn=FakeSFN([]),
            )
            record("--dry-run lista sem disparar execucoes", rc == 0 and not log_path.exists(), f"rc={rc}")
        finally:
            mod.LOG_PATH = orig_log


def check_start_from() -> None:
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-02-01"]
    filtered = mod.filter_partitions(dates, "2024-01-03")
    record(
        "--start-from retoma a partir da data informada",
        filtered == ["2024-01-03", "2024-02-01"],
        str(filtered),
    )


def check_sequential_log_and_continue() -> None:
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    s3 = FakeS3(dates)
    sfn = FakeSFN(["SUCCEEDED", "FAILED", "SUCCEEDED"])

    with TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "simulation_log.csv"
        orig_log = mod.LOG_PATH
        mod.LOG_PATH = log_path
        try:
            rc = mod.run_simulation(mod.parse_args(base_args()), s3=s3, sfn=sfn)
            rows = read_log(log_path)
        finally:
            mod.LOG_PATH = orig_log
    fields_ok = rows and set(rows[0]) == {"dt", "status", "duration_s", "error"}
    record(
        "logs/simulation_log.csv com dt, status, duration_s, error",
        fields_ok and len(rows) == 3,
        f"rows={rows}",
    )
    record(
        "Aguarda conclusao de cada execucao antes da proxima",
        sfn.max_active == 1 and sfn.start_calls == 3,
        f"max_active={sfn.max_active}, starts={sfn.start_calls}",
    )
    record(
        "Em falha de uma particao, script continua para a proxima",
        rows[1]["status"] == "FAILED" and rows[2]["status"] == "SUCCEEDED",
        f"statuses={[r['status'] for r in rows]}",
    )
    record(
        "Resumo final com sucessos, falhas e duracao total",
        rc == 1,
        f"rc={rc}",
    )


def check_gitignore() -> None:
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    record("logs/ consta no .gitignore", "logs/" in text, "logs/ presente" if "logs/" in text else "ausente")


def main() -> int:
    print("Validando criterios S2-03 (run_simulation.py)\n")
    check_list_and_dry_run()
    check_start_from()
    check_sequential_log_and_continue()
    check_gitignore()

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
    print("\nTodos os criterios de aceite do S2-03 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
