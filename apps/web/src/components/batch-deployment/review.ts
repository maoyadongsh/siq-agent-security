import { readChangeReview, type ChangeReview } from '@/api/changeReview';
import type { DeploymentPreview } from '@/api/deploymentPreview';

/** Content inspection only: this does not prove shared runtime impact or grant execution authority. */
export async function readBatchItemReview(item: DeploymentPreview): Promise<ChangeReview> {
  const review = await readChangeReview(item.change_id);
  if (review.change_id !== item.change_id || review.policy_version !== item.policy_version
    || review.policy_name !== item.policy_name || review.enforcement_mode !== item.enforcement_mode
    || !['approved', 'emergency_applied'].includes(review.status)) {
    throw new Error('变更状态或策略版本与批次预览不一致，请重新生成预览。');
  }
  if (review.sections.some(section => section.redacted || section.truncated)) {
    throw new Error('权限内容包含隐藏或截断部分，无法完整审阅；请先核对变更。');
  }
  return review;
}
