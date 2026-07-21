import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LayoutDashboard, ClipboardList, Wallet, FileDown, BookUser, Banknote, Landmark, ShoppingBag, Truck, HandCoins, FileText, ArrowLeftRight, ShieldAlert, LogOut } from "lucide-react";
import InstallPrompt from "./InstallPrompt";
import { useAuth } from "../lib/auth";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/orders", label: "Orders", icon: ClipboardList, testId: "nav-orders" },
  { to: "/sales-payments", label: "Sales Payments", icon: Banknote, testId: "nav-sales-payments" },
  { to: "/purchases", label: "Purchases", icon: ShoppingBag, testId: "nav-purchases" },
  { to: "/purchase-payments", label: "Purchase Payments", icon: HandCoins, testId: "nav-purchase-payments" },
  { to: "/vendors", label: "Vendors", icon: Truck, testId: "nav-vendors" },
  { to: "/payments", label: "Cash Book", icon: Wallet, testId: "nav-payments" },
  { to: "/transfers", label: "Transfers", icon: ArrowLeftRight, testId: "nav-transfers" },
  { to: "/party-ledger", label: "Party Ledger", icon: BookUser, testId: "nav-party-ledger" },
  { to: "/accounts", label: "Accounts", icon: Landmark, testId: "nav-accounts" },
  { to: "/quotations", label: "Quotations", icon: FileText, testId: "nav-quotations" },
  { to: "/exports", label: "Exports", icon: FileDown, testId: "nav-exports" },
];

const adminNav = [
  { to: "/settings/admin/data-management", label: "Data Management", icon: ShieldAlert, testId: "admin-controls-nav-link" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const nav_ = useNavigate();
  const isAdmin = user?.role === "admin";

  const doLogout = async () => {
    await logout();
    nav_("/login", { replace: true });
  };

  return (
    <div className="App min-h-screen" data-testid="app-shell">
      <div className="flex min-h-screen">
        {/* Sidebar */}
        <aside
          className="hidden md:flex md:w-64 border-r bg-white/60 flex-col"
          style={{ borderColor: "var(--border-warm)" }}
          data-testid="sidebar"
        >
          <div className="px-7 pt-10 pb-8">
            <div className="label-caps mb-2">Personal ledger</div>
            <h1 className="serif text-4xl leading-none" style={{ color: "var(--ink)" }}>
              Artisan
              <span style={{ color: "var(--terracotta)" }}>.</span>
            </h1>
            <p className="text-xs mt-2" style={{ color: "var(--muted)" }}>
              Profit & Loss workbook
            </p>
          </div>

          <nav className="px-4 flex-1 space-y-1 overflow-y-auto">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                data-testid={n.testId}
                end={n.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
                    isActive
                      ? "bg-[var(--surface-alt)] text-[var(--ink)] font-medium"
                      : "text-[var(--muted)] hover:text-[var(--ink)] hover:bg-[var(--surface-alt)]"
                  }`
                }
              >
                <n.icon size={16} strokeWidth={1.75} />
                <span>{n.label}</span>
              </NavLink>
            ))}

            {isAdmin && (
              <>
                <div className="label-caps px-3 pt-6 pb-1 text-[10px]" data-testid="admin-section-heading">
                  Settings · Admin
                </div>
                {adminNav.map((n) => (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    data-testid={n.testId}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors ${
                        isActive
                          ? "bg-[var(--surface-alt)] text-[var(--danger)] font-medium"
                          : "text-[var(--muted)] hover:text-[var(--danger)] hover:bg-[var(--surface-alt)]"
                      }`
                    }
                  >
                    <n.icon size={16} strokeWidth={1.75} />
                    <span>{n.label}</span>
                  </NavLink>
                ))}
              </>
            )}
          </nav>

          <div className="px-4 pb-4">
            <InstallPrompt />
          </div>

          {/* User + logout */}
          {user && (
            <div className="px-7 py-4 border-t text-xs" style={{ borderColor: "var(--border-warm)" }}>
              <div className="flex items-center justify-between">
                <div className="min-w-0">
                  <div className="serif text-sm truncate" data-testid="sidebar-user-email">{user.email}</div>
                  <div style={{ color: "var(--muted)" }}>{user.role}</div>
                </div>
                <button onClick={doLogout} data-testid="sidebar-logout-btn"
                        className="p-1.5 rounded hover:bg-[var(--surface-alt)]"
                        title="Sign out">
                  <LogOut size={14} strokeWidth={1.75} />
                </button>
              </div>
            </div>
          )}
          <div className="px-7 py-3 text-xs" style={{ color: "var(--muted)" }}>
            <div className="serif text-lg" style={{ color: "var(--ink)" }}>Ledger since Apr '24</div>
            <div className="mt-1">Made for your workshop</div>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 min-w-0">
          {/* Mobile top nav — deliberately excludes admin controls (never in quick-actions) */}
          <div className="md:hidden border-b px-4 py-4 flex items-center justify-between"
               style={{ borderColor: "var(--border-warm)" }}>
            <h1 className="serif text-2xl">Artisan<span style={{ color: "var(--terracotta)" }}>.</span></h1>
            <div className="flex gap-1">
              {nav.map((n) => (
                <NavLink key={n.to} to={n.to} end={n.to === "/"} data-testid={`m-${n.testId}`}
                         className={({ isActive }) =>
                           `p-2 rounded-md ${isActive ? "bg-[var(--surface-alt)]" : ""}`
                         }>
                  <n.icon size={18} strokeWidth={1.75} />
                </NavLink>
              ))}
            </div>
          </div>

          <div className="px-6 md:px-12 pt-10 md:pt-14 pb-16 max-w-[1400px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
