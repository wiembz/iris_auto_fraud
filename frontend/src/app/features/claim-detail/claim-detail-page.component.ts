import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import {
  ClaimDecisionRecord,
  ClaimDecisionValue,
  ClaimPostInspectionItem,
  ClaimReviewResponse,
  ClaimReviewSignal,
  ClaimTimelineEvent,
  IrisApiService,
  VhsInspectionDetail
} from '../../core/services/iris-api.service';
import { AttentionBadgeComponent } from '../worklist/attention-badge/attention-badge.component';

const DECISION_LABELS: Record<ClaimDecisionValue, string> = {
  SUSPICION_CONFIRMED: 'Suspicion confirmee',
  CONFORME: 'Dossier conforme',
  A_COMPLETER: 'A completer'
};

interface SignalDetailRow {
  label: string;
  value: string;
}

interface SignalViewModel {
  key: string;
  label: string;
  points: number;
  pointsShare: number;
  tone: 'high' | 'medium' | 'low';
  explanation: string | null;
  details: SignalDetailRow[];
}

interface SignalFamilyGroup {
  family: string;
  familyLabel: string;
  totalPoints: number;
  signals: SignalViewModel[];
}

interface TimelineNode {
  event: ClaimTimelineEvent;
  icon: 'contract' | 'inspection' | 'declaration' | 'claim' | 'analysis' | 'default';
  gapFromPrevious: TimelineGap | null;
}

interface TimelineGap {
  days: number;
  label: string;
  tone: 'alert' | 'neutral';
}

const ML_FACTOR_LABELS: Record<string, string> = {
  driver_claim_count_12m: 'Sinistres lies au meme conducteur (12 mois)',
  driver_days_since_previous_claim: 'Delai depuis le sinistre precedent du conducteur',
  amount_vs_guarantee_median_ratio: 'Montant compare aux dossiers de la meme garantie',
  amount_percentile_by_guarantee: 'Position du montant dans la garantie',
  client_claim_count_12m: 'Sinistres du client (12 mois)',
  client_claim_count_24m: 'Sinistres du client (24 mois)',
  client_guarantee_claim_count_12m: 'Sinistres du client sur cette garantie (12 mois)',
  vehicle_claim_count_12m: 'Sinistres du meme vehicule (12 mois)',
  vehicle_days_since_previous_claim: 'Delai depuis le sinistre precedent du vehicule',
  third_party_days_since_previous_claim: 'Delai depuis le sinistre precedent du tiers',
  days_since_previous_claim: 'Delai depuis le sinistre precedent',
  days_claim_to_declaration: 'Delai entre survenance et declaration',
  days_contract_start_to_claim: 'Anciennete du contrat au moment du sinistre',
  claim_amount: 'Montant du sinistre'
};

const FAMILY_LABELS: Record<string, string> = {
  DELAY: 'Delais et chronologie',
  TIMING: 'Delais et chronologie',
  AMOUNT: 'Montants',
  MONTANT: 'Montants',
  FINANCIAL: 'Montants',
  HISTORY: 'Historique client',
  RECURRENCE: 'Recurrence',
  DATA_QUALITY: 'Completude du dossier',
  QUALITY: 'Completude du dossier',
  VEHICULE: 'Vehicule',
  VEHICLE: 'Vehicule',
  CONTRACT: 'Contrat',
  ML: 'Signal statistique',
  POST_INSPECTION: 'Post-inspection'
};

const SIGNAL_VALUE_LABELS: Record<string, string> = {
  ratio: 'Ecart par rapport a la mediane',
  percentile: 'Position dans la distribution',
  high_amount_flag: 'Montant signale eleve',
  min_delay_days: 'Delai minimum inspection -> sinistre',
  signal_count: 'Nombre de signaux post-inspection',
  strongest_confidence: 'Confiance la plus forte',
  zones: 'Zone(s) du vehicule concernee(s)'
};

const DELAY_BUCKET_LABELS: Record<string, string> = {
  DAYS_0_7: 'moins de 7 jours',
  DAYS_8_30: 'entre 8 et 30 jours',
  DAYS_31_90: 'entre 31 et 90 jours',
  DAYS_91_PLUS: 'plus de 90 jours'
};

