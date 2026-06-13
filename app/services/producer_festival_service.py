from datetime import date, datetime
import re
import unicodedata

from fastapi import HTTPException

from app.core.firebase import db
from app.core.utils import serialize_date, utc_now_iso
from app.schemas.festival_schema import (
    FestivalProducerResponse,
    FestivalSelectionResponse,
    FestivalStatus,
)


FESTIVALS_COLLECTION = "festivals"
FESTIVAL_SELECTIONS_COLLECTION = "festival_selections"
SELECTED_STATUS = "SELECTED"
REMOVED_STATUS = "REMOVED"


def _normalize_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_key(value) -> str:
    text = unicodedata.normalize("NFKD", _normalize_text(value).lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _normalize_status(value) -> FestivalStatus:
    try:
        return FestivalStatus(_normalize_text(value).upper())
    except ValueError:
        return FestivalStatus.UNKNOWN


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw_value = _normalize_text(value)
    if not raw_value:
        return None

    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw_value[:10], date_format).date()
        except ValueError:
            continue
    return None


def _selection_id(producer_uid: str, festival_id: str) -> str:
    return f"{producer_uid}_{festival_id}"


def _get_selected_festival_ids(producer_uid: str) -> set[str]:
    snapshots = (
        db.collection(FESTIVAL_SELECTIONS_COLLECTION)
        .where("producer_uid", "==", producer_uid)
        .stream()
    )
    return {
        data.get("festival_id")
        for snapshot in snapshots
        if (data := snapshot.to_dict() or {}).get("status") == SELECTED_STATUS
        and data.get("festival_id")
    }


def _serialize_festival(
    festival_id: str,
    data: dict,
    selected_festival_ids: set[str],
) -> FestivalProducerResponse:
    deadline = _parse_date(data.get("deadline"))
    return FestivalProducerResponse(
        id=data.get("id") or festival_id,
        name=_normalize_text(data.get("name")),
        country=_normalize_text(data.get("country")),
        website=_normalize_text(data.get("website")),
        submission_url=_normalize_text(data.get("submission_url")),
        platform=_normalize_text(data.get("platform")),
        opening_date=serialize_date(data.get("opening_date")) or "",
        deadline=serialize_date(data.get("deadline")) or "",
        event_date=serialize_date(data.get("event_date")) or "",
        fee=_normalize_text(data.get("fee")),
        status=_normalize_status(data.get("status")),
        edition_year=_normalize_text(data.get("edition_year")),
        notes=_normalize_text(data.get("notes")),
        source=_normalize_text(data.get("source")) or "excel",
        days_until_deadline=(deadline - date.today()).days if deadline else None,
        selected_by_me=festival_id in selected_festival_ids,
    )


def list_producer_festivals(
    producer_uid: str,
    status: str | None = None,
    country: str | None = None,
    platform: str | None = None,
    search: str | None = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    limit: int = 100,
) -> list[FestivalProducerResponse]:
    requested_status = _normalize_status(status) if status else None
    visible_statuses = (
        {requested_status}
        if requested_status
        else {FestivalStatus.OPEN, FestivalStatus.UPCOMING}
    )
    country_filter = _normalize_key(country)
    platform_filter = _normalize_key(platform)
    search_filter = _normalize_key(search)
    selected_festival_ids = _get_selected_festival_ids(producer_uid)
    items = []

    for snapshot in db.collection(FESTIVALS_COLLECTION).stream():
        data = snapshot.to_dict() or {}
        festival_status = _normalize_status(data.get("status"))
        if festival_status == FestivalStatus.ARCHIVED:
            continue
        if festival_status not in visible_statuses:
            continue
        if country_filter and country_filter not in _normalize_key(data.get("country")):
            continue
        if platform_filter and platform_filter not in _normalize_key(data.get("platform")):
            continue
        if search_filter:
            searchable = " ".join(
                _normalize_key(data.get(field))
                for field in ("name", "country", "platform", "website")
            )
            if search_filter not in searchable:
                continue

        deadline = _parse_date(data.get("deadline"))
        if deadline_from and (deadline is None or deadline < deadline_from):
            continue
        if deadline_to and (deadline is None or deadline > deadline_to):
            continue

        items.append(
            _serialize_festival(snapshot.id, data, selected_festival_ids)
        )

    items.sort(
        key=lambda item: (
            _parse_date(item.deadline) is None,
            _parse_date(item.deadline) or date.max,
            item.name.lower(),
        )
    )
    return items[:limit]


