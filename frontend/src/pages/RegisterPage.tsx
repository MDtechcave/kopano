import type React from 'react';
import AuthPage from './AuthPage';
import type { Page } from '../types';

type Props = Omit<React.ComponentProps<typeof AuthPage>, 'mode'>;
export default function RegisterPage(props: Props) {
  return <AuthPage {...props} mode={'register' as Page} />;
}
