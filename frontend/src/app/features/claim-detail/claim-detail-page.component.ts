import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Subscription, combineLatest } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import {
  ClaimDecisionRecord,
  ClaimDecisionValue,
  ClaimPostInspectionItem,
  ClaimReviewResponse,
  ClaimRelatedItem,
  ClaimReviewSignal,
  ClaimTimelineEvent,
  IrisApiService,
  VhsCheckpointItem,
  VhsImageLink,
  VhsInspectionDetail,
  WorkflowEvent,
  WorkflowState,
  WorkflowStatus
} from '../../core/services/iris-api.service';
import { AttentionBadgeComponent } from '../worklist/attention-badge/attention-badge.component';

function formatDdMmYyyy(value: string): string {
  // Parse the Y-M-D prefix directly instead of `new Date(value)` : claim_date
  // is a DATE column (no time-of-day), and letting the JS Date constructor
  // interpret it as UTC midnight can shift the displayed day by one when the
  // browser's local timezone is negative relative to UTC.
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) {
    return value;
  }
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}

const DECISION_LABELS: Record<ClaimDecisionValue, string> = {
  SUSPICION_CONFIRMED: 'Fraude',
  CONFORME: 'Non fraude',
  A_COMPLETER: 'Incomplet'
};

const WORKFLOW_STATUS_LABELS: Record<WorkflowStatus, string> = {
  NOUVEAU: 'Nouveau',
  AFFECTE: 'Affecte',
  EN_COURS: 'En cours',
  EN_ATTENTE_PIECES: 'En attente de pieces',
  PRET_POUR_DECISION: 'Pret pour decision',
  TRANSMIS_INVESTIGATION: 'Transmis a l investigation',
  RETOUR_INVESTIGATION: 'Retour investigation',
  CLOTURE: 'Cloture'
};

const WORKFLOW_STATUS_ORDER: WorkflowStatus[] = [
  'NOUVEAU',
  'AFFECTE',
  'EN_COURS',
  'EN_ATTENTE_PIECES',
  'PRET_POUR_DECISION',
  'TRANSMIS_INVESTIGATION',
  'RETOUR_INVESTIGATION',
  'CLOTURE'
];

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

type InspectionCheckpointFilter = 'all' | 'anomalies' | 'critical';

interface VhsCheckpointZoneGroup {
  zone: string;
  label: string;
  total: number;
  anomalies: number;
  critical: number;
  checkpoints: VhsCheckpointItem[];
}

interface GroupedPostInspectionItem extends ClaimPostInspectionItem {
  defective_zones: string[];
  checkpoint_labels: string[];
  signal_count: number;
  max_critical_checkpoint_count: number;
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

const ZONE_LABELS: Record<string, string> = {
  TOUR_DU_VEHICULE: 'Tour du vehicule',
  INTERIEUR: 'Interieur',
  SOUS_CAPOT: 'Sous le capot',
  SOUS_VEHICULE: 'Sous le vehicule',
  ENTRETIEN: 'Entretien'
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
  private workflowSubscription?: Subscription;
  private workflowHistorySubscription?: Subscription;
  private workflowActionSubscription?: Subscription;
  private activeClaimSk: number | null = null;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly review = signal<ClaimReviewResponse | null>(null);
  readonly expandedSignals = signal<ReadonlySet<string>>(new Set());

  readonly activeVhsDetail = signal<VhsInspectionDetail | null>(null);
  readonly vhsModalLoading = signal(false);
  readonly inspectionFilters: InspectionCheckpointFilter[] = ['all', 'anomalies', 'critical'];
  readonly inspectionCheckpointFilter = signal<InspectionCheckpointFilter>('all');
  readonly selectedInspectionPhoto = signal<{ url: string; label: string } | null>(null);
  readonly returnToClaimSk = signal<number | null>(null);

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
  readonly workflowState = signal<WorkflowState | null>(null);
  readonly workflowHistory = signal<WorkflowEvent[]>([]);
  readonly workflowStatusOrder = WORKFLOW_STATUS_ORDER;
  readonly selectedWorkflowStatus = signal<WorkflowStatus | ''>('');
  readonly workflowStatusComment = signal('');
  readonly submittingWorkflowStatus = signal(false);
  readonly workflowStatusError = signal<string | null>(null);
  readonly workflowStatusSuccess = signal(false);

  readonly assigneeEmailInput = signal('');
  readonly submittingWorkflowAssignment = signal(false);
  readonly workflowAssignmentError = signal<string | null>(null);
  readonly workflowAssignmentSuccess = signal(false);

  readonly newTaskLabel = signal('');
  readonly submittingWorkflowTask = signal(false);
  readonly workflowTaskError = signal<string | null>(null);
  readonly completingTaskId = signal<number | null>(null);

  readonly isCorrection = computed(() => !!this.latestDecision());
  readonly isRedundantSelection = computed(() => {
    const latest = this.latestDecision();
    const selected = this.selectedDecision();
    return !!latest && !!selected && latest.decision === selected;
  });

  readonly claim = computed(() => this.review()?.claim ?? null);
  readonly vehicle = computed(() => this.review()?.vehicle ?? null);
  readonly mlAnomaly = computed(() => this.review()?.ml_anomaly ?? null);
  readonly postInspectionRows = computed(() => this.review()?.post_inspection.items ?? []);
  readonly postInspections = computed<GroupedPostInspectionItem[]>(() => this.groupPostInspections(this.postInspectionRows()));
  readonly sameSinistreGuarantees = computed(() => this.review()?.related_claims?.same_sinistre_guarantees ?? []);
  readonly clientHistory24m = computed(() => this.review()?.related_claims?.client_history_24m ?? []);
  readonly showReturnToWorkClaim = computed(() => {
    const returnTo = this.returnToClaimSk();
    const current = this.claim()?.claim_sk;
    return !!returnTo && !!current && returnTo !== current;
  });
  readonly clientHistory12m = computed(() => {
    const claimDate = this.claim()?.claim_date ? new Date(this.claim()!.claim_date as string) : null;
    if (!claimDate) {
      return [];
    }
    const minDate = new Date(claimDate);
    minDate.setMonth(minDate.getMonth() - 12);
    return this.clientHistory24m().filter((item) => {
      if (!item.claim_date) {
        return false;
      }
      const itemDate = new Date(item.claim_date);
      return itemDate >= minDate && itemDate < claimDate;
    });
  });


  readonly vhsCheckpointGroups = computed<VhsCheckpointZoneGroup[]>(() => {
    const detail = this.activeVhsDetail();
    const filter = this.inspectionCheckpointFilter();
    const checkpoints = detail?.checkpoints ?? [];
    const filtered = checkpoints.filter((checkpoint) => {
      if (filter === 'critical') {
        return checkpoint.est_anomalie_critique === true;
      }
      if (filter === 'anomalies') {
        return checkpoint.est_anomalie === true || Number(checkpoint.penalty_applied || 0) > 0;
      }
      return true;
    });
    const allByCode = new Map(checkpoints.map((checkpoint) => [checkpoint.checkpoint_code, checkpoint]));
    const groups = new Map<string, VhsCheckpointZoneGroup>();
    for (const checkpoint of filtered) {
      const zone = checkpoint.zone_controle ?? 'AUTRE';
      const current = groups.get(zone) ?? {
        zone,
        label: this.zoneLabel(zone),
        total: 0,
        anomalies: 0,
        critical: 0,
        checkpoints: []
      };
      current.checkpoints.push(checkpoint);
      groups.set(zone, current);
    }
    for (const checkpoint of allByCode.values()) {
      const zone = checkpoint.zone_controle ?? 'AUTRE';
      const current = groups.get(zone) ?? {
        zone,
        label: this.zoneLabel(zone),
        total: 0,
        anomalies: 0,
        critical: 0,
        checkpoints: []
      };
      current.total += 1;
      if (checkpoint.est_anomalie === true || Number(checkpoint.penalty_applied || 0) > 0) {
        current.anomalies += 1;
      }
      if (checkpoint.est_anomalie_critique === true) {
        current.critical += 1;
      }
      groups.set(zone, current);
    }
    return [...groups.values()].filter((group) => group.checkpoints.length > 0);
  });

  // --- REAL DATA MAPPED FOR 360 VIEW ---
  // Noms de propriete alignes sur la donnee reelle qu ils portent (pas sur le
  // libelle affiche, qui peut regrouper plusieurs sources dans un meme
  // article HTML) : evite qu une lecture du code source donne une fausse
  // idee de ce qui est realmente calcule.
  readonly client360 = computed(() => {
    const c = this.review()?.client_context;
    const birthDate = c?.date_naissance ? new Date(c.date_naissance) : null;
    const age = birthDate ? new Date().getFullYear() - birthDate.getFullYear() : null;
    const ageStr = age ? `, ${age} ans` : '';
    const history = this.review()?.related_claims?.client_history_24m ?? [];
    const lastClaim = history.find((item) => !!item.claim_date);
    return {
      anciennete: c ? `${c.nature_client ? c.nature_client.replace(/_/g, ' ').toLowerCase() : 'personne physique'}${ageStr}` : 'Client BNA',
      identifiantClient: c?.idclt ?? 'Non renseigné',
      sinistres24m: this.claim()?.client_claim_count_24m ?? 0,
      profilDeclare: c?.sexe ?? 'Non renseigné',
      dernierSinistre: lastClaim?.claim_date
        ? formatDdMmYyyy(lastClaim.claim_date)
        : 'Aucun sinistre anterieur (24 derniers mois)'
    };
  });

  readonly vehicule360 = computed(() => {
    const v = this.vehicle();
    const vhs = this.review()?.vhs_context;
    return {
      immatriculation: v?.immatriculation ?? 'Non renseignée',
      gradeSecuriteVhs: vhs?.safety_grade ?? 'Non disponible',
      kilometrage: vhs?.kilometrage ? `${Math.round(vhs.kilometrage).toLocaleString('fr-FR')} km` : 'Kilométrage inconnu',
      vhs: vhs?.vhs_final_score !== undefined ? `${Math.round(vhs.vhs_final_score)}/100 (${vhs.decision ?? '—'})` : 'Aucun score VHS',
      inspection: this.postInspections().length > 0 ? 'Oui' : 'Non'
    };
  });

  readonly conducteur360 = computed(() => {
    const cond = this.review()?.conducteur_context;
    const name = cond?.nom_conducteur ? cond.nom_conducteur.trim() : 'Conducteur principal';
    return {
      sinistres: name,
      retraitPermis: cond?.numero_permis ? `Permis: ${cond.numero_permis} (Cat. ${cond.categorie_permis ?? 'B'})` : 'Aucun permis saisi'
    };
  });

  readonly contrat360 = computed(() => {
    const con = this.review()?.contract_context;
    const dateDebut = con?.date_debut_contrat ? new Date(con.date_debut_contrat).getFullYear() : null;
    const validity = con?.validity_at_claim_date;
    let validiteLabel = 'Non déterminable (dates de contrat manquantes)';
    if (validity && validity.is_valid_at_claim_date !== null) {
      validiteLabel = validity.is_valid_at_claim_date
        ? 'Couvert à la date du sinistre'
        : 'Non couvert à la date du sinistre';
    }
    return {
      type: con?.statut_contrat ?? 'Non renseigné',
      depuis: dateDebut,
      numeroContrat: con?.numero_contrat ?? 'Non renseigné',
      dateFin: con?.date_fin_contrat ?? null,
      dateDebutEffet: con?.date_debut_effet ?? null,
      dateFinEffet: con?.date_fin_effet ?? null,
      validiteLabel,
      isValidAtClaimDate: validity?.is_valid_at_claim_date ?? null
    };
  });

  readonly tiers360 = computed(() => {
    const t = this.review()?.tiers_context;
    return {
      compagnie: t?.nom_tiers ?? 'Aucun tiers identifié',
      garage: t?.immatriculation_vehicule_tiers ?? 'Non renseignée',
      expert: t?.numero_contrat_tiers ?? 'Non renseigné'
    };
  });

  readonly documents360 = computed(() => {
    const hasInspection = this.postInspections().length > 0;
    return hasInspection
      ? [{ type: 'Inspection STAFIM', label: 'Donnée confirmée par la source inspection', status: 'present' }]
      : [{ type: 'Pièces justificatives', label: 'Aucune pièce confirmée par les données disponibles', status: 'unknown' }];
  });

  readonly geographie360 = computed(() => {
    const g = this.review()?.geo_context;
    return {
      lieu: g?.localite ? `${g.localite}, ${g.gouvernorat ?? ''}` : 'Géographie inconnue',
      region: g?.region ?? 'Non renseignée',
      zoneSinistralite: g?.pays ?? 'Non renseigné'
    };
  });

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
    const current = new Set(this.checkedActions());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.checkedActions.set(current);
    this.persistChecklist();
  }

  readonly checkedActions = signal<ReadonlySet<string>>(new Set());

  private checklistStorageKey(): string | null {
    const email = this.currentUser()?.email;
    return this.activeClaimSk && email
      ? `iris.claim-checklist.v1.${email.toLowerCase()}.${this.activeClaimSk}`
      : null;
  }

  private restoreChecklist(): void {
    const key = this.checklistStorageKey();
    if (!key) {
      return;
    }
    try {
      const saved = JSON.parse(localStorage.getItem(key) ?? '[]');
      const validIds = new Set(this.recommendedActions().map((item) => item.id));
      this.checkedActions.set(new Set((Array.isArray(saved) ? saved : []).filter((id) => validIds.has(id))));
    } catch {
      this.checkedActions.set(new Set());
    }
  }

  private persistChecklist(): void {
    const key = this.checklistStorageKey();
    if (key) {
      localStorage.setItem(key, JSON.stringify([...this.checkedActions()]));
    }
  }


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
    this.subscription = combineLatest([this.route.paramMap, this.route.queryParamMap]).subscribe(([params, queryParams]) => {
      const claimSk = Number(params.get('claimSk'));
      if (!Number.isInteger(claimSk) || claimSk <= 0) {
        this.errorMessage.set('Ce dossier est introuvable.');
        this.loading.set(false);
        return;
      }
      const returnTo = Number(queryParams.get('returnTo'));
      this.returnToClaimSk.set(Number.isInteger(returnTo) && returnTo > 0 ? returnTo : null);
      this.loadClaim(claimSk);
    });
  }

  private loadClaim(claimSk: number): void {
    this.activeClaimSk = claimSk;
    this.loading.set(true);
    this.errorMessage.set(null);
    this.review.set(null);
    this.decisionHistory.set([]);
    this.selectedDecision.set(null);
    this.commentText.set('');
    this.decisionError.set(null);
    this.decisionSuccess.set(false);
    this.activeVhsDetail.set(null);
    this.selectedInspectionPhoto.set(null);
    this.workflowState.set(null);
    this.workflowHistory.set([]);
    this.selectedWorkflowStatus.set('');
    this.workflowStatusComment.set('');
    this.workflowStatusError.set(null);
    this.workflowStatusSuccess.set(false);
    this.assigneeEmailInput.set('');
    this.workflowAssignmentError.set(null);
    this.workflowAssignmentSuccess.set(false);
    this.newTaskLabel.set('');
    this.workflowTaskError.set(null);

    this.historySubscription?.unsubscribe();
    this.vhsDetailSubscription?.unsubscribe();
    this.workflowSubscription?.unsubscribe();
    this.workflowHistorySubscription?.unsubscribe();
    this.workflowActionSubscription?.unsubscribe();

    this.api.getClaimReview(claimSk).subscribe({
      next: (review) => {
        this.review.set(review);
        this.restoreChecklist();
        this.loading.set(false);
      },
      error: (error) => {
        this.errorMessage.set(
          error?.status === 404
            ? 'Ce dossier est introuvable dans la dernière analyse.'
            : 'La revue de ce dossier est momentanément indisponible. Réessayez dans quelques instants.'
        );
        this.loading.set(false);
      }
    });
    this.historySubscription = this.api.getClaimDecisionHistory(claimSk).subscribe({
      next: (res) => this.decisionHistory.set(res.items),
      error: () => {
        // Non bloquant : l'absence d'historique ne doit pas empêcher la lecture du dossier.
      }
    });
    this.workflowSubscription = this.api.getWorkflowState(claimSk).subscribe({
      next: (state) => this.workflowState.set(state),
      error: () => {
        // Non bloquant : l'absence de suivi ne doit pas empêcher la lecture du dossier.
      }
    });
    this.workflowHistorySubscription = this.api.getWorkflowHistory(claimSk).subscribe({
      next: (res) => this.workflowHistory.set(res.items),
      error: () => {
        // Non bloquant.
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
    this.historySubscription?.unsubscribe();
    this.decisionSubscription?.unsubscribe();
    this.vhsDetailSubscription?.unsubscribe();
    this.workflowSubscription?.unsubscribe();
    this.workflowHistorySubscription?.unsubscribe();
    this.workflowActionSubscription?.unsubscribe();
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

  workflowStatusLabel(status: WorkflowStatus | null | undefined): string {
    return status ? WORKFLOW_STATUS_LABELS[status] ?? status : 'Non defini';
  }

  onWorkflowStatusSelect(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as WorkflowStatus | '';
    this.selectedWorkflowStatus.set(value);
    this.workflowStatusSuccess.set(false);
    this.workflowStatusError.set(null);
  }

  onWorkflowStatusCommentInput(event: Event): void {
    this.workflowStatusComment.set((event.target as HTMLTextAreaElement).value);
  }

  submitWorkflowStatus(): void {
    const status = this.selectedWorkflowStatus();
    const user = this.currentUser();
    const claimSk = this.claim()?.claim_sk;
    if (!status || !claimSk) {
      return;
    }
    if (!user?.email) {
      this.workflowStatusError.set('Votre session ne porte pas d adresse e-mail valide. Reconnectez-vous.');
      return;
    }
    const email = user.email;

    this.submittingWorkflowStatus.set(true);
    this.workflowStatusError.set(null);
    this.workflowStatusSuccess.set(false);

    this.workflowActionSubscription = this.api
      .setWorkflowStatus(claimSk, status, email, this.workflowStatusComment().trim() || undefined)
      .subscribe({
        next: (event) => {
          this.workflowHistory.update((items) => [event, ...items]);
          this.workflowState.update((state) => ({
            claim_sk: claimSk,
            status,
            status_changed_at: event.created_at,
            status_changed_by: email,
            assignee_email: state?.assignee_email ?? null,
            assigned_at: state?.assigned_at ?? null,
            assigned_by: state?.assigned_by ?? null,
            open_tasks: state?.open_tasks ?? []
          }));
          this.selectedWorkflowStatus.set('');
          this.workflowStatusComment.set('');
          this.submittingWorkflowStatus.set(false);
          this.workflowStatusSuccess.set(true);
        },
        error: (error) => {
          this.submittingWorkflowStatus.set(false);
          this.workflowStatusError.set(
            error?.error?.message ?? 'Impossible d enregistrer le statut. Reessayez dans quelques instants.'
          );
        }
      });
  }

  onAssigneeEmailInput(event: Event): void {
    this.assigneeEmailInput.set((event.target as HTMLInputElement).value);
    this.workflowAssignmentSuccess.set(false);
    this.workflowAssignmentError.set(null);
  }

  submitWorkflowAssignment(): void {
    const user = this.currentUser();
    const claimSk = this.claim()?.claim_sk;
    if (!claimSk) {
      return;
    }
    if (!user?.email) {
      this.workflowAssignmentError.set('Votre session ne porte pas d adresse e-mail valide. Reconnectez-vous.');
      return;
    }
    const email = user.email;

    const assignee = this.assigneeEmailInput().trim().toLowerCase() || null;
    this.submittingWorkflowAssignment.set(true);
    this.workflowAssignmentError.set(null);
    this.workflowAssignmentSuccess.set(false);

    this.workflowActionSubscription = this.api.setWorkflowAssignment(claimSk, assignee, email).subscribe({
      next: (event) => {
        this.workflowHistory.update((items) => [event, ...items]);
        this.workflowState.update((state) => ({
          claim_sk: claimSk,
          status: state?.status ?? null,
          status_changed_at: state?.status_changed_at ?? null,
          status_changed_by: state?.status_changed_by ?? null,
          assignee_email: assignee,
          assigned_at: event.created_at,
          assigned_by: email,
          open_tasks: state?.open_tasks ?? []
        }));
        this.assigneeEmailInput.set('');
        this.submittingWorkflowAssignment.set(false);
        this.workflowAssignmentSuccess.set(true);
      },
      error: (error) => {
        this.submittingWorkflowAssignment.set(false);
        this.workflowAssignmentError.set(
          error?.error?.message ?? 'Impossible d enregistrer l affectation. Reessayez dans quelques instants.'
        );
      }
    });
  }

  onNewTaskLabelInput(event: Event): void {
    this.newTaskLabel.set((event.target as HTMLInputElement).value);
    this.workflowTaskError.set(null);
  }

  submitNewTask(): void {
    const label = this.newTaskLabel().trim();
    const user = this.currentUser();
    const claimSk = this.claim()?.claim_sk;
    if (!label || !claimSk) {
      return;
    }
    if (!user?.email) {
      this.workflowTaskError.set('Votre session ne porte pas d adresse e-mail valide. Reconnectez-vous.');
      return;
    }
    const email = user.email;

    this.submittingWorkflowTask.set(true);
    this.workflowTaskError.set(null);

    this.workflowActionSubscription = this.api.createWorkflowTask(claimSk, label, email).subscribe({
      next: (event) => {
        this.workflowHistory.update((items) => [event, ...items]);
        this.workflowState.update((state) => ({
          claim_sk: claimSk,
          status: state?.status ?? null,
          status_changed_at: state?.status_changed_at ?? null,
          status_changed_by: state?.status_changed_by ?? null,
          assignee_email: state?.assignee_email ?? null,
          assigned_at: state?.assigned_at ?? null,
          assigned_by: state?.assigned_by ?? null,
          open_tasks: [
            {
              task_ref_id: event.event_id,
              task_label: label,
              created_by: email,
              created_at: event.created_at
            },
            ...(state?.open_tasks ?? [])
          ]
        }));
        this.newTaskLabel.set('');
        this.submittingWorkflowTask.set(false);
      },
      error: (error) => {
        this.submittingWorkflowTask.set(false);
        this.workflowTaskError.set(
          error?.error?.message ?? 'Impossible de creer la tache. Reessayez dans quelques instants.'
        );
      }
    });
  }

  completeWorkflowTask(taskRefId: number): void {
    const user = this.currentUser();
    const claimSk = this.claim()?.claim_sk;
    if (!claimSk) {
      return;
    }
    if (!user?.email) {
      this.workflowTaskError.set('Votre session ne porte pas d adresse e-mail valide. Reconnectez-vous.');
      return;
    }

    this.completingTaskId.set(taskRefId);
    this.workflowTaskError.set(null);

    this.workflowActionSubscription = this.api.completeWorkflowTask(claimSk, taskRefId, user.email).subscribe({
      next: (event) => {
        this.workflowHistory.update((items) => [event, ...items]);
        this.workflowState.update((state) =>
          state ? { ...state, open_tasks: state.open_tasks.filter((task) => task.task_ref_id !== taskRefId) } : state
        );
        this.completingTaskId.set(null);
      },
      error: (error) => {
        this.completingTaskId.set(null);
        this.workflowTaskError.set(
          error?.error?.message ?? 'Impossible de cloturer la tache. Reessayez dans quelques instants.'
        );
      }
    });
  }

  workflowEventLabel(event: WorkflowEvent): string {
    switch (event.event_type) {
      case 'STATUS_CHANGE':
        return `Statut -> ${this.workflowStatusLabel(event.status)}`;
      case 'ASSIGNMENT':
        return event.assignee_email ? `Affecte a ${event.assignee_email}` : 'Desaffecte';
      case 'TASK_CREATED':
        return `Tache creee : ${event.task_label}`;
      case 'TASK_COMPLETED': {
        const created = this.workflowHistory().find(
          (item) => item.event_type === 'TASK_CREATED' && item.event_id === event.task_ref_id
        );
        return created ? `Tache cloturee : ${created.task_label}` : 'Tache cloturee';
      }
      default:
        return event.event_type;
    }
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

  printDossier(): void {
    window.print();
  }

  // Code source brut (etatgrnt) : seuls C/O sont documentes et confirmes par
  // la logique metier existante (etl/dwh/load_fact_sinistre.py::_bool_cloture).
  // Les autres codes observes (E/G/M, <0.01% des dossiers) restent affiches
  // en brut plutot que de deviner leur sens.
  guaranteeStatusLabel(code: string | null | undefined): string {
    if (!code) {
      return '—';
    }
    const known: Record<string, string> = { C: 'Clos', O: 'Ouvert' };
    return known[code.toUpperCase()] ?? `Code source : ${code}`;
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

  private groupPostInspections(items: ClaimPostInspectionItem[]): GroupedPostInspectionItem[] {
    const groups = new Map<string, GroupedPostInspectionItem>();
    for (const item of items) {
      const key = [
        item.inspection_sk ?? 'no-sk',
        item.immatriculation ?? '',
        item.inspection_date ?? '',
        item.days_inspection_to_claim ?? ''
      ].join('|');
      const current = groups.get(key) ?? {
        ...item,
        defective_zones: [],
        checkpoint_labels: [],
        signal_count: 0,
        max_critical_checkpoint_count: 0
      };

      current.signal_count += 1;
      current.defective_checkpoint_count = Math.max(
        Number(current.defective_checkpoint_count ?? 0),
        Number(item.defective_checkpoint_count ?? 0)
      );
      current.critical_checkpoint_count = Math.max(
        Number(current.critical_checkpoint_count ?? 0),
        Number(item.critical_checkpoint_count ?? 0)
      );
      current.max_critical_checkpoint_count = Math.max(
        current.max_critical_checkpoint_count,
        Number(item.critical_checkpoint_count ?? 0)
      );
      if (item.defective_zone && !current.defective_zones.includes(item.defective_zone)) {
        current.defective_zones.push(item.defective_zone);
      }
      for (const label of this.checkpointLabels(item)) {
        if (!current.checkpoint_labels.includes(label)) {
          current.checkpoint_labels.push(label);
        }
      }
      if (!current.business_explanation && item.business_explanation) {
        current.business_explanation = item.business_explanation;
      }
      groups.set(key, current);
    }
    return [...groups.values()].sort((a, b) => Number(a.days_inspection_to_claim ?? 99999) - Number(b.days_inspection_to_claim ?? 99999));
  }

  relatedClaimQueryParams(): { returnTo?: number } | null {
    const current = this.claim()?.claim_sk;
    return current ? { returnTo: current } : null;
  }
  relatedClaimLabel(item: ClaimRelatedItem): string {
    const root = item.numero_sinistre ?? item.claim_business_id ?? `#${item.claim_sk}`;
    const garantie = item.code_garantie ? ` | ${item.code_garantie}` : '';
    return `${root}${garantie}`;
  }

  relatedClaimAmount(item: ClaimRelatedItem): string {
    if (item.claim_amount === null || item.claim_amount === undefined) {
      return 'Montant non renseigné';
    }
    return `${Math.round(Number(item.claim_amount)).toLocaleString('fr-FR')} TND`;
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
      .replace(/[\u0300-\u036f]/g, '');
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
      .replace(/[\u0300-\u036f]/g, '');
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

  setInspectionCheckpointFilter(filter: InspectionCheckpointFilter): void {
    this.inspectionCheckpointFilter.set(filter);
  }

  inspectionCheckpointFilterLabel(filter: InspectionCheckpointFilter): string {
    const labels: Record<InspectionCheckpointFilter, string> = {
      all: 'Tous',
      anomalies: 'Anomalies',
      critical: 'Critiques'
    };
    return labels[filter];
  }

  zoneLabel(zone: string | null | undefined): string {
    if (!zone) {
      return 'Autre';
    }
    return ZONE_LABELS[zone] ?? zone.toLowerCase().replace(/_/g, ' ');
  }

  checkpointTone(checkpoint: VhsCheckpointItem): 'ok' | 'medium' | 'high' | 'unknown' {
    if (checkpoint.est_anomalie_critique === true || checkpoint.is_vital === true || checkpoint.is_immobilizing === true) {
      return 'high';
    }
    if (checkpoint.est_anomalie === true || Number(checkpoint.penalty_applied || 0) > 0) {
      return 'medium';
    }
    if (checkpoint.est_controle_renseigne === true) {
      return 'ok';
    }
    return 'unknown';
  }

  inspectionImageUrl(image: VhsImageLink): string | null {
    if (!image.asset_url) {
      return null;
    }
    if (/^https?:\/\//i.test(image.asset_url)) {
      return image.asset_url;
    }
    const apiRoot = this.api.apiBaseUrl.replace(/\/api$/, '');
    return `${apiRoot}${image.asset_url}`;
  }

  inspectionImageLabel(image: VhsImageLink): string {
    return image.slot.replace('image', 'Photo ');
  }


  openInspectionPhoto(image: VhsImageLink): void {
    if (this.inspectionAssetKind(image) !== 'image') {
      return;
    }
    const url = this.inspectionImageUrl(image);
    if (!url) {
      return;
    }
    this.selectedInspectionPhoto.set({ url, label: this.inspectionImageLabel(image) });
  }

  closeInspectionPhoto(): void {
    this.selectedInspectionPhoto.set(null);
  }
  inspectionImageStatusLabel(image: VhsImageLink): string {
    const mime = (image.display_mime_type ?? image.mime_type ?? '').toLowerCase();
    if (image.is_imported && ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif'].includes(mime)) {
      return 'Affichee dans IRIS';
    }
    if (image.is_imported) {
      return 'Apercu a generer';
    }
    if (image.storage_status === 'ERROR') {
      return 'Erreur import';
    }
    return 'Non integree';
  }

  inspectionAssetKind(image: VhsImageLink): 'image' | 'heic' | 'pdf' | 'document' | 'missing' {
    if (!image.is_imported || !image.asset_url) {
      return 'missing';
    }
    const mime = (image.display_mime_type ?? image.mime_type ?? '').toLowerCase();
    if (mime === 'image/heic' || mime === 'image/heif') {
      return 'heic';
    }
    if (['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif'].includes(mime)) {
      return 'image';
    }
    if (mime === 'application/pdf') {
      return 'pdf';
    }
    return 'document';
  }

  openVhsModal(item: { inspection_sk?: number | null; immatriculation?: string | null; inspection_date?: string | null }): void {
    const immatriculation = item.immatriculation;
    const inspectionDate = item.inspection_date;

    if (!immatriculation || !inspectionDate) {
      return;
    }
    this.vhsModalLoading.set(true);
    this.inspectionCheckpointFilter.set('all');
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











