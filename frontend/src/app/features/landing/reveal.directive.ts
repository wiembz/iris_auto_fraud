import { Directive, ElementRef, Input, OnDestroy, OnInit } from '@angular/core';

/**
 * Revele l'element au scroll (fade + translation) via IntersectionObserver.
 * Usage : <div lpReveal [lpRevealDelay]="120">
 */
@Directive({
  selector: '[lpReveal]',
  standalone: true
})
export class LpRevealDirective implements OnInit, OnDestroy {
  @Input() lpRevealDelay = 0;

  private observer?: IntersectionObserver;

  constructor(private readonly el: ElementRef<HTMLElement>) {}

  ngOnInit(): void {
    const node = this.el.nativeElement;
    node.classList.add('lp-reveal');

    if (this.lpRevealDelay > 0) {
      node.style.transitionDelay = `${this.lpRevealDelay}ms`;
    }

    const reducedMotion =
      typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (reducedMotion || typeof IntersectionObserver === 'undefined') {
      node.classList.add('lp-reveal--in');
      return;
    }

    this.observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            node.classList.add('lp-reveal--in');
            this.observer?.unobserve(node);
          }
        }
      },
      { threshold: 0.12, rootMargin: '0px 0px -36px' }
    );

    this.observer.observe(node);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }
}
