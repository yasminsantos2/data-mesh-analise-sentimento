#!/usr/bin/env python3
"""Validacao automatizada dos criterios de aceite do S1-04 (upload_partitions.py).

Exercita scripts/upload_partitions.py de ponta a ponta usando:
  - um CSV sintetico de 23.486 linhas (mesmo tamanho do dataset real), e
  - um cliente S3 FAKE em memoria (sem AWS, sem dependencias extras),

de modo que os 7 criterios de aceite sao verificados de forma deterministica
sem precisar do CSV do Kaggle nem tocar em um bucket real.

Uso:
    python tests/validate_s1_04.py
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "upload_partitions.py"
TOTAL_ROWS = 23486
BATCH_SIZE = 100
EXPECTED_BATCHES = 235  # ceil(23486 / 100)
START_DATE = "2024-01-01"
# 235 lotes sequenciais a partir de 2024-01-01 terminam em 2024-08-22.
# (O ticket cita "ate 2024-08-23", mas 2024-01-01 + 234 dias = 2024-08-22;
#  para chegar a 2024-08-23 seriam 236 lotes, conflitando com ceil(23486/100)=235.
#  Mantemos o invariante real: 235 particoes sequenciais sem gaps.)
EXPECTED_END_DATE = "2024-08-22"
BUCKET = "fake-raw-bucket"
PREFIX = "reviews/"

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))


# ---------------------------------------------------------------------------
# Importa o script alvo como modulo
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("upload_partitions", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Cliente S3 fake em memoria (subconjunto usado pelo script)
# ---------------------------------------------------------------------------
class FakeClientError(Exception):
    def __init__(self, code: str):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class FakeS3:
    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.put_calls = 0
        self.head_calls = 0

    def head_object(self, Bucket: str, Key: str):  # noqa: N803
        self.head_calls += 1
        if (Bucket, Key) not in [(Bucket, k) for k in self.store if k == Key]:
            if Key not in self.store:
                raise FakeClientError("404")
        return {"ContentLength": len(self.store[Key])}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kwargs):  # noqa: N803
        self.put_calls += 1
        self.store[Key] = Body


def make_csv(path: Path, rows: int) -> None:
    df = pd.DataFrame(
        {
            "Clothing ID": range(1000, 1000 + rows),
            "Age": [20 + (i % 60) for i in range(rows)],
            "Review Text": [f"review {i}" for i in range(rows)],
            "Rating": [(i % 5) + 1 for i in range(rows)],
            "Recommended IND": [i % 2 for i in range(rows)],
            "Department Name": ["Tops", "Dresses", "Bottoms", "Intimate"][0:1] * rows,
        }
    )
    df.to_csv(path, index=False)


def run_script(fake: FakeS3, csv_path: Path, start_date: str = START_DATE) -> None:
    """Patcha boto3 para devolver o FakeS3 e roda o main do script."""
    orig_session = mod.boto3.session.Session
    orig_clienterror = mod.ClientError

    class _Sess:
        def __init__(self, *a, **k):
            pass

        def client(self, *a, **k):
            return fake

    mod.boto3.session.Session = _Sess  # type: ignore[assignment]
    mod.ClientError = FakeClientError  # type: ignore[assignment]
    try:
        mod.main([
            "--bucket", BUCKET,
            "--prefix", PREFIX,
            "--start-date", start_date,
            "--csv", str(csv_path),
            "--batch-size", str(BATCH_SIZE),
        ])
    finally:
        mod.boto3.session.Session = orig_session
        mod.ClientError = orig_clienterror


def main() -> int:
    print("Validando criterios de aceite S1-04 (upload_partitions.py)\n")

    with TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "reviews.csv"
        make_csv(csv_path, TOTAL_ROWS)

        # 1a execucao
        fake = FakeS3()
        run_script(fake, csv_path)
        keys = sorted(fake.store.keys())

        # 1. 235 particoes com estrutura correta
        structure_ok = all(
            k.startswith(f"{PREFIX}dt=") and "/batch_" in k and k.endswith(".csv")
            for k in keys
        )
        record(
            "235 particoes no S3 raw com estrutura correta",
            len(keys) == EXPECTED_BATCHES and structure_ok,
            f"{len(keys)} objetos; exemplo={keys[0] if keys else 'n/a'}",
        )

        # 2. Cada particao com no maximo 100 linhas (linhas de dados, sem header)
        max_rows = 0
        for body in fake.store.values():
            n = body.decode("utf-8").strip().count("\n")  # linhas de dados (header nao tem \n final extra)
            max_rows = max(max_rows, n)
        record(
            "Cada particao com no maximo 100 linhas",
            max_rows <= BATCH_SIZE,
            f"max linhas de dados por lote={max_rows}",
        )

        # 3. Datas de 2024-01-01 ate 2024-08-23 sem gaps
        dts = sorted({k.split("dt=")[1].split("/")[0] for k in keys})
        start = date.fromisoformat(START_DATE)
        expected_dts = [(start + timedelta(days=i)).isoformat() for i in range(EXPECTED_BATCHES)]
        no_gaps = dts == expected_dts
        record(
            "Datas sequenciais a partir de 2024-01-01 sem gaps (235 dias)",
            no_gaps and dts[-1] == EXPECTED_END_DATE,
            f"primeira={dts[0]}, ultima={dts[-1]} (ticket cita 08-23; 235 lotes => 08-22), total_dias={len(dts)}",
        )

        # 4. Re-executar nao duplica nem sobrescreve (idempotencia)
        objs_before = dict(fake.store)
        put_after_first = fake.put_calls
        run_script(fake, csv_path)  # 2a execucao
        no_dup = len(fake.store) == EXPECTED_BATCHES
        no_overwrite = fake.store == objs_before
        no_new_puts = fake.put_calls == put_after_first
        record(
            "Re-executar nao duplica nem sobrescreve particoes",
            no_dup and no_overwrite and no_new_puts,
            f"objetos={len(fake.store)}, puts_2a_exec={fake.put_calls - put_after_first}",
        )

    # 5. Log exibe enviados / ignorados / erros  (inspeciona a fonte do resumo)
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    log_ok = all(tok in src for tok in ("Enviados", "Ignorados", "Erros"))
    record("Log exibe enviados / ignorados / erros", log_ok,
           "resumo imprime os 3 contadores")

    # 6. --start-date funciona para offset de datas
    with TemporaryDirectory() as tmp2:
        csv2 = Path(tmp2) / "reviews.csv"
        make_csv(csv2, 250)  # 3 lotes, rapido
        fake2 = FakeS3()
        run_script(fake2, csv2, start_date="2024-03-10")
        dts2 = sorted({k.split("dt=")[1].split("/")[0] for k in fake2.store})
        offset_ok = dts2 == ["2024-03-10", "2024-03-11", "2024-03-12"]
        record("--start-date funciona para offset de datas", offset_ok,
               f"dts={dts2}")

    # 7. data/ consta no .gitignore
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    record("data/ consta no .gitignore", "data/" in gi.splitlines(),
           "presente" if "data/" in gi.splitlines() else "ausente")

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
    print("\nTodos os criterios de aceite do S1-04 foram atendidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
