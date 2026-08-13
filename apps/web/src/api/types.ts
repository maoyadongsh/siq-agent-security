/**
 * SIQ Agent Security — 控制面 API 类型定义（与后端契约对齐）
 *
 * 事实源：packages/contracts/*.schema.json（本仓库为唯一事实源，改动必须升 schema 版本）。
 * 以下类型是对 JSON Schema 的 1:1 翻译，字段名/枚举值必须与 schema 一致。
 *
 * 补充类型（Environment / AgentAsset / Finding / ChangeRequest）为控制面管理对象
 * 的 Phase 1 最小字段，后续以 Control API 的 OpenAPI 契约为准。
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
 * Evidence — 可验证证据（evidence.schema.json，字段对齐设计文档 §10.5）
 * 原始配置不默认上传，payload_ref 仅在管理员批准且满足驻留策略时存在。
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
  /** 租户内唯一（tenant_id + evidence_id 复合唯一） */
  evidence_id: string;
  tenant_id?: string;
  environment_id?: string;
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
  /** Edge 对证据包的签名或证明（Ed25519，hex） */
  signature: string;
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
  | 'onboarding'
  | 'managed'
  | 'offboarding'
  | 'dismissed';

/** 智能体资产（由 Candidate 纳管后形成，设计文档 §10 资产生命周期） */
export interface AgentAsset {
  agent_id: string;
  name: string;
  /** 业务角色，如 contract-review / incident-response */
  role?: string;
  status: AgentStatus;
  /** hermes / openclaw / pi / unknown */
  framework: string;
  environment_id?: string;
  /** 来源候选引用 */
  candidate_id?: string;
  discovered_at?: string;
  updated_at?: string;
}

export type EnvironmentKind = 'kubernetes' | 'docker' | 'systemd' | 'hermes' | 'siq_hub' | 'sandbox';

export type EnvironmentStatus = 'healthy' | 'degraded' | 'unknown' | 'offline';

/** 环境与 Connector（Edge Agent 采集/执行单元，设计文档 §26） */
export interface Environment {
  environment_id: string;
  name: string;
  kind: EnvironmentKind;
  status: EnvironmentStatus;
  /** 已安装的 Connector 版本，如 docker/v1.2.0 */
  connector_version?: string;
  last_seen_at?: string;
  description?: string;
}

export type FindingSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export type FindingStatus = 'open' | 'investigating' | 'mitigated' | 'accepted' | 'resolved';

/** 风险中心条目（聚合 Evidence 与 PermissionFact 的风险结论） */
export interface Finding {
  finding_id: string;
  /** 关联智能体资产（可为空：环境/基础设施级风险） */
  agent_id?: string;
  environment_id?: string;
  /** 触发风险的相关策略 */
  policy_id?: string;
  title: string;
  description?: string;
  severity: FindingSeverity;
  status: FindingStatus;
  /** 支撑证据 */
  evidence_ids: string[];
  detected_at: string;
  assigned_to?: string;
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
