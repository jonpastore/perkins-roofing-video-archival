# Perkins revenue command center prototype

Disposable mock-data prototype for the UX decision package. It has no production routes, APIs, authentication or external dependencies.

Run locally from the repository root:

```bash
python3 -m http.server 4173
```

Open `http://127.0.0.1:4173/.ux-review/prototype/`. The prototype reads the existing `web/public/perkins-logo.png`; it does not replace or copy the Perkins logo.

Selective capability-preservation prototypes:

- `estimate-workspace.html` — preserves the complex customer/property, measurement, pricing and proposal-preparation workflow.
- `platform-operations.html` — preserves restricted readiness, integration, diagnostics, audit and remediation capabilities outside the branch operating home.

Representative states:

- Branch manager, salesperson mobile and corporate portfolio scenarios
- Prioritized revenue-risk queue
- Customer/property context and activity timeline
- Async human-attempt logging simulation
- Dense, loading, empty, integration-error and long-content panels
