export type AttentionLevelTone = 'priority' | 'reinforced' | 'review' | 'standard' | 'unknown';
export type ConfidenceLevelTone = 'high' | 'medium' | 'limited' | 'unknown';
export type WorklistViewMode = 'compact' | 'comfortable';
export type SortDirection = 'asc' | 'desc';

export interface ClaimSummary {
  claim_sk: number;
  claim_root_id: string;
  claim_business_id: string | null;
  claim_date: string | null;
  client_label: string | null;
  vehicle_label: string | null;
  agency_label: string | null;
  region_label: string | null;
  claim_amount: number | null;
  attention_score: number;
  attention_level: string;
  attention_tone: AttentionLevelTone;
  main_reason: string | null;
  confidence_level: string;
  confidence_tone: ConfidenceLevelTone;
  assignee_label: string | null;
  workflow_status: string | null;
  age_days: number | null;
  guarantee_label: string | null;
  claim_type_label: string | null;
  business_validation_status: string | null;
  has_ml_signal: boolean;
  has_post_inspection_signal: boolean;
  score_version?: string;
  score_run_id?: string | null;
  created_at?: string | null;
}

export interface WorklistFilters {
  scoreVersion: string;
  search?: string;
  attentionLevel?: string;
  confidenceLevel?: string;
  validationStatus?: string;
  hasMl?: boolean;
  hasPostInspection?: boolean;
  page: number;
  pageSize: number;
  sortBy: string;
  sortDirection: SortDirection;
  viewMode: WorklistViewMode;
  includeTotal?: boolean;
}

export interface WorklistOption {
  value: string;
  label: string;
}

