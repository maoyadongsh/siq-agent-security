/** siq-agent-security 本地控制台类型（对接 Go /v1/*，不是 Control API）。 */

export interface PlatformInfo {
  name: string;
  detected: boolean;
  adapter: string;
  tier: string;
  note: string;
  diagnosis?: AdapterDiagnosis;
}

export interface AdapterDiagnosis {
  platform: string;
  configuration_state: 'not_installed' | 'incomplete' | 'ready' | 'needs_verification' | 'unsupported';
  runtime_state: 'unverified';
  checks: { code: string; status: 'pass' | 'fail' | 'unknown' | 'not_applicable'; message: string }[];
  next_steps: string[];
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
  schema_version: 'local-ui-config/v1';
  product: 'siq-agent-security';
  session_recovery: boolean;
  pairing_available: boolean;
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
  excerpt?: string | null;
  location?: { path?: string; line?: number | null };
}

export interface Admission {
  admission_id: string;
  skill_id: string;
  skill_name: string;
  verdict: string;
  decided_at: string;
  content_hash: string;
  source: { type: string; locator: string; trust_level: string; ref?: string | null };
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
  conditions?: { require_approval?: boolean };
}

export interface GrantResourceEdit {
  tools: string[];
  network: { endpoint: string; effect: 'allow' | 'deny' }[];
  filesystem: { read_only: string[]; read_write: string[] };
  models: string[];
}

export interface Grant {
  signature?: string;
  hermes_toolset_allowlist?: string[];
  openclaw_tool_policy?: { allow: string[]; deny: string[]; require_approval: string[] };
  grant_id: string;
  admission_id: string;
  platform: string;
  status: string;
  subject: { type: string; id: string };
  overlap_conflicts?: Overlap[];
  facts?: GrantFact[];
  enforcement_mode: string;
  created_at: string;
  /** Signed server deadline; null preserves legacy unlimited lifetime. */
  expires_at?: string | null;
  /** Disk version seq from GET/POST responses; required for mutate CAS. */
  state_revision?: number;
  desired_policy_ref?: {
    static_domains_unavailable?: string[];
  };
}

export interface RuntimeCheckPlan {
  schema_version: 'local-runtime-check-plan/v1';
  check_id: string;
  instance_id: string;
  plan_digest: string;
  snapshot_digest: string;
  expires_at: string;
  duration_seconds: number;
  effects: string[];
  limitations: string[];
}

export interface RuntimeCheckResult {
  schema_version: 'local-runtime-check-result/v1';
  check_id: string;
  instance_id: string;
  status: 'preparing' | 'waiting_host' | 'running' | 'passed' | 'failed' | 'cancelled' | 'invalidated';
  reason_code: string;
  started_at: string;
  finished_at: string | null;
  expires_at: string;
  snapshot_digest: string;
  cleanup: 'pending' | 'complete' | 'failed';
  receipt_ids: string[];
  checks: Record<string, boolean>;
  limitations: string[];
}

