# Event Types — Author's Guide

Every detection category in this product is defined by a single YAML file under
`config/event-types/`. Dropping a new YAML file and restarting the openclaw
container is enough to add a new detection category — no code changes required.

## File layout

```yaml
id:   <integer, see "ID ranges" below>
key:  <snake_case, globally unique>
name: <display name, any language>
description: <short one-liner>
version: 1
enabled: true

classes:
  - id: 0
    key: <snake_case>
    label: <display label>

vlm:
  max_frames: 8
  max_tokens: 800
  prefill: '{"class":"'
  prompt: |
    <the instruction you want the VLM to follow>

output_guards:
  enforce_json: true
  no_thinking_leak: true
  description_length: [20, 150]

notifications:
  severity: high | medium | low | critical
  throttle_seconds: 60
  default_channels: [line]
```

The full JSON Schema lives at [`schemas/event-type.schema.json`](../schemas/event-type.schema.json)
and is validated at container start.

## ID ranges

| Range | Who owns it |
|---|---|
| `1–99` | Reserved for AiUnion built-in types. Do not reuse. |
| `100–999` | Customer-defined types. **Choose an ID not already used in your deployment.** |
| `1000+` | Third-party plugin marketplace (future). |

**The `id` and each `classes[].id` are persisted in MongoDB and must not be
renumbered after any real events have been recorded.** Change the name/label
freely; change the IDs never.

## Prompt authoring tips

1. **Always state the required JSON output format first.** Qwen family models
   are notably better when the format appears early in the prompt.
2. **Forbid prose ("不可寫分析步驟")** — thinking-style models will otherwise
   put their reasoning inside the `description` field.
3. **Provide one worked example** of the expected `description` text.
4. **Keep descriptions 30–70 characters.** Longer descriptions tend to drift
   into bullet lists or numbered steps.
5. **Never ask the model to write markdown.** The downstream LINE renderer
   does not parse it and the leading `*` will look like a typo.

## Adding a customer-defined type — example

File: `config/event-types/company_x_ppe.yaml`

```yaml
id: 150
key: ppe_violation
name: PPE 違規
description: 工地內員工未依規定穿戴個人防護裝備。
version: 1
enabled: true

classes:
  - id: 0
    key: no_helmet
    label: 未戴安全帽
  - id: 1
    key: no_vest
    label: 未穿反光背心

vlm:
  max_frames: 8
  max_tokens: 600
  prefill: '{"class":"'
  prompt: |
    請判斷畫面中是否有人員未依規定穿戴個人防護裝備。
    只輸出 JSON,格式:{"class":"no_helmet" 或 "no_vest","description":"..."}。
    description 單段、30 到 70 字、不要條列、不要寫推理過程,
    例如「畫面中可見一名作業人員在施工區內未佩戴安全帽,研判為未戴安全帽違規。」

output_guards:
  enforce_json: true
  no_thinking_leak: true
  description_length: [20, 120]

notifications:
  severity: medium
  throttle_seconds: 120
  default_channels: [line]
```

Apply:

```bash
docker compose restart openclaw
```

Validate:

```bash
docker compose exec openclaw fpg-list-event-types
# ... ppe_violation [150] ok
```

## Upgrading an existing type

- You may change `name`, `description`, `label`, `prompt`, `max_frames`,
  `max_tokens`, `output_guards`, `notifications` freely.
- You may **add** a new class (pick an unused `id` within that type).
- You may **disable** a type (`enabled: false`) — existing events stay, but no
  new detections run.
- You may NOT change `id` or any existing `classes[].id`.
- Bump `version:` when you make a semantically meaningful change; this will be
  surfaced in the admin UI (Phase 3).

## Limitations (current)

- The VLM model is shared across all event types; per-type model override
  (`vlm.model`) is accepted by the schema but not yet honored at runtime.
- `output_guards.description_length` is enforced only on the final stage; the
  VLM is still allowed to overshoot, in which case the description is
  truncated with a trailing ellipsis.
- No per-type RBAC yet — any operator who can reach the LINE channel can
  receive any event type's notifications.

These gaps close in Phase 3 (admin UI + RBAC) and Phase 4 (plugin system).
