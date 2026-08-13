import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <section className="not-found">
      <h1>404</h1>
      <p>页面不存在或尚未纳入信息架构（设计文档 §20.1）。</p>
      <p>
        <Link to="/overview">← 返回总览</Link>
      </p>
    </section>
  );
}
