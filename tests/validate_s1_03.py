#!/usr/bin/env python3
"""Automated validation of the S1-03 (Glue Jobs) acceptance criteria.

The Glue runtime is currently blocked at the AWS account level (CreateJob /
CreateCrawler return "Account is denied access"), so the data-correctness
criteria are validated by running the SAME business rules (glue_jobs/transforms.py)
over a 100-review batch locally with pandas, reproducing the job_clean and
job_agg pipelines. Provisioning criteria are checked against S3 / Terraform.

Usage:
    python tests/validate_s1_03.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
GLUE_JOBS = REPO_ROOT / "glue_jobs"
DEV_DIR = REPO_ROOT / "terraform" / "environments" / "dev"
REGION = "us-east-1"
DT = "2024-01-01"

sys.path.insert(0, str(GLUE_JOBS))
from transforms import age_band, sentiment, to_snake_case  # noqa: E402

AGE_BANDS = {"Jovem", "Adulto", "Madura", "Sênior"}
AGG_COLUMNS = ["age_band", "department_name", "sentiment", "review_count", "avg_rating", "dt"]

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Sample data: 100 reviews using the raw CSV header style (Title Case w/ spaces)
# ---------------------------------------------------------------------------
def make_sample_reviews(n: int = 100) -> pd.DataFrame:
    ages = [22, 35, 52, 68]          # one per age_band
    departments = ["Tops", "Dresses", "Bottoms", "Intimate"]
    rows = []
    for i in range(n):
        age = ages[i % 4]
        rating = (i % 5) + 1          # 1..5
        rec = i % 2                   # 0/1
        # ~10% of rows have empty review text -> must be dropped by job_clean.
        text = "" if i % 10 == 0 else f"review number {i}"
        rows.append({
            "Clothing ID": 1000 + i,
            "Age": age,
            "Title": f"title {i}",
            "Review Text": text,
            "Rating": rating,
            "Recommended IND": rec,
            "Division Name": "General",
            "Department Name": departments[i % 4],
            "Class Name": "Knits",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Pipelines reproducing job_clean / job_agg using the shared rules.
# ---------------------------------------------------------------------------
def run_job_clean(raw: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    df = raw.rename(columns={c: to_snake_case(c) for c in raw.columns})
    df = df[df["review_text"].notna() & (df["review_text"].astype(str).str.strip() != "")]
    df = df.copy()
    df["age_band"] = df["age"].apply(age_band)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "part-0000.snappy.parquet", compression="snappy", index=False)
    return df


def run_job_agg(trusted_dir: Path, out_dir: Path, dt: str) -> pd.DataFrame:
    df = pd.read_parquet(trusted_dir)
    df = df.copy()
    df["sentiment"] = df.apply(lambda r: sentiment(r["rating"], r["recommended_ind"]), axis=1)
    df = df[df["age_band"].notna() & df["department_name"].notna()]
    agg = (
        df.groupby(["age_band", "department_name", "sentiment"], dropna=False)
        .agg(review_count=("rating", "size"), avg_rating=("rating", "mean"))
        .reset_index()
    )
    agg["review_count"] = agg["review_count"].astype("int32")
    agg["avg_rating"] = agg["avg_rating"].astype(float).round(2)
    agg["dt"] = dt
    agg = agg[AGG_COLUMNS]
    out_dir.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(out_dir / "part-0000.parquet", index=False)
    return agg


def check_data_pipeline() -> None:
    raw = make_sample_reviews(100)

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        trusted = tmp_path / "trusted" / "reviews_clean" / f"dt={DT}"
        product = tmp_path / "product" / "customer_sentiment_by_age" / f"dt={DT}"

        t0 = time.time()
        clean = run_job_clean(raw, trusted)
        agg = run_job_agg(trusted, product, DT)
        elapsed = time.time() - t0

        # 1. job_clean grava Parquet em trusted com age_band (4 categorias).
        clean_parquet = list(trusted.glob("*.parquet"))
        bands = set(clean[clean["age_band"].notna()]["age_band"].unique())
        record(
            "job_clean grava Parquet em trusted com age_band (4 categorias)",
            bool(clean_parquet) and "age_band" in clean.columns and bands == AGE_BANDS,
            f"parquet={len(clean_parquet)} arquivo(s), bands={sorted(bands)}",
        )

        # Linhas com review_text vazio removidas (10 das 100).
        record(
            "job_clean remove review_text nulo/vazio",
            len(clean) == 90,
            f"linhas apos limpeza={len(clean)} (esperado 90)",
        )

        # 2. job_agg grava Parquet em data-product com as colunas exatas.
        product_parquet = list(product.glob("*.parquet"))
        cols_ok = list(agg.columns) == AGG_COLUMNS
        record(
            "job_agg grava Parquet em data-product com colunas corretas",
            bool(product_parquet) and cols_ok,
            f"parquet={len(product_parquet)} arquivo(s), colunas={list(agg.columns)}",
        )

        # 4. Nenhum nulo nas colunas de agregação.
        nulls = {c: int(agg[c].isna().sum()) for c in AGG_COLUMNS}
        record(
            "Nenhum nulo nas colunas de agregacao",
            sum(nulls.values()) == 0,
            f"nulos={nulls}",
        )

        # 8. Tempo de processamento para 100 reviews.
        record(
            "Processa lote de 100 reviews em < 5 min (logica local)",
            elapsed < 300,
            f"{elapsed:.3f}s (logica de transformacao; nao inclui cold start do Glue)",
        )

    # 5. Idempotência: reprocessar o mesmo dt produz o mesmo resultado.
    with TemporaryDirectory() as t1, TemporaryDirectory() as t2:
        p1, p2 = Path(t1), Path(t2)
        a1 = run_job_agg_full(raw, p1)
        a2 = run_job_agg_full(raw, p2)
        same = a1.equals(a2)
        record("Jobs idempotentes (reprocessar mesmo dt = mesmo resultado)", same,
               "saidas identicas" if same else "saidas divergentes")


def run_job_agg_full(raw: pd.DataFrame, base: Path) -> pd.DataFrame:
    trusted = base / "trusted" / "reviews_clean" / f"dt={DT}"
    product = base / "product" / "customer_sentiment_by_age" / f"dt={DT}"
    run_job_clean(raw, trusted)
    agg = run_job_agg(trusted, product, DT)
    return agg.sort_values(AGG_COLUMNS).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Regra de sentimento validada com 10 amostras manuais.
# ---------------------------------------------------------------------------
def check_sentiment_samples() -> None:
    samples = [
        (5, 1, "Positivo"), (4, 1, "Positivo"), (5, 0, "Negativo"), (4, 0, "Negativo"),
        (3, 1, "Neutro"), (3, 0, "Neutro"), (2, 1, "Negativo"), (1, 0, "Negativo"),
        (2, 0, "Negativo"), (1, 1, "Negativo"),
    ]
    failures = [(r, rec, exp, sentiment(r, rec)) for r, rec, exp in samples if sentiment(r, rec) != exp]
    record("Regra de sentimento validada com 10 amostras manuais", not failures,
           "10/10 corretas" if not failures else f"falhas={failures}")


# ---------------------------------------------------------------------------
# 7. Scripts uploaded automaticamente para S3 via aws_s3_object.
# ---------------------------------------------------------------------------
def tf_value(key: str):
    out = json.loads(run(["terraform", "output", "-json"], cwd=DEV_DIR).stdout)
    return out[key]["value"]


def check_scripts_in_s3() -> None:
    try:
        trusted_bucket = tf_value("bucket_ids")["trusted"]
    except Exception as exc:  # noqa: BLE001
        record("Scripts uploaded para S3 via aws_s3_object", False, f"terraform output: {exc}")
        return
    keys = ["assets/glue/job_clean.py", "assets/glue/job_agg.py", "assets/glue/transforms.py"]
    missing = []
    for key in keys:
        r = run(["aws", "s3api", "head-object", "--bucket", trusted_bucket, "--key", key, "--region", REGION])
        if r.returncode != 0:
            missing.append(key)
    record("Scripts uploaded para S3 via aws_s3_object", not missing,
           "3/3 scripts no S3" if not missing else f"faltando={missing}")


# ---------------------------------------------------------------------------
# 6. Jobs e crawler provisionados via Terraform.
# ---------------------------------------------------------------------------
def check_jobs_provisioned() -> None:
    state = run(["terraform", "state", "list"], cwd=DEV_DIR).stdout
    has_clean = "module.glue.aws_glue_job.clean" in state
    has_agg = "module.glue.aws_glue_job.agg" in state
    has_crawler = "module.glue.aws_glue_crawler.data_product" in state
    ok = has_clean and has_agg and has_crawler
    record("Jobs e crawler provisionados via Terraform", ok,
           "todos no state" if ok else "BLOQUEADO pela AWS: CreateJob/CreateCrawler 'Account is denied access' "
           "(codigo pronto; abrir caso no AWS Support p/ habilitar Glue)")


def main() -> int:
    print("Validando criterios de aceite S1-03 (Glue Jobs)\n")

    check_data_pipeline()
    check_sentiment_samples()
    check_scripts_in_s3()
    check_jobs_provisioned()

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
        print(f"\n{failed} criterio(s) FALHARAM ou estao BLOQUEADOS (ver detalhe).")
        return 1
    print("\nTodos os criterios de aceite do S1-03 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
