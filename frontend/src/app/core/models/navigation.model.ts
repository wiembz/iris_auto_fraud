import { IrisRole } from './user-role.model';

export interface IrisNavigationItem {
  label: string;
  route: string;
  roles?: IrisRole[];
}
