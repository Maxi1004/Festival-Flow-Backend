"""Backfill denormalized crew_members fields required by the talent crew feed."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.firebase import db  # noqa: E402


BATCH_SIZE = 400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing crew_members fields required by /crew/me/feed.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report eligible documents and updates without writing changes.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates in Firestore batches of at most 400 writes.",
    )
    return parser.parse_args()


def first_value(data: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def get_document_data(
    collection_name: str,
    document_id: str,
    cache: dict[tuple[str, str], dict[str, Any] | None],
) -> dict[str, Any] | None:
    cache_key = (collection_name, document_id)
    if cache_key in cache:
        return cache[cache_key]

    try:
        doc = db.collection(collection_name).document(document_id).get()
    except Exception as error:
        print(
            f"[ERROR] Failed to read {collection_name}/{document_id}: {error}",
            file=sys.stderr,
        )
        cache[cache_key] = None
        return None

    if not doc.exists:
        print(f"[WARN] Referenced document not found: {collection_name}/{document_id}")
        cache[cache_key] = None
        return None

    cache[cache_key] = doc.to_dict() or {}
    return cache[cache_key]


def resolve_reference_field(
    *,
    crew_member_id: str,
    data: dict[str, Any],
    updates: dict[str, Any],
    target_field: str,
    source_id_field: str,
    collection_name: str,
    value_fields: tuple[str, ...],
    cache: dict[tuple[str, str], dict[str, Any] | None],
) -> None:
    if data.get(target_field):
        return

    source_id = data.get(source_id_field)
    if not source_id:
        return

    referenced_data = get_document_data(collection_name, str(source_id), cache)
    if referenced_data is None:
        return

    resolved_value = first_value(referenced_data, *value_fields)
    if resolved_value:
        updates[target_field] = resolved_value
        return

    fields = ", ".join(value_fields)
    print(
        f"[WARN] crew_members/{crew_member_id}: cannot set {target_field}; "
        f"{collection_name}/{source_id} has no value in [{fields}]"
    )


def build_updates(
    crew_member_id: str,
    data: dict[str, Any],
    cache: dict[tuple[str, str], dict[str, Any] | None],
) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    if not data.get("talent_uid") and data.get("talent_user_id"):
        updates["talent_uid"] = data["talent_user_id"]

    resolve_reference_field(
        crew_member_id=crew_member_id,
        data=data,
        updates=updates,
        target_field="project_title",
        source_id_field="project_id",
        collection_name="projects",
        value_fields=("title", "name"),
        cache=cache,
    )
    resolve_reference_field(
        crew_member_id=crew_member_id,
        data=data,
        updates=updates,
        target_field="opportunity_title",
        source_id_field="opportunity_id",
        collection_name="opportunities",
        value_fields=("title", "role_needed"),
        cache=cache,
    )
    resolve_reference_field(
        crew_member_id=crew_member_id,
        data=data,
        updates=updates,
        target_field="producer_name",
        source_id_field="producer_uid",
        collection_name="users",
        value_fields=("name", "email"),
        cache=cache,
    )
    return updates


def get_eligible_crew_members():
    eligible_docs = []
    cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    scanned = 0

    for doc in db.collection("crew_members").stream():
        scanned += 1
        data = doc.to_dict() or {}
        updates = build_updates(doc.id, data, cache)
        if updates:
            eligible_docs.append((doc.reference, updates))
            fields = ", ".join(f"{key}={value!r}" for key, value in updates.items())
            print(f"[PLAN] crew_members/{doc.id}: {fields}")

    return eligible_docs, scanned


def apply_backfill(eligible_docs) -> int:
    updated = 0

    for offset in range(0, len(eligible_docs), BATCH_SIZE):
        batch_docs = eligible_docs[offset : offset + BATCH_SIZE]
        batch = db.batch()

        for document_ref, updates in batch_docs:
            batch.update(document_ref, updates)

        batch_number = offset // BATCH_SIZE + 1
        try:
            batch.commit()
        except Exception as error:
            print(f"[ERROR] Batch {batch_number} failed: {error}", file=sys.stderr)
            raise

        updated += len(batch_docs)
        print(
            f"[INFO] Applied batch {batch_number}: "
            f"updated={len(batch_docs)}, total_updated={updated}"
        )

    return updated


def main() -> int:
    args = parse_args()

    try:
        eligible_docs, scanned = get_eligible_crew_members()
    except Exception as error:
        print(f"[ERROR] Failed to scan crew_members: {error}", file=sys.stderr)
        return 1

    print(f"[INFO] Scanned documents: {scanned}")
    print(f"[INFO] Eligible documents: {len(eligible_docs)}")

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
