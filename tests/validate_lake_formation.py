#!/usr/bin/env python3
"""Automated validation of the S1-02 (Lake Formation) acceptance criteria.

Checks the live AWS Glue Catalog + Lake Formation state against every
acceptance criterion and prints a PASS/FAIL report (exit non-zero on failure).

Requirements: AWS CLI + Terraform on PATH, valid AWS credentials.

Usage:
    python tests/validate_lake_formation.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REGION = "us-east-1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = REPO_ROOT / "terraform" / "environments" / "dev"

REVIEWS_DB = "reviews_trusted"
CUSTOMER_DB = "customer_sentiment"
TABLE = "customer_sentiment_by_age"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def aws_json(args: list[str]) -> dict:
    proc = run(["aws", *args, "--region", REGION, "--output", "json"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def role_arn(name_key: str) -> str:
    out = json.loads(run(["terraform", "output", "-json"], cwd=DEV_DIR).stdout)
    return out[name_key]["value"]


def tf_value(key: str):
    out = json.loads(run(["terraform", "output", "-json"], cwd=DEV_DIR).stdout)
    return out[key]["value"]


def assume_role(arn: str) -> dict:
    """Assume a role and return its temporary credentials as env vars."""
    out = aws_json([
        "sts", "assume-role",
        "--role-arn", arn,
        "--role-session-name", "s1-02-validate",
    ])
    c = out["Credentials"]
    return {
        "AWS_ACCESS_KEY_ID": c["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": c["SecretAccessKey"],
        "AWS_SESSION_TOKEN": c["SessionToken"],
    }


def run_as(creds: dict, args: list[str]) -> subprocess.CompletedProcess:
    """Run an AWS CLI command using the supplied temporary credentials."""
    env = dict(os.environ)
    env.update(creds)
    return subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True, text=True, env=env,
    )


def poll_athena(creds: dict, qid: str, timeout: int = 90) -> tuple[str, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = run_as(creds, ["athena", "get-query-execution", "--query-execution-id", qid])
        if r.returncode != 0:
            return "ERROR", r.stderr.strip()[-200:]
        status = json.loads(r.stdout)["QueryExecution"]["Status"]
        state = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return state, status.get("StateChangeReason", "")
        time.sleep(3)
    return "TIMEOUT", ""


# ---------------------------------------------------------------------------
# 1. Databases visible in the Glue Catalog
# ---------------------------------------------------------------------------
def check_databases() -> None:
    try:
        dbs = aws_json(["glue", "get-databases"])
        names = {d["Name"] for d in dbs.get("DatabaseList", [])}
        for db in (REVIEWS_DB, CUSTOMER_DB):
            record(f"Database visivel no Glue Catalog [{db}]", db in names,
                   "encontrada" if db in names else f"ausente (db={sorted(names)})")
    except Exception as exc:  # noqa: BLE001
        record("Databases visiveis no Glue Catalog", False, str(exc))


# ---------------------------------------------------------------------------
# 2. IAMAllowedPrincipals revoked on both databases
# ---------------------------------------------------------------------------
def iam_allowed_on_db(db: str) -> bool:
    perms = aws_json([
        "lakeformation", "list-permissions",
        "--resource", json.dumps({"Database": {"Name": db}}),
    ])
    for p in perms.get("PrincipalResourcePermissions", []):
        ident = p.get("Principal", {}).get("DataLakePrincipalIdentifier", "")
        if ident == "IAM_ALLOWED_PRINCIPALS":
            return True
    return False


def check_iam_allowed_revoked() -> None:
    for db in (REVIEWS_DB, CUSTOMER_DB):
        try:
            present = iam_allowed_on_db(db)
            record(f"IAMAllowedPrincipals revogado [{db}]", not present,
                   "ausente" if not present else "AINDA presente")
        except Exception as exc:  # noqa: BLE001
            record(f"IAMAllowedPrincipals revogado [{db}]", False, str(exc))


# ---------------------------------------------------------------------------
# 3 + 4. athena_role SELECT on customer_sentiment, DENIED on reviews_trusted
# ---------------------------------------------------------------------------
def perms_for_principal(principal: str, db: str) -> list[str]:
    """Return the LF permissions granted to a principal on a DB's tables."""
    resource = {"Table": {"DatabaseName": db, "TableWildcard": {}}}
    out = aws_json([
        "lakeformation", "list-permissions",
        "--principal", json.dumps({"DataLakePrincipalIdentifier": principal}),
        "--resource", json.dumps(resource),
    ])
    perms: list[str] = []
    for p in out.get("PrincipalResourcePermissions", []):
        if p.get("Principal", {}).get("DataLakePrincipalIdentifier") == principal:
            perms.extend(p.get("Permissions", []))
    return perms


