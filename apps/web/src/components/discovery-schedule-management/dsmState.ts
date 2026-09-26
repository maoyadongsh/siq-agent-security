import type { DiscoveryScheduleItem, DiscoverySchedulePage, DiscoveryScheduleStatus } from '@/api/discoveryScheduleManagement';

export interface DsmMessage { kind: 'status' | 'alert'; text: string }

export interface DsmState {
  phase: 'idle' | 'loading' | 'ready' | 'error';
  items: DiscoveryScheduleItem[];
  nextCursor: string | null;
  evaluatedAt: string | null;
  canRevoke: boolean;
  ticket: number;
  moreTicket: number;
  morePhase: 'idle' | 'loading' | 'error';
  revokeTarget: DiscoveryScheduleItem | null;
  revokeBusy: boolean;
  message: DsmMessage | null;
}

export type DsmAction =
  | { type: 'loadStart'; ticket: number }
  | { type: 'loadSuccess'; ticket: number; page: DiscoverySchedulePage }
  | { type: 'loadFailure'; ticket: number }
  | { type: 'loadMoreStart'; ticket: number }
  | { type: 'loadMoreSuccess'; ticket: number; page: DiscoverySchedulePage }
  | { type: 'loadMoreFailure'; ticket: number }
  | { type: 'revokeOpen'; item: DiscoveryScheduleItem }
  | { type: 'revokeCancel' }
  | { type: 'revokeStart' }
  | { type: 'revokeSuccess' }
  | { type: 'revokeFailure'; text: string };

export function initialDsmState(): DsmState {
  return { phase: 'idle', items: [], nextCursor: null, evaluatedAt: null, canRevoke: false,
    ticket: 0, moreTicket: 0, morePhase: 'idle', revokeTarget: null, revokeBusy: false, message: null };
}

/** Messages never claim an outcome the server did not confirm; revoke failures forbid auto-retry. */
export function revokeFailureMessage(status: number): string {
  if (status === 409) return '计划已发生变化（版本冲突），未撤销。请先只读刷新核对最新状态，再重新确认；不会自动用新版本重试。';
  if (status === 403) return '当前账号没有撤销周期计划的权限，未执行撤销。';
  return '撤销结果未知：未收到确认响应。请先只读刷新核对该计划当前状态，再决定下一步；不会自动重发撤销请求。';
}

export function dsmReducer(state: DsmState, action: DsmAction): DsmState {
  switch (action.type) {
    case 'loadStart':
      if (state.revokeBusy) return state;
      // 刷新从第一页整页替换；同一票号同时使在途加载更多失效；保留已展示的提示信息。
      return { ...state, phase: 'loading', items: [], nextCursor: null, evaluatedAt: null, canRevoke: false,
        ticket: action.ticket, moreTicket: action.ticket, morePhase: 'idle', revokeTarget: null };
    case 'loadSuccess':
      if (action.ticket !== state.ticket) return state;
      return { ...state, phase: 'ready', items: action.page.items, nextCursor: action.page.next_cursor,
        evaluatedAt: action.page.evaluated_at, canRevoke: action.page.can_revoke,
        message: state.message?.kind === 'status' ? state.message : null };
    case 'loadFailure':
      if (action.ticket !== state.ticket) return state;
      return { ...state, phase: 'error', message: { kind: 'alert', text: '无法读取周期发现计划，请重试。' } };
    case 'loadMoreStart':
      if (state.revokeBusy || state.phase !== 'ready' || state.nextCursor === null || state.morePhase === 'loading') return state;
      return { ...state, morePhase: 'loading', moreTicket: action.ticket, canRevoke: false, revokeTarget: null };
    case 'loadMoreSuccess':
      if (action.ticket !== state.moreTicket || state.phase !== 'ready') return state;
      return { ...state, morePhase: 'idle', items: [...state.items, ...action.page.items],
        nextCursor: action.page.next_cursor, evaluatedAt: action.page.evaluated_at, canRevoke: action.page.can_revoke,
        message: state.message?.kind === 'status' ? state.message : null };
    case 'loadMoreFailure':
      // 保留已成功页与同一游标，允许同游标重试。
      if (action.ticket !== state.moreTicket || state.phase !== 'ready') return state;
      return { ...state, morePhase: 'error', canRevoke: false, revokeTarget: null,
        message: { kind: 'alert', text: '加载更多失败，已保留已加载记录，可用同一游标重试。' } };
    case 'revokeOpen':
      if (state.revokeBusy || state.phase !== 'ready' || state.morePhase !== 'idle'
        || !canOfferRevoke(action.item, state.canRevoke)) return state;
      return { ...state, revokeTarget: action.item };
    case 'revokeCancel':
      if (state.revokeBusy) return state;
      return { ...state, revokeTarget: null };
    case 'revokeStart':
      if (!state.revokeTarget || state.revokeBusy || state.phase !== 'ready' || state.morePhase !== 'idle'
        || !canOfferRevoke(state.revokeTarget, state.canRevoke)) return state;
      return { ...state, revokeBusy: true };
    case 'revokeSuccess':
      return { ...state, revokeTarget: null, revokeBusy: false,
        message: { kind: 'status', text: '已撤销该计划：停止其后续调度。列表将以只读刷新结果为准。' } };
    case 'revokeFailure':
      return { ...state, revokeTarget: null, revokeBusy: false, canRevoke: false,
        message: { kind: 'alert', text: action.text } };
  }
}

const STATUS_LABELS: Record<DiscoveryScheduleStatus, string> = {
  pending_confirmation: '待设备确认', active: '已确认的计划', paused: '已暂停', revoked: '已撤销',
};

export function statusLabel(status: DiscoveryScheduleStatus): string {
  return STATUS_LABELS[status];
}

export type WindowFact = 'not_started' | 'within' | 'expired';

/** Window facts use the server evaluated_at, never the browser clock; not a scheduling promise. */
export function windowState(item: Pick<DiscoveryScheduleItem, 'starts_at' | 'expires_at'>, evaluatedAt: string): WindowFact {
  const now = Date.parse(evaluatedAt);
  return Date.parse(item.starts_at) > now ? 'not_started' : Date.parse(item.expires_at) <= now ? 'expired' : 'within';
}

const WINDOW_LABELS: Record<WindowFact, string> = { not_started: '窗口未开始', within: '窗口内', expired: '已过期' };

export function windowLabel(fact: WindowFact): string {
  return WINDOW_LABELS[fact];
}

/** max_runs - reserved_runs is unreserved budget only, still bounded by deadline and other gates. */
export function remainingBudget(item: Pick<DiscoveryScheduleItem, 'max_runs' | 'reserved_runs'>): number {
  return item.max_runs - item.reserved_runs;
}

export function canOfferRevoke(item: Pick<DiscoveryScheduleItem, 'status'>, canRevoke: boolean): boolean {
  return canRevoke && item.status !== 'revoked';
}
