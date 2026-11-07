import type * as React from 'react';
export type Lang = 'en' | 'no';
export interface LonewatchData {
  isExample: boolean; defaultLang: Lang;
  counts: { evaluated: number | null; red: number | null; blocked: number | null; allowed: number | null; waitingForHuman: number | null; followedUp: number | null };
  agents: { id: string; name: Record<Lang, string>; actions: number | null; red: number | null; blocked: number | null; allowed: number | null }[];
  logChain: { status: 'ok' | 'broken' | null; checkedAt?: string | null };
  sandbox: { tested: number | null; blocked: number | null };
  log: { status: 'ok' | 'broken' | null };
  chartShapes: { data: number[]; ghost?: number[]; marks?: number[] }[];
  text: Record<Lang, Record<string, any>>;
}
export type Tab = 'overview' | 'before' | 'under' | 'after' | 'custom';
export interface DashboardProps { data?: LonewatchData; lang?: Lang; onLangChange?: (lang: Lang) => void; onNavigate?: (tab: Tab) => void; bare?: boolean }
export declare function Dashboard(props: DashboardProps): React.ReactElement;
export interface SidebarProps { lang?: Lang; data?: LonewatchData; active?: number; onLangChange?: (lang: Lang) => void; onNavigate?: (tab: Tab) => void }
export declare function Sidebar(props: SidebarProps): React.ReactElement;
export interface LanguageToggleProps { value?: Lang; onChange?: (lang: Lang) => void; vertical?: boolean; label?: string }
export declare function LanguageToggle(props: LanguageToggleProps): React.ReactElement;
export interface PromoCardProps { title: React.ReactNode; text: React.ReactNode; cta?: React.ReactNode; onCta?: () => void; art?: React.ReactNode }
export declare function PromoCard(props: PromoCardProps): React.ReactElement;
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> { variant?: 'primary' | 'quiet'; icon?: string | false }
export declare function Button(props: ButtonProps): React.ReactElement;
export interface PanelProps { title?: React.ReactNode; subtitle?: React.ReactNode; action?: React.ReactNode; className?: string; style?: React.CSSProperties; children?: React.ReactNode }
export declare function Panel(props: PanelProps): React.ReactElement;
export interface StatCardProps { title: React.ReactNode; value: React.ReactNode; rows?: { label: React.ReactNode; value: React.ReactNode }[]; data: number[]; ghost?: number[]; color?: string; marks?: number[] }
export declare function StatCard(props: StatCardProps): React.ReactElement;
export interface ProgressStatProps { icon?: 'alert' | 'check' | 'shield' | string; label: React.ReactNode; value: React.ReactNode; progress: number }
export declare function ProgressStat(props: ProgressStatProps): React.ReactElement;
export interface AgentRow { id?: string; name: string; actions: number | null; red: number | null; blocked: number | null; allowed: number | null }
export interface AgentTableProps { columns: string[]; rows: AgentRow[]; lang?: Lang }
export declare function AgentTable(props: AgentTableProps): React.ReactElement;
export interface StatusRingProps { status: 'ok' | 'broken' | null; display: React.ReactNode; label: string; size?: number }
export declare function StatusRing(props: StatusRingProps): React.ReactElement;
export interface StatusRowsProps { rows: { label: React.ReactNode; status: React.ReactNode }[] }
export declare function StatusRows(props: StatusRowsProps): React.ReactElement;
export declare function ExampleTag(props: { children?: React.ReactNode }): React.ReactElement;
export interface GlassObjectProps { size?: number; className?: string }
export declare function GlassObject(props: GlassObjectProps): React.ReactElement;
declare global { interface Window { Lonewatch: { Dashboard: typeof Dashboard; Sidebar: typeof Sidebar; LanguageToggle: typeof LanguageToggle; PromoCard: typeof PromoCard; Button: typeof Button; Panel: typeof Panel; StatCard: typeof StatCard; ProgressStat: typeof ProgressStat; AgentTable: typeof AgentTable; StatusRing: typeof StatusRing; StatusRows: typeof StatusRows; ExampleTag: typeof ExampleTag; GlassObject: typeof GlassObject; data: LonewatchData; setData(next: LonewatchData): void } } }
