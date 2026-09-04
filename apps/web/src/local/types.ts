/** AgentShield 本地控制台类型（对接 Go /v1/*，不是 Control API）。 */

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
}

export interface InventoryCandidate {
  candidate_id: string;
  source_type: string;
  source_locator: string;
  name: string;
  framework: string;
  status: string;
  attributes?: Record<string, string>;
}

export interface InventoryReport {
  generated_at: string;
  home: string;
  platforms: string[];
  candidates: InventoryCandidate[];
  skipped?: string[];
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
  desired_policy_ref?: {
    static_domains_unavailable?: string[];
  };
}

export interface Receipt {
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