export interface Receipt {
  authority_status?: "valid" | "invalid" | "unbound_legacy";
  context_assertion_id?: string;
  parameter_provenance?: { parameter_path: string; provenance_refs: string[] }[];
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

export interface AdapterInstance {
  instance_id: string;
  platform: 'hermes';
  name: string;
  config_dir: string;
  source: string;
  default: boolean;
  active: boolean;
  detected: boolean;
  diagnosis: AdapterDiagnosis;
}
export interface AdapterInstances {
  schema_version: 'local-adapter-instances/v1';
  platform_changes: false;
  native_available: boolean;
  instances: AdapterInstance[];
  issues: string[];
}

export interface AdapterPlan {
  schema_version: 'local-adapter-plan/v1' | 'local-adapter-plan/v2' | 'local-adapter-plan/v3';
  runtime_identity_id?: string;
  instance_id?: string;
  instance_name?: string;
  native_enable?: boolean;
  plan_id: string;
  plan_digest: string;
  platform: string;
  action: 'install' | 'uninstall';
  expires_at: string;
  changes: { path: string; action: 'create' | 'replace' | 'remove'; purpose: string; before_sha256: string; after_sha256: string }[];
  next_steps: string[];
  restart_required: boolean;
  runtime_verified: false;
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
  relationships?: DiscoveryRelationship[];
}

export interface DiscoveryRelationship {
  relationship_id: string;
  source_id: string;
  skill_id: string;
  basis: 'platform_directory' | 'profile_directory' | 'workspace_config';
  state: 'inferred';
  evidence_ids: string[];
}

export interface DiscoveryRoot {
  path: string;
  kind: string;
  platform: string;
  status: 'available' | 'missing' | 'unreadable';
}

export interface DiscoveryInput { project_dir?: string; skill_dir?: string }
export interface DiscoveryPreview {
  schema_version: 'local-discovery-preview/v1';
  roots: DiscoveryRoot[];
  platform_changes: false;
}
export interface DiscoveryStatus {
  schema_version: 'local-discovery/v1';
  roots: DiscoveryRoot[];
  platform_changes: false;
  run: {
    run_id?: string;
    state: 'idle' | 'running' | 'succeeded' | 'partial' | 'failed';
    started_at?: string;
    finished_at?: string;
    asset_count: number;
    skill_count: number;
    issue_count: number;
    issues?: string[];
    error?: string;
  };
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
  related_assets?: { id: string; name: string; framework: string; source_type: string }[];
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

export interface RuntimeIdentity {
  identity_id: string;
  instance_id: string;
  agent_id: string;
  platform: 'hermes';
  grant_ref: { grant_id: string; admission_id: string; permission_digest: string };
  actor_id: string;
  created_at: string;
  session_ttl_seconds: number;
  status: 'issued' | 'revoked' | 'grant_unavailable';
  runtime_state: 'unverified';
}

export interface Confirmation {
  action_id: string;
  decision_receipt_id: string;
  decision_hash: string;
  params_digest: string;
  platform: string;
  agent_id: string;
  session_id: string;
  tool: string;
  tool_call_id: string;
  grant_id: string;
  issued_at: string;
  expires_at: string | null;
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'consumed' | 'unavailable';
  params_excerpt: string | null;
}

export interface LocalSkillImportRequest {
  schema_version: 'local-skill-import-create/v1';
  import_id: string;
  source_kind: 'local_dir' | 'local_zip';
  path: string;
  actor_id: string;
}
export interface RemoteSkillImportRequest {
  schema_version: 'local-skill-import-remote-create/v1';
  import_id: string;
  url: string;
  archive_path: string;
  expected_sha256: string;
  actor_id: string;
}
export type SkillImportRequest = LocalSkillImportRequest | RemoteSkillImportRequest;
export type SkillImportSourceKind = 'local_dir' | 'local_zip' | 'https_zip';
export interface SkillImportRemoteMetadata {
  archive_sha256: string;
  archive_bytes: number;
  final_locator_digest: string;
  archive_path: string;
  expected_sha256: string;
}
export interface SkillImportSummary {
  created_at: string;
  source_kind: SkillImportSourceKind;
  actor_id: string;
  artifact_digest: string;
  file_count: number;
  total_bytes: number;
}
export interface SkillImportListItem {
  import_id: string;
  record_status: 'metadata_verified' | 'unavailable';
  payload_status: 'unchecked';
  summary: SkillImportSummary | null;
}
export interface SkillImportList {
  schema_version: 'local-skill-import-list/v1' | 'local-skill-import-list/v2';
  items: SkillImportListItem[];
}
interface SkillImportRecordFields {
  import_id: string;
  actor_id: string;
  created_at: string;
  artifact_digest: string;
  analysis_sha256: string;
  excluded_git_metadata: boolean;
  directories: string[];
  files: { path: string; sha256: string; bytes: number; executable: boolean }[];
}
interface SkillImportResultFields {
  admission: Admission & { declared_facts: {
    domain: string; action: string; state: string; effect: string;
    resource: { type: string; value: string };
  }[] };
  reused: boolean;
  installed: false;
}
export type SkillImportResult = SkillImportResultFields & ({
  schema_version: 'local-skill-import-result/v1';
  import: SkillImportRecordFields & {
    schema_version: 'local-skill-import/v1';
    source_kind: 'local_dir' | 'local_zip';
    remote?: never;
  };
} | {
  schema_version: 'local-skill-import-result/v2';
  import: SkillImportRecordFields & {
    schema_version: 'local-skill-import/v2';
    source_kind: 'https_zip';
    remote: SkillImportRemoteMetadata;
  };
});

export interface ImportPermissionSource {
  schema_version: 'local-skill-import-permission-source/v1';
  import_id: string;
  artifact_digest: string;
  analysis_sha256: string;
}
export interface ImportPermissionRequest {
  schema_version: 'local-skill-import-permission-create/v1';
  request_id: string;
  artifact_digest: string;
  analysis_sha256: string;
  instance_id: string;
  actor_id: string;
}
export interface ImportPermissionResult {
  schema_version: 'local-skill-import-permission-created/v1';
  import_id: string;
  source: ImportPermissionSource;
  grant: Grant;
  state_revision: number;
  reused: boolean;
  installed: false;
}


export interface SkillInstallRequest {
  schema_version: 'local-skill-install-stage-create/v1';
  request_id: string;
  grant_id: string;
  expected_revision: number;
  instance_id: string;
  directory_name: string;
  actor_id: string;
}
export interface SkillInstallPlan {
  schema_version: 'local-skill-install-plan/v1';
  plan_id: string;
  request_id: string;
  source: ImportPermissionSource;
  grant_id: string;
  grant_revision: number;
  grant_signature: string;
  grant_permission_digest: string;
  platform: 'hermes';
  instance_id: string;
  directory_name: string;
  target_locator_digest: string;
  target_display: string;
  actor_id: string;
  created_at: string;
  expires_at: string;
  file_count: number;
  total_bytes: number;
  installed: false;
  runtime_verified: false;
  signature: string;
}
export interface SkillInstallCreated {
  schema_version: 'local-skill-install-plan-created/v1';
  plan: SkillInstallPlan;
  reused: boolean;
}

export interface SkillInstallApply {
  schema_version: 'local-skill-install-apply/v1'; plan_id: string; plan_signature: string; actor_id: string; confirm_install: true;
}
export interface SkillInstallOperation {
  schema_version: 'local-skill-install-operation/v1'; install_id: string; plan_id: string; claim_signature: string;
  status: 'installed_unverified' | 'rolled_back' | 'recovery_required'; actor_id: string; recorded_at: string; runtime_verified: false; signature: string;
}
export interface SkillInstallView {
  schema_version: 'local-skill-install-view/v1'; install_id: string; plan: SkillInstallPlan; claim_signature: string;
  status: SkillInstallOperation['status']; operation: SkillInstallOperation | null;
}

export interface SkillRuntimeBinding {
  schema_version: 'local-skill-install-runtime-binding/v1'; binding_id: string; install_id: string;
  plan_signature: string; operation_signature: string; grant_id: string; approved_revision: number;
  approved_signature: string; permission_digest: string; instance_id: string; source: ImportPermissionSource;
  actor_id: string; created_at: string; signature: string;
}
export interface SkillRuntimeReadiness {
  schema_version: 'local-skill-install-runtime-readiness/v1'; install_id: string; grant: Grant;
  state_revision: number; status: 'not_prepared' | 'incomplete' | 'prepared' | 'no_tools'; binding: SkillRuntimeBinding | null;
}
export interface SkillActivateRequest {
  schema_version: 'local-skill-install-activate/v1'; operation_signature: string; expected_revision: number;
  actor_id: string; confirm_instance_scope: true;
}
export interface SkillActivated {
  schema_version: 'local-skill-install-activated/v1'; binding: SkillRuntimeBinding; grant_id: string;
  state_revision: number; runtime_verified: false;
}

export interface SkillInstallationRecord {
  schema_version: 'local-skill-install-record/v1'; install_id: string; plan: SkillInstallPlan;
  claim_signature: string; recorded_status: SkillInstallOperation['status']; operation: SkillInstallOperation | null;
}
export interface SkillInstallationCatalog {
  schema_version: 'local-skill-install-catalog/v1'; checked_at: string; platform_changes: false;
  items: SkillInstallationRecord[]; issues: { install_id: string | null; code: 'record_unavailable' }[];
}
export interface SkillContentChange {
  path_display: string; path_digest: string; kind: 'file' | 'directory' | 'other';
  change: 'added' | 'modified' | 'removed' | 'type_changed' | 'ownership_changed';
}
export interface SkillInstallationInspection {
  schema_version: 'local-skill-install-inspection/v1'; record: SkillInstallationRecord; checked_at: string;
  platform_changes: false; target_state: 'matched' | 'changed' | 'missing' | 'unavailable'; comparison_complete: boolean;
  changes: SkillContentChange[]; changes_total: number; changes_truncated: boolean;
  issue_code: null | 'target_unavailable' | 'comparison_budget_exceeded';
}

export interface SkillRemoveRequest {
  schema_version: 'local-skill-install-remove/v1'; operation_signature: string; expected_grant_revision: number;
  expected_binding_signature: string; actor_id: string; confirm_remove: true;
}
export interface SkillRemovalClaim {
  schema_version: 'local-skill-install-removal-claim/v1'; install_id: string; installation_claim_signature: string;
  operation_signature: string; grant_id: string; grant_revision: number; grant_signature: string;
  binding_signature: string; retained_install_id: string; revoke_grant: boolean; actor_id: string; created_at: string; signature: string;
}
export interface SkillRemovalResult {
  schema_version: 'local-skill-install-removal-result/v1'; install_id: string; removal_claim_signature: string; status: 'removed';
  grant_id: string; grant_revision: number; grant_signature: string; grant_revoked: boolean; retained_install_id: string;
  actor_id: string; recorded_at: string; target_absent: true; signature: string;
}
export interface SkillRemovalView {
  schema_version: 'local-skill-install-removal-view/v1'; record: SkillInstallationRecord;
  claim: SkillRemovalClaim | null; result: SkillRemovalResult | null; grant: Grant | null; state_revision: number | null;
  status: 'not_requested' | 'revocation_pending' | 'cleanup_pending' | 'removed';
  will_revoke_grant: boolean; retained_install_id: string; binding_signature: string;
}

export interface SkillUpdateCompareRequest {
  schema_version: 'local-skill-update-compare/v1'; operation_signature: string; candidate_grant_id: string; expected_candidate_revision: number;
}
export interface SkillUpdateContent { kind: 'file' | 'directory'; sha256: string; bytes: number; executable: boolean }
export interface SkillUpdateRule {
  domain: string; action: string; resource: { type: string; value: string }; effect: 'allow' | 'deny'; conditions: Record<string, unknown> | null; state: string;
}
export interface SkillUpdateComparison {
  schema_version: 'local-skill-update-comparison/v1'; record: SkillInstallationRecord; candidate_source: ImportPermissionSource;
  previous_grant: Grant; previous_revision: number; candidate_grant: Grant; candidate_revision: number; checked_at: string;
  comparison_basis: 'signed_installation_manifest'; platform_changes: false; runtime_verified: false; requires_confirmation: true;
  content_changes: { path_display: string; path_digest: string; before: SkillUpdateContent | null; after: SkillUpdateContent | null }[];
  content_changes_total: number; content_changes_truncated: boolean;
  permission_changes: { change: 'added' | 'removed'; rule: SkillUpdateRule }[];
  permission_changes_total: number; permission_changes_truncated: boolean;
  settings_changed: string[];
}
export interface SkillUpdateStageRequest {
  schema_version: 'local-skill-update-stage-create/v1'; request_id: string; operation_signature: string; candidate_grant_id: string;
  expected_candidate_revision: number; expected_previous_revision: number; expected_binding_signature: string; actor_id: string;
}
export interface SkillUpdatePlan {
  schema_version: 'local-skill-update-plan/v1'; update_id: string; request_id: string; record: SkillInstallationRecord;
  candidate_source: ImportPermissionSource; candidate_grant_id: string; candidate_revision: number; candidate_signature: string;
  candidate_permission_digest: string; previous_revision: number; previous_signature: string; binding_signature: string;
  retained_install_id: string; revoke_previous_grant: boolean; actor_id: string; created_at: string; expires_at: string;
  file_count: number; total_bytes: number; platform_changes: false; runtime_verified: false; requires_confirmation: true; signature: string;
}
export interface SkillUpdateCreated { schema_version: 'local-skill-update-plan-created/v1'; plan: SkillUpdatePlan; reused: boolean }
export interface SkillUpdateCommit { schema_version: 'local-skill-update-commit/v1'; update_id: string; plan_signature: string; actor_id: string; confirm_update: true }
export interface SkillUpdateRecover { schema_version: 'local-skill-update-recover/v1'; update_id: string; claim_signature: string; actor_id: string; confirm_recovery: true }
export interface SkillUpdateClaim {
  schema_version: 'local-skill-update-claim/v1'; update_id: string; plan: SkillUpdatePlan; replacement_plan: SkillInstallPlan; actor_id: string; created_at: string; signature: string;
}
export interface SkillUpdateResult {
  schema_version: 'local-skill-update-result/v1'; update_id: string; claim_signature: string; status: 'updated_unverified' | 'aborted';
  removal_signature: string; installation_signature: string; actor_id: string; recorded_at: string; runtime_verified: false; signature: string;
}
export interface SkillUpdateView {
  schema_version: 'local-skill-update-view/v1'; update_id: string; claim: SkillUpdateClaim; result: SkillUpdateResult | null;
  removal: SkillRemovalView | null; installation: SkillInstallOperation | null;
  status: 'confirmed' | 'removing_previous' | 'installing_candidate' | 'recovery_required' | 'updated_unverified' | 'aborted';
}
