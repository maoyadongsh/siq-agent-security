/** siq-agent-security 本地控制台类型（对接 Go /v1/*，不是 Control API）。 */

export interface PlatformInfo {
  name: string;
  detected: boolean;
  adapter: string;
  tier: string;
  note: string;
}

export interface ChainHead {
  id: string;
  head_seq: number;
  head_hash: string;
}

export interface Status {
  version: string;
  enforcement_mode: string;
  local_mode: boolean;
  single_user: boolean;
  rulepack_version: number;
  signing_public_key: string;
  chain: ChainHead;
  platforms: PlatformInfo[];
}

export interface UiBoot {
  version: string;
  enforcement_mode: string;
  local_mode: boolean;
  single_user: boolean;
  trust_profile?: string;
  pairing_required?: boolean;
}

export interface Finding {
  finding_id: string;
  rule_id: string;
  category: string;
  severity: string;
  disposition: string;
  location?: { path?: string; line?: number | null };
}

export interface Admission {
  admission_id: string;
  skill_id: string;
  skill_name: string;
  verdict: string;
  decided_at: string;
  content_hash: string;
  source: { type: string; locator: string; trust_level: string };
  findings?: Finding[];
}

export interface Overlap {
  domain: string;
  fact_ids: string[];
  resolution: string;
  note?: string | null;
}

export interface GrantFact {
  fact_id: string;
  domain: string;
  action: string;
  state: string;
  effect: string;
  resource: { type: string; value: string };
}

export interface Grant {
  grant_id: string;
  admission_id: string;
  platform: string;
  status: string;
  subject: { type: string; id: string };
  overlap_conflicts?: Overlap[];
  facts?: GrantFact[];
  enforcement_mode: string;
  created_at: string;
  /** Disk version seq from GET/POST responses; required for mutate CAS. */
  state_revision?: number;
  desired_policy_ref?: {
    static_domains_unavailable?: string[];
  };
}

export interface Receipt {
  authority_status?: "valid" | "invalid" | "unbound_legacy";
  context_assertion_id?: string;
  authority_reason_code?: string;
  policy_action?: "allow" | "deny" | "hold" | "redact";
  effective_action?: "allow" | "deny" | "hold" | "redact";
  record_type?: 'decision' | 'observation' | 'hold_resolution';
  decision_receipt_id?: string;
  action_id?: string;
  parent_action_id?: string;
  task_seq?: number;
  task_id?: string;
  intent_id?: string;
  intent_digest?: string;
  intent_binding?: 'bound' | 'unbound';
  authority_revision?: string;
  principal?: { type: 'user'; id: string };
  resource_refs?: { domain: 'filesystem' | 'network' | 'message'; digest: string }[];
  provenance_refs?: string[];
  operation?: string;
  effects?: string[];
  reason_code?: string;
  receipt_id: string;
  seq: number;
  issued_at: string;
  platform: string;
  session_id: string;
  tool: string;
  action: string;
  advisory_action?: string | null;
  reason: string;
  hash: string;
  taint_labels?: string[];
}

export interface AdapterResult {
  platform: string;
  action: string;
  paths?: string[];
  note?: string;
}

export interface LedgerAsset {
  id: string;
  name: string;
  framework: string;
  source_type: string;
  source_locator: string;
  status: string;
  admission_id?: string;
  admission_verdict?: string;
  grant_id?: string;
  grant_status?: string;
  declared_tools?: string[];
  evidence_ids: string[];
  admit_path?: string;
  content_hash?: string;
  attributes?: Record<string, string>;
  updated_at?: string;
  dismiss_reason?: string;
  dismiss_until?: string;
  hook_lost?: boolean;
  actor_id?: string;
}

export interface LedgerEvidence {
  evidence_id: string;
  source_type: string;
  source_locator: string;
  collected_at?: string;
  content_hash?: string;
  classification?: string;
}

export interface LedgerAssetDetail extends LedgerAsset {
  evidence?: LedgerEvidence[];
  admission?: Admission;
  grants?: Grant[];
}

export interface LedgerOverview {
  assets: number;
  unadmitted_skills: number;
  open_findings: number;
  recent_denies: number;
  grants_deployed: number;
}

export interface PermissionFact {
  fact_id: string;
  subject_type: string;
  subject_id: string;
  domain: string;
  action: string;
  resource_type: string;
  resource_value: string;
  effect: string;
  state: string;
  authority: string;
  authority_revision?: string | null;
  evidence_ids?: string[];
  source: string;
  grant_id?: string;
  grant_status?: string;
  receipt_id?: string;
  admission_id?: string;
}

export interface LedgerFinding {
  finding_id: string;
  rule_id: string;
  category: string;
  severity: string;
  disposition: string;
  status: string;
  admission_id: string;
  skill_name: string;
  path?: string;
  line?: number | null;
  excerpt?: string | null;
  evidence_ids?: string[];
  source?: string;
  subject_ref?: string;
  accept_reason?: string;
  accept_until?: string;
}
