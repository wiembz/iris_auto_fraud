import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { SortDirection } from '../models/claim-summary.model';

export interface AttentionDistributionItem {
  attention_level: string;
  claims: number;
}

export interface ConfidenceDistributionItem {
  confidence_level: string;
  claims: number;
}

export interface ClaimListItem {
  claim_sk: number;
  claim_root_id?: string | null;
  claim_business_id: string | null;
  numero_sinistre?: string | null;
  code_garantie?: string | null;
  claim_date?: string | null;
  client_label?: string | null;
  vehicle_label?: string | null;
  agency_label?: string | null;
  region_label?: string | null;
  claim_amount?: number | null;
  attention_score: number;
  attention_level: string;
  confidence_level: string;
  main_reason_1?: string | null;
  main_reason_2?: string | null;
  main_reason_3?: string | null;
  assignee_label?: string | null;
  workflow_status?: string | null;
  age_days?: number | null;
  guarantee_label?: string | null;
  claim_type_label?: string | null;
  business_validation_status?: string | null;
  score_version?: string;
  score_run_id?: string | null;
  created_at?: string | null;
  has_ml_signal?: boolean;
  has_post_inspection_signal?: boolean;
  validation_status?: ClaimDecisionValue | null;
  validation_decided_at?: string | null;
  validation_reviewer_email?: string | null;
}

export interface FinancialExposureItem {
  attention_level: string;
  claims: number;
  total_amount: number;
  avg_amount: number;
}

export interface GuaranteeBreakdownItem {
  code_garantie: string;
  claims: number;
  priority_claims: number;
  total_amount: number;
}

export interface MonthlyTrendItem {
  month: string;
  claims: number;
  priority_claims: number;
}

export interface ReasonDistributionItem {
  reason: string;
  claims: number;
}

export interface ValidationCoverage {
  total_claims: number;
  decided_claims: number;
  suspicion_confirmed: number;
  conforme: number;
  a_completer: number;
}

export interface PortfolioInsightsResponse {
  score_version: string;
  score_run_id: string | null;
  financial_exposure: FinancialExposureItem[];
  guarantee_breakdown: GuaranteeBreakdownItem[];
  monthly_trend: MonthlyTrendItem[];
  reason_distribution: ReasonDistributionItem[];
  validation_coverage: ValidationCoverage | null;
}

export interface SummaryResponse {
  score_version: string;
  score_run_id: string | null;
  total_claims: number;
  attention_distribution: AttentionDistributionItem[];
  confidence_distribution: ConfidenceDistributionItem[];
  top_claims: ClaimListItem[];
  cache?: {
    hit: boolean;
    ttl_seconds: number;
  };
}

export interface ClaimsResponse {
  score_version: string;
  score_run_id: string | null;
  page: number;
  page_size: number;
  total: number;
  has_next?: boolean;
  total_is_exact?: boolean;
  items: ClaimListItem[];
}

export interface ClaimReviewClaim {
  claim_sk: number;
  claim_business_id: string | null;
  numero_sinistre?: string | null;
  code_garantie?: string | null;
  attention_score: number;
  attention_level: string;
  confidence_level: string;
  main_reason_1?: string | null;
  main_reason_2?: string | null;
  main_reason_3?: string | null;
  claim_date?: string | null;
  declaration_date?: string | null;
  contract_start_date?: string | null;
  claim_amount?: number | string | null;
  client_claim_count_12m?: number | null;
  client_claim_count_24m?: number | null;
  days_claim_to_declaration?: number | null;
  days_contract_start_to_claim?: number | null;
  missing_keys_count?: number | null;
  unknown_dimensions_count?: number | null;
  missing_vehicle_flag?: boolean | number | null;
  vehicle_recurrence_ready_flag?: boolean | number | null;
  score_version?: string;
  score_run_id?: string | null;
  created_at?: string | null;
  confidence_explanation?: string;
}

export interface ClaimReviewSignal {
  signal_family: string;
  signal_code: string;
  signal_label: string;
  signal_value?: string | number | null;
  points: number;
  severity?: string | null;
  business_explanation?: string | null;
}

export interface ClaimTimelineEvent {
  event_type: string;
  event_date: string | null;
  description?: string | null;
  business_explanation?: string | null;
}

export interface ClaimPostInspectionItem {
  inspection_sk?: number | null;
  scenario_label?: string | null;
  inspection_date?: string | null;
  claim_date?: string | null;
  days_inspection_to_claim?: number | null;
  delay_bucket?: string | null;
  defective_zone?: string | null;
  defective_checkpoint_count?: number | null;
  critical_checkpoint_count?: number | null;
  representative_checkpoint_labels?: string | null;
  claim_area?: string | null;
  zone_match_status?: string | null;
  attention_level?: string | null;
  confidence_level?: string | null;
  business_explanation?: string | null;
  immatriculation?: string | null;
}

