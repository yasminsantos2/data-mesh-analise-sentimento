#!/usr/bin/env python3
"""Automated validation of the S2-01 (Step Functions) acceptance criteria.

Usage:
    python tests/validate_s2_01.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = REPO_ROOT / "terraform" / "environments" / "dev"
ASL_PATH = REPO_ROOT / "terraform" / "modules" / "step_functions" / "state_machine.asl.json"
REGION = "us-east-1"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def aws_json(args: list[str]) -> dict:
    proc = run(["aws", *args, "--region", REGION, "--output", "json"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def check_asl_definition() -> None:
    if not ASL_PATH.exists():
        record("state_machine.asl.json versionado no repositorio", False, "arquivo ausente")
        return
    record(
        "state_machine.asl.json versionado no repositorio",
        True,
        str(ASL_PATH.relative_to(REPO_ROOT)),
    )

    asl = json.loads(ASL_PATH.read_text(encoding="utf-8"))
    states = asl.get("States", {})

    clean = states.get("StartJobClean", {})
    agg = states.get("StartJobAgg", {})
    args_clean = clean.get("Parameters", {}).get("Arguments", {})
    args_agg = agg.get("Parameters", {}).get("Arguments", {})

    input_ok = (
        args_clean.get("--dt.$") == "$.dt"
        and args_clean.get("--bucket_raw.$") == "$.bucket_raw"
        and args_clean.get("--bucket_trusted.$") == "$.bucket_trusted"
        and args_agg.get("--bucket_product.$") == "$.bucket_product"
    )
    record("Input aceita dt e buckets no formato esperado", input_ok, f"clean={args_clean}, agg={args_agg}")

    clean_retry = clean.get("Retry", [{}])[0]
    agg_retry = agg.get("Retry", [{}])[0]
    retry_ok = (
        clean_retry.get("MaxAttempts") == 3
        and agg_retry.get("MaxAttempts") == 3
        and clean_retry.get("BackoffRate") == 2.0
        and "States.ALL" in clean_retry.get("ErrorEquals", [])
    )
    record(
        "Retry automatico em falha do Glue Job (max 3x com backoff)",
        retry_ok,
        f"clean={clean_retry}, agg={agg_retry}",
    )

    polling_ok = all(
        name in states
        for name in (
            "WaitJobClean",
            "GetJobCleanRun",
            "CheckJobClean",
            "WaitJobAgg",
            "GetJobAggRun",
            "CheckJobAgg",
        )
    )
    record("Glue Jobs usam polling GetJobRun", polling_ok, "Wait/Check pattern presente")

    crawler_flow = (
        states.get("CheckJobAgg", {}).get("Choices", [{}])[0].get("Next") == "StartCrawler"
        and states.get("WaitCrawler", {}).get("Seconds") == 20
    )
    record(
        "Crawler so inicia apos job_agg concluir com SUCCEEDED",
        crawler_flow,
        f"CheckJobAgg -> {states.get('CheckJobAgg', {}).get('Choices', [{}])[0].get('Next')}",
    )

    athena_ok = "AthenaValidation" in states and "CheckCount" in states
    empty = states.get("EmptyPartition", {})
    empty_ok = empty.get("Type") == "Fail" and empty.get("Error") == "EmptyPartition"
    record(
        "Pipeline falha com erro EmptyPartition se COUNT=0 no Athena",
        athena_ok and empty_ok,
        f"AthenaValidation={('AthenaValidation' in states)}, Error={empty.get('Error')}",
    )


def check_terraform_provisioned() -> None:
    state = run(["terraform", "state", "list"], cwd=DEV_DIR)
    if state.returncode != 0:
        record("Provisionada 100% via Terraform", False, state.stderr.strip()[-200:])
        return

    required = [
        "module.step_functions.aws_sfn_state_machine.pipeline",
        "module.step_functions.aws_cloudwatch_log_group.sfn",
    ]
    missing = [r for r in required if r not in state.stdout]
    record(
        "Provisionada 100% via Terraform",
        not missing,
        "ok" if not missing else f"faltando={missing}",
    )


def tf_outputs() -> dict:
    proc = run(["terraform", "output", "-json"], cwd=DEV_DIR)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return json.loads(proc.stdout)


def poll_execution(execution_arn: str, timeout: int = 900) -> tuple[str, str]:
    """Return (status, error_code) for a Step Functions execution."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = aws_json(["stepfunctions", "describe-execution", "--execution-arn", execution_arn])
        status = out.get("status", "UNKNOWN")
        if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
            return status, out.get("error", "")
        time.sleep(20)
    return "TIMEOUT", ""


def start_pipeline(dt: str, buckets: dict, sm_arn: str) -> str:
    payload = {**buckets, "dt": dt}
    out = aws_json([
        "stepfunctions", "start-execution",
        "--state-machine-arn", sm_arn,
        "--input", json.dumps(payload),
    ])
    return out["executionArn"]


