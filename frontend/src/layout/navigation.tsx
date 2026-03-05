/* eslint-disable react-refresh/only-export-components */
import type { ReactElement, SVGProps } from "react";

export type NavItem = {
  label: string;
  path: string;
  icon: (props: SVGProps<SVGSVGElement>) => ReactElement;
};

export type NavSection = {
  title: string;
  items: NavItem[];
};

const baseIconProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  viewBox: "0 0 24 24",
  "aria-hidden": true
} as const;

function HomeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10.5V20h14v-9.5" />
    </svg>
  );
}

function UsersIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M16.5 20a4.5 4.5 0 0 0-9 0" />
      <circle cx="12" cy="9" r="3" />
      <path d="M20.5 20a3.5 3.5 0 0 0-3.5-3.5" />
      <path d="M17 7.5a2.5 2.5 0 1 1 0 5" />
    </svg>
  );
}

function ShieldIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M12 3 4.5 6v5.5C4.5 16.5 8 20 12 21c4-1 7.5-4.5 7.5-9.5V6L12 3Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

function CpuIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <rect x="7" y="7" width="10" height="10" rx="2" />
      <path d="M9.5 1.5V5M14.5 1.5V5M9.5 19V22.5M14.5 19V22.5M1.5 9.5H5M1.5 14.5H5M19 9.5h3.5M19 14.5h3.5" />
    </svg>
  );
}

function ChatIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M6 17.5h9l4 3v-3a4.5 4.5 0 0 0 3-4.2V8a4.5 4.5 0 0 0-4.5-4.5H6A4.5 4.5 0 0 0 1.5 8v5A4.5 4.5 0 0 0 6 17.5Z" />
    </svg>
  );
}

function DocumentIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M7 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1-1.4Z" />
      <path d="M14 3.5V8h4" />
    </svg>
  );
}

function PlugIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M8 3.5v6M16 3.5v6M6 9.5h12v1a6 6 0 0 1-6 6h0a6 6 0 0 1-6-6v-1Z" />
      <path d="M12 16v4.5" />
    </svg>
  );
}

function BotIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <rect x="5" y="7" width="14" height="12" rx="3" />
      <path d="M12 3v4M9 13h0M15 13h0M8 17h8" />
    </svg>
  );
}

function HammerIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="m5 20 9-9" />
      <path d="m12 4 8 8-2 2-8-8 2-2Z" />
      <path d="M3 22 1.5 20.5 10 12" />
    </svg>
  );
}

function GovernanceIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...baseIconProps} {...props}>
      <path d="M12 3 3.5 7v5.5C3.5 17.7 7.1 21 12 22c4.9-1 8.5-4.3 8.5-9.5V7L12 3Z" />
      <path d="M8.5 12h7M12 8.5v7" />
    </svg>
  );
}

export const navigationSections: NavSection[] = [
  {
    title: "Overview",
    items: [{ label: "Dashboard", path: "/", icon: HomeIcon }]
  },
  {
    title: "Administration",
    items: [
      { label: "Users", path: "/admin/users", icon: UsersIcon },
      { label: "Groups", path: "/admin/groups", icon: UsersIcon },
      { label: "Roles", path: "/admin/roles", icon: ShieldIcon },
      { label: "Policies", path: "/admin/policies", icon: ShieldIcon },
      { label: "AI Models", path: "/settings/ai-models", icon: CpuIcon },
      { label: "Workspace", path: "/settings/workspace", icon: ShieldIcon }
    ]
  },
  {
    title: "Knowledge",
    items: [
      { label: "Chat", path: "/chat", icon: ChatIcon },
      { label: "Documents", path: "/documents", icon: DocumentIcon },
      { label: "Health", path: "/knowledge/health", icon: DocumentIcon }
    ]
  },
  {
    title: "Connectors",
    items: [
      { label: "Connectors Hub", path: "/connectors", icon: PlugIcon },
      { label: "Google Workspace", path: "/connectors/google-workspace", icon: PlugIcon },
      { label: "Channels", path: "/channels", icon: PlugIcon }
    ]
  },
  {
    title: "Agents",
    items: [
      { label: "Agent Catalog", path: "/agents", icon: BotIcon },
      { label: "Agent Builder", path: "/agent-builder", icon: HammerIcon },
      { label: "Recipes", path: "/recipes", icon: HammerIcon }
    ]
  },
  {
    title: "Governance",
    items: [{ label: "Governance", path: "/governance", icon: GovernanceIcon }]
  }
];
