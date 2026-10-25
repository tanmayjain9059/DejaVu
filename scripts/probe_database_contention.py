#!/usr/bin/env python3
"""Bounded staging probe for PostgreSQL pool wait and transaction-lock contention.

This probe performs read-only SELECTs inside the application's transaction lock.
It can still queue application transactions, so it requires an explicit staging
confirmation and must never be run against production.
"""
from __future__ import annotations

import argparse
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-staging", action="store_true",
                        help="confirm DATABASE_URL points to a disposable/staging PostgreSQL database")
    parser.add_argument("--workers", type=int, default=4, help="concurrent workers (1-20; default: 4)")
    parser.add_argument("--iterations", type=int, default=20, help="transactions per worker (1-1000; default: 20)")
    parser.add_argument("--hold-ms", type=int, default=0,
                        help="optional lock hold time per transaction, for controlled contention tests (0-100 ms)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = os.getenv("DATABASE_URL", "")
    if not args.confirm_staging:
        raise SystemExit("Refusing to run without --confirm-staging.")
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("DATABASE_URL must point to a staging PostgreSQL database.")
    if os.getenv("APP_ENV", "").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production":
        raise SystemExit("Refusing to run when APP_ENV/ENVIRONMENT is production.")
    if not 1 <= args.workers <= 20:
        raise SystemExit("--workers must be between 1 and 20.")
    if not 1 <= args.iterations <= 1000:
        raise SystemExit("--iterations must be between 1 and 1000.")
    if not 0 <= args.hold_ms <= 100:
        raise SystemExit("--hold-ms must be between 0 and 100.")

    from app.core.database import close_database_pool, connect_db

    def sample(_: int) -> float:
        started = time.perf_counter()
        with connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("SELECT 1 AS ready").fetchone()
            if args.hold_ms:
                time.sleep(args.hold_ms / 1000)
        return (time.perf_counter() - started) * 1000

    durations: list[float] = []
    failures = 0
    started = time.perf_counter()
    total = args.workers * args.iterations
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(sample, index) for index in range(total)]
            for future in as_completed(futures):
                try:
                    durations.append(future.result())
                except Exception as exc:
                    failures += 1
                    print(f"transaction failed: {type(exc).__name__}")
    finally:
        close_database_pool()

    elapsed = time.perf_counter() - started
    if not durations:
        raise SystemExit("No transactions succeeded; inspect staging DB connectivity and pool configuration.")
    print("LostLink staging database contention probe (read-only transactions)")
    print(f"workers={args.workers} iterations_per_worker={args.iterations} hold_ms={args.hold_ms}")
    print(f"transactions={total} succeeded={len(durations)} failed={failures}")
    print(f"throughput_ops_per_second={len(durations) / elapsed:.2f}")
    print(f"latency_ms_p50={statistics.median(durations):.2f}")
    print(f"latency_ms_p95={percentile(durations, 0.95):.2f}")
    print(f"latency_ms_max={max(durations):.2f}")
    print("Interpretation: compare runs with the same staging size/configuration; these timings include pool wait and transaction-lock wait.")
    print("This synthetic probe is not a substitute for end-to-end load testing or production traffic measurements.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