def _serialize_selection(
    selection_id: str,
    selection_data: dict,
    festival_id: str,
    festival_data: dict,
) -> FestivalSelectionResponse:
    return FestivalSelectionResponse(
        id=selection_data.get("id") or selection_id,
        producer_uid=selection_data.get("producer_uid", ""),
        festival_id=festival_id,
        status=selection_data.get("status") or SELECTED_STATUS,
        created_at=serialize_date(selection_data.get("created_at")) or "",
        updated_at=serialize_date(selection_data.get("updated_at")) or "",
        festival=_serialize_festival(festival_id, festival_data, {festival_id}),
    )


def list_festival_selections(producer_uid: str) -> list[FestivalSelectionResponse]:
    snapshots = (
        db.collection(FESTIVAL_SELECTIONS_COLLECTION)
        .where("producer_uid", "==", producer_uid)
        .stream()
    )
    selections = []

    for snapshot in snapshots:
        selection_data = snapshot.to_dict() or {}
        if selection_data.get("status") != SELECTED_STATUS:
            continue

        festival_id = selection_data.get("festival_id")
        if not festival_id:
            continue
        festival_snapshot = db.collection(FESTIVALS_COLLECTION).document(festival_id).get()
        if not festival_snapshot.exists:
            continue

        selections.append(
            _serialize_selection(
                snapshot.id,
                selection_data,
                festival_id,
                festival_snapshot.to_dict() or {},
            )
        )

    selections.sort(
        key=lambda item: (
            _parse_date(item.festival.deadline) is None,
            _parse_date(item.festival.deadline) or date.max,
            item.festival.name.lower(),
        )
    )
    return selections


def select_festival(
    producer_uid: str,
    festival_id: str,
) -> FestivalSelectionResponse:
    festival_snapshot = db.collection(FESTIVALS_COLLECTION).document(festival_id).get()
    if not festival_snapshot.exists:
        raise HTTPException(status_code=404, detail="Festival no encontrado")

    festival_data = festival_snapshot.to_dict() or {}
    festival_status = _normalize_status(festival_data.get("status"))
    if festival_status == FestivalStatus.ARCHIVED:
        raise HTTPException(
            status_code=400,
            detail="No se puede seleccionar un festival archivado",
        )
    if festival_status not in {FestivalStatus.OPEN, FestivalStatus.UPCOMING}:
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden seleccionar festivales OPEN o UPCOMING",
        )

    selection_id = _selection_id(producer_uid, festival_id)
    selection_ref = db.collection(FESTIVAL_SELECTIONS_COLLECTION).document(selection_id)
    selection_snapshot = selection_ref.get()
    existing_data = selection_snapshot.to_dict() or {} if selection_snapshot.exists else {}
    timestamp = utc_now_iso()
    selection_data = {
        "id": selection_id,
        "producer_uid": producer_uid,
        "festival_id": festival_id,
        "status": SELECTED_STATUS,
        "created_at": existing_data.get("created_at") or timestamp,
        "updated_at": timestamp,
    }
    selection_ref.set(selection_data)
    return _serialize_selection(
        selection_id,
        selection_data,
        festival_id,
        festival_data,
    )


def remove_festival_selection(producer_uid: str, festival_id: str) -> None:
    selection_id = _selection_id(producer_uid, festival_id)
    selection_ref = db.collection(FESTIVAL_SELECTIONS_COLLECTION).document(selection_id)
    selection_snapshot = selection_ref.get()
    if not selection_snapshot.exists:
        raise HTTPException(status_code=404, detail="Seleccion de festival no encontrada")

    selection_data = selection_snapshot.to_dict() or {}
    if selection_data.get("producer_uid") != producer_uid:
        raise HTTPException(status_code=404, detail="Seleccion de festival no encontrada")

    selection_ref.set(
        {
            "status": REMOVED_STATUS,
            "updated_at": utc_now_iso(),
        },
        merge=True,
    )
