# Knowify Contacts + Properties Backfill Spec

## Why
The sales UI now expects customers to have contacts and properties before estimates/proposals are created. The Knowify MCP mirror currently imports customers, invoices, payments, projects, contracts, and deliverables, but only promotes customers/items/invoices/payments into first-class tables. This leaves historical Knowify customer addresses, project/job-site addresses, and contacts invisible in the production UI.

## What
- Pull Knowify `Contacts` through the MCP transport into the raw mirror.
- Promote Knowify `Contacts` and client primary contact fields into native `contacts`.
- Promote Knowify `Projects` job-site addresses and client billing addresses into native `properties`.
- Keep promotion idempotent so hourly syncs and manual backfills do not duplicate rows.

## Constraints
- Knowify has no populated `Roofs` measurement data for Perkins; do not invent measurements.
- Properties require a street and city before promotion.
- Production writes must be dry-run counted before backfill.
- No PII in logs beyond aggregate counts and source ids in debug/error logs.

## Non-goals
- Roofr measurement import.
- Two-way writes to Knowify.
- Deleting existing local contacts/properties when a Knowify record disappears.