export interface ClaimMlAnomaly {
  anomaly_percentile_score?: number | null;
  score_ml?: number | null;
  ml_attention_points?: number | null;
  ml_attention_level?: string | null;
  top_variable_1?: string | null;
  top_variable_2?: string | null;
  top_variable_3?: string | null;
}

export interface ClaimVehicleContext {
  vehicle_sk?: number | null;
  missing_vehicle_flag?: boolean | number | null;
  vehicle_recurrence_ready_flag?: boolean | number | null;
  immatriculation?: string | null;
  post_inspection_signal_count?: number | null;
}

export interface ClaimReviewResponse {
  claim: ClaimReviewClaim;
  signals: { items: ClaimReviewSignal[] };
  timeline: { items: ClaimTimelineEvent[] };
  post_inspection: { items: ClaimPostInspectionItem[] };
  ml_anomaly: ClaimMlAnomaly | null;
  vehicle: ClaimVehicleContext | null;
  checklist?: string[];
}

export type ClaimDecisionValue = 'SUSPICION_CONFIRMED' | 'CONFORME' | 'A_COMPLETER';

export interface ClaimDecisionInput {
  decision: ClaimDecisionValue;
  comment?: string;
  reviewerEmail: string;
  reviewerRole?: string;
  scoreVersion?: string;
}

export interface ClaimDecisionRecord {
  decision_id: number;
  claim_sk: number;
  claim_business_id?: string | null;
  attention_level?: string | null;
  attention_score?: number | null;
  score_version: string;
  score_run_id: string | null;
  decision: ClaimDecisionValue;
  comment: string | null;
  reviewer_email: string;
  reviewer_role: string | null;
  decided_at: string;
  created_at?: string;
  corrects_decision_id?: number | null;
  corrected_decision_value?: ClaimDecisionValue | null;
}

export type VhsDecision = 'OK' | 'DEGRADE' | 'CRITIQUE' | 'IMMOBILISE';

export interface VhsDecisionDistributionItem {
  decision: VhsDecision;
  vehicles: number;
  average_score: number;
}

export interface VhsScoreBand {
  band_start: number;
  vehicles: number;
}

export interface VhsZonePenalty {
  zone_controle: string;
  penalty_count: number;
  total_penalty: number;
  critical_count: number;
}

export interface VhsOverviewResponse {
  run_id: string | null;
  total_vehicles: number;
  average_score: number | null;
  not_drivable: number;
  with_critical_anomalies: number;
  decision_distribution: VhsDecisionDistributionItem[];
  grade_distribution: { safety_grade: string; vehicles: number }[];
  score_bands: VhsScoreBand[];
  zone_penalties: VhsZonePenalty[];
}

export interface VhsVehicleItem {
  vhs_score_sk: number;
  inspection_key: string;
  vehicule_sk: number;
  immatriculation_norm: string;
  date_inspection_sk: number;
  kilometrage: number | null;
  vhs_final_score: number;
  safety_score: number | null;
  functional_score: number | null;
  cosmetic_score: number | null;
  safety_grade: string;
  decision: VhsDecision;
  is_drivable: boolean;
  hard_cap_applied: boolean;
  hard_cap_type: string | null;
  nb_anomalies_total: number;
  nb_anomalies_critiques: number;
  nb_checkpoints_scored: number;
  nb_ok: number;
  nb_worn: number;
  nb_worn_strong: number;
  nb_broken: number;
  total_penalty?: number;
  nb_systems_penalized?: number;
  penalty_raw_before_cap?: number;
  penalty_after_system_cap?: number;
}

export interface VhsPenaltyItem {
  checkpoint_code: string;
  checkpoint_libelle: string;
  zone_controle: string | null;
  observed_value: string | null;
  observed_status: string | null;
  penalty_applied: number;
  penalty_reason: string | null;
  tier: string | null;
  is_vital: boolean | null;
  is_immobilizing: boolean | null;
  is_hard_cap_trigger: boolean | null;
  est_anomalie_critique: boolean | null;
  systeme_fonctionnel?: string | null;
  penalty_raw_checkpoint?: number;
  penalty_capped_by_system?: boolean | null;
}

export interface VhsInspectionDetail extends VhsVehicleItem {
  run_id: string;
  penalties: VhsPenaltyItem[];
  nom_agent_inspection?: string | null;
  nom_personne_inspection?: string | null;
  telephone_personne_inspection?: string | null;
  vin?: string | null;
  motorisation?: string | null;
  numero_commande_travaux?: string | null;
  heure_entree?: string | null;
  horodateur?: string | null;
}

export interface ClaimFilters {
  scoreVersion: string;
  attentionLevel?: string;
  confidenceLevel?: string;
  validationStatus?: string;
  search?: string;
  hasMl?: boolean;
  hasPostInspection?: boolean;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortDirection?: SortDirection;
  includeTotal?: boolean;
}

