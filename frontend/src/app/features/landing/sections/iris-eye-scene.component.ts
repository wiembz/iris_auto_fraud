import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy } from '@angular/core';

/**
 * Scene hero "L'oeil vivant" : l'iris de la marque en grand format.
 * - La pupille suit le curseur du visiteur (eye-tracking).
 * - Des particules de donnees convergent vers l'oeil (flux entrant),
 *   des particules validees en ressortent vers la carte decision (flux sortant).
 * - Pupille qui se dilate, anneaux qui tournent : l'oeil est vivant.
 * 100% SVG + CSS + SMIL — leger, net, fidele au logo.
 */
@Component({
  selector: 'app-iris-eye-scene',
  standalone: true,
  templateUrl: './iris-eye-scene.component.html',
  styleUrl: './iris-eye-scene.component.scss'
})
export class IrisEyeSceneComponent implements AfterViewInit, OnDestroy {
  /* Meme roue chromatique que le logo iris-logo. */
  readonly petals = [
    { angle: 0, color: '#1ee6c0' },
    { angle: 45, color: '#1fd2ce' },
    { angle: 90, color: '#1fbedb' },
    { angle: 135, color: '#2ba7e5' },
    { angle: 180, color: '#3f8fee' },
    { angle: 225, color: '#2ba7e5' },
    { angle: 270, color: '#1fbedb' },
    { angle: 315, color: '#1fd2ce' }
  ];

  private readonly reducedMotion =
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  private frameId = 0;
  private pendingEvent?: MouseEvent;
  private readonly onMouseMove = (event: MouseEvent): void => {
    this.pendingEvent = event;
    if (!this.frameId) {
      this.frameId = requestAnimationFrame(() => this.applyGaze());
    }
  };

  constructor(
    private readonly host: ElementRef<HTMLElement>,
    private readonly ngZone: NgZone
  ) {}

  ngAfterViewInit(): void {
    if (this.reducedMotion) {
      return;
    }
    this.ngZone.runOutsideAngular(() => {
      window.addEventListener('mousemove', this.onMouseMove, { passive: true });
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('mousemove', this.onMouseMove);
    cancelAnimationFrame(this.frameId);
  }

  private applyGaze(): void {
    this.frameId = 0;
    const event = this.pendingEvent;
    if (!event) {
      return;
    }

    const node = this.host.nativeElement;
    const rect = node.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;

    /* Regard normalise puis attenue : l'oeil suit sans loucher. */
    const nx = Math.max(-1, Math.min(1, (event.clientX - cx) / (rect.width * 0.9)));
    const ny = Math.max(-1, Math.min(1, (event.clientY - cy) / (rect.height * 0.9)));

    node.classList.add('is-tracking');
    node.style.setProperty('--gaze-x', `${(nx * 30).toFixed(1)}px`);
    node.style.setProperty('--gaze-y', `${(ny * 24).toFixed(1)}px`);
  }
}
