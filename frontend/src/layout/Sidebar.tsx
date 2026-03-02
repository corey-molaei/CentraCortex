import { NavLink, useLocation } from "react-router-dom";
import { cn } from "../components/ui/cn";
import { navigationSections, type NavItem } from "./navigation";

type SidebarProps = {
  open: boolean;
  desktopOpen: boolean;
  onClose: () => void;
};

function isItemActive(pathname: string, item: NavItem) {
  if (item.path === "/") {
    return pathname === "/";
  }
  return pathname.startsWith(item.path);
}

export function Sidebar({ open, desktopOpen, onClose }: SidebarProps) {
  const location = useLocation();

  return (
    <>
      <div
        aria-hidden={!open}
        className={cn(
          "fixed inset-0 z-30 bg-black/50 transition md:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0"
        )}
        onClick={onClose}
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-white/10 bg-ink/95 p-5 transition-transform md:sticky md:top-0 md:h-screen",
          open ? "translate-x-0" : "-translate-x-full",
          desktopOpen ? "md:translate-x-0" : "md:hidden"
        )}
      >
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-indigo-300">TailAdmin</p>
            <h1 className="text-xl font-bold text-white">CentraCortex</h1>
          </div>
          <button className="rounded-md border border-white/10 px-2 py-1 text-sm md:hidden" onClick={onClose} type="button">
            Close
          </button>
        </div>

        <nav className="space-y-5 overflow-y-auto pr-1">
          {navigationSections.map((section) => (
            <div key={section.title}>
              <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">{section.title}</p>
              <ul className="space-y-1">
                {section.items.map((item) => {
                  const active = isItemActive(location.pathname, item);
                  const Icon = item.icon;
                  return (
                    <li key={item.path}>
                      <NavLink
                        className={cn(
                          "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                          active
                            ? "bg-accent text-white shadow-[0_0_0_1px_rgba(255,255,255,0.08)]"
                            : "text-slate-200 hover:bg-white/10"
                        )}
                        onClick={onClose}
                        to={item.path}
                      >
                        <Icon className="h-4 w-4" />
                        <span>{item.label}</span>
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
    </>
  );
}
