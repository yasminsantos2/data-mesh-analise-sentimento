#!/usr/bin/env python3
"""Automated validation of the S1-05 (Step Functions) acceptance criteria.

Checks the versioned ASL definition, Terraform state, and (when AWS
credentials are available) the live state machine + CloudWatch log group.

Usage:
    python tests/validate_s1_05.py
"""
from __future__ import annotations

import json
import subprocess
import sys
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
    record("state_machine.asl.json versionado no repositorio", True, str(ASL_PATH.relative_to(REPO_ROOT)))

    asl = json.loads(ASL_PATH.read_text(encoding="utf-8"))
    states = asl.get("States", {})

    clean = states.get("StartJobClean", states.get("RunJobClean", {}))
    agg = states.get("StartJobAgg", states.get("RunJobAgg", {}))
    args_clean = clean.get("Parameters", {}).get("Arguments", {})
    args_agg = agg.get("Parameters", {}).get("Arguments", {})
    dt_in_clean = args_clean.get("--dt.$") == "$.dt"
    dt_in_agg = args_agg.get("--dt.$") == "$.dt"
    record(
        "Input aceita parametro dt (YYYY-MM-DD)",
        dt_in_clean and dt_in_agg,
        f"job_clean={dt_in_clean}, job_agg={dt_in_agg}",
    )

    # Retry max 3 on Glue jobs
    clean_retry = clean.get("Retry", [{}])[0]
    agg_retry = agg.get("Retry", [{}])[0]
    retry_ok = (
        clean_retry.get("MaxAttempts") == 3
        and agg_retry.get("MaxAttempts") == 3
        and clean_retry.get("BackoffRate") == 2.0
    )
    record(
        "Retry automatico em falha do Glue Job (max 3x com backoff)",
        retry_ok,
        f"clean={clean_retry}, agg={agg_retry}",
    )

    # Crawler only after job_agg SUCCEEDED
    check_agg = states.get("CheckJobAgg", {})
    agg_choices = check_agg.get("Choices", [])
    crawler_after_agg = any(
        c.get("StringEquals") == "SUCCEEDED" and c.get("Next") == "StartCrawler"
        for c in agg_choices
    )
    record(
        "Crawler so inicia apos job_agg concluir",
        crawler_after_agg,
        f"CheckJobAgg choices={agg_choices}",
    )

    # EmptyPartition fail state (validacao Athena no final)
    empty = states.get("EmptyPartition", {})
    empty_ok = empty.get("Type") == "Fail" and empty.get("Error") == "EmptyPartition"
    record(
        "Pipeline falha com erro EmptyPartition se COUNT=0 no Athena",
        empty_ok and "AthenaValidation" in states,
        f"Error={empty.get('Error')}",
    )


def check_terraform_provisioned() -> None:
    state = run(["terraform", "state", "list"], cwd=DEV_DIR)
    if state.returncode != 0:
        record("Provisionada 100% via Terraform", False, state.stderr.strip()[-200:])
        return

    resources = state.stdout
    required = [
        "module.step_functions.aws_sfn_state_machine.pipeline",
        "module.step_functions.aws_cloudwatch_log_group.sfn",
    ]
    missing = [r for r in required if r not in resources]
    record(
        "Provisionada 100% via Terraform",
        not missing,
        "ok" if not missing else f"faltando={missing}",
    )


def check_live_aws() -> None:
    try:
        out = json.loads(run(["terraform", "output", "-json"], cwd=DEV_DIR).stdout)
        sm_name = out["state_machine_name"]["value"]
        log_group = out["state_machine_log_group"]["value"]
    except Exception as exc:  # noqa: BLE001
        record("State Machine existe na AWS", False, str(exc))
        return

    try:
        sm = aws_json(["stepfunctions", "describe-state-machine", "--state-machine-arn",
                       out["state_machine_arn"]["value"]])
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
    print("Validando criterios de aceite S1-05 (Step Functions)\n")

    check_asl_definition()
    check_terraform_provisioned()
    check_live_aws()

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
    print("\nTodos os criterios de aceite do S1-05 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
