#!/usr/bin/env python3
"""S2-03 - Dispara a State Machine para cada particao raw em sequencia.

Lista particoes disponiveis em s3://{bucket_raw}/reviews/dt=YYYY-MM-DD/, ordena
cronologicamente e executa a pipeline Step Functions uma por vez, registrando o
resultado em logs/simulation_log.csv.

Exemplos:
    python scripts/run_simulation.py \\
        --state-machine-arn arn:aws:states:us-east-1:123:stateMachine:pipeline \\
        --bucket-raw data-mesh-sentimento-dev-raw-082846230365 \\
        --bucket-trusted data-mesh-sentimento-dev-trusted-082846230365 \\
        --bucket-product data-mesh-sentimento-dev-data-product-082846230365

    python scripts/run_simulation.py ... --start-from 2024-03-01 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREFIX = "reviews/"
DEFAULT_POLL_SECONDS = 10
LOG_PATH = REPO_ROOT / "logs" / "simulation_log.csv"
CSV_FIELDS = ("dt", "status", "duration_s", "error")
TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa a State Machine sequencialmente para cada particao raw.",
    )
    parser.add_argument("--state-machine-arn", required=True, help="ARN da State Machine.")
    parser.add_argument("--bucket-raw", required=True, help="Bucket S3 raw.")
    parser.add_argument("--bucket-trusted", required=True, help="Bucket S3 trusted.")
    parser.add_argument("--bucket-product", required=True, help="Bucket S3 data-product.")
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"Prefixo das particoes no bucket raw (default: {DEFAULT_PREFIX}).",
    )
    parser.add_argument(
        "--start-from",
        default=None,
        metavar="YYYY-MM-DD",
        help="Pula particoes anteriores a esta data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista particoes sem disparar execucoes.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help=f"Intervalo de polling do describe_execution (default: {DEFAULT_POLL_SECONDS}).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Regiao AWS (default: configuracao do ambiente).",
    )
    return parser.parse_args(argv)


def normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip().lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def parse_date(value: str, flag: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"{flag} invalido '{value}': use o formato YYYY-MM-DD") from exc
    return value


def list_partitions(s3, bucket: str, prefix: str) -> list[str]:
    """Retorna datas YYYY-MM-DD encontradas em s3://{bucket}/{prefix}dt=.../."""
    prefix = normalize_prefix(prefix)
    paginator = s3.get_paginator("list_objects_v2")
    dates: set[str] = set()

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for common in page.get("CommonPrefixes", []):
            folder = common["Prefix"][len(prefix) :].rstrip("/")
            if folder.startswith("dt="):
                dates.add(folder[3:])

    return sorted(dates)


def filter_partitions(dates: list[str], start_from: str | None) -> list[str]:
    if not start_from:
        return dates
    return [dt for dt in dates if dt >= start_from]


def build_execution_input(
    dt: str,
    bucket_raw: str,
    bucket_trusted: str,
    bucket_product: str,
) -> str:
    return json.dumps(
        {
            "dt": dt,
            "bucket_raw": bucket_raw,
            "bucket_trusted": bucket_trusted,
            "bucket_product": bucket_product,
        }
    )


def execution_name_for(dt: str) -> str:
    stamp = datetime.utcnow().strftime("%H%M%S%f")
    return f"sim-{dt.replace('-', '')}-{stamp}"


def poll_execution(
    sfn,
    execution_arn: str,
    poll_seconds: int,
) -> tuple[str, float, str]:
    """Aguarda conclusao e retorna (status, duration_s, error)."""
    started = time.monotonic()
    while True:
        resp = sfn.describe_execution(executionArn=execution_arn)
        status = resp["status"]
        if status in TERMINAL_STATUSES:
            duration = _execution_duration_seconds(resp, started)
            error = _execution_error(resp, status)
            return status, duration, error
        time.sleep(poll_seconds)


def _execution_duration_seconds(resp: dict, fallback_started: float) -> float:
    start = resp.get("startDate")
    stop = resp.get("stopDate")
    if start and stop:
        return max(0.0, (stop - start).total_seconds())
    return max(0.0, time.monotonic() - fallback_started)


def _execution_error(resp: dict, status: str) -> str:
    if status == "SUCCEEDED":
        return ""
    parts = [p for p in (resp.get("error"), resp.get("cause")) if p]
    return " | ".join(parts)


def init_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=CSV_FIELDS).writeheader()


def append_log(path: Path, row: dict[str, str | float]) -> None:
    with path.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=CSV_FIELDS).writerow(row)


def format_progress(index: int, total: int, dt: str, status: str, duration_s: float) -> str:
    return f"[{index}/{total}] {dt} -> {status} ({duration_s:.0f}s)"


def run_simulation(args: argparse.Namespace, s3=None, sfn=None) -> int:
    session = boto3.session.Session(region_name=args.region)
    s3 = s3 or session.client("s3")
    sfn = sfn or session.client("stepfunctions")

    prefix = normalize_prefix(args.prefix)
    start_from = parse_date(args.start_from, "--start-from") if args.start_from else None

    try:
        all_dates = list_partitions(s3, args.bucket_raw, prefix)
    except ClientError as exc:
        print(f"ERRO ao listar particoes em s3://{args.bucket_raw}/{prefix}: {exc}")
        return 2

    dates = filter_partitions(all_dates, start_from)
    total = len(dates)

    if not dates:
        print("Nenhuma particao encontrada para processar.")
        if start_from:
            print(f"(filtro --start-from={start_from}, total no bucket: {len(all_dates)})")
        return 0

    print(f"Particoes a processar: {total} (de {len(all_dates)} no bucket)")
    if start_from:
        print(f"Retomando a partir de {start_from}")

    if args.dry_run:
        print("\n--dry-run: nenhuma execucao sera disparada.\n")
        for i, dt in enumerate(dates, start=1):
            print(f"[{i}/{total}] {dt}")
        print(f"\nTotal: {total} particoes")
        return 0

    init_log(LOG_PATH)
    successes = failures = 0
    run_started = time.monotonic()

    for i, dt in enumerate(dates, start=1):
        execution_input = build_execution_input(
            dt,
            args.bucket_raw,
            args.bucket_trusted,
            args.bucket_product,
        )
        try:
            started = sfn.start_execution(
                stateMachineArn=args.state_machine_arn,
                name=execution_name_for(dt),
                input=execution_input,
            )
            status, duration_s, error = poll_execution(
                sfn,
                started["executionArn"],
                args.poll_seconds,
            )
        except ClientError as exc:
            status = "FAILED"
            duration_s = 0.0
            error = str(exc)

        append_log(
            LOG_PATH,
            {
                "dt": dt,
                "status": status,
                "duration_s": round(duration_s, 1),
                "error": error,
            },
        )

        if status == "SUCCEEDED":
            successes += 1
        else:
            failures += 1

        print(format_progress(i, total, dt, status, duration_s))
        if error:
            print(f"         erro: {error[:300]}")

    total_duration = time.monotonic() - run_started
    print("\n=========== RESUMO ===========")
    print(f"Sucessos : {successes}")
    print(f"Falhas   : {failures}")
    print(f"Total    : {total} particoes")
    print(f"Duracao  : {total_duration:.0f}s")
    print(f"Log CSV  : {LOG_PATH}")
    print("==============================")

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_simulation(args)


if __name__ == "__main__":
    sys.exit(main())
