from __future__ import annotations

import argparse
import sys
import logging
import random
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from open_dive_log import db
from open_dive_log.repositories import buddies, dives, sites

logger = logging.getLogger(__name__)


def _generate_buddy_names(rng: random.Random) -> tuple[str, str]:
    first_names = ["Mia", "Liam", "Noah", "Emma", "Sophia", "Oliver", "Ava", "Ethan"]
    last_names = ["Clark", "Nguyen", "Patel", "Garcia", "Kim", "Lopez", "Brown", "Singh"]
    return rng.choice(first_names), rng.choice(last_names)


def _generate_buddies(conn: sqlite3.Connection, count: int, rng: random.Random) -> list[buddies.Buddy]:
    generated: list[buddies.Buddy] = []
    for _ in range(count):
        first_name, last_name = _generate_buddy_names(rng)
        generated.append(buddies.find_or_create(conn, first_name, last_name))
    return generated


def _random_date(rng: random.Random, start_date: date, end_date: date) -> str:
    delta = end_date - start_date
    return (start_date + timedelta(days=rng.randint(0, delta.days))).isoformat()


def generate_dives(
    *,
    count: int,
    db_path: str | Path,
    seed: int | None = None,
    site_ids: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    force: bool = False,
    skip_confirmation: bool = False,
) -> int:
    """Generate synthetic dives using existing sites from the database."""
    if count <= 0:
        raise ValueError("count must be positive")

    if db_path is None:
        raise ValueError("DB path must be provided")
    
    start_date = date.fromisoformat(date_from) if date_from else date.today() - timedelta(days=365 * 5)
    end_date = date.fromisoformat(date_to) if date_to else date.today()
    if start_date > end_date:
        raise ValueError("date_from must be before or equal to date_to")

    with db.connect(db_path) as conn:
        db.apply_migrations(conn)

        if not force and not dives.is_empty(conn):
            raise ValueError("Dive table is not empty; use --force to overwrite existing data")


        if not skip_confirmation:
            response = input(f"Generate {count} synthetic dives to {db_path}? (y/N): ")
            confirmation_response = ["y", "Y", "yes", "Yes", "YES"]
            if response.lower() not in confirmation_response:
                logger.info("Operation cancelled by user.")
                sys.exit(0)


        rng = random.Random(seed)
        started_at = time.perf_counter()
        logger.info(
            "Starting synthesis: count=%d seed=%s date_range=%s..%s",
            count,
            seed,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        available_sites = sites.list_by_ids(conn, site_ids)
        if not available_sites:
            raise ValueError("No sites available to synthesize dives")

        available_site_ids = [site.id for site in available_sites]

        with conn:
            # Keep the buddy pool small enough to feel repeatable, but large enough to
            # avoid making every generated dive look identical.
            generated_buddies = _generate_buddies(
                conn,
                max(3, min(8, count // 10 + 1)),
                rng,
            )
            for _ in range(count):
                dive_date = _random_date(rng, start_date, end_date)
                dive_time_minutes = rng.randint(20, 60)
                max_depth_m = round(rng.uniform(10.0, 40.0), 1)
                dive_id = dives.create(
                    conn,
                    dive_date=dive_date,
                    dive_time_minutes=dive_time_minutes,
                    max_depth_m=max_depth_m,
                    avg_depth_m=round(max_depth_m * 0.8, 1),
                    notes="Synthetic dive generated for testing",
                )
                dives.attach_sites(conn, dive_id, [rng.choice(available_site_ids)])

                selected_buddy = rng.choice(generated_buddies)
                dives.add_buddy_to_dive(
                    conn,
                    dive_id,
                    selected_buddy.first_name,
                    selected_buddy.last_name,
                    role_id=None,
                )

    elapsed = time.perf_counter() - started_at
    logger.info("Result: created %d dives and %d buddies in %.2fs", count, len(generated_buddies), elapsed)
    return count


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Generate synthetic dives")
    parser.add_argument("count", type=int)
    parser.add_argument("--db", type=str, required=True, help="Path to the SQLite DB")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--site-ids", type=str, default=None, help="Comma-separated site ids")
    parser.add_argument("--from", dest="date_from", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=str, default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Force generation even if it would overwrite existing data")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args(argv)

    site_ids = None
    if args.site_ids:
        site_ids = [int(item) for item in args.site_ids.split(",") if item.strip()]

    generate_dives(
        count=args.count,
        db_path=args.db,
        seed=args.seed,
        site_ids=site_ids,
        date_from=args.date_from,
        date_to=args.date_to,
        force=args.force,
        skip_confirmation=args.yes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())