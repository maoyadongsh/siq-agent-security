/**
 * SIQ Agent Security — 控制面 API 类型定义（与后端契约对齐）
 *
 * 契约事实源：packages/contracts/*.schema.json（本仓库为唯一事实源，改动必须升 schema 版本）。
 * 契约类型（AgentCandidate / PermissionFact / DesiredPolicy / EventEnvelope）是对
 * JSON Schema 的 1:1 翻译，字段名/枚举值必须与 schema 一致。
 *
 * 控制面管理对象（AgentAsset / Environment / Finding / Evidence / AuditEvent 等）
 * 已与 Control API 实际响应字段对齐（事实源：apps/control-api/app/schemas.py 的 *Out 模型）。
 */

/* ---------------------------------------------------------------------------
 * AgentCandidate — 确定性发现阶段产生的智能体候选（candidate.schema.json）
 * Connector 只产生候选与证据，不直接创建纳管资产（设计文档 §10.2）
 * ------------------------------------------------------------------------- */

export type AgentSourceType =
  | 'hermes_profile'
  | 'docker'
  | 'kubernetes'
  | 'systemd'
  | 'siq_hub'
  | 'process_list'
  | 'human';

export type CandidateStatus = 'candidate' | 'needs_review' | 'dismissed';

export interface AgentCandidate {
  /** 采集端生成的稳定候选 ID（含 connector 前缀，如 hermes:siq_legal_advisor@v1） */
  candidate_id: string;
  source_type: AgentSourceType;
  /** 脱敏后的稳定来源定位，不含凭据 */
  source_locator: string;
  /** ISO 8601 date-time */
  discovered_at: string;
  name: string;
  /** hermes / openclaw / pi / unknown */
  framework: string;
  /** 制品摘要（镜像 digest / 资产 sha256），可选 */
  artifact_digest?: string;
  /**
   * 框架特有属性，必须已脱敏；禁止包含 token/secret/env 正文。
   * schema 中 additionalProperties: true
   */
  attributes?: Record<string, unknown>;
  /** 引用同一批次上传的 Evidence.evidence_id */
  evidence_ids: string[];
  /** 确定性规则产生的候选为 1.0；模型辅助分类不回写本字段 */
  confidence?: number;
  status?: CandidateStatus;
}

/* ---------------------------------------------------------------------------
 * Evidence — 可验证证据（API 投影 = schemas.py EvidenceOut）
 * Connector 侧完整证据契约（含 signature 等）见 evidence.schema.json；
 * 控制面 API 返回管理投影：原始配置不默认上传，payload_ref 仅授权场景存在。
 * ------------------------------------------------------------------------- */

export type EvidenceSourceType =
  | 'registry'
  | 'manifest'
  | 'process'
  | 'container'
  | 'k8s'
  | 'iam'
  | 'gateway'
  | 'openshell'
  | 'human'
  | 'deny_log';

export type EvidenceClassification =
  | 'public'
  | 'internal'
  | 'confidential'
  | 'secret_ref';

export interface Evidence {
  /** 服务端证据 ID（入库时保留 Connector 生成的 evidence_id） */
  id: string;
  source_type: EvidenceSourceType;
  /** 脱敏后的稳定来源定位，不含凭据 */
  source_locator: string;
  /** Candidate / Asset / Instance 引用 */
  subject_ref?: string | null;
  /** 来源事实的观察时间 */
  observed_at: string;
  /** Collector 采集时间 */
  collected_at: string;
  /** 采集主体（Edge Agent 设备身份） */
  collector_id: string;
  connector_version: string;
  /** 原始证据规范化后的 sha256 */
  content_hash: string;
  /** 使用的脱敏规则版本，如 siq.redaction.v1 */
  redaction_profile: string;
  classification: EvidenceClassification;
  /** 加密对象引用；默认 null（仅结构化摘要） */
  payload_ref?: string | null;
  /** 证据新鲜度或例外失效时间 */
  expires_at?: string | null;
}

/* ---------------------------------------------------------------------------
 * PermissionFact — 权限事实（permission-fact.schema.json，设计文档 §12.3）
 * 智能体代用户运行时必须携带 delegated_user 维度：
 * 有效数据范围 = Agent 自身权限 ∩ 调用用户数据范围。
 * ------------------------------------------------------------------------- */

