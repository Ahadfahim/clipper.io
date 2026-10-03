import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { MARKET_LABEL, PLATFORM_LABEL, ROLE_LABEL } from "@/lib/platforms";
import { useBoard, useStatus, useSwitches } from "@/api/queries";
import { useUi } from "@/state/ui";

type Node = { key: string; label: string; to?: string; search?: Record<string, unknown>; params?: Record<string, string>; count?: ReactNode; warn?: boolean; dim?: boolean; children?: Node[] };

function Row({ node, depth, active }: { node: Node; depth: number; active: (n: Node) => boolean }) {
  const open = useUi((s) => s.treeOpen[node.key] ?? true);
  const toggle = useUi((s) => s.toggleTree);
  const hasKids = Boolean(node.children?.length);
  const sel = active(node);
  const inner = (
    <>
      <span
        role={hasKids ? "button" : undefined}
        aria-label={hasKids ? (open ? `Collapse ${node.label}` : `Expand ${node.label}`) : undefined}
        onClick={(e) => {
          if (!hasKids) return;
          e.preventDefault();
          e.stopPropagation();
          toggle(node.key);
        }}
        className="w-2.5 text-[9px] text-muted"
      >
        {hasKids ? (open ? "▾" : "▸") : ""}
      </span>
      <span className="truncate-1 flex-1">{node.label}</span>
      {node.count !== undefined && node.count !== "" && <span className={cn("num text-[11px]", node.warn ? "text-warn" : "text-muted")}>{node.count}</span>}
    </>
  );
  const cls = cn(
    "mx-1 flex h-[26px] items-center gap-1.5 rounded-[var(--radius)] pr-2 outline-none",
    sel ? "bg-accent-soft" : "hover:bg-[color-mix(in_srgb,var(--fg)_6%,transparent)]",
    node.dim && "text-muted",
  );
  return (
    <li role="treeitem" aria-expanded={hasKids ? open : undefined} aria-selected={sel}>
      {node.to ? (
        <Link to={node.to} params={node.params as never} search={node.search as never} className={cls} style={{ paddingLeft: 6 + depth * 16 }}>
          {inner}
        </Link>
      ) : (
        <div className={cls} style={{ paddingLeft: 6 + depth * 16 }}>
          {inner}
        </div>
      )}
      {hasKids && open && (
        <ul role="group">
          {node.children!.map((c) => (
            <Row key={c.key} node={c} depth={depth + 1} active={active} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Left navigation tree with right-aligned counts (UI.md §2). */
export function NavTree() {
  const status = useStatus().data;
  const board = useBoard().data;
  const switches = useSwitches().data;
  const loc = useRouterState({ select: (s) => s.location });

  const sessions = (board?.slots ?? []).filter((s) => s.role && s.session_id);
  const nodes: Node[] = [
    { key: "overview", label: "Overview", to: "/" },
    {
      key: "agents",
      label: "Agents",
      to: "/agents",
      count: status ? `${status.agents_running}/${status.agents_capacity || "∞"}` : "",
      children: sessions.map((s) => ({
        key: `session-${s.session_id}`,
        label: `${ROLE_LABEL[s.role ?? ""] ?? s.role}${s.campaign_title ? ` · ${s.campaign_title}` : ""}`,
        to: "/agents",
        search: { session: s.session_id },
        count: s.priority !== null ? `P${s.priority}` : "",
      })),
    },
    {
      key: "campaigns",
      label: "Campaigns",
      to: "/campaigns",
      count: status ? Object.values(status.campaigns_by_market).reduce((a, b) => a + b, 0) : "",
      children: Object.entries(status?.campaigns_by_market ?? {}).map(([m, n]) => ({
        key: `market-${m}`,
        label: MARKET_LABEL[m] ?? m,
        to: "/campaigns",
        search: { market: m },
        count: n,
        dim: switches?.marketplaces[m]?.enabled === false,
      })),
    },
    { key: "library", label: "Library", to: "/library", count: status?.library_count },
    { key: "review", label: "Review", to: "/review", count: status?.review_pending || "", warn: Boolean(status?.review_pending) },
    {
      key: "publishing",
      label: "Publishing",
      to: "/publishing",
      children: (switches?.accounts ?? []).map((a) => ({
        key: `account-${a.id}`,
        label: `${PLATFORM_LABEL[a.platform] ?? a.platform} · ${a.handle}`,
        to: "/publishing",
        search: { tab: "accounts", account: a.id },
        count: !a.enabled ? "off" : a.status === "active" ? "" : a.status.replace("_", " "),
        warn: a.enabled && a.status !== "active",
        dim: !a.enabled || switches?.socials[a.platform]?.enabled === false,
      })),
    },
    { key: "earnings", label: "Earnings", to: "/earnings" },
  ];

  const active = (n: Node): boolean => {
    if (!n.to) return false;
    if (n.search) {
      const sp = loc.search as Record<string, unknown>;
      return loc.pathname === n.to && Object.entries(n.search).every(([k, v]) => String(sp[k]) === String(v));
    }
    if (n.to === "/") return loc.pathname === "/";
    const hasSearchChild: boolean = n.children?.some((c): boolean => Boolean(c.search) && active(c)) ?? false;
    return !hasSearchChild && (loc.pathname === n.to || loc.pathname.startsWith(`${n.to}/`)) && !(n.key === "campaigns" && "market" in (loc.search as object));
  };

  return (
    <nav aria-label="Navigation" className="flex min-h-0 flex-1 flex-col overflow-auto py-1.5">
      <ul role="tree" aria-label="Pages">
        {nodes.map((n) => (
          <Row key={n.key} node={n} depth={0} active={active} />
        ))}
        <li role="treeitem" aria-selected={false}>
          <button type="button" onClick={() => useUi.getState().openSettings()} className="mx-1 flex h-[26px] w-[calc(100%-8px)] items-center gap-1.5 rounded-[var(--radius)] pr-2 pl-1.5 text-left hover:bg-[color-mix(in_srgb,var(--fg)_6%,transparent)]">
            <span className="w-2.5" />
            Settings
          </button>
        </li>
      </ul>
    </nav>
  );
}
