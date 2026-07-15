import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges, inject } from '@angular/core';
import { ReactiveFormsModule, NonNullableFormBuilder } from '@angular/forms';
import { Subscription, debounceTime } from 'rxjs';
import { WorklistFilters, WorklistOption, WorklistViewMode } from '../../../core/models/claim-summary.model';

@Component({
  selector: 'app-worklist-filters',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './worklist-filters.component.html',
  styleUrl: './worklist-filters.component.scss'
})
export class WorklistFiltersComponent implements OnInit, OnChanges, OnDestroy {
  private readonly fb = inject(NonNullableFormBuilder);
  private subscription?: Subscription;

  @Input({ required: true }) filters!: WorklistFilters;
  @Output() filtersChange = new EventEmitter<Partial<WorklistFilters>>();
  @Output() resetFilters = new EventEmitter<void>();

  // Les valeurs correspondent aux attention_level reellement produits par le
  // scoring (mart.fact_claim_attention_score) — pas de libelles inventes.
  readonly attentionOptions: WorklistOption[] = [
    { value: '', label: 'Tous niveaux' },
    { value: 'Examen prioritaire suggere', label: 'Examen prioritaire' },
    { value: 'Examen renforce suggere', label: 'Examen renforce' },
    { value: 'Points a verifier', label: 'Points a verifier' },
    { value: 'Analyse standard', label: 'Analyse standard' }
  ];

  readonly confidenceOptions: WorklistOption[] = [
    { value: '', label: 'Toute confiance' },
    { value: 'HIGH', label: 'Elevee' },
    { value: 'MEDIUM', label: 'Moyenne' },
    { value: 'LOW', label: 'Limitee' }
  ];

  readonly validationOptions: WorklistOption[] = [
    { value: '', label: 'Toute validation' },
    { value: 'NONE', label: 'Non revu' },
    { value: 'SUSPICION_CONFIRMED', label: 'Suspicion confirmee' },
    { value: 'CONFORME', label: 'Conforme' },
    { value: 'A_COMPLETER', label: 'A completer' }
  ];

  readonly form = this.fb.group({
    search: [''],
    attentionLevel: [''],
    confidenceLevel: [''],
    validationStatus: [''],
    hasMl: [false],
    hasPostInspection: [false],
    viewMode: ['comfortable' as WorklistViewMode]
  });

  ngOnInit(): void {
    this.form.patchValue({
      search: this.filters.search ?? '',
      attentionLevel: this.filters.attentionLevel ?? '',
      confidenceLevel: this.filters.confidenceLevel ?? '',
      validationStatus: this.filters.validationStatus ?? '',
      hasMl: this.filters.hasMl ?? false,
      hasPostInspection: this.filters.hasPostInspection ?? false,
      viewMode: this.filters.viewMode
    }, { emitEvent: false });

    this.subscription = this.form.valueChanges.pipe(debounceTime(450)).subscribe((value) => {
      const search = value.search?.trim() ?? '';
      if (search.length > 0 && search.length < 3) {
        return;
      }
      this.filtersChange.emit({
        ...value,
        viewMode: value.viewMode as WorklistViewMode,
        page: 1
      });
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    // Les filtres peuvent changer depuis l exterieur (puces de triage) :
    // le formulaire doit rester le reflet de l etat courant, sans re-emettre.
    if (changes['filters'] && !changes['filters'].isFirstChange()) {
      this.form.patchValue(
        {
          search: this.filters.search ?? '',
          attentionLevel: this.filters.attentionLevel ?? '',
          confidenceLevel: this.filters.confidenceLevel ?? '',
          validationStatus: this.filters.validationStatus ?? '',
          hasMl: this.filters.hasMl ?? false,
          hasPostInspection: this.filters.hasPostInspection ?? false,
          viewMode: this.filters.viewMode
        },
        { emitEvent: false }
      );
    }
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }
}

