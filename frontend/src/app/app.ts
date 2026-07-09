import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterOutlet } from '@angular/router';

import { AttentionBadgeComponent } from './components/attention-badge/attention-badge.component';
import { ClaimListItem, ClaimsResponse, IrisApiService, SummaryResponse } from './core/services/iris-api.service';

interface ScoreVersionOption {
  label: string;
  value: string;
  helper: string;
}

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule, RouterOutlet, AttentionBadgeComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  private readonly api = inject(IrisApiService);

  readonly scoreVersions: ScoreVersionOption[] = [
    {
      label: 'Score enrichi par atypicite statistique',
      value: 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE',
      helper: 'Version candidate avancee avec signal statistique separe.'
    },
    {
      label: 'Score principal metier',
      value: 'IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE',
      helper: 'Version deterministe basee sur les regles metier.'
    }
  ];

  selectedScoreVersion = this.scoreVersions[0].value;
  selectedAttentionLevel = '';
  selectedConfidenceLevel = '';
  hasMlOnly = false;
  hasPostInspectionOnly = false;

  summary: SummaryResponse | null = null;
  claims: ClaimListItem[] = [];
  totalClaims = 0;
  page = 1;
  pageSize = 25;
  isLoading = false;
  errorMessage = '';

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.errorMessage = '';
    this.isLoading = true;
    this.loadSummary();
    this.loadClaims();
  }

  loadSummary(): void {
    this.api.getSummary(this.selectedScoreVersion).subscribe({
      next: (summary) => {
        this.summary = summary;
      },
      error: () => {
        this.errorMessage = 'Synthese indisponible. Verifiez que Flask est demarre et que PostgreSQL est accessible.';
      }
    });
  }

  loadClaims(): void {
    this.api.getClaims({
      scoreVersion: this.selectedScoreVersion,
      attentionLevel: this.selectedAttentionLevel || undefined,
      confidenceLevel: this.selectedConfidenceLevel || undefined,
      hasMl: this.hasMlOnly,
      hasPostInspection: this.hasPostInspectionOnly,
      page: this.page,
      pageSize: this.pageSize
    }).subscribe({
      next: (response: ClaimsResponse) => {
        this.claims = response.items;
        this.totalClaims = response.total;
        this.isLoading = false;
      },
      error: () => {
        this.isLoading = false;
        this.errorMessage = 'Liste des dossiers indisponible. Aucun recalcul n\'a ete lance.';
      }
    });
  }

  onFilterChange(): void {
    this.page = 1;
    this.loadClaims();
  }

  get selectedVersionHelper(): string {
    return this.scoreVersions.find((item) => item.value === this.selectedScoreVersion)?.helper ?? '';
  }

  get attentionLevels(): string[] {
    return this.summary?.attention_distribution.map((item) => item.attention_level) ?? [];
  }

  get confidenceLevels(): string[] {
    return this.summary?.confidence_distribution.map((item) => item.confidence_level) ?? [];
  }

  trackByClaim(index: number, claim: ClaimListItem): number {
    return claim.claim_sk;
  }
}
