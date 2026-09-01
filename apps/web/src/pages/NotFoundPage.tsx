import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <section className="not-found">
      <h1>404</h1>
      <p>页面不存在，或你当前没有访问该页面的入口。</p>
      <p>
        <Link to="/overview">← 返回总览</Link>
      </p>
    </section>
  );
}
