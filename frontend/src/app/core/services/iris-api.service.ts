import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

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
  claim_business_id: string | null;
  attention_score: number;
  attention_level: string;
  confidence_level: string;
  main_reason_1: string | null;
  main_reason_2: string | null;
  main_reason_3: string | null;
  score_version: string;
  score_run_id: string;
  created_at: string;
  has_ml_signal: boolean;
  has_post_inspection_signal: boolean;
}

export interface SummaryResponse {
  score_version: string;
  score_run_id: string | null;
  total_claims: number;
  attention_distribution: AttentionDistributionItem[];
  confidence_distribution: ConfidenceDistributionItem[];
  top_claims: ClaimListItem[];
}

export interface ClaimsResponse {
  score_version: string;
  score_run_id: string | null;
  page: number;
  page_size: number;
  total: number;
  items: ClaimListItem[];
}

export interface ClaimFilters {
  scoreVersion: string;
  attentionLevel?: string;
  confidenceLevel?: string;
  hasMl?: boolean;
  hasPostInspection?: boolean;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class IrisApiService {
  private readonly http = inject(HttpClient);
  private readonly apiBaseUrl = 'http://127.0.0.1:5000/api';

  getSummary(scoreVersion: string): Observable<SummaryResponse> {
    const params = new HttpParams().set('score_version', scoreVersion);
    return this.http.get<SummaryResponse>(`${this.apiBaseUrl}/summary`, { params });
  }

  getClaims(filters: ClaimFilters): Observable<ClaimsResponse> {
    let params = new HttpParams()
      .set('score_version', filters.scoreVersion)
      .set('page', String(filters.page ?? 1))
      .set('page_size', String(filters.pageSize ?? 25));

    if (filters.attentionLevel) {
      params = params.set('attention_level', filters.attentionLevel);
    }
    if (filters.confidenceLevel) {
      params = params.set('confidence_level', filters.confidenceLevel);
    }
    if (filters.hasMl) {
      params = params.set('has_ml', 'true');
    }
    if (filters.hasPostInspection) {
      params = params.set('has_post_inspection', 'true');
    }

    return this.http.get<ClaimsResponse>(`${this.apiBaseUrl}/claims`, { params });
  }
}