@Injectable({ providedIn: 'root' })
export class IrisApiService {
  private readonly http = inject(HttpClient);
  private readonly apiBaseUrl = 'http://127.0.0.1:5000/api';

  getSummary(scoreVersion = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'): Observable<SummaryResponse> {
    const params = new HttpParams().set('score_version', scoreVersion);
    return this.http.get<SummaryResponse>(`${this.apiBaseUrl}/summary`, { params });
  }

  getPortfolioInsights(
    scoreVersion = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'
  ): Observable<PortfolioInsightsResponse> {
    const params = new HttpParams().set('score_version', scoreVersion);
    return this.http.get<PortfolioInsightsResponse>(`${this.apiBaseUrl}/portfolio/insights`, { params });
  }

  getClaimReview(
    claimSk: number,
    scoreVersion = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'
  ): Observable<ClaimReviewResponse> {
    const params = new HttpParams().set('score_version', scoreVersion);
    return this.http.get<ClaimReviewResponse>(`${this.apiBaseUrl}/claims/${claimSk}/review`, { params });
  }

  getClaims(filters: ClaimFilters): Observable<ClaimsResponse> {
    let params = new HttpParams()
      .set('score_version', filters.scoreVersion)
      .set('page', String(filters.page ?? 1))
      .set('page_size', String(filters.pageSize ?? 25))
      .set('sort_by', filters.sortBy ?? 'attention_score')
      .set('sort_direction', filters.sortDirection ?? 'desc')
      .set('include_total', filters.includeTotal === true ? 'true' : 'false');

    params = this.setParam(params, 'attention_level', filters.attentionLevel);
    params = this.setParam(params, 'confidence_level', filters.confidenceLevel);
    params = this.setParam(params, 'validation_status', filters.validationStatus);
    params = this.setParam(params, 'search', filters.search);

    if (filters.hasMl) {
      params = params.set('has_ml', 'true');
    }
    if (filters.hasPostInspection) {
      params = params.set('has_post_inspection', 'true');
    }

    return this.http.get<ClaimsResponse>(`${this.apiBaseUrl}/claims`, { params });
  }

  submitClaimDecision(claimSk: number, input: ClaimDecisionInput): Observable<ClaimDecisionRecord> {
    return this.http.post<ClaimDecisionRecord>(`${this.apiBaseUrl}/claims/${claimSk}/decision`, {
      decision: input.decision,
      comment: input.comment,
      reviewer_email: input.reviewerEmail,
      reviewer_role: input.reviewerRole,
      score_version: input.scoreVersion
    });
  }

  getClaimDecisionHistory(claimSk: number): Observable<{ claim_sk: number; items: ClaimDecisionRecord[] }> {
    return this.http.get<{ claim_sk: number; items: ClaimDecisionRecord[] }>(
      `${this.apiBaseUrl}/claims/${claimSk}/decisions`
    );
  }

  getDecisionsFeed(reviewerEmail?: string, limit = 50): Observable<{ items: ClaimDecisionRecord[] }> {
    let params = new HttpParams().set('limit', String(limit));
    if (reviewerEmail) {
      params = params.set('reviewer_email', reviewerEmail);
    }
    return this.http.get<{ items: ClaimDecisionRecord[] }>(`${this.apiBaseUrl}/decisions`, { params });
  }

  getVhsOverview(): Observable<VhsOverviewResponse> {
    return this.http.get<VhsOverviewResponse>(`${this.apiBaseUrl}/vhs/overview`);
  }

  getVhsVehicles(decision?: string, search?: string): Observable<{ run_id: string | null; items: VhsVehicleItem[] }> {
    let params = new HttpParams();
    params = this.setParam(params, 'decision', decision);
    params = this.setParam(params, 'search', search);
    return this.http.get<{ run_id: string | null; items: VhsVehicleItem[] }>(`${this.apiBaseUrl}/vhs/vehicles`, { params });
  }

  getVhsInspectionDetail(vhsScoreSk: number): Observable<VhsInspectionDetail> {
    return this.http.get<VhsInspectionDetail>(`${this.apiBaseUrl}/vhs/inspections/${vhsScoreSk}`);
  }

  getVhsInspectionDetailByKey(immatriculation: string, inspectionDate: string): Observable<VhsInspectionDetail> {
    // Convert YYYY-MM-DD or ISO date string to YYYYMMDD integer format
    const dateSk = inspectionDate.slice(0, 10).replace(/-/g, '');
    return this.http.get<VhsInspectionDetail>(
      `${this.apiBaseUrl}/vhs/inspections/by-key?immatriculation=${encodeURIComponent(immatriculation)}&date_sk=${dateSk}`
    );
  }

  private setParam(params: HttpParams, key: string, value?: string): HttpParams {
    return value ? params.set(key, value) : params;
  }
}