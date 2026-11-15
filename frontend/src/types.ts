export type Day = {
  date: string; close: number; volume: number;
  ret_pct: number | null; mkt_ret_pct: number | null; sector_ret_pct: number | null;
  vol_mult: number | null; vol_z: number | null; beta: number | null;
  abnormal_pct: number | null; abnormal_z: number | null;
  pred: number | null; band_lo: number | null; band_hi: number | null; traj_z: number | null;
};

export type Holding = { symbol: string; name: string; sector: string; size: string; index?: string; days: Day[] };

export type ResultsRow = { metric: "revenue" | "ebitda" | "pbt" | "pat"; value: number | null; qoq: number | null; yoy: number | null };
export type ResultsCard = { period: string; source?: string; rows: ResultsRow[]; ebitda_margin?: number; margin_change_bps_yoy?: number };

export type Person = {
  name: string; role?: string; action?: string; effective?: string | null; reason?: string | null;
  profile?: string | null; background?: string; sources?: { title: string; url: string; snippet: string }[];
};

export type Filing = {
  id: string; symbol: string; ts: string; subject: string; body: string; url: string; source: string;
  category: string; subtype: string; score: number; reason: string; summary: string | null;
  extra: { results?: ResultsCard | null; people?: Person[]; move?: Partial<Day>; synthetic?: boolean; classified_by?: string };
};

export type Thresholds = {
  price_move_pct: number; volume_multiple: number; abnormal_z: number; trajectory_z: number;
  alert_categories: string[]; waterline: number;
};

export type Meta = {
  generated_at: string; synthetic: boolean; last_price_date: string | null; last_filing_ts: string | null;
  holdings: Omit<Holding, "days">[]; research_demo: string[]; thresholds: Thresholds;
  category_labels: Record<string, string>; models: Record<string, string>;
};

export type Trigger = { kind: "price" | "volume" | "abnormal" | "trajectory" | "category"; text: string };

export type Alert = {
  id: string; kind: "move" | "filing"; symbol: string; date: string; severity: number;
  headline: string; triggers: Trigger[]; day?: Day; explainedBy?: Filing[]; filing?: Filing;
};

export type Flag = { text: string; tone: "good" | "watch" | "bad" };
export type Tile = { k: string; v: number | null; unit: string };
export type Section = { tiles: Tile[]; flags?: Flag[]; series?: Record<string, (number | null)[] | string[]>; note?: string };

export type Claim = {
  id: string; doc: string; call: string; metric: string; claim: string; target?: string; horizon?: string;
  verdict: "kept" | "partial" | "missed" | "pending" | "unclear"; evidence?: string; cites?: string[]; quote?: string; page?: number;
};

export type Cited = { cite: string };
export type Research = {
  symbol: string; name: string; screener_url?: string; synthetic?: boolean; cached?: boolean; cost_usd?: number;
  headline_quarter: ResultsCard | null;
  metrics: { is_bank: boolean; basis: string; snapshot: Section; trajectory: Section; balance_sheet: Section; cash_quality: Section };
  sources?: { id: string; label: string; url: string; pages: number }[];
  ledger?: { status: string; claims: Claim[]; score?: number | null; counts?: Record<string, number> };
  synthesis?: {
    status: string;
    business?: { one_liner?: string; segments: ({ name: string; share?: string; note: string } & Cited)[] };
    guidance?: ({ metric: string; what: string } & Cited)[];
    narrative_vs_numbers?: ({ says: string; numbers: string; verdict: string } & Cited)[];
    bull?: ({ point: string } & Cited)[]; bear?: ({ point: string } & Cited)[];
    watch_next?: string; dropped_uncited?: number;
  };
};
