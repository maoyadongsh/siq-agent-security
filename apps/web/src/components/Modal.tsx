/** 模态基座（对齐 SIQ 设计系统模态契约）：藏蓝幕布 + 轻模糊 + 16px 圆角浮层；
 * Esc / 点幕布关闭、焦点圈定、关闭还原焦点、背景滚动锁定。零依赖 portal 实现。 */
import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])';

const focusableItems = (panel: HTMLElement) => Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
  .filter((element) => element.getClientRects().length > 0 && !element.closest('[inert]'));

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  className?: string;
  children: ReactNode;
}

export default function Modal({ open, onClose, title, description, className, children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const restoreTo = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // 初始焦点落到面板内第一个可聚焦元素，落空则聚焦面板本身
    const panel = panelRef.current;
    const first = panel ? focusableItems(panel)[0] : undefined;
    (first ?? panel)?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab' || !panel) return;
      const items = focusableItems(panel);
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown, true);
      restoreTo?.focus();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={className ? `modal ${className}` : 'modal'}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={panelRef}
        tabIndex={-1}
      >
        <h2 className="modal-title">{title}</h2>
        {description ? <p className="modal-desc">{description}</p> : null}
        {children}
      </div>
    </div>,
    document.body,
  );
}