@Component({
  selector: 'app-claim-detail-page',
  standalone: true,
  imports: [RouterLink, DatePipe, DecimalPipe, AttentionBadgeComponent],
  templateUrl: './claim-detail-page.component.html',
  styleUrl: './claim-detail-page.component.scss'
})
export class ClaimDetailPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private subscription?: Subscription;
  private historySubscription?: Subscription;
  private decisionSubscription?: Subscription;
  private vhsDetailSubscription?: Subscription;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly review = signal<ClaimReviewResponse | null>(null);
  readonly expandedSignals = signal<ReadonlySet<string>>(new Set());

  readonly activeVhsDetail = signal<VhsInspectionDetail | null>(null);
  readonly vhsModalLoading = signal(false);

  readonly currentUser = this.auth.currentUser;
  readonly decisionHistory = signal<ClaimDecisionRecord[]>([]);
  readonly latestDecision = computed(() => this.decisionHistory()[0] ?? null);
  readonly selectedDecision = signal<ClaimDecisionValue | null>(null);
  readonly commentText = signal('');
  readonly submittingDecision = signal(false);
  readonly decisionError = signal<string | null>(null);
  readonly decisionSuccess = signal(false);

  // Une decision existante n'est jamais modifiee (audit trail append-only) :
  // choisir une nouvelle option enregistre une correction qui la remplace.
  // On le rend explicite plutot que de laisser l utilisateur deviner l effet
  // d un nouveau clic (faute de frappe corrigee, reexamen apres nouvelle info...).
  readonly isCorrection = computed(() => !!this.latestDecision());
  readonly isRedundantSelection = computed(() => {
    const latest = this.latestDecision();
    const selected = this.selectedDecision();
    return !!latest && !!selected && latest.decision === selected;
  });

  readonly claim = computed(() => this.review()?.claim ?? null);
  readonly vehicle = computed(() => this.review()?.vehicle ?? null);
  readonly mlAnomaly = computed(() => this.review()?.ml_anomaly ?? null);
  readonly postInspections = computed(() => this.review()?.post_inspection.items ?? []);

  // --- MOCK DATA FOR 360 VIEW ---
  readonly mockClient360 = computed(() => ({
    anciennete: '9 ans',
    contratsActifs: 3,
    sinistres24m: this.claim()?.client_claim_count_24m ?? 10,
    dernierSinistre: '42 jours'
  }));

  readonly mockVehicule360 = computed(() => {
    const v = this.vehicle();
    return {
      marqueModele: 'Peugeot 208',
      annee: 2019,
      kilometrage: '145 000 km',
      vhs: '58/100',
      inspection: this.postInspections().length > 0 ? 'Oui' : 'Non',
      immatriculation: v?.immatriculation ?? 'Inconnue'
    };
  });

  readonly mockConducteur360 = computed(() => ({
    sinistres: 2,
    retraitPermis: 'Aucun retrait de permis'
  }));

  readonly mockContrat360 = computed(() => ({
    type: 'Tous risques',
    depuis: this.claim()?.contract_start_date ? new Date(this.claim()!.contract_start_date!).getFullYear() : 2024,
    prime: 'Annuelle'
  }));

  readonly mockTiers360 = computed(() => ({
    compagnie: 'Assurance XYZ',
    garage: 'Garage Central',
    expert: 'Cabinet Dupont'
  }));

  readonly mockDocuments360 = computed(() => [
    { type: 'Constat', label: 'constat_amiable.pdf', status: 'present' },
    { type: 'Photos', label: '3 photos jointes', status: 'present' },
    { type: 'Rapport expert', label: 'En attente', status: 'missing' }
  ]);

  readonly mockGeographie360 = computed(() => ({
    lieu: 'Tunis, Centre-ville',
    distanceDomicile: '12 km',
    zoneSinistralite: 'Forte'
  }));

  // --- CHECKLIST / ACTIONS RECOMMANDEES ---
  readonly recommendedActions = computed(() => {
    const backendChecklist = this.review()?.checklist;
    if (backendChecklist && backendChecklist.length > 0) {
      return backendChecklist.map((label, index) => ({
        id: `c${index + 1}`,
        label,
        done: false
      }));
    }
    return [
      { id: 'c1', label: 'Vérifier la cohérence des réparations avec les dommages déclarés.', done: false },
      { id: 'c2', label: 'Vérifier les précédents sinistres du client.', done: false },
      { id: 'c3', label: 'Vérifier l\'historique des sinistres de ce véhicule (même avec d\'anciens proprios).', done: false },
      { id: 'c4', label: 'Contrôler la validité et la lisibilité des justificatifs (permis, carte grise).', done: false },
      { id: 'c5', label: 'Analyser les liens éventuels entre le conducteur et le tiers.', done: false }
    ];
  });

  toggleChecklistItem(id: string): void {
    // In a real app, we might persist this state. Here we can just mutate the array if we make it a state signal,
    // but since it's computed, we'll need a proper state signal.
    // To keep it simple without deep state management for this POC, let's create a local signal for checked items.
    const current = new Set(this.checkedActions());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.checkedActions.set(current);
  }

  readonly checkedActions = signal<ReadonlySet<string>>(new Set());


  readonly scoreTone = computed<'high' | 'medium' | 'low' | 'ok'>(() => {
    const level = this.claim()?.attention_level ?? '';
    return this.toneForLevel(level);
  });

  readonly scoreGaugeDashOffset = computed(() => {
    const score = this.claim()?.attention_score ?? 0;
    const circumference = 2 * Math.PI * 54 * 0.75; // 3/4 circle arc length
    const clamped = Math.max(0, Math.min(100, score));
    return circumference * (1 - clamped / 100);
  });

  readonly timelineNodes = computed<TimelineNode[]>(() => {
    const items = [...(this.review()?.timeline.items ?? [])].sort((a, b) =>
      (a.event_date ?? '').localeCompare(b.event_date ?? '')
    );
    const nodes: TimelineNode[] = [];
    let previous: ClaimTimelineEvent | null = null;
    for (const event of items) {
      const gap = this.computeGap(previous, event);
      nodes.push({ event, icon: this.iconForEvent(event.event_type), gapFromPrevious: gap });
      previous = event;
    }
    return nodes;
  });

  readonly signalGroups = computed<SignalFamilyGroup[]>(() => {
    const items = this.review()?.signals.items ?? [];
    const maxPoints = Math.max(...items.map((item) => Number(item.points) || 0), 1);
    const groups = new Map<string, SignalFamilyGroup>();
    for (const item of items) {
      const family = item.signal_family || 'Autre';
      const group = groups.get(family) ?? {
        family,
        familyLabel: this.familyLabel(family),
        totalPoints: 0,
        signals: []
      };
      group.signals.push(this.toSignalViewModel(item, maxPoints));
      group.totalPoints += Number(item.points) || 0;
      groups.set(family, group);
    }
    return [...groups.values()].sort((a, b) => b.totalPoints - a.totalPoints);
  });

  readonly mlTopFactors = computed(() => {
    const ml = this.mlAnomaly();
    if (!ml) {
      return [];
    }
    return [ml.top_variable_1, ml.top_variable_2, ml.top_variable_3]
      .filter((value): value is string => !!value)
      .map((value) => this.humanizeMlFactor(value));
  });

  readonly mlPercentileText = computed(() => {
    const percentile = this.mlAnomaly()?.anomaly_percentile_score;
    if (percentile === null || percentile === undefined) {
      return null;
    }
    const share = Math.round(Number(percentile) * 100);
    if (!Number.isFinite(share)) {
      return null;
    }
    return `Plus atypique que ${share} % des dossiers comparables`;
  });

  readonly mlGaugeShare = computed(() => {
    const percentile = this.mlAnomaly()?.anomaly_percentile_score;
    if (percentile === null || percentile === undefined) {
      return 0;
    }
    return Math.max(0, Math.min(100, Math.round(Number(percentile) * 100)));
  });

  ngOnInit(): void {
    const claimSk = Number(this.route.snapshot.paramMap.get('claimSk'));
    if (!Number.isInteger(claimSk) || claimSk <= 0) {
      this.errorMessage.set('Ce dossier est introuvable.');
      this.loading.set(false);
      return;
    }
    this.subscription = this.api.getClaimReview(claimSk).subscribe({
      next: (review) => {
        this.review.set(review);
        this.loading.set(false);
      },
      error: (error) => {
        this.errorMessage.set(
          error?.status === 404
            ? 'Ce dossier est introuvable dans la derniere analyse.'
            : 'La revue de ce dossier est momentanement indisponible. Reessayez dans quelques instants.'
        );
        this.loading.set(false);
      }
    });
    this.historySubscription = this.api.getClaimDecisionHistory(claimSk).subscribe({
      next: (res) => this.decisionHistory.set(res.items),
      error: () => {
        // Non bloquant : l'absence d'historique ne doit pas empecher la lecture du dossier.
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
    this.historySubscription?.unsubscribe();
    this.decisionSubscription?.unsubscribe();
    this.vhsDetailSubscription?.unsubscribe();
  }

  decisionLabel(value: ClaimDecisionValue | string): string {
    return DECISION_LABELS[value as ClaimDecisionValue] ?? value;
  }

  correctionNote(item: ClaimDecisionRecord): string | null {
    if (!item.corrects_decision_id) {
      return null;
    }
    const previous = item.corrected_decision_value ? this.decisionLabel(item.corrected_decision_value) : 'une decision precedente';
    return `Correction de : ${previous} -> ${this.decisionLabel(item.decision)}`;
  }

  selectDecision(value: ClaimDecisionValue): void {
    this.selectedDecision.set(value);
    this.decisionSuccess.set(false);
    this.decisionError.set(null);
  }

  onCommentInput(event: Event): void {
    this.commentText.set((event.target as HTMLTextAreaElement).value);
  }

  submitDecision(): void {
    const decision = this.selectedDecision();
    const user = this.currentUser();
    const claimSk = this.claim()?.claim_sk;
    if (!decision || !claimSk) {
      return;
    }
    if (!user?.email) {
      this.decisionError.set('Votre session ne porte pas d adresse e-mail valide. Reconnectez-vous.');
      return;
    }

    this.submittingDecision.set(true);
    this.decisionError.set(null);
    this.decisionSuccess.set(false);

    this.decisionSubscription = this.api
      .submitClaimDecision(claimSk, {
        decision,
        comment: this.commentText().trim() || undefined,
        reviewerEmail: user.email,
        reviewerRole: user.role,
        scoreVersion: this.claim()?.score_version
      })
      .subscribe({
        next: (record) => {
          this.decisionHistory.update((items) => [record, ...items]);
          this.selectedDecision.set(null);
          this.commentText.set('');
          this.submittingDecision.set(false);
          this.decisionSuccess.set(true);
        },
        error: (error) => {
          this.submittingDecision.set(false);
          this.decisionError.set(
            error?.error?.message ?? 'Impossible d enregistrer la decision. Reessayez dans quelques instants.'
          );
        }
      });
  }

  toggleSignal(key: string): void {
    const current = new Set(this.expandedSignals());
    if (current.has(key)) {
      current.delete(key);
    } else {
      current.add(key);
    }
    this.expandedSignals.set(current);
  }

  isSignalExpanded(key: string): boolean {
    return this.expandedSignals().has(key);
  }

  displayText(value: string | number | null | undefined): string {
    if (value === null || value === undefined || value === '') {
      return '—';
    }
    return String(value);
  }

  amountOf(value: number | string | null | undefined): number | null {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  confidenceLabel(level: string | null | undefined): string {
    const normalized = (level ?? '').toLowerCase();
    if (normalized.includes('high') || normalized.includes('elev')) {
      return 'Confiance elevee';
    }
    if (normalized.includes('medium') || normalized.includes('moy')) {
      return 'Confiance moyenne';
    }
    if (normalized.includes('low') || normalized.includes('limit')) {
      return 'Confiance limitee';
    }
    return level ?? '—';
  }

  delayBucketLabel(bucket: string | null | undefined): string {
    if (!bucket) {
      return '';
    }
    return DELAY_BUCKET_LABELS[bucket] ?? bucket.toLowerCase().replace(/_/g, ' ');
  }

  inspectionDelayTone(item: ClaimPostInspectionItem): 'high' | 'medium' | 'low' {
    const days = item.days_inspection_to_claim;
    if (days === null || days === undefined) {
      return 'low';
    }
    if (days <= 30) {
      return 'high';
    }
    if (days <= 90) {
      return 'medium';
    }
    return 'low';
  }

  checkpointLabels(item: ClaimPostInspectionItem): string[] {
    return (item.representative_checkpoint_labels ?? '')
      .split(/[;,]/)
      .map((label) => label.trim())
      .filter(Boolean);
  }

  hasVehicleIdentified(): boolean {
    const vehicle = this.vehicle();
    if (!vehicle) {
      return false;
    }
    return !this.isTruthyFlag(vehicle.missing_vehicle_flag) && !!vehicle.vehicle_sk;
  }

  isTruthyFlag(value: boolean | number | null | undefined): boolean {
    return value === true || value === 1;
  }

  private toneForLevel(level: string): 'high' | 'medium' | 'low' | 'ok' {
    const normalized = level
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '');
    if (normalized.includes('priorit')) {
      return 'high';
    }
    if (normalized.includes('renforc')) {
      return 'medium';
    }
    if (normalized.includes('verif')) {
      return 'low';
    }
    return 'ok';
  }

  private computeGap(previous: ClaimTimelineEvent | null, current: ClaimTimelineEvent): TimelineGap | null {
    if (!previous?.event_date || !current.event_date) {
      return null;
    }
    const previousDate = new Date(previous.event_date);
    const currentDate = new Date(current.event_date);
    const days = Math.round((currentDate.getTime() - previousDate.getTime()) / (1000 * 60 * 60 * 24));
    if (!Number.isFinite(days) || days < 0) {
      return null;
    }
    // Toute etape survenant peu apres une inspection merite d etre signalee,
    // que l etape suivante soit la survenance ou sa declaration (meme date frequente).
    const isRightAfterInspection = previous.event_type.toLowerCase().includes('inspection');
    const tone: TimelineGap['tone'] = isRightAfterInspection && days <= 30 ? 'alert' : 'neutral';
    return { days, label: `${days} jour${days > 1 ? 's' : ''}`, tone };
  }

  private iconForEvent(eventType: string): TimelineNode['icon'] {
    const normalized = eventType.toLowerCase();
    if (normalized.includes('contrat')) {
      return 'contract';
    }
    if (normalized.includes('inspection')) {
      return 'inspection';
    }
    if (normalized.includes('declaration')) {
      return 'declaration';
    }
    if (normalized.includes('survenance') || normalized.includes('sinistre')) {
      return 'claim';
    }
    if (normalized.includes('analyse')) {
      return 'analysis';
    }
    return 'default';
  }

  private toSignalViewModel(item: ClaimReviewSignal, maxPoints: number): SignalViewModel {
    const points = Number(item.points) || 0;
    return {
      key: item.signal_code,
      label: item.signal_label,
      points,
      pointsShare: maxPoints ? Math.max(6, Math.round((points / maxPoints) * 100)) : 0,
      tone: this.severityTone(item.severity),
      explanation: item.business_explanation ?? null,
      details: this.parseSignalValue(item.signal_value)
    };
  }

  private severityTone(severity: string | null | undefined): 'high' | 'medium' | 'low' {
    const normalized = (severity ?? '').toLowerCase();
    if (normalized.includes('high') || normalized.includes('fort')) {
      return 'high';
    }
    if (normalized.includes('medium') || normalized.includes('moy')) {
      return 'medium';
    }
    return 'low';
  }

  private parseSignalValue(raw: string | number | null | undefined): SignalDetailRow[] {
    if (raw === null || raw === undefined || raw === '') {
      return [];
    }
    if (typeof raw === 'number') {
      return [{ label: 'Valeur observee', value: this.formatNumber(raw) }];
    }
    const text = String(raw).trim();
    const asObject = this.tryParseStructured(text);
    if (asObject) {
      return Object.entries(asObject)
        .filter(([key]) => key !== 'high_amount_flag')
        .map(([key, value]) => ({
          label: SIGNAL_VALUE_LABELS[key] ?? key.replace(/_/g, ' '),
          value: this.formatDetailValue(key, value)
        }));
    }
    if (/^-?\d+(\.\d+)?$/.test(text)) {
      return [{ label: 'Valeur observee', value: this.formatNumber(Number(text)) }];
    }
    return [{ label: 'Valeur observee', value: text }];
  }

  private tryParseStructured(text: string): Record<string, unknown> | null {
    if (!text.startsWith('{')) {
      return null;
    }
    try {
      return JSON.parse(text);
    } catch {
      // Python dict repr: single quotes, True/False/None
      try {
        const jsonish = text
          .replace(/'/g, '"')
          .replace(/\bTrue\b/g, 'true')
          .replace(/\bFalse\b/g, 'false')
          .replace(/\bNone\b/g, 'null');
        return JSON.parse(jsonish);
      } catch {
        return null;
      }
    }
  }

  private formatDetailValue(key: string, value: unknown): string {
    if (typeof value === 'boolean') {
      return value ? 'Oui' : 'Non';
    }
    if (typeof value === 'number') {
      if (key.toLowerCase().includes('percentile') && value <= 1) {
        return `${Math.round(value * 100)}e percentile`;
      }
      if (key.toLowerCase() === 'ratio') {
        return `${this.formatNumber(value)}x la mediane observee`;
      }
      return this.formatNumber(value);
    }
    return String(value);
  }

  private formatNumber(value: number): string {
    if (Number.isInteger(value)) {
      return value.toLocaleString('fr-FR');
    }
    return value.toLocaleString('fr-FR', { maximumFractionDigits: 2 });
  }

  private humanizeMlFactor(raw: string): { label: string; reading: string } {
    const match = raw.match(/^([\w]+):\s*value=([-\d.]+),\s*percentile=([-\d.]+)/);
    if (!match) {
      return { label: raw, reading: '' };
    }
    const [, name, , percentileText] = match;
    const percentile = Number(percentileText);
    const label = ML_FACTOR_LABELS[name] ?? name.replace(/_/g, ' ');
    let reading = 'valeur a verifier dans le dossier';
    if (percentile >= 0.9) {
      reading = 'valeur inhabituellement elevee';
    } else if (percentile <= 0.1) {
      reading = 'valeur inhabituellement basse';
    }
    return { label, reading };
  }

  private familyLabel(family: string): string {
    const normalized = family
      .toUpperCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '');
    for (const [key, label] of Object.entries(FAMILY_LABELS)) {
      if (normalized.includes(key)) {
        return label;
      }
    }
    return family
      .toLowerCase()
      .replace(/[_-]+/g, ' ')
      .replace(/^\w/, (char) => char.toUpperCase());
  }

  openVhsModal(item: { inspection_sk?: number | null; immatriculation?: string | null; inspection_date?: string | null }): void {
    const immatriculation = item.immatriculation;
    const inspectionDate = item.inspection_date;

    if (!immatriculation || !inspectionDate) {
      return;
    }
    this.vhsModalLoading.set(true);
    this.vhsDetailSubscription?.unsubscribe();
    this.vhsDetailSubscription = this.api.getVhsInspectionDetailByKey(immatriculation, inspectionDate).subscribe({
      next: (detail) => {
        this.activeVhsDetail.set(detail);
        this.vhsModalLoading.set(false);
      },
      error: () => {
        this.vhsModalLoading.set(false);
      }
    });
  }

  closeVhsModal(): void {
    this.activeVhsDetail.set(null);
  }

  inspectionDate(dateSk: number | null | undefined): string {
    if (!dateSk || dateSk <= 0) {
      return '—';
    }
    const raw = String(dateSk);
    return `${raw.slice(6, 8)}/${raw.slice(4, 6)}/${raw.slice(0, 4)}`;
  }

  roundScore(score: number | null | undefined): number {
    return Math.round(Number(score ?? 0));
  }

  vhsScoreTone(score: number | null | undefined): 'high' | 'medium' | 'low' | 'ok' {
    const value = Number(score ?? 0);
    if (value >= 80) {
      return 'ok';
    }
    if (value >= 60) {
      return 'low';
    }
    if (value >= 40) {
      return 'medium';
    }
    return 'high';
  }

  vhsGaugeOffset(score: number | null | undefined): number {
    const circumference = 2 * Math.PI * 54 * 0.75;
    const clamped = Math.max(0, Math.min(100, Number(score ?? 0)));
    return circumference * (1 - clamped / 100);
  }

  statusLabel(status: string | null | undefined): string {
    if (!status) {
      return '—';
    }
    const labels: Record<string, string> = {
      OK: 'Bon etat',
      WORN: 'Use',
      WORN_STRONG: 'Fortement use',
      BROKEN: 'Defaillant',
      REPAIRED: 'Repare',
      UNKNOWN: 'Non evalue'
    };
    return labels[status.toUpperCase()] ?? status;
  }
}
