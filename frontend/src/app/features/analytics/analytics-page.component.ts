import { Component, inject, signal } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { AuthService } from '../../core/auth/auth.service';

/**
 * URL du rapport publie sur Power BI Report Server (on-premises).
 * Laisser vide tant que la publication n'est pas faite : la page affiche
 * alors l'etat "publication a venir" au lieu d'un lien mort.
 *
 * Deux copies distinctes du rapport : la session IRIS (auth simulee cote
 * navigateur) n'a aucun lien avec l'identite Windows reelle qui authentifie
 * l'iframe Power BI Report Server (RLS/OLS Power BI ne peut donc pas suivre
 * le role choisi a la connexion IRIS). La copie "analyste" ne contient
 * simplement pas la page Qualite et Gouvernance : la restriction est garantie
 * par l'absence de la page dans le fichier publie, pas par un role Power BI.
 *
 * Le chemin publie sur le serveur Power BI (irisdash2-gestionnaire) garde
 * encore l'ancien nom de role : c'est un artefact externe (fichier deja
 * publie), pas la terminologie IRIS -- a renommer cote Power BI Report
 * Server separement si besoin, ce n'est pas un simple refactoring de code.
 */
const REPORT_SERVER_URL_FULL = 'http://localhost/Reports/powerbi/irisdash2';
const REPORT_SERVER_URL_ANALYSTE = 'http://localhost/Reports/powerbi/irisdash2-gestionnaire';

@Component({
  selector: 'app-analytics-page',
  standalone: true,
  templateUrl: './analytics-page.component.html',
  styleUrl: './analytics-page.component.scss'
})
export class AnalyticsPageComponent {
  private readonly sanitizer = inject(DomSanitizer);
  private readonly auth = inject(AuthService);

  readonly reportUrl =
    this.auth.currentUser()?.role === 'analyste' ? REPORT_SERVER_URL_ANALYSTE : REPORT_SERVER_URL_FULL;
  readonly reportEmbedLoaded = signal(false);

  /**
   * rs:embed=true masque le bandeau/toolbar natif de Power BI Report Server
   * pour un rendu propre en iframe, sans dupliquer sa propre navigation.
   */
  readonly reportEmbedUrl: SafeResourceUrl | null = this.reportUrl
    ? this.sanitizer.bypassSecurityTrustResourceUrl(`${this.reportUrl}?rs:embed=true`)
    : null;
}
