# TRD: Knowify Contacts + Properties Backfill

- `SYNC_ENTITIES` includes `contacts` in FK-safe order immediately after `clients`.
- MCP `_SPEC.contacts` queries `Contacts` fields: `Id`, `ClientId`, `ContactName`, `Email`, `Phone`, `ObjectState`.
- `promote_run` accepts `contacts` and `projects` and promotes in order: clients -> contacts/properties -> items -> invoices -> payments.
- Native contact idempotency uses `contacts.knowify_contact_id` unique per tenant when non-null.
- Native property idempotency uses `(tenant_id, customer_id, normalized street/city/state/zip)` lookup because multiple projects may refer to the same physical property.
