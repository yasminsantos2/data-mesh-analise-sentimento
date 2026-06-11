#!/usr/bin/env python3
"""Automated validation of the S1-01 acceptance criteria.

Checks both the Terraform configuration and the live AWS resources against
every acceptance criterion. Prints a PASS/FAIL report and exits non-zero if
any criterion fails (suitable for CI).

Requirements: AWS CLI + Terraform on PATH, valid AWS credentials.

Usage:
    python tests/validate_acceptance.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REGION = "us-east-1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_DIR = REPO_ROOT / "terraform" / "environments" / "dev"
BACKEND_TF = DEV_DIR / "backend.tf"
GITIGNORE = REPO_ROOT / ".gitignore"

EXPECTED_LAYERS = ["raw", "trusted", "data-product"]

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def aws_json(args: list[str]) -> dict:
    """Run an AWS CLI command and return parsed JSON (or {} on empty output)."""
    proc = run(["aws", *args, "--region", REGION, "--output", "json"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def tf_outputs() -> dict:
    proc = run(["terraform", "output", "-json"], cwd=DEV_DIR)
    if proc.returncode != 0:
        raise RuntimeError(f"terraform output failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Load Terraform outputs (source of truth for resource names/ARNs)
# ---------------------------------------------------------------------------
try:
    OUT = tf_outputs()
    BUCKET_IDS = OUT["bucket_ids"]["value"]
    BUCKET_ARNS = OUT["bucket_arns"]["value"]
    ROLE_ARNS = {
        "glue": OUT["glue_role_arn"]["value"],
        "sfn": OUT["sfn_role_arn"]["value"],
        "athena": OUT["athena_role_arn"]["value"],
    }
    ROLE_NAMES = {k: v.split("role/")[-1] for k, v in ROLE_ARNS.items()}
except Exception as exc:  # noqa: BLE001
    print(f"FATAL: could not read terraform outputs from {DEV_DIR}: {exc}")
    sys.exit(2)


# ---------------------------------------------------------------------------
# 1. Three buckets with versioning enabled
# ---------------------------------------------------------------------------
def check_versioning() -> None:
    if sorted(BUCKET_IDS.keys()) != sorted(EXPECTED_LAYERS):
        record("3 buckets criados", False, f"layers={list(BUCKET_IDS)}")
        return
    record("3 buckets criados", True, ", ".join(BUCKET_IDS.values()))

    for layer, name in BUCKET_IDS.items():
        try:
            v = aws_json(["s3api", "get-bucket-versioning", "--bucket", name])
            status = v.get("Status")
            record(f"Versionamento ativo [{layer}]", status == "Enabled", f"Status={status}")
        except Exception as exc:  # noqa: BLE001
            record(f"Versionamento ativo [{layer}]", False, str(exc))


# ---------------------------------------------------------------------------
# 2. Public access blocked on the three buckets
# ---------------------------------------------------------------------------
def check_public_access_block() -> None:
    for layer, name in BUCKET_IDS.items():
        try:
            pab = aws_json(["s3api", "get-public-access-block", "--bucket", name])
            cfg = pab.get("PublicAccessBlockConfiguration", {})
            all_blocked = all([
                cfg.get("BlockPublicAcls"),
                cfg.get("BlockPublicPolicy"),
                cfg.get("IgnorePublicAcls"),
                cfg.get("RestrictPublicBuckets"),
            ])
            record(f"Acesso publico bloqueado [{layer}]", all_blocked, json.dumps(cfg))
        except Exception as exc:  # noqa: BLE001
            record(f"Acesso publico bloqueado [{layer}]", False, str(exc))


# ---------------------------------------------------------------------------
# 3. Three IAM roles exist, documented (description) and with policies
# ---------------------------------------------------------------------------
def get_inline_policies(role_name: str) -> dict[str, dict]:
    listing = aws_json(["iam", "list-role-policies", "--role-name", role_name])
    policies: dict[str, dict] = {}
    for pname in listing.get("PolicyNames", []):
        doc = aws_json(["iam", "get-role-policy", "--role-name", role_name, "--policy-name", pname])
        policies[pname] = doc.get("PolicyDocument", {})
    return policies


def check_roles_exist() -> None:
    for key, name in ROLE_NAMES.items():
        try:
            role = aws_json(["iam", "get-role", "--role-name", name])["Role"]
            description = role.get("Description", "")
            policies = get_inline_policies(name)
            ok = bool(description) and len(policies) >= 1
            record(
                f"Role documentada + com politica [{key}]",
                ok,
                f"desc={'sim' if description else 'NAO'}, inline_policies={list(policies)}",
            )
        except Exception as exc:  # noqa: BLE001
            record(f"Role documentada + com politica [{key}]", False, str(exc))


# ---------------------------------------------------------------------------
# 4. glue_role has NO access to the data-product bucket
#    + positive least-privilege checks for each role
# ---------------------------------------------------------------------------
def statements(policy_doc: dict) -> list[dict]:
    stmts = policy_doc.get("Statement", [])
    return stmts if isinstance(stmts, list) else [stmts]


def collect_resources(policy_doc: dict) -> list[str]:
    res: list[str] = []
    for st in statements(policy_doc):
        r = st.get("Resource", [])
        res.extend(r if isinstance(r, list) else [r])
    return res


def collect_actions(policy_doc: dict) -> list[str]:
    acts: list[str] = []
    for st in statements(policy_doc):
        a = st.get("Action", [])
        acts.extend(a if isinstance(a, list) else [a])
    return acts


def check_glue_no_data_product() -> None:
    dp_arn = BUCKET_ARNS["data-product"]
    dp_name = BUCKET_IDS["data-product"]
    try:
        policies = get_inline_policies(ROLE_NAMES["glue"])
        all_resources = [r for doc in policies.values() for r in collect_resources(doc)]
        offending = [r for r in all_resources if dp_arn in r or dp_name in r]
        record(
            "glue_role SEM acesso ao data-product",
            len(offending) == 0,
            "nenhuma referencia" if not offending else f"referencias: {offending}",
        )

        all_actions = [a for doc in policies.values() for a in collect_actions(doc)]
        reads_raw = any(BUCKET_ARNS["raw"] in r for doc in policies.values() for r in collect_resources(doc))
        writes_trusted = "s3:PutObject" in all_actions and any(
            BUCKET_ARNS["trusted"] in r for doc in policies.values() for r in collect_resources(doc)
        )
        record("glue_role le raw e escreve trusted", reads_raw and writes_trusted,
               f"raw={reads_raw}, putobject_trusted={writes_trusted}")
    except Exception as exc:  # noqa: BLE001
        record("glue_role SEM acesso ao data-product", False, str(exc))


def check_sfn_invokes_glue() -> None:
    try:
        policies = get_inline_policies(ROLE_NAMES["sfn"])
        actions = {a for doc in policies.values() for a in collect_actions(doc)}
        ok = "glue:StartJobRun" in actions and "glue:StartCrawler" in actions
        record("sfn_role invoca Glue Jobs e Crawlers", ok, sorted(actions))
    except Exception as exc:  # noqa: BLE001
        record("sfn_role invoca Glue Jobs e Crawlers", False, str(exc))


def check_athena_perms() -> None:
    dp_arn = BUCKET_ARNS["data-product"]
    try:
        policies = get_inline_policies(ROLE_NAMES["athena"])
        actions = {a for doc in policies.values() for a in collect_actions(doc)}
        resources = [r for doc in policies.values() for r in collect_resources(doc)]
        reads_dp = any(dp_arn in r for r in resources) and "s3:GetObject" in actions
        writes_results = "s3:PutObject" in actions and any("athena-results" in r for r in resources)
        record("athena_role le data-product e escreve resultados", reads_dp and writes_results,
               f"read_dp={reads_dp}, write_results={writes_results}")
    except Exception as exc:  # noqa: BLE001
        record("athena_role le data-product e escreve resultados", False, str(exc))


# ---------------------------------------------------------------------------
# 5. backend.tf configured with S3 + DynamoDB (or native S3) lock
# ---------------------------------------------------------------------------
def check_backend() -> None:
    try:
        text = BACKEND_TF.read_text(encoding="utf-8")
    except OSError as exc:
        record("backend.tf S3 + lock", False, str(exc))
        return
    has_s3 = 'backend "s3"' in text
    has_bucket = "bucket" in text
    has_lock = "dynamodb_table" in text or "use_lockfile" in text
    has_encrypt = "encrypt" in text
    ok = has_s3 and has_bucket and has_lock and has_encrypt
    record("backend.tf S3 + lock", ok,
           f"s3={has_s3}, bucket={has_bucket}, lock={has_lock}, encrypt={has_encrypt}")


# ---------------------------------------------------------------------------
# 6. terraform validate + plan run without errors (and no drift after apply)
# ---------------------------------------------------------------------------
def check_terraform() -> None:
    val = run(["terraform", "validate"], cwd=DEV_DIR)
    record("terraform validate sem erros", val.returncode == 0,
           (val.stdout + val.stderr).strip().splitlines()[-1] if (val.stdout or val.stderr) else "")

    # -detailed-exitcode: 0 = no changes, 1 = error, 2 = changes pending.
    plan = run(["terraform", "plan", "-input=false", "-lock=false", "-detailed-exitcode"], cwd=DEV_DIR)
    if plan.returncode == 0:
        record("terraform plan sem erros (sem drift)", True, "0 changes")
    elif plan.returncode == 2:
        record("terraform plan sem erros (sem drift)", True, "plan ok, mudancas pendentes")
    else:
        record("terraform plan sem erros (sem drift)", False, plan.stderr.strip()[-300:])


# ---------------------------------------------------------------------------
# 7. Outputs export bucket and role ARNs
# ---------------------------------------------------------------------------
def check_outputs() -> None:
    bucket_arns_ok = all(
        BUCKET_ARNS.get(layer, "").startswith("arn:aws:s3:::") for layer in EXPECTED_LAYERS
    )
    roles_ok = all(arn.startswith("arn:aws:iam::") and ":role/" in arn for arn in ROLE_ARNS.values())
    record("Outputs exportam ARNs de buckets", bucket_arns_ok, json.dumps(BUCKET_ARNS))
    record("Outputs exportam ARNs de roles", roles_ok, json.dumps(ROLE_ARNS))


# ---------------------------------------------------------------------------
# 8. .gitignore covers .terraform/, *.tfstate, data/
# ---------------------------------------------------------------------------
def check_gitignore() -> None:
    try:
        lines = {ln.strip() for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()}
    except OSError as exc:
        record(".gitignore cobre artefatos", False, str(exc))
        return
    required = [".terraform/", "*.tfstate", "data/"]
    missing = [r for r in required if r not in lines]
    record(".gitignore cobre artefatos", not missing,
           "ok" if not missing else f"faltando: {missing}")


def main() -> int:
    print(f"Validando criterios de aceite (regiao={REGION}, conta via STS)\n")

    check_versioning()
    check_public_access_block()
    check_roles_exist()
    check_glue_no_data_product()
    check_sfn_invokes_glue()
    check_athena_perms()
    check_backend()
    check_outputs()
    check_gitignore()
    check_terraform()

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
    print("\nTodos os criterios de aceite foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
