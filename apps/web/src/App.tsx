import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from '@/components/Layout';
import OverviewPage from '@/pages/OverviewPage';
import AgentsPage from '@/pages/AgentsPage';
import AgentDetailPage from '@/pages/AgentDetailPage';
import PermissionsPage from '@/pages/PermissionsPage';
import FindingsPage from '@/pages/FindingsPage';
import PoliciesPage from '@/pages/PoliciesPage';
import ChangesPage from '@/pages/ChangesPage';
import RuntimeBindingsPage from '@/pages/RuntimeBindingsPage';
import EnvironmentsPage from '@/pages/EnvironmentsPage';
import AuditPage from '@/pages/AuditPage';
import SettingsPage from '@/pages/SettingsPage';
import NotFoundPage from '@/pages/NotFoundPage';

/**
 * 控制台路由（对齐设计文档 §20.1 信息架构）。
 * 各页已对接 Control API；API 不可达时页面降级为本地示例数据，不阻塞浏览。
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/agents/:id" element={<AgentDetailPage />} />
        <Route path="/permissions" element={<PermissionsPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route path="/changes" element={<ChangesPage />} />
        <Route path="/runtime-bindings" element={<RuntimeBindingsPage />} />
        <Route path="/environments" element={<EnvironmentsPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