export type PermissionSubjectType = 'agent_instance' | 'agent_asset' | 'identity_binding';

export type PermissionDomain =
  | 'business'
  | 'data_scope'
  | 'tool'
  | 'filesystem'
  | 'network'
  | 'process'
  | 'model'
  | 'credential'
  | 'resource'
  | 'control_plane';

export type PermissionEffect = 'allow' | 'deny';

export type PermissionState = 'declared' | 'inferred' | 'observed' | 'effective' | 'unknown';

export interface PermissionSubject {
  type: PermissionSubjectType;
  id: string;
}

export interface PermissionResource {
  /** endpoint / path / tool / model / credential_ref / namespace */
  type: string;
  value: string;
}

export interface DelegatedUser {
  user_id: string;
  token_ref: string;
  purpose?: string;
}

export interface PermissionFact {
  subject: PermissionSubject;
  /**
   * 委托维度；来源优先为 SIQ IAM /auth/delegated-token
   * （act claim、purpose、TTL≤300s），而非 Agent 自报身份
   */
  delegated_user?: DelegatedUser | null;
  domain: PermissionDomain;
  /** 如 http.request / fs.write / model.generate */
  action: string;
  resource: PermissionResource;
  effect: PermissionEffect;
  /** methods / binary_paths / purpose / ttl 等约束（additionalProperties: true） */
  conditions?: Record<string, unknown>;
  state: PermissionState;
  /** openshell / siq-iam / siq-gateway / os / container / business-service */
  authority: string;
  /** 权威源 revision，如 OpenShell 策略 revision */
  authority_revision?: string | null;
  evidence_ids: string[];
  valid_from?: string | null;
  valid_until?: string | null;
}

/* ---------------------------------------------------------------------------
 * DesiredPolicy — 后端无关的期望安全状态（desired-policy.schema.json，设计文档 §14.1）
 * 后端不支持的字段必须标记为 unsupported 或由其他执行点承担，编译时不得静默丢失。
 * ------------------------------------------------------------------------- */

export type PolicyStatus =
  | 'draft'
  | 'validated'
  | 'proposed'
  | 'approved'
  | 'deploying'
  | 'effective'
  | 'rejected'
  | 'failed'
  | 'superseded'
  | 'rollback_pending'
  | 'rolled_back';

/** 渐进执行档位，对齐 Observe→Canary→A/B→Enforced→Default 架构 */
export type EnforcementMode = 'audit_only' | 'warn' | 'block';

export interface PolicySelector {
  agent_ids: string[];
  environment_ids?: string[];
  system_ref?: string | null;
  labels?: Record<string, string>;
}

export interface NetworkRule {
  /** host:port/path 形式，如 api.example.com:443/orders/** */
  endpoint: string;
  effect: PermissionEffect;
  methods?: string[];
  binary_paths?: string[];
  purpose?: string;
}

export interface PolicySecretRef {
  /** 凭据引用，永不存明文 */
  ref: string;
  purpose: string;
  injection?: 'gateway' | 'env_ref' | 'none';
}

export interface PolicyException {
  reason: string;
  owner: string;
  expires_at: string;
  approval_ref?: string;
}

export interface PolicyResources {
  cpu?: string;
  memory?: string;
  concurrency?: number;
}

export interface DesiredPolicy {
  policy_id: string;
  selector: PolicySelector;
  filesystem?: {
    read_only?: string[];
    read_write?: string[];
  };
  network?: NetworkRule[];
  process?: {
    /** uid:gid */
    run_as?: string | null;
    forbid_privilege_escalation?: boolean;
    seccomp_profile?: string | null;
  };
  model_routing?: {
    allowed_models?: string[];
    provider?: string | null;
  };
  /** 工具引用（tool_ref），参数约束经 tool_policies 表达 */
  tools?: string[];
  /** additionalProperties: true — 每个 tool_ref 的约束对象 */
  tool_policies?: Record<string, Record<string, unknown>>;
  /** 业务数据范围引用，权威源为业务 IAM */
  data_scope_refs?: string[];
  secrets?: PolicySecretRef[];
  resources?: PolicyResources;
  audit?: { required_level?: string };
  exceptions?: PolicyException[];
  /** 编译后由其他执行点承担或标记 unsupported 的字段清单 */
  unsupported_by_backend?: string[];
  version: number;
  status: PolicyStatus;
  enforcement_mode: EnforcementMode;
}

