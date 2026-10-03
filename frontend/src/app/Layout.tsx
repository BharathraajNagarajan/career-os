import { Link, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="shell">
      <header className="shell-header">
        <span className="wordmark">Career OS</span>{" "}
        <nav aria-label="Main" className="shell-nav">
          <Link to="/profile">Profile</Link> <Link to="/resumes">Resumes</Link>{" "}
          <Link to="/lanes">Lanes</Link> <Link to="/opportunities">Opportunities</Link>{" "}
          <Link to="/applications">Applications</Link> <Link to="/companies">Companies</Link>{" "}
          <Link to="/review">Review</Link> <Link to="/settings">Settings</Link>
        </nav>
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
      <footer className="shell-footer">Created by Bharathraaj Nagarajan</footer>
    </div>
  );
}
