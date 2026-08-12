import { Component, Input } from '@angular/core';

let nextIrisLogoId = 0;

/**
 * Marque IRIS : une iris stylisee en "bloom" — huit petales-lamelles
 * disposes en diaphragme autour d'une pupille, degrade teal -> bleu.
 */
@Component({
  selector: 'iris-logo',
  standalone: true,
  template: `
    <svg
      [attr.width]="size"
      [attr.height]="size"
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      [class.is-animated]="animated"
      role="img"
      aria-label="Logo IRIS"
    >
      <defs>
        <radialGradient [attr.id]="'iris-p-' + uid" cx="0.38" cy="0.32" r="0.9">
          <stop offset="0" stop-color="#0d4a52" />
          <stop offset="1" stop-color="#041c22" />
        </radialGradient>
      </defs>

      <g class="petals">
        @for (petal of petals; track petal.angle; let i = $index) {
          <path
            d="M 0 -8 C 7.5 -9.5 13.5 -15 13 -26.5 C 4.5 -28.5 -3.5 -24 -5.8 -16.8 C -7.2 -12.2 -4.6 -8.8 0 -8 Z"
            [attr.transform]="'translate(32 32) rotate(' + petal.angle + ')'"
            [attr.fill]="petal.color"
            [attr.opacity]="i % 2 === 0 ? 0.96 : 0.66"
          />
        }
      </g>

      <circle cx="32" cy="32" r="7.4" [attr.fill]="'url(#iris-p-' + uid + ')'" />
      <circle cx="32" cy="32" r="7.4" fill="none" stroke="rgba(255, 255, 255, 0.35)" stroke-width="1" />
      <circle cx="29.5" cy="29.3" r="1.7" fill="#eafffb" opacity="0.9" />
    </svg>
  `,
  styles: [
    `
      :host {
        display: inline-flex;
        line-height: 0;
      }

      .petals {
        transform-origin: 32px 32px;
      }

      svg.is-animated .petals {
        animation: iris-logo-spin 32s linear infinite;
      }

      @keyframes iris-logo-spin {
        to {
          transform: rotate(360deg);
        }
      }

      @media (prefers-reduced-motion: reduce) {
        svg.is-animated .petals {
          animation: none;
        }
      }
    `
  ]
})
export class IrisLogoComponent {
  @Input() size = 32;
  @Input() animated = false;

  readonly uid = nextIrisLogoId++;

  /* Roue chromatique teal -> cyan -> bleu, symetrique autour de la pupille. */
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
}
