/**
 * ENT-019-AUDIT-SEARCH-UI：审计精确查询表单。
 *
 * 交互契约：
 * - 输入只更新草稿（draft），绝不触发请求；显式提交（按钮或 Enter）才应用条件；
 * - 提交前做长度校验，超长给出可读提示且不发送请求；
 * - 「清空查询条件」同时清空草稿与已应用条件（由父组件重置查询与分页）；
 * - 更多查询条件默认折叠（原生 details/summary，键盘可操作）。
 */
import { useState, type FormEvent } from 'react';
import {
  AUDIT_ADVANCED_FIELDS,
  AUDIT_FILTER_FIELDS,
  AUDIT_PRIMARY_FIELDS,
  hasActiveAuditFilters,
  hasAuditFilterErrors,
  validateAuditFilters,
  type AuditFilterErrors,
  type AuditFilterFieldSpec,
  type AuditSearchFilters,
} from './auditSearch';

interface AuditSearchFormProps {
  /** 输入中的草稿（未生效） */
  draft: AuditSearchFilters;
  /** 当前已应用条件（用于决定清空按钮可用性） */
  applied: AuditSearchFilters;
  onDraftChange: (next: AuditSearchFilters) => void;
  /** 校验通过的提交；相同条件的去重由父组件决定 */
  onApply: (next: AuditSearchFilters) => void;
  onClear: () => void;
}

function AuditSearchField({
  spec,
  value,
  error,
  onChange,
}: {
  spec: AuditFilterFieldSpec;
  value: string;
  error: string | undefined;
  onChange: (value: string) => void;
}) {
  const id = `audit-search-${spec.key}`;
  return (
    <div className="field audit-search-field">
      <label htmlFor={id}>
        {spec.label}（{spec.key}）
      </label>
      <input
        id={id}
        name={spec.key}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete="off"
        spellCheck={false}
        placeholder={`精确匹配，最长 ${spec.max} 字符`}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      {error ? (
        <p className="audit-search-field-error" id={`${id}-error`}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export default function AuditSearchForm({
  draft,
  applied,
  onDraftChange,
  onApply,
  onClear,
}: AuditSearchFormProps) {
  const [errors, setErrors] = useState<AuditFilterErrors>({});

  const changeField = (key: keyof AuditSearchFilters, value: string) => {
    onDraftChange({ ...draft, [key]: value });
    // 输入时只清除该字段的既有错误，不重新校验、不发请求
    setErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextErrors = validateAuditFilters(draft);
    setErrors(nextErrors);
    if (hasAuditFilterErrors(nextErrors)) return; // 超长：提示且不发送请求
    onApply(draft);
  };

  const clearable = hasActiveAuditFilters(draft) || hasActiveAuditFilters(applied);

  const renderField = (spec: AuditFilterFieldSpec) => (
    <AuditSearchField
      key={spec.key}
      spec={spec}
      value={draft[spec.key]}
      error={errors[spec.key]}
      onChange={(value) => changeField(spec.key, value)}
    />
  );

  return (
    <form className="audit-search-form" aria-label="审计事件精确查询" onSubmit={handleSubmit}>
      {hasAuditFilterErrors(errors) ? (
        <div className="audit-search-errors" role="alert">
          <p>查询条件未通过校验，未发送请求：</p>
          <ul>
            {AUDIT_FILTER_FIELDS.filter(({ key }) => errors[key]).map(({ key }) => (
              <li key={key}>{errors[key]}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="audit-search-primary">{AUDIT_PRIMARY_FIELDS.map(renderField)}</div>
      <details className="audit-search-more">
        <summary>更多查询条件（操作者、动作、对象类型、决策）</summary>
        <div className="audit-search-more-grid">{AUDIT_ADVANCED_FIELDS.map(renderField)}</div>
      </details>
      <div className="audit-search-actions">
        <button type="submit" className="btn btn-primary">
          查询审计事件
        </button>
        <button type="button" className="btn" onClick={onClear} disabled={!clearable}>
          清空查询条件
        </button>
      </div>
      <p className="audit-search-note">
        精确匹配：多个条件同时满足（AND）；空字段不参与查询；查询作用于服务端审计记录，不限于当前已加载列表。
      </p>
    </form>
  );
}
