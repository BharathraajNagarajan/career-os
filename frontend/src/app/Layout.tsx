import { Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="shell">
      <header className="shell-header">
        <span className="wordmark">Career OS</span>
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
      <footer className="shell-footer">Created by Bharathraaj Nagarajan</footer>
    </div>
  );
}
