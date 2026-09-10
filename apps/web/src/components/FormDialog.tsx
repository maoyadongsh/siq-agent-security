/** 表单模态：一个或多个输入字段 + 必填校验，替代原生 window.prompt。
 * 打开时重置字段；Enter 提交；必填项为空时内联报错。 */
import { useEffect, useState } from 'react';
import Modal from './Modal';

export interface FormField {
  key: string;
  label: string;
  placeholder?: string;
  required?: boolean;
}

interface FormDialogProps {
  open: boolean;
  title: string;
  description?: string;
  fields: FormField[];
  submitLabel?: string;
  cancelLabel?: string;
  /** 危险提交（如不可逆解决）：按钮用红边红字语言 */
  danger?: boolean;
  busy?: boolean;
  onSubmit: (values: Record<string, string>) => void;
  onClose: () => void;
}

export default function FormDialog({
  open,
  title,
  description,
  fields,
  submitLabel = '提交',
  cancelLabel = '取消',
  danger = false,
  busy = false,
  onSubmit,
  onClose,
}: FormDialogProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setValues({});
      setError(null);
    }
  }, [open]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const missing = fields.find((f) => f.required && !values[f.key]?.trim());
    if (missing) {
      setError(`请填写「${missing.label}」`);
      return;
    }
    onSubmit(values);
  };

  return (
    <Modal open={open} onClose={onClose} title={title} description={description}>
      <form onSubmit={handleSubmit}>
        <div className="modal-body">
          {fields.map((f) => (
            <label key={f.key} className="login-field">
              {f.label}
              {f.required ? '' : '（可选）'}
              <input
                value={values[f.key] ?? ''}
                placeholder={f.placeholder}
                onChange={(e) => {
                  setValues((v) => ({ ...v, [f.key]: e.target.value }));
                  setError(null);
                }}
              />
            </label>
          ))}
          {error ? (
            <p className="action-error" role="alert">
              {error}
            </p>
          ) : null}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="submit"
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            disabled={busy}
          >
            {busy ? '执行中…' : submitLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}
