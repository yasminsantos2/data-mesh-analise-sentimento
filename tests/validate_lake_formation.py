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
import subprocess
import sys
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


def check_athena_grants() -> None:
    athena = role_arn("athena_role_arn")

    try:
        cust = perms_for_principal(athena, CUSTOMER_DB)
        record("athena_role SELECT em customer_sentiment", "SELECT" in cust,
               f"permissions={cust}")
    except Exception as exc:  # noqa: BLE001
        record("athena_role SELECT em customer_sentiment", False, str(exc))

    try:
        rev = perms_for_principal(athena, REVIEWS_DB)
        record("athena_role DENIED em reviews_trusted (sem grants)", len(rev) == 0,
               "nenhuma permissao" if not rev else f"permissions={rev}")
    except Exception as exc:  # noqa: BLE001
        record("athena_role DENIED em reviews_trusted (sem grants)", False, str(exc))


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
    plan = run(["terraform", "plan", "-input=false", "-lock=false", "-detailed-exitcode"], cwd=DEV_DIR)
    if plan.returncode == 0:
        record("terraform apply idempotente (sem changes)", True, "0 changes")
    elif plan.returncode == 2:
        record("terraform apply idempotente (sem changes)", False, "mudancas pendentes (drift)")
    else:
        record("terraform apply idempotente (sem changes)", False, plan.stderr.strip()[-300:])


def main() -> int:
    print(f"Validando criterios S1-02 (Lake Formation) regiao={REGION}\n")

    check_databases()
    check_iam_allowed_revoked()
    check_athena_grants()
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
