-- 0054 claims (04 section 5.11; CCR-029, CCR-132; ticket P4-04): the claims Agent 06 extracts
-- and verifies, with Agent 16's final_verdict (final authority, Q5). TENANT, T0+, Std + Mut:
-- org_id, standard tenant RLS (ENABLE + FORCE), grants of a mutable table. Enum columns are text
-- + CHECK with the exact GLOSSARY values (04 section 1 rule 4). citations (also 5.11) is not
-- part of this ticket.
SET LOCAL ROLE amw_owner;

CREATE TABLE claims (
  id uuid PRIMARY KEY,
  org_id uuid NOT NULL REFERENCES organisations (id),
  script_id uuid NOT NULL,
  job_id uuid NOT NULL,
  segment_id text NOT NULL,
  char_start int NOT NULL,
  char_end int NOT NULL,
  quote text NOT NULL,
  normalized_claim text NOT NULL,
  claim_type text NOT NULL CHECK (claim_type IN ('FACTUAL', 'STATISTICAL', 'DEFINITION', 'HISTORICAL_MARKET', 'HYPOTHETICAL_EXAMPLE', 'RECOMMENDATION', 'FORWARD_VIEW', 'PRICE_LEVEL', 'PERFORMANCE_CLAIM', 'TESTIMONIAL', 'PROMOTION', 'QUOTED_THIRD_PARTY', 'PRODUCT_CLAIM', 'COMPARATIVE', 'OPINION')),
  time_reference_kind text NOT NULL CHECK (time_reference_kind IN ('HISTORICAL', 'CURRENT', 'FUTURE', 'TIMELESS', 'UNSPECIFIED')),
  status text NOT NULL CHECK (status IN ('EXTRACTED', 'VERIFIED', 'CONTRADICTED', 'UNVERIFIABLE', 'NEEDS_SUBSTANTIATION', 'SUBSTANTIATED', 'REMOVED')),
  rule_flags jsonb NOT NULL CHECK (jsonb_typeof(rule_flags) = 'array'),
  proposed_verdict text NOT NULL CHECK (proposed_verdict IN ('ALLOWED', 'BLOCKED', 'NEEDS_HUMAN_REVIEW')),
  final_verdict text CHECK (final_verdict IN ('ALLOWED', 'BLOCKED', 'NEEDS_HUMAN_REVIEW')),
  requires_citation boolean NOT NULL,
  substantiation_ref text,
  extracted_by_task_id uuid NOT NULL,
  verified_by_task_id uuid,
  status_reasons text[] CHECK (status_reasons <@ ARRAY['NO_EVIDENCE_CANDIDATES', 'SKIPPED_BY_POLICY', 'QUOTE_NOT_ATTRIBUTABLE', 'NO_CHART_FACTS', 'CHART_PENDING', 'RESTRICTED_NOT_RELEASED', 'CITATION_UNRESOLVABLE', 'LOW_RELIABILITY_ONLY', 'NUMBER_NOT_IN_EVIDENCE', 'EVIDENCE_CONFLICT', 'NO_SCRIPT_CITATION', 'OVERREACH', 'CONTRADICTED_BY_EVIDENCE', 'NOT_FOUND_IN_EVIDENCE', 'MODEL_UNCERTAIN', 'MODEL_REFUSED', 'INJECTED_EVIDENCE_DISCARDED', 'SPAN_INVALID', 'CLAIM_CONFLICT']::text[]),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  row_version int NOT NULL DEFAULT 1,
  UNIQUE (org_id, id),
  -- CCR-029: replay-safe insert key.
  UNIQUE (org_id, script_id, extracted_by_task_id, segment_id, char_start, char_end),
  FOREIGN KEY (org_id, script_id) REFERENCES scripts (org_id, id),
  FOREIGN KEY (org_id, job_id) REFERENCES jobs (org_id, id),
  FOREIGN KEY (org_id, extracted_by_task_id) REFERENCES tasks (org_id, id),
  FOREIGN KEY (org_id, verified_by_task_id) REFERENCES tasks (org_id, id),
  CONSTRAINT claims_span CHECK (char_end > char_start)
);
CREATE INDEX claims_org_script ON claims (org_id, script_id);
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON claims
  FOR EACH ROW EXECUTE FUNCTION amw_touch_updated_at();
SELECT amw_setup_tenant_table('claims', 'mutable');