/* ---------------------------------------------------------------------------
 * EventEnvelope — 领域事件统一信封（event-envelope.schema.json，设计文档 §18.3）
 * 消费者按 event_id 幂等处理；payload 必须脱敏。
 * ------------------------------------------------------------------------- */

export interface EventActor {
  actor_type: string;
  actor_id: string;
}

export interface EventEnvelope {
  event_id: string;
  /** 如 agent.candidate.discovered.v1 */
  event_type: string;
  occurred_at: string;
  tenant_id: string;
  environment_id?: string | null;
  actor?: EventActor | null;
  resource_ref?: string | null;
  request_id?: string | null;
  schema_version: number;
  /** 脱敏后的领域载荷 */
  payload?: Record<string, unknown>;
}

/* ===========================================================================
 * 控制面管理对象（Phase 1 最小字段）
 * 以 packages/contracts 的 schema 为事实源；以下对象待 Control API 的
 * OpenAPI 契约落地后对齐。字段保持最小化，避免臆造契约。
 * ========================================================================= */

export type AgentStatus =
  | 'candidate'
  | 'needs_review'
  | 'confirmed'
  | 'managed'
  | 'stale'
  | 'retired'
  | 'dismissed';

/**
 * 智能体资产（schemas.py AgentAssetOut）。
 * /candidates 与 /agents 均返回此结构：候选状态为 candidate|needs_review，
 * 已纳管为 confirmed|managed|stale|retired（dismissed 为驳回终态）。
 */
export interface AgentAsset {
  id: string;
  name: string;
  /** 业务角色，如 contract-review / incident-response */
  role: string | null;
  /** hermes / openclaw / pi / unknown */
  framework: string;
  status: AgentStatus;
  system_id: string | null;
  owner_user_id: string | null;
  /** 来源采集类型（hermes_profile / docker / process_list …） */
  source_type: string | null;
  /** 脱敏后的稳定来源定位，不含凭据 */
  source_locator: string | null;
  /** ISO 8601 date-time */
  updated_at: string;
}

/** 运行时实例（GET /agents/{id}/instances） */
export interface AgentInstance {
  id: string;
  /** hermes / openclaw / pi / embedded / unknown */
  runtime: string;
  version: string | null;
  artifact_digest: string | null;
  location: Record<string, unknown>;
  /** observed / running / stopped */
  status: string;
  observed_at: string | null;
}

/** 候选分类运行结果（POST /candidates/{id}/classify） */
export interface ClassificationRunResult {
  classification_run_id: string;
  classifier: string;
  asset_status: string;
  output: Record<string, unknown>;
}

/** 环境类型 / 运行模式 / 风险级别（schemas.py EnvironmentOut） */
export type EnvironmentType = 'host' | 'container' | 'k8s' | 'account';
export type EnvironmentMode = 'discovery' | 'observe' | 'recommend' | 'enforce';
export type EnvironmentRiskLevel = 'low' | 'medium' | 'high';

/** 环境与 Connector（GET /environments，设计文档 §26） */
export interface Environment {
  id: string;
  tenant_id: string;
  name: string;
  env_type: EnvironmentType;
  /** 渐进执行档位：discovery → observe → recommend → enforce */
  mode: EnvironmentMode;
  risk_level: EnvironmentRiskLevel;
  /** 最近一次 Edge 心跳时间（EdgeAgent 心跳回写） */
  last_heartbeat_at: string | null;
}

export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export type FindingStatus = 'open' | 'acknowledged' | 'resolved' | 'risk_accepted' | 'expired';

/** risk_acceptance 内容（acknowledge / resolve / accept-risk 回写） */
export interface FindingRiskAcceptance {
  reason?: string;
  accepted_by?: string;
  expires_at?: string;
  resolved_by?: string;
  evidence_ref?: string;
}

