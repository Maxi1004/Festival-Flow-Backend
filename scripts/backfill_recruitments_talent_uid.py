"""Backfill recruitments.talent_uid from the legacy talent_user_id field."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.firebase import db  # noqa: E402


BATCH_SIZE = 400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing recruitments.talent_uid values from talent_user_id.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report eligible documents without writing changes.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates in Firestore batches.",
    )
    return parser.parse_args()


def get_eligible_recruitments():
    eligible_docs = []
    scanned = 0
    skipped_existing = 0
    skipped_missing_legacy = 0

    for doc in db.collection("recruitments").stream():
        scanned += 1
        data = doc.to_dict() or {}

        if "talent_uid" in data:
            skipped_existing += 1
            continue

        talent_user_id = data.get("talent_user_id")
        if not talent_user_id:
            skipped_missing_legacy += 1
            continue

        eligible_docs.append((doc.reference, talent_user_id))

    return eligible_docs, scanned, skipped_existing, skipped_missing_legacy


def apply_backfill(eligible_docs) -> int:
    updated = 0

    for offset in range(0, len(eligible_docs), BATCH_SIZE):
        batch_docs = eligible_docs[offset : offset + BATCH_SIZE]
        batch = db.batch()

        for document_ref, talent_user_id in batch_docs:
            batch.update(document_ref, {"talent_uid": talent_user_id})

        try:
            batch.commit()
        except Exception as error:
            batch_number = offset // BATCH_SIZE + 1
            print(f"[ERROR] Batch {batch_number} failed: {error}", file=sys.stderr)
            raise

        updated += len(batch_docs)
        print(f"[INFO] Applied batch: updated={len(batch_docs)}, total_updated={updated}")

    return updated


def main() -> int:
    args = parse_args()

    try:
        eligible_docs, scanned, skipped_existing, skipped_missing_legacy = get_eligible_recruitments()
    except Exception as error:
        print(f"[ERROR] Failed to scan recruitments: {error}", file=sys.stderr)
        return 1

    print(f"[INFO] Scanned documents: {scanned}")
    print(f"[INFO] Already normalized, skipped: {skipped_existing}")
    print(f"[INFO] Missing talent_user_id, skipped: {skipped_missing_legacy}")
    print(f"[INFO] Eligible for update: {len(eligible_docs)}")

    if args.dry_run:
        print("[DRY-RUN] No documents were updated.")
        return 0

    if not eligible_docs:
        print("[INFO] No updates required.")
        return 0

    try:
        updated = apply_backfill(eligible_docs)
    except Exception:
        return 1

    print(f"[SUCCESS] Backfill completed. Updated documents: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
