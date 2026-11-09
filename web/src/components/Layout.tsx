/**
 * SASAA – App Shell Layout
 * Renders the sidebar + main content wrapper.
 * Active route is detected from the current pathname.
 */

import {
  AlertTriangle,
  BarChart3,
  Bell,
  Inbox,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const NAV_ITEMS = [
  { icon: LayoutDashboard, label: 'Dashboard',      href: '/' },
  { icon: Inbox,           label: 'Voice Messages', href: '/messages' },
  { icon: ShieldCheck,     label: 'Verification',   href: '/verification' },
  { icon: AlertTriangle,   label: 'Alerts',         href: '/alerts' },
  { icon: BarChart3,       label: 'Analytics',      href: '/analytics' },
  { icon: Settings,        label: 'Settings',       href: '/settings' },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const location = useLocation();

  const initials = user?.full_name
    ? user.full_name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase()
    : user?.email?.slice(0, 2).toUpperCase() ?? 'SA';

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark small-mark">S</div>
          <div>
            <strong>SASAA</strong>
            <span>VOICE NOTE GUARDIAN</span>
          </div>
        </div>

        <div className="nav-label">WORKSPACE</div>

        {NAV_ITEMS.map(({ icon: Icon, label, href }) => {
          const active =
            href === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(href);
          return (
            <Link
              key={href}
              to={href}
              className={`nav-item${active ? ' active' : ''}`}
            >
              <Icon size={14} style={{ marginRight: 9 }} />
              {label}
            </Link>
          );
        })}

        <div className="sidebar-bottom">
          <div className="secure-note">
            <ShieldCheck size={12} style={{ marginRight: 7, verticalAlign: 'middle' }} />
            Your voice. Protected.
          </div>

          {/* User chip */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 9,
              padding: '10px 12px',
              marginBottom: 8,
              background: '#1a1728',
              borderRadius: 9,
            }}
          >
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 9,
                background: 'linear-gradient(135deg, #ae56fa, #5740e9)',
                display: 'grid',
                placeItems: 'center',
                fontSize: 11,
                fontWeight: 800,
                color: 'white',
                flexShrink: 0,
              }}
            >
              {initials}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user?.full_name ?? user?.email}
              </div>
              <div style={{ fontSize: 10, color: '#8d829f', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user?.email}
              </div>
            </div>
          </div>

          <button className="nav-item" onClick={logout}>
            <LogOut size={14} style={{ marginRight: 9 }} />
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="main-content">
        <header className="topbar">
          <div>
            <span className="eyebrow">SASAA WORKSPACE</span>
            <h2 style={{ margin: 0, fontSize: 20 }}>
              {NAV_ITEMS.find((n) =>
                n.href === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(n.href),
              )?.label ?? 'Dashboard'}
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Link to="/alerts" style={{ position: 'relative', color: 'inherit', textDecoration: 'none' }}>
              <Bell size={18} color="#a49bb7" />
            </Link>
            <div className="user-chip">
              <span className="online-dot" />
              Guardian active
            </div>
          </div>
        </header>

        {children}

        <footer style={{ marginTop: 60, paddingTop: 20, borderTop: '1px solid #1e1a2b', color: '#5e5670', fontSize: 11, textAlign: 'center' }}>
          © 2026 SASAA · AI Voice Note Guardian · Version 1.0
        </footer>
      </main>
    </div>
  );
}
