import { AccountManager } from './AccountManager';
import { useEffect, useId, useRef, useState } from 'react';
import { Bell, LogOut, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ThemeToggle } from '@/components/theme-toggle';
import { getSession } from '@/lib/api';
import type { AuthUser } from '@/lib/auth';
import type { Metric } from './mock-data';

type Alert = Metric & { section: string; sectionId: string };

export function HeaderActions({user, initials, alerts, scope, onSelect, onSignOut}: {
  user: AuthUser | null;
  initials: string;
  alerts: Alert[];
  scope: string;
  onSelect: (alert: Alert) => void;
  onSignOut: () => void;
}) {
  const actions = useRef<HTMLDivElement>(null);
  const notificationId = useId();
  const profileId = useId();
  const usersId = useId();
  const [openPanel, setOpenPanel] = useState<'notifications' | 'profile' | 'users' | null>(null);
  const [sessionRole, setSessionRole] = useState<'INFRA_ADMIN' | 'VIEW_ONLY' | 'error' | null>(null);
  const notificationsOpen = openPanel === 'notifications';
  const profileOpen = openPanel === 'profile';
  const usersOpen = openPanel === 'users';
  const role = sessionRole === 'INFRA_ADMIN' ? 'Administrador'
    : sessionRole === 'VIEW_ONLY' ? 'Somente leitura'
    : sessionRole === 'error' ? 'Não foi possível consultar as permissões.' : 'Consultando permissões…';

  useEffect(() => {
    let active = true;
    getSession().then(session => {
      if (active) setSessionRole(session.role);
    }).catch(() => {
      if (active) setSessionRole('error');
    });
    return () => { active = false; };
  }, [user?.email]);

  useEffect(() => {
    if (!openPanel) return;
    function closeOutside(event: PointerEvent) {
      if (event.target instanceof Node && !actions.current?.contains(event.target)) {
        setOpenPanel(null);
      }
    }
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, [openPanel]);

  const panel = 'absolute right-0 top-full z-50 mt-2 max-h-[65dvh] w-[min(22rem,calc(100vw-6rem))] overflow-auto rounded-lg border border-[#dce6df] bg-white p-4 shadow-lg';
  return <div ref={actions} className="relative flex items-center gap-2.5" onKeyDown={event => {
    if (event.key !== 'Escape' || !openPanel) return;
    actions.current?.querySelector<HTMLButtonElement>('button[aria-expanded="true"]')?.focus();
    setOpenPanel(null);
  }}>

    {sessionRole === 'INFRA_ADMIN' && <>
      <Button type="button" variant="ghost" aria-label="Usuários" aria-expanded={usersOpen} aria-controls={usersId}
        onClick={() => setOpenPanel(usersOpen ? null : 'users')} className="h-9 gap-1.5 px-2 text-[#326b4d]">
        <Users size={16} aria-hidden="true" /> <span className="hidden sm:inline">Usuários</span>
      </Button>
      <section id={usersId} hidden={!usersOpen} className={panel}>
        {usersOpen && <AccountManager email={user?.email} onSignOut={onSignOut} />}
      </section>
    </>}
        <ThemeToggle />
        <Button variant="ghost" size="icon" data-testid="button-notifications"
          aria-expanded={notificationsOpen} aria-controls={notificationId}
          onClick={() => setOpenPanel(notificationsOpen ? null : 'notifications')}
          aria-label={`Notificações · ${alerts.length} alertas ativos`}
          className="relative h-9 w-9 text-[#69796f] hover:bg-[#f0f5f1]">
          <Bell className="h-[17px] w-[17px]" aria-hidden="true" />
          {alerts.length > 0 && <span className="absolute right-1 top-0 rounded-full bg-[#286b4c] px-1 text-[9px] text-white">{alerts.length}</span>}
        </Button>
      <section id={notificationId} hidden={!notificationsOpen} className={panel}>
        <h2 className="font-semibold text-[#203329]">Notificações</h2>
        <p className="mb-2 text-xs text-muted-foreground">Alertas ativos · {scope}</p>
        {!alerts.length && <p className="text-sm text-muted-foreground">Nenhum alerta ativo no escopo atual.</p>}
        <ul className="divide-y divide-[#e5ebe7]">
          {alerts.map(alert => <li key={`${alert.sectionId}.${alert.id}`}>
            <button type="button" className="w-full rounded-md p-3 text-left text-sm hover:bg-[#f0f5f1]"
              onClick={() => { setOpenPanel(null); onSelect(alert); }}>
              <span className="block font-semibold text-[#203329]">{alert.label} · {alert.value}</span>
              <span className={alert.severity === 'critical' ? 'text-red-700 dark:text-red-300' : 'text-amber-800 dark:text-amber-300'}>
                {alert.severity === 'critical' ? 'Crítico' : 'Atenção'} · {alert.section}
              </span>
              {alert.action && <span className="block text-muted-foreground">{alert.action}</span>}
            </button>
          </li>)}
        </ul>
      </section>
    <span className="hidden h-7 w-px bg-[#e6ece8] sm:block" />
        <button type="button" aria-label="Abrir perfil" aria-expanded={profileOpen} aria-controls={profileId}
          onClick={() => setOpenPanel(profileOpen ? null : 'profile')}
          data-testid="text-team-avatar"
          className="flex h-8 w-8 items-center justify-center rounded-full border border-[#d7e5dc] bg-[#eff6f1] text-[10px] font-bold tracking-wide text-[#326b4d] hover:bg-[#e0eee5]">
          {initials}
        </button>
      <section id={profileId} hidden={!profileOpen} className={panel}>
        <h2 className="mb-3 font-semibold text-[#203329]">Meu perfil</h2>
        <dl className="grid gap-2 break-words rounded-lg bg-[#f1f7f3] p-4 text-sm">
          <div><dt className="font-semibold">Nome</dt><dd>{user?.name}</dd></div>
          <div><dt className="font-semibold">E-mail</dt><dd>{user?.email}</dd></div>
          <div><dt className="font-semibold">Permissão</dt><dd aria-live="polite">{role}</dd></div>
        </dl>
        <Button variant="outline" onClick={onSignOut} className="mt-3 w-fit">
          <LogOut size={16} aria-hidden="true" /> Sair
        </Button>
      </section>
  </div>;
}
