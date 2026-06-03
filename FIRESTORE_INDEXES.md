# Firestore indexes

The project collaboration endpoints query the following collections:

| Collection | Fields | Purpose |
| --- | --- | --- |
| `crew_members` | `project_id ASC`, `status ASC` | List only active or accepted members for the selected project, including lowercase legacy status variants. |
| `crew_project_messages` | `project_id ASC`, `created_at DESC` | Fetch the latest 50 group messages efficiently. |
| `crew_direct_messages` | `conversation_key ASC`, `created_at DESC` | Fetch the latest 50 direct messages efficiently. |
| `crew_messages` | `crew_member_id ASC`, `created_at DESC` | Fetch the latest 50 legacy producer-talent messages when opening a conversation. |

These are composite indexes. Responses are sorted ascending by `created_at` after
fetching the latest documents. The team chat HTTP 500 was caused by its missing
`crew_project_messages(project_id, created_at)` index; that index has already been
created in Firestore.

No backfill is required for the new message collections. Existing `crew_members`
documents need a populated `project_id` to participate in project collaboration.

## Unified message inbox

The `crew_conversations` collection stores lightweight conversation summaries for
`GET /messages/me/conversations`. Documents are updated when a message is posted
through legacy producer-talent chat, project direct messages, or project team chat.

Each summary includes:

```text
id
type
transport
project_id
participant_uids
last_message
last_message_at
updated_at
```

Firestore must keep its default single-field array index for:

```text
crew_conversations:
  participant_uids ARRAY_CONTAINS
```

Existing legacy conversations remain visible from `crew_members` without reading
their message histories. A backfill is optional if historical `last_message`
previews from legacy, team, or project direct histories must appear immediately;
otherwise summaries are populated on the next message.

## Team chat settings

The `crew_project_chat_settings` collection stores one document per `project_id`:

```text
project_id
name
photo_url
updated_by
updated_at
```

Conversation feeds read these documents by ID to display the custom team name and
photo. No composite index is required.

New clients upload team photos through:

```text
POST /messages/me/conversations/{conversation_id}/team-photo
multipart/form-data field: file
```

Cloudinary stores the image at:

```text
FestivalFlow/projects/{project_id}/team-chat/group-photo
```

Any active or accepted project member may update the team photo. Only the project
owner producer may change the team name.

The `photo_url` field in
`PATCH /messages/me/conversations/{conversation_id}/team-settings` is deprecated
and rejected. Team photos must be uploaded through Cloudinary using `team-photo`.