/** 风险中心条目（schemas.py FindingOut，GET /findings，设计文档 §13） */
export interface Finding {
  id: string;
  rule_id: string;
  rule_version: number;
  severity: FindingSeverity;
  domain: string | null;
  /** 关联智能体资产（可为空：环境/基础设施级风险） */
  asset_id: string | null;
  /** 支撑证据 */
  evidence_ids: string[];
  impact: string | null;
  remediation: string | null;
  status: FindingStatus;
  owner_user_id: string | null;
  due_at: string | null;
  risk_acceptance: FindingRiskAcceptance | null;
  first_seen_at: string;
  last_seen_at: string;
}

/* --- 请求体（schemas.py CandidateConfirm / CandidateDismiss） --- */

export interface CandidateConfirmBody {
  role?: string | null;
  system_id?: string | null;
  owner_user_id?: string | null;
}

export interface CandidateDismissBody {
  reason: string;
  expires_at?: string | null;
}

export type ChangeType = 'create' | 'update' | 'delete' | 'rollback' | 'emergency';

export type ChangeStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'deploying'
  | 'deployed'
  | 'failed'
  | 'rolled_back';

/** 变更中心条目（策略/资产变更申请与执行记录，设计文档 §14.3） */
export interface ChangeRequest {
  change_id: string;
  policy_id?: string;
  agent_id?: string;
  change_type: ChangeType;
  summary?: string;
  status: ChangeStatus;
  requested_by?: string;
  approved_by?: string;
  created_at: string;
  applied_at?: string;
  /** 变更原因/审计说明 */
  reason?: string;
}

/* ---------------------------------------------------------------------------
 * AuditEvent — 审计事件（schemas.py AuditEventOut，GET /audit-events，设计文档 §24）
 * 审计只读、租户隔离、游标分页；summary 字段已脱敏。
 * ------------------------------------------------------------------------- */

export interface AuditEvent {
  id: string;
  actor_type: string;
  actor_id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  decision: string;
  request_id: string | null;
  /** 脱敏摘要：标识/数量/哈希，禁止原文 */
  summary: Record<string, unknown>;
  created_at: string;
}

/* ---------------------------------------------------------------------------
 * API 信封 — 控制面响应包装（Phase 1 约定，待 Control API 联调确认）
 * 兼容两种形态：
 *   1. 信封：{ "ok": true, "data": ... }
 *   2. 裸数据：直接返回数组 / 对象
 * ------------------------------------------------------------------------- */

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

/** 权限事实（后端 API 扁平形状，对齐 apps/control-api/app/schemas.py PermissionFactOut） */
export interface PermissionFactRow {
  id: string;
  subject_type: string;
  subject_id: string;
  delegated_user: Record<string, string> | null;
  domain: string;
  action: string;
  resource_type: string;
  resource_value: string;
  effect: 'allow' | 'deny';
  conditions: Record<string, unknown>;
  state: 'declared' | 'inferred' | 'observed' | 'effective' | 'unknown';
  authority: string;
  authority_revision: string | null;
  evidence_ids: string[];
  valid_from: string | null;
  valid_until: string | null;
}

/** 策略行（对齐 PolicyOut） */
export interface PolicyRow {
  id: string;
  name: string;
  selector: Record<string, unknown>;
  enforcement_mode: 'audit_only' | 'warn' | 'block';
  version: number;
  status: string;
  unsupported_by_backend: string[];
  updated_at: string;
}

/** 变更单行（对齐 ChangeRequestOut） */
export interface ChangeRequestRow {
  id: string;
  policy_id: string;
  proposer_user_id: string;
  approver_user_id: string | null;
  approval_policy: string;
  status: string;
  idempotency_key: string;
  created_at: string;
}

/** 部署行（对齐 DeploymentOut） */
export interface DeploymentRow {
  id: string;
  environment_id: string;
  change_request_id: string;
  target: string;
  from_revision: string | null;
  to_revision: string;
  status: string;
  verification: Record<string, unknown> | null;
}

/** 总览统计（对齐 GET /api/v1/overview） */
export interface OverviewStats {
  agents: number;
  candidates: number;
  open_findings: number;
  critical_findings: number;
  environments: number;
  edges_online: number;
  policies: number;
}

export interface ApiEnvelope<T> {
  ok: boolean;
  data?: T;
  error?: ApiErrorBody;
  request_id?: string;
}

export interface ApiListResponse<T> {
  items: T[];
  total?: number;
  page?: number;
  page_size?: number;
}
