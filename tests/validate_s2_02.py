#!/usr/bin/env python3
"""Automated validation of the S2-02 (Athena Marketing workgroup) acceptance criteria.

Usage:
    python tests/validate_s2_02.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = REPO_ROOT / "terraform" / "environments" / "dev"
VIEWS_SQL = REPO_ROOT / "terraform" / "modules" / "athena" / "views.sql"
REGION = "us-east-1"
EXPECTED_VIEWS = ("vw_sentiment_by_age", "vw_sentiment_by_dept", "vw_daily_trend")
BYTES_CUTOFF = 1_073_741_824
MAX_QUERY_SECONDS = 10

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


def tf_outputs() -> dict:
    out = json.loads(run(["terraform", "output", "-json"], cwd=DEV_DIR).stdout)
    return {k: v["value"] for k, v in out.items()}


def assume_role(arn: str) -> dict:
    out = aws_json([
        "sts", "assume-role",
        "--role-arn", arn,
        "--role-session-name", "s2-02-validate",
    ])
    c = out["Credentials"]
    return {
        "AWS_ACCESS_KEY_ID": c["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": c["SecretAccessKey"],
        "AWS_SESSION_TOKEN": c["SessionToken"],
    }


def run_as(creds: dict, args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(creds)
    return subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True, text=True, env=env,
    )


def poll_athena(creds: dict, qid: str, timeout: int = 60) -> tuple[str, float, str]:
    """Return (state, elapsed_seconds, reason)."""
    started = time.time()
    deadline = started + timeout
    while time.time() < deadline:
        r = run_as(creds, ["athena", "get-query-execution", "--query-execution-id", qid])
        if r.returncode != 0:
            return "ERROR", time.time() - started, r.stderr.strip()[-200:]
        body = json.loads(r.stdout)["QueryExecution"]
        status = body["Status"]
        state = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            stats = body.get("Statistics", {})
            elapsed = stats.get("EngineExecutionTimeInMillis", 0) / 1000.0
            if elapsed <= 0:
                elapsed = time.time() - started
            return state, elapsed, status.get("StateChangeReason", "")
        time.sleep(2)
    return "TIMEOUT", time.time() - started, ""


def check_views_sql() -> None:
    if not VIEWS_SQL.exists():
        record("views.sql versionado em terraform/modules/athena/", False, "arquivo ausente")
        return
    text = VIEWS_SQL.read_text(encoding="utf-8")
    missing = [v for v in EXPECTED_VIEWS if f"-- @query {v}" not in text]
    record(
        "views.sql versionado em terraform/modules/athena/",
        not missing,
        str(VIEWS_SQL.relative_to(REPO_ROOT)) if not missing else f"faltam: {missing}",
    )


def check_workgroup(workgroup: str, results_location: str) -> None:
    try:
        wg = aws_json(["athena", "get-work-group", "--work-group", workgroup])["WorkGroup"]
        cfg = wg.get("Configuration", {})
        cutoff = cfg.get("BytesScannedCutoffPerQuery")
        enforce = cfg.get("EnforceWorkGroupConfiguration")
        output = cfg.get("ResultConfiguration", {}).get("OutputLocation", "")

        record(
            "Workgroup marketing_wg criado com limite de 1GB por query",
            cutoff == BYTES_CUTOFF,
            f"bytes_scanned_cutoff={cutoff}",
        )
        record(
            "enforce_workgroup_configuration=true (cliente nao pode sobrescrever)",
            enforce is True,
            f"enforce={enforce}",
        )
        record(
            "Resultados gravados em s3://athena-results/marketing/",
            output == results_location and "/marketing/" in output,
            f"output={output}",
        )
    except Exception as exc:  # noqa: BLE001
        record("Workgroup marketing_wg criado com limite de 1GB por query", False, str(exc))
        record("enforce_workgroup_configuration=true (cliente nao pode sobrescrever)", False, str(exc))
        record("Resultados gravados em s3://athena-results/marketing/", False, str(exc))


def check_named_queries(workgroup: str) -> dict[str, str]:
    """Return map view_name => named_query_id."""
    ids: dict[str, str] = {}
    try:
        listed = aws_json(["athena", "list-named-queries", "--work-group", workgroup])
        query_ids = listed.get("NamedQueryIds", [])
        if not query_ids:
            record("3 named queries visiveis no console Athena dentro de marketing_wg", False, "nenhuma query")
            return ids

        batch = aws_json(["athena", "batch-get-named-query", "--named-query-ids", *query_ids])
        by_name = {q["Name"]: q["NamedQueryId"] for q in batch.get("NamedQueries", [])}
        ids = {name: by_name[name] for name in EXPECTED_VIEWS if name in by_name}
        record(
            "3 named queries visiveis no console Athena dentro de marketing_wg",
            len(ids) == len(EXPECTED_VIEWS),
            f"encontradas={sorted(ids)}",
        )
    except Exception as exc:  # noqa: BLE001
        record("3 named queries visiveis no console Athena dentro de marketing_wg", False, str(exc))
    return ids


def check_athena_access(athena_arn: str, workgroup: str, named_ids: dict[str, str]) -> None:
    try:
        creds = assume_role(athena_arn)
    except Exception as exc:  # noqa: BLE001
        record("athena_role acessa o workgroup marketing_wg sem erro", False, str(exc))
        record("athena_role NAO consegue acessar outros workgroups", False, str(exc))
        for view in EXPECTED_VIEWS:
            record(f"Cada query executa em < 10s [{view}]", False, str(exc))
        return

    # marketing_wg OK
    start = run_as(creds, [
        "athena", "start-query-execution",
        "--query-string", 'SELECT count(*) AS n FROM customer_sentiment.customer_sentiment_by_age',
        "--query-execution-context", "Database=customer_sentiment",
        "--work-group", workgroup,
    ])
    if start.returncode != 0:
        record("athena_role acessa o workgroup marketing_wg sem erro", False, start.stderr.strip()[-300:])
    else:
        qid = json.loads(start.stdout)["QueryExecutionId"]
        state, _, reason = poll_athena(creds, qid)
        record(
            "athena_role acessa o workgroup marketing_wg sem erro",
            state == "SUCCEEDED",
            f"state={state} {reason}".strip(),
        )

    # primary workgroup denied
    denied = run_as(creds, [
        "athena", "start-query-execution",
        "--query-string", "SELECT 1",
        "--work-group", "primary",
    ])
    combined = (denied.stderr or "") + (denied.stdout or "")
    is_denied = denied.returncode != 0 and (
        "AccessDenied" in combined or "not authorized" in combined.lower()
    )
    record(
        "athena_role NAO consegue acessar outros workgroups",
        is_denied,
        "AccessDenied" if is_denied else f"rc={denied.returncode} {combined.strip()[-200:]}",
    )

    # Named queries performance
    for view in EXPECTED_VIEWS:
        nqid = named_ids.get(view)
        if not nqid:
            record(f"Cada query executa em < 10s [{view}]", False, "named query ausente")
            continue
        try:
            nq = aws_json(["athena", "get-named-query", "--named-query-id", nqid])["NamedQuery"]
            sql = nq["QueryString"]
            t0 = time.time()
            start = run_as(creds, [
                "athena", "start-query-execution",
                "--query-string", sql,
                "--query-execution-context", f"Database={nq['Database']}",
                "--work-group", workgroup,
            ])
            if start.returncode != 0:
                record(f"Cada query executa em < 10s [{view}]", False, start.stderr.strip()[-300:])
                continue
            qid = json.loads(start.stdout)["QueryExecutionId"]
            state, elapsed, reason = poll_athena(creds, qid)
            ok = state == "SUCCEEDED" and elapsed < MAX_QUERY_SECONDS
            record(
                f"Cada query executa em < 10s [{view}]",
                ok,
                f"state={state} elapsed={elapsed:.1f}s {reason}".strip(),
            )
        except Exception as exc:  # noqa: BLE001
            record(f"Cada query executa em < 10s [{view}]", False, str(exc))


def main() -> int:
    print(f"Validando criterios S2-02 (Athena Marketing) regiao={REGION}\n")

    check_views_sql()

    try:
        outputs = tf_outputs()
        workgroup = outputs["athena_workgroup_name"]
        results_location = outputs["athena_results_location"]
        athena_arn = outputs["athena_role_arn"]
    except Exception as exc:  # noqa: BLE001
        record("Terraform outputs do modulo athena", False, str(exc))
        workgroup = "marketing_wg"
        results_location = ""
        athena_arn = ""

    check_workgroup(workgroup, results_location)
    named_ids = check_named_queries(workgroup)
    if athena_arn:
        check_athena_access(athena_arn, workgroup, named_ids)

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
        print(f"\n{failed} criterio(s) FALHARAM.")
        return 1
    print("\nTodos os criterios de aceite do S2-02 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
