// Cellule fraude BNA : deux profils metier (analyste, responsable) + un profil
// technique (administrateur) qui n'appartient pas a la cellule elle-meme.
// "gestionnaire"/"manager" ne sont plus les termes utilises par le metier.
export type IrisRole = 'analyste' | 'responsable' | 'administrateur';

export const IRIS_ROLE_LABELS: Record<IrisRole, string> = {
  analyste: 'Analyste fraude',
  responsable: 'Responsable',
  administrateur: 'Administrateur'
};

export const IRIS_ROLE_HOME_ROUTE: Record<IrisRole, string> = {
  analyste: '/app/claims',
  responsable: '/app/dashboard',
  administrateur: '/app/administration'
};

// Autorisation par route (source de verite pour roleGuard). Doit rester en
// phase avec les tableaux "roles" de app-layout.component.ts (navItems) --
// ceux-la controlent l'affichage du lien, celui-ci controle l'acces reel a
// l'URL : avant l'ajout de roleGuard, n'importe quel utilisateur authentifie
// pouvait ouvrir n'importe quelle page /app/* en tapant l'URL directement,
// quel que soit son role.
export const IRIS_ROUTE_ROLES: Record<string, IrisRole[]> = {
  dashboard: ['responsable', 'administrateur'],
  claims: ['analyste', 'responsable'],
  vehicle: ['analyste', 'responsable'],
  analytics: ['analyste', 'responsable', 'administrateur'],
  feedback: ['analyste', 'responsable'],
  assignments: ['responsable'],
  audit: ['responsable', 'administrateur'],
  administration: ['administrateur']
};

export interface IrisUserContext {
  displayName: string;
  email?: string;
  role: IrisRole;
  roleLabel: string;
}
