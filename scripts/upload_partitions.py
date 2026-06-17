#!/usr/bin/env python3
"""S1-04 - Particiona o CSV de reviews em lotes de ~100 linhas e envia ao S3 raw.

Le o CSV de reviews, divide em lotes de `--batch-size` linhas (default 100),
atribui uma data sequencial a cada lote a partir de `--start-date` (simulando
N dias de ingestao) e envia cada lote para:

    s3://{bucket}/{prefix}dt=YYYY-MM-DD/batch_{NNN:03d}.csv

E idempotente: antes de cada upload verifica via head_object se o objeto ja
existe; se existir, ignora (nao duplica nem sobrescreve).

Exemplos:
    python scripts/upload_partitions.py --bucket data-mesh-sentimento-dev-raw-082846230365
    python scripts/upload_partitions.py --bucket meu-bucket --start-date 2024-03-01
    python scripts/upload_partitions.py --bucket meu-bucket --prefix reviews/ --csv "data/Womens Clothing E-Commerce Reviews.csv"
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "data" / "Womens Clothing E-Commerce Reviews.csv"
DEFAULT_PREFIX = "reviews/"
DEFAULT_START_DATE = "2024-01-01"
DEFAULT_BATCH_SIZE = 100


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Particiona o CSV de reviews em lotes diarios e envia ao S3 raw.",
    )
    parser.add_argument("--bucket", required=True, help="Bucket S3 de destino (raw).")
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"Prefixo no bucket (default: {DEFAULT_PREFIX}).",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help=f"Data inicial YYYY-MM-DD (default: {DEFAULT_START_DATE}).",
    )
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help="Caminho do CSV de entrada (default: data/Womens Clothing E-Commerce Reviews.csv).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Linhas por lote/particao (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Regiao AWS (default: usa a configuracao do ambiente).",
    )
    return parser.parse_args(argv)


def normalize_prefix(prefix: str) -> str:
    """Garante que o prefixo termine com '/' e nao comece com '/'."""
    prefix = prefix.strip().lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def parse_start_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"--start-date invalido '{value}': use o formato YYYY-MM-DD") from exc


def object_exists(s3, bucket: str, key: str) -> bool:
    """Retorna True se o objeto ja existe no S3 (idempotencia)."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def chunk_dataframe(df: pd.DataFrame, batch_size: int):
    """Gera (indice_0based, sub_dataframe) para cada lote de `batch_size` linhas."""
    for i in range(0, len(df), batch_size):
        yield i // batch_size, df.iloc[i : i + batch_size]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERRO: CSV nao encontrado em '{csv_path}'.")
        print("Coloque o arquivo em data/ (nao versionado) ou informe --csv.")
        return 2

    prefix = normalize_prefix(args.prefix)
    start_date = parse_start_date(args.start_date)

    print(f"Lendo {csv_path} ...")
    df = pd.read_csv(csv_path)
    total_rows = len(df)
    num_batches = (total_rows + args.batch_size - 1) // args.batch_size  # ceil
    end_date = start_date + timedelta(days=num_batches - 1)
    print(
        f"{total_rows} linhas -> {num_batches} lotes de ate {args.batch_size} linhas "
        f"(dt {start_date.isoformat()} .. {end_date.isoformat()})"
    )

    session = boto3.session.Session(region_name=args.region)
    s3 = session.client("s3")

    sent = ignored = errors = 0

    for idx, chunk in tqdm(
        chunk_dataframe(df, args.batch_size),
        total=num_batches,
        desc="Upload particoes",
        unit="lote",
    ):
        dt = (start_date + timedelta(days=idx)).isoformat()
        key = f"{prefix}dt={dt}/batch_{idx + 1:03d}.csv"
        try:
            if object_exists(s3, args.bucket, key):
                ignored += 1
                continue
            buffer = StringIO()
            chunk.to_csv(buffer, index=False)
            s3.put_object(
                Bucket=args.bucket,
                Key=key,
                Body=buffer.getvalue().encode("utf-8"),
                ContentType="text/csv",
            )
            sent += 1
        except ClientError as exc:
            errors += 1
            tqdm.write(f"ERRO em s3://{args.bucket}/{key}: {exc}")

    print("\n=========== RESUMO ===========")
    print(f"Enviados : {sent}")
    print(f"Ignorados: {ignored} (ja existiam)")
    print(f"Erros    : {errors}")
    print(f"Total    : {num_batches} lotes")
    print("==============================")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
