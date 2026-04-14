import type { ReactNode } from "react";

import { NavLink } from "@/components/nav-link";


type AppShellProps = Readonly<{
  children: ReactNode;
}>;

export function AppShell({ children }: AppShellProps) {
  return (
    <div>
      <aside>
        <h1>EngageAI</h1>
        <nav>
          <NavLink href="/dashboard" label="Dashboard" />
          <NavLink href="/campaigns" label="Campaigns" />
          <NavLink href="/analytics" label="Analytics" />
          <NavLink href="/settings" label="Settings" />
        </nav>
      </aside>
      <main>{children}</main>
    </div>
  );
}
