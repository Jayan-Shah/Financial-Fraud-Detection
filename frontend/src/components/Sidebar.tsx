import { LayoutDashboard, Activity, BarChart3, ShieldCheck, LogOut, Radio } from "lucide-react";

export type Tab = "overview" | "live" | "reports" | "admin";

interface SidebarProps {
  activeTab: Tab;
  onNavigate: (tab: Tab) => void;
  role: string | null;
  orgName: string | null;
  userEmail: string | null;
  connected: boolean;
  onSignOut: () => void;
}

const NAV_ITEMS: { id: Tab; label: string; icon: typeof LayoutDashboard; adminOnly?: boolean }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "live", label: "Live Feed", icon: Activity },
  { id: "reports", label: "Reports", icon: BarChart3 },
  { id: "admin", label: "Rules Admin", icon: ShieldCheck, adminOnly: true },
];

export function Sidebar({ activeTab, onNavigate, role, orgName, userEmail, connected, onSignOut }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">
          <ShieldCheck size={20} strokeWidth={2.5} />
        </div>
        <div className="brand-text">
          <span className="brand-name">Sentinel</span>
          <span className="brand-tagline">Fraud Intelligence</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.filter((item) => !item.adminOnly || role === "compliance_admin").map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`sidebar-nav-item ${activeTab === item.id ? "active" : ""}`}
              onClick={() => onNavigate(item.id)}
            >
              <Icon size={17} strokeWidth={2} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar-status">
        <Radio size={13} className={connected ? "pulse-live" : "pulse-down"} />
        <span>{connected ? "Live" : "Reconnecting..."}</span>
      </div>

      <div className="sidebar-footer">
        <div className="sidebar-org">
          <span className="org-name">{orgName ?? "..."}</span>
          <span className="org-user">{userEmail}</span>
        </div>
        <button className="sidebar-signout" onClick={onSignOut} title="Sign out">
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  );
}