def check_athena_behavioral() -> None:
    """Behavioral test: assume athena_role and exercise real access."""
    athena = role_arn("athena_role_arn")
    try:
        creds = assume_role(athena)
    except Exception as exc:  # noqa: BLE001
        record("Assumir athena_role", False, str(exc))
        return
    record("Assumir athena_role", True, "ok")

    # SELECT OK em customer_sentiment: roda uma query Athena REAL no marketing_wg.
    workgroup = tf_value("athena_workgroup_name")
    sql = 'SELECT count(*) AS n FROM "customer_sentiment"."customer_sentiment_by_age"'
    try:
        start = run_as(creds, [
            "athena", "start-query-execution",
            "--query-string", sql,
            "--query-execution-context", "Database=customer_sentiment",
            "--work-group", workgroup,
        ])
        if start.returncode != 0:
            record("athena_role SELECT OK em customer_sentiment (query real)",
                   False, start.stderr.strip()[-300:])
        else:
            qid = json.loads(start.stdout)["QueryExecutionId"]
            state, reason = poll_athena(creds, qid)
            record("athena_role SELECT OK em customer_sentiment (query real)",
                   state == "SUCCEEDED", f"state={state} {reason}".strip())
    except Exception as exc:  # noqa: BLE001
        record("athena_role SELECT OK em customer_sentiment (query real)", False, str(exc))

    # AccessDeniedException em reviews_trusted: GetDatabase exige a permissao
    # DESCRIBE no Lake Formation. Como athena_role nao tem grant em
    # reviews_trusted (e IAMAllowedPrincipals foi revogado), o LF nega.
    # (get-tables nao serve: o LF filtra o resultado silenciosamente.)
    denied = run_as(creds, ["glue", "get-database", "--name", REVIEWS_DB])
    combined = (denied.stderr or "") + (denied.stdout or "")
    is_denied = denied.returncode != 0 and "AccessDenied" in combined
    record("athena_role AccessDeniedException em reviews_trusted", is_denied,
           "AccessDeniedException" if is_denied else f"rc={denied.returncode} {combined.strip()[-200:]}")


# ---------------------------------------------------------------------------
# 5. glue_role can write to both databases (ALL on both DBs)
# ---------------------------------------------------------------------------
def db_perms_for_principal(principal: str, db: str) -> list[str]:
    out = aws_json([
        "lakeformation", "list-permissions",
        "--principal", json.dumps({"DataLakePrincipalIdentifier": principal}),
        "--resource", json.dumps({"Database": {"Name": db}}),
    ])
    perms: list[str] = []
    for p in out.get("PrincipalResourcePermissions", []):
        if p.get("Principal", {}).get("DataLakePrincipalIdentifier") == principal:
            perms.extend(p.get("Permissions", []))
    return perms


def check_glue_grants() -> None:
    glue = role_arn("glue_role_arn")
    for db in (REVIEWS_DB, CUSTOMER_DB):
        try:
            perms = db_perms_for_principal(glue, db)
            ok = "ALL" in perms or "CREATE_TABLE" in perms
            record(f"glue_role escreve em [{db}]", ok, f"permissions={perms}")
        except Exception as exc:  # noqa: BLE001
            record(f"glue_role escreve em [{db}]", False, str(exc))


# ---------------------------------------------------------------------------
# 6. Table customer_sentiment_by_age with schema and dt partition
# ---------------------------------------------------------------------------
def check_table() -> None:
    try:
        t = aws_json(["glue", "get-table", "--database-name", CUSTOMER_DB, "--name", TABLE])["Table"]
        cols = {c["Name"]: c["Type"] for c in t["StorageDescriptor"]["Columns"]}
        parts = {p["Name"]: p["Type"] for p in t.get("PartitionKeys", [])}
        params = t.get("Parameters", {})

        expected_cols = {
            "age_band": "string",
            "department_name": "string",
            "sentiment": "string",
            "review_count": "int",
            "avg_rating": "double",
        }
        schema_ok = all(cols.get(k) == v for k, v in expected_cols.items())
        record("Tabela: schema correto", schema_ok, f"cols={cols}")

        part_ok = parts.get("dt") == "date"
        record("Tabela: particao por dt (date)", part_ok, f"partitions={parts}")

        serde = t["StorageDescriptor"].get("SerdeInfo", {}).get("SerializationLibrary", "")
        record("Tabela: formato Parquet", "parquet" in serde.lower(), serde)

        params_ok = (
            params.get("owner") == "data-team"
            and params.get("sla") == "30min"
            and params.get("domain") == "marketing"
        )
        record("Tabela: params owner/sla/domain", params_ok,
               f"owner={params.get('owner')}, sla={params.get('sla')}, domain={params.get('domain')}")
    except Exception as exc:  # noqa: BLE001
        record("Tabela customer_sentiment_by_age", False, str(exc))


# ---------------------------------------------------------------------------
# 7. terraform apply idempotent (no changes on a fresh plan)
# ---------------------------------------------------------------------------
def check_idempotent() -> None:
    # Scoped to the lake_formation module: the global plan would also show the
    # Glue jobs/crawler that AWS is currently blocking at the account level,
    # which is unrelated to S1-02 drift.
    plan = run([
        "terraform", "plan", "-input=false", "-lock=false",
        "-detailed-exitcode", "-target=module.lake_formation",
    ], cwd=DEV_DIR)
    if plan.returncode == 0:
        record("terraform apply idempotente (lake_formation sem changes)", True, "0 changes")
    elif plan.returncode == 2:
        record("terraform apply idempotente (lake_formation sem changes)", False, "mudancas pendentes (drift)")
    else:
        record("terraform apply idempotente (lake_formation sem changes)", False, plan.stderr.strip()[-300:])


def main() -> int:
    print(f"Validando criterios S1-02 (Lake Formation) regiao={REGION}\n")

    check_databases()
    check_iam_allowed_revoked()
    check_athena_behavioral()
    check_glue_grants()
    check_table()
    check_idempotent()

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
    print("\nTodos os criterios de aceite do S1-02 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
