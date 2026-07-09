-- 0022: proposal-accept-page RLS resolver (deepsec H2).
--
-- The public accept page must resolve the owning tenant from an opaque 512-bit
-- accept_token BEFORE any tenant context exists, so it reads the RLS-FORCED
-- `proposals` table with no app.tenant_id set. The original tenant_isolation
-- policy used 1-arg current_setting('app.tenant_id')::int which RAISES on an
-- unset GUC → the accept page 500s under forced RLS.
--
-- Fix (scoped to the proposals table ONLY — the other 28 tenant tables keep their
-- fail-loud 1-arg policies): replace the policy with a 2-arg form (returns NULL,
-- not an error, when the GUC is unset) OR'd with an exact accept_token match,
-- gated on a transaction-local `app.accept_token` GUC that the resolver sets.
--
-- Security: the token is a 512-bit bearer capability, so token-equality is the
-- correct, non-widening grant — a caller must present the exact token to see its
-- one row (no cross-tenant enumeration; USING is NOT `true`). WITH CHECK stays
-- tenant-scoped so the accept WRITE still requires a stamped app.tenant_id (the
-- accept happens in a subsequent tenant-stamped session, not the token session).
-- Idempotent (DROP ... IF EXISTS + CREATE). `app` owns the table (no admin role).

-- NULLIF(..., '') is load-bearing: a custom GUC that was set-then-reset on a
-- POOLED connection reads back as '' (empty string), not NULL, and ''::int raises.
-- The accept-page resolver runs on pooled PlatformSessionLocal connections that may
-- have previously served a tenant-stamped request, so a bare 2-arg current_setting
-- would still 500. NULLIF collapses both never-set (NULL) and reset ('') to NULL.
DROP POLICY IF EXISTS tenant_isolation ON proposals;
CREATE POLICY tenant_isolation ON proposals
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int
        OR (
            NULLIF(current_setting('app.accept_token', true), '') IS NOT NULL
            AND accept_token = current_setting('app.accept_token', true)
        )
    )
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
