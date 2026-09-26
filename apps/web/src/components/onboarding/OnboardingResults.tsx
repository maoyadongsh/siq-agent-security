import type { OnboardingStatus } from '@/api/onboarding';

const scanLabels = { pending: '等待设备执行', uploaded: '已上报，等待完成回执', delivered: '已完成发现', failed: '发现失败', expired: '任务已过期' };

export default function OnboardingResults({ progress }: { progress: OnboardingStatus }) {
  const online = progress.devices.filter(device => device.status === 'online').length;
  return <div aria-label="自动接入结果">
    <h3>接入结果</h3>
    <p>已注册 {progress.device_count} 台设备；当前列表中 {online} 台最近心跳正常。</p>
    {progress.device_count === 0 ? <p>尚未收到设备注册。请在目标 Linux 设备完成可信安装器的范围确认；在 Mac 浏览器打开本页不会自动安装到 Linux。</p>
      : online === 0 ? <p>尚未确认在线设备，请检查目标设备的后台服务。不要重复注册已有设备。</p>
        : <p>已收到设备心跳。已确认安装范围的后台服务会申请首扫；无需另开终端手动领取任务。</p>}
    {progress.devices_truncated ? <p>仅显示最近 100 台设备，在线数量不是环境完整统计。</p> : null}
    <h3>近期发现</h3>
    {progress.scans.length ? <ul>{progress.scans.map(scan => <li key={scan.id}>
      <strong>{scan.connector}：{scanLabels[scan.status]}</strong>
      {scan.status === 'delivered' && scan.candidate_count !== null ? <span> · 回执报告 {scan.candidate_count} 个对象。{scan.candidate_count === 0 ? '请核对框架配置和已确认范围，不据此认定软件未安装。' : '可进入资产清单评审，尚未自动纳管。'}</span> : null}
      {scan.status === 'failed' || scan.status === 'expired' ? <span> · 历史资产保留，请检查安装服务及采集范围，不会自动扩大范围或重提任务。</span> : null}
    </li>)}</ul> : <p>尚未收到发现任务记录。设备已在线时，请核对安装计划范围确认和后台服务；不要将此状态理解为没有智能体。</p>}
    {progress.scans_truncated ? <p>仅展示最近 20 个任务，不代表完整扫描历史。</p> : null}
    <p>已保存 {progress.evidence_count} 条发现证据。接入和发现不表示业务权限已批准或运行时防御已生效。</p>
    <p>状态核验时间：{new Date(progress.evaluated_at).toLocaleString('zh-CN', { hour12: false })}</p>
  </div>;
}
