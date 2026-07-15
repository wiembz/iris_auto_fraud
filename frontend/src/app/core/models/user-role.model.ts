export type IrisRole = 'gestionnaire' | 'responsable' | 'manager' | 'administrateur';

export const IRIS_ROLE_LABELS: Record<IrisRole, string> = {
  gestionnaire: 'Gestionnaire sinistre',
  responsable: 'Responsable sinistre',
  manager: 'Manager',
  administrateur: 'Administrateur'
};

export const IRIS_ROLE_HOME_ROUTE: Record<IrisRole, string> = {
  gestionnaire: '/app/claims',
  responsable: '/app/dashboard',
  manager: '/app/dashboard',
  administrateur: '/app/administration'
};

export interface IrisUserContext {
  displayName: string;
  email?: string;
  role: IrisRole;
  roleLabel: string;
}