def seed_raw_empty_reviews(bucket: str, dt: str) -> None:
    """Upload a 1-row CSV whose review text is empty (job_clean drops it -> COUNT=0)."""
    import tempfile

    csv_body = (
        "Clothing ID,Age,Title,Review Text,Rating,Recommended IND,"
        "Division Name,Department Name,Class Name\n"
        "1000,25,title,,4,1,General,Tops,Knits\n"
    )
    key = f"reviews/dt={dt}/batch_001.csv"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        tmp.write(csv_body)
        tmp_path = tmp.name
    proc = run(["aws", "s3", "cp", tmp_path, f"s3://{bucket}/{key}"])
    Path(tmp_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())


def check_behavioral_e2e() -> None:
    """Behavioral tests: full pipeline success + EmptyPartition failure."""
    try:
        out = tf_outputs()
        sm_arn = out["state_machine_arn"]["value"]
        log_group = out["state_machine_log_group"]["value"]
        example = out["pipeline_input_example"]["value"]
        buckets = {
            "bucket_raw": example["bucket_raw"],
            "bucket_trusted": example["bucket_trusted"],
            "bucket_product": example["bucket_product"],
        }
    except Exception as exc:  # noqa: BLE001
        record("State Machine executa ponta a ponta (E2E)", False, str(exc))
        record("EmptyPartition em dt sem dados (E2E)", False, "outputs indisponiveis")
        return

    # 1. EmptyPartition: raw existe mas job_clean remove tudo -> agg vazio -> COUNT=0
    empty_dt = "2024-12-31"
    try:
        seed_raw_empty_reviews(buckets["bucket_raw"], empty_dt)
        arn_empty = start_pipeline(empty_dt, buckets, sm_arn)
        status, error = poll_execution(arn_empty, timeout=600)
        empty_ok = status == "FAILED" and error == "EmptyPartition"
        record(
            "EmptyPartition em dt sem dados agregados (E2E)",
            empty_ok,
            f"dt={empty_dt}, status={status}, error={error or 'n/a'}",
        )
    except Exception as exc:  # noqa: BLE001
        record("EmptyPartition em dt sem dados agregados (E2E)", False, str(exc))

    # 2. Ponta a ponta com dt que tem dados no raw
    try:
        arn_ok = start_pipeline("2024-01-01", buckets, sm_arn)
        status, error = poll_execution(arn_ok, timeout=900)
        record(
            "State Machine executa ponta a ponta (E2E)",
            status == "SUCCEEDED",
            f"status={status}, error={error or 'n/a'}",
        )
        if status == "SUCCEEDED":
            streams = aws_json([
                "logs", "describe-log-streams",
                "--log-group-name", log_group,
                "--order-by", "LastEventTime",
                "--descending",
                "--limit", "1",
            ])
            has_logs = bool(streams.get("logStreams"))
            record(
                "Logs de execucao gerados apos run E2E",
                has_logs,
                log_group if has_logs else "nenhum log stream",
            )
    except Exception as exc:  # noqa: BLE001
        record("State Machine executa ponta a ponta (E2E)", False, str(exc))


def check_live_aws() -> None:
    try:
        out = tf_outputs()
        sm_name = out["state_machine_name"]["value"]
        log_group = out["state_machine_log_group"]["value"]
    except Exception as exc:  # noqa: BLE001
        record("State Machine existe na AWS", False, str(exc))
        return

    try:
        sm = aws_json([
            "stepfunctions", "describe-state-machine",
            "--state-machine-arn", out["state_machine_arn"]["value"],
        ])
        record("State Machine existe na AWS", sm.get("name") == sm_name, sm_name)
    except Exception as exc:  # noqa: BLE001
        record("State Machine existe na AWS", False, str(exc))

    try:
        logs = aws_json(["logs", "describe-log-groups", "--log-group-name-prefix", log_group])
        groups = [g["logGroupName"] for g in logs.get("logGroups", [])]
        record(
            "Logs de execucao visiveis no CloudWatch",
            log_group in groups,
            log_group if log_group in groups else f"nao encontrado (prefix={log_group})",
        )
    except Exception as exc:  # noqa: BLE001
        record("Logs de execucao visiveis no CloudWatch", False, str(exc))


def main() -> int:
    print("Validando criterios de aceite S2-01 (Step Functions)\n")

    check_asl_definition()
    check_terraform_provisioned()
    check_live_aws()
    print("\n--- Testes comportamentais (E2E na AWS) ---\n")
    check_behavioral_e2e()

    print(f"{'RESULTADO':<8} CRITERIO")
    print("-" * 72)
    failed = 0
    for name, passed, detail in results:
        tag = "[PASS]" if passed else "[FAIL]"
        if not passed:
            failed += 1
        print(f"{tag:<8} {name}")
        if detail:
            print(f"         -> {detail}")

    total = len(results)
    print("-" * 72)
    print(f"{total - failed}/{total} criterios aprovados")
    if failed:
        print(f"\n{failed} criterio(s) FALHARAM.")
        return 1
    print("\nTodos os criterios de aceite do S2-01 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
