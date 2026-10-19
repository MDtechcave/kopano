import { useCallback, useEffect, useState } from 'react';
import { api, TOKEN_KEY } from './services/api';
import type { BasketLine, Page, Quote, User } from './types';
import { Button, ErrorBox, Footer, Logo } from './components/ui';
import RegisterPage from './pages/RegisterPage';
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import CataloguePage from './pages/CataloguePage';
import BasketPage from './pages/BasketPage';
import ClientWorkspace from './pages/ClientWorkspace';
import SalesWorkspace from './pages/SalesWorkspace';
import QuoteWorkspace from './pages/QuoteWorkspace';
import TeamWorkspace from './pages/TeamWorkspace';

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(null);
  const [page, setPage] = useState<Page>('catalogue');
  const [businessName, setBusinessName] = useState('Kopano Industrial Supply');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [basket, setBasket] = useState<BasketLine[]>(() => { try { return JSON.parse(localStorage.getItem('tradeline_quote_basket') || '[]') as BasketLine[]; } catch { return []; } });
  const [activeQuoteId, setActiveQuoteId] = useState<number | null>(null);
  const [returnPage, setReturnPage] = useState<Page>('catalogue');

  const refreshMe = useCallback(async (currentToken: string) => {
    const me = await api<User>('/api/auth/me', {}, currentToken);
    setUser(me);
    if (me.must_change_password) setPage('password');
    return me;
  }, []);

  useEffect(() => {
    api<{ business_name?: string }>('/api/config').then((c) => { if (c.business_name) setBusinessName(c.business_name); }).catch(() => undefined);
    if (token) refreshMe(token).catch(() => { setToken(null); localStorage.removeItem(TOKEN_KEY); setUser(null); });
  }, []); // initial session only
  useEffect(() => { try { localStorage.setItem('tradeline_quote_basket', JSON.stringify(basket)); } catch { /* Storage may be unavailable; basket still works for this session. */ } }, [basket]);
  useEffect(() => {
    const expired = () => { setToken(null); setUser(null); setPage('login'); setError('Your session has ended. Please sign in again.'); };
    window.addEventListener('tradeline:session-expired', expired);
    return () => window.removeEventListener('tradeline:session-expired', expired);
  }, []);

  const clearMessages = () => { setError(''); setNotice(''); };
  const go = (next: Page) => { clearMessages(); setPage(next); setMenuOpen(false); window.scrollTo({ top: 0, behavior: 'smooth' }); };
  const signOut = () => { localStorage.removeItem(TOKEN_KEY); setToken(null); setUser(null); setActiveQuoteId(null); go('catalogue'); setNotice('You have signed out safely.'); };
  const signIn = async (email: string, password: string) => {
    setLoading(true); clearMessages();
    try { const result = await api<{ access_token: string; user: User }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }); localStorage.setItem(TOKEN_KEY, result.access_token); setToken(result.access_token); setUser(result.user); if (result.user.must_change_password) go('password'); else if (returnPage === 'basket' && result.user.role === 'client') go('basket'); else go(result.user.role === 'sales' ? (result.user.is_admin ? 'team' : 'sales') : 'client'); }
    catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  const register = async (form: { full_name: string; company: string; email: string; password: string }) => {
    setLoading(true); clearMessages();
    try { const result = await api<{ access_token: string; user: User }>('/api/auth/register', { method: 'POST', body: JSON.stringify(form) }); localStorage.setItem(TOKEN_KEY, result.access_token); setToken(result.access_token); setUser(result.user); go('client'); setNotice('Your client account is ready. Welcome to Kopano Industrial Supply.'); }
    catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  const afterPasswordChange = async () => { if (token) { const me = await refreshMe(token); setNotice('Password updated successfully.'); setPage(me.role === 'sales' ? (me.is_admin ? 'team' : 'sales') : 'client'); } };
  const forgotPassword = async (email: string): Promise<string | null> => {
    setLoading(true); clearMessages();
    try {
      const result = await api<{ message: string; temporary_password?: string | null }>('/api/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) });
      setNotice(result.temporary_password ? `Temporary password: ${result.temporary_password}. Sign in with it, then choose a new password.` : result.message);
      return result.temporary_password ?? null;
    }
    catch (e) {
      setError((e as Error).message);
      return null;
    }
    finally {
      setLoading(false);
    }
  };
  const openQuote = (id: number) => { setReturnPage(page); setActiveQuoteId(id); go('quote'); };
  const basketCount = basket.reduce((n, line) => n + line.quantity, 0);

  return <div className="app-shell">
    {page === 'login' || page === 'register' || page === 'password' ? (() => { const authProps = { businessName, loading, error, onLogin: signIn, onRegister: register, onForgotPassword: forgotPassword, onPasswordChange: async (current: string, next: string) => { setLoading(true); clearMessages(); try { await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) }, token); await afterPasswordChange(); } catch (e) { setError((e as Error).message); } finally { setLoading(false); } }, onMode: go, onBack: () => go('catalogue') }; return page === 'register' ? <RegisterPage {...authProps} /> : page === 'login' ? <LoginPage {...authProps} /> : <ChangePasswordPage {...authProps} />; })() : <>
      {['catalogue', 'basket'].includes(page) && <>
        <div className="utility-bar"><div className="wrap utility-inner"><span>Your partner in industrial supply.</span><span><b>Built for business</b><i className="utility-dot" />Quotation-led ordering · South Africa</span></div></div>
        <header className="site-header"><div className="wrap header-inner"><Logo onClick={() => go('catalogue')} /><nav className={menuOpen ? 'nav-open' : ''}><button className={page === 'catalogue' ? 'nav-current' : ''} onClick={() => go('catalogue')}>Catalogue</button>{user?.role === 'client' && <button onClick={() => go('client')}>My portal</button>}{user?.role === 'sales' && <button onClick={() => go('sales')}>Sales workspace</button>}{user?.is_admin && <button onClick={() => go('team')}>Team admin</button>}<button className="nav-mobile-only" onClick={() => user ? signOut() : go('login')}>{user ? 'Sign out' : 'Sign in'}</button></nav><div className="header-actions">{user ? <><span className="header-greeting">Hi, {user.full_name.split(' ')[0]}</span><Button kind="secondary" onClick={signOut}>Sign out</Button></> : <><Button kind="ghost" onClick={() => go('login')}>Sign in</Button><Button onClick={() => go('register')}>Create account</Button></>}<button className="basket-chip" onClick={() => go('basket')} aria-label={`Quote basket, ${basketCount} items`}><span>▤</span><b>{basketCount}</b></button><button className="hamburger" onClick={() => setMenuOpen(!menuOpen)} aria-label="Toggle navigation">{menuOpen ? '×' : '☰'}</button></div></div></header>
      </>}
      {error && <div className="wrap global-message"><ErrorBox message={error} /><button onClick={() => setError('')}>Dismiss</button></div>}{notice && <div className="wrap global-notice"><span>✓</span>{notice}<button onClick={() => setNotice('')}>×</button></div>}
      {page === 'catalogue' && <CataloguePage token={token} user={user} basket={basket} setBasket={setBasket} onBasket={() => go('basket')} onLogin={() => { setReturnPage('catalogue'); go('login'); }} />}
      {page === 'basket' && <BasketPage basket={basket} setBasket={setBasket} user={user} token={token} onBrowse={() => go('catalogue')} onLogin={() => { setReturnPage('basket'); go('login'); }} onSubmitted={(quote) => { setBasket([]); setActiveQuoteId(quote.id); go('client'); setNotice(`Request ${quote.reference} was submitted successfully.`); }} />}
      {page === 'client' && user?.role === 'client' && token && <ClientWorkspace token={token} user={user} onOpenQuote={openQuote} onBrowse={() => go('catalogue')} />}
      {page === 'sales' && user?.role === 'sales' && token && <SalesWorkspace token={token} user={user} onOpenQuote={openQuote} onManageTeam={() => go('team')} onSignOut={signOut} />}
      {page === 'team' && user?.role === 'sales' && user.is_admin && token && <TeamWorkspace token={token} onSales={() => go('sales')} onSignOut={signOut} />}
      {page === 'quote' && token && user && activeQuoteId !== null && <QuoteWorkspace token={token} user={user} quoteId={activeQuoteId} onBack={() => go(['client', 'sales', 'team'].includes(returnPage) ? returnPage : (user.role === 'sales' ? (user.is_admin ? 'team' : 'sales') : 'client'))} onChanged={() => { clearMessages(); }} />}
      {!user && !['catalogue', 'basket'].includes(page) && <div className="wrap section-pad"><div className="empty-card"><h2>Sign in to continue</h2><p>This area is available to registered Kopano Industrial Supply accounts.</p><Button onClick={() => go('login')}>Sign in</Button></div></div>}
      {['catalogue', 'basket'].includes(page) && <Footer businessName={businessName} onCatalogue={() => go('catalogue')} onLogin={() => go('login')} />}
    </>}
  </div>;
}
