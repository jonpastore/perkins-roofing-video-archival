import { BRAND, FONT, Card, Badge, PageTitle } from "../ui";

// Legacy standalone estimate calculator. Superseded by the customer-linked Estimates
// workflow (Sales → Estimates → Quoting): pick a customer, attach a property, record a
// measurement, then build the estimate so it stays linked and reusable in a proposal.
// This page is retained but explicitly marked legacy so nobody mistakes the unattached
// quick calculator for the canonical, customer-attached path. [estimates-consolidation]
export function Estimator() {
  return (
    <main style={{ maxWidth: 720, fontFamily: FONT }}>
      <PageTitle right={<Badge tone="amber">Legacy / unattached calculator</Badge>}>
        Legacy Quick Estimate Calculator
      </PageTitle>

      <Card style={{ marginTop: 16, borderLeft: `4px solid ${BRAND.red}` }}>
        <div style={{ fontWeight: 700, color: BRAND.navyText, fontSize: 15, marginBottom: 8 }}>
          Legacy / unattached calculator
        </div>
        <p style={{ margin: 0, color: BRAND.sub, fontSize: 14, lineHeight: 1.55 }}>
          This is a quick, standalone roof-price calculator kept for reference only.{" "}
          <strong style={{ color: BRAND.navyText }}>It does not create a customer</strong>,
          property, measurement, or a saved estimate — nothing entered here is linked to a
          record or reusable in a proposal.
        </p>
        <p style={{ marginTop: 10, color: BRAND.sub, fontSize: 14, lineHeight: 1.55 }}>
          For a real, customer-linked estimate that flows into a proposal, use the{" "}
          <strong style={{ color: BRAND.navyText }}>Estimates</strong> workflow instead
          (Sales → Estimates): pick a customer, attach a property, record a measurement, then
          build the estimate.
        </p>
      </Card>
    </main>
  );
}
