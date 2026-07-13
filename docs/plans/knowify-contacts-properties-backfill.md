# Knowify Contacts + Properties Backfill Plan

1. Extend schema/model with `contacts.knowify_contact_id` for idempotent upserts.
2. Extend MCP spec and sync entity list to include `contacts` after `clients`.
3. Add promotion functions:
   - clients -> synthetic primary contact + fallback property address
   - contacts -> native contacts by Knowify contact id
   - projects -> native properties by customer/address tuple
4. Add tests for MCP spec, sync entity order, contact promotion, property promotion, and rerun idempotency.
5. Build/test locally.
6. Apply migration, deploy job/API image, dry-run production counts, then run backfill/sync.
