import { useEffect, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { listAccounts, saveAccount, type DashboardAccount } from '@/lib/api';

const blank: DashboardAccount = {email: '', role: 'VIEW_ONLY'};
const roleLabels = {VIEW_ONLY: 'Somente leitura', INFRA_ADMIN: 'Administrador'};

export function AccountManager({email, onSignOut}: {email?: string; onSignOut: () => void}) {
  const [accounts, setAccounts] = useState<DashboardAccount[] | null>(null);
  const [draft, setDraft] = useState<DashboardAccount | null>(null);
  const [original, setOriginal] = useState<DashboardAccount | null>(null);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    listAccounts().then(items => { if (active) setAccounts(items); })
      .catch(() => { if (active) setError('Não foi possível carregar os usuários.'); });
    return () => { active = false; };
  }, []);

  function edit(account: DashboardAccount | null) {
    setOriginal(account);
    setDraft(account ?? blank);
    setPassword('');
    setError('');
    setSaved(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || busy) return;
    setBusy(true);
    setError('');
    try {
      const account = await saveAccount(draft, password, original?.email);
      if (original && original.email === email &&
          (original.email !== account.email || original.role !== account.role || password)) {
        onSignOut();
        return;
      }
      setAccounts(items => [...(items ?? []).filter(item => item.email !== original?.email), account]
        .sort((a, b) => a.email.localeCompare(b.email)));
      setDraft(null);
      setPassword('');
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível salvar o usuário.');
    } finally {
      setBusy(false);
    }
  }

  const field = 'w-full rounded-md border border-[#cfddd3] bg-white p-2';
  return <section className="space-y-2 text-sm">
    <div className="flex items-center justify-between gap-2">
      <h3 className="font-semibold">Usuários</h3>
      <Button size="sm" variant="outline" disabled={busy || !accounts} onClick={() => edit(null)}>Adicionar</Button>
    </div>
    {accounts === null && !error && <p role="status">Carregando usuários…</p>}
    <ul className="divide-y divide-[#e5ebe7]">
      {accounts?.map(account => <li key={account.email} className="flex items-center justify-between gap-2 py-2">
        <span className="min-w-0 break-words">{account.email}<span className="block text-xs text-muted-foreground">{roleLabels[account.role]}</span></span>
        <Button size="sm" variant="ghost" disabled={busy} aria-label={`Editar ${account.email}`} onClick={() => edit(account)}>Editar</Button>
      </li>)}
    </ul>
    {draft && <form onSubmit={submit} className="space-y-2 rounded-md bg-[#f1f7f3] p-3">
      <fieldset disabled={busy} className="space-y-2">
        <legend className="font-semibold">{original ? 'Editar usuário' : 'Novo usuário'}</legend>
        <label className="block">E-mail
          <input className={field} inputMode="email" required maxLength={254} value={draft.email}
            onChange={event => setDraft({...draft, email: event.target.value})} />
        </label>
        <label className="block">Permissão
          <select className={field} value={draft.role} onChange={event => setDraft({...draft, role: event.target.value as DashboardAccount['role']})}>
            <option value="VIEW_ONLY">Somente leitura</option><option value="INFRA_ADMIN">Administrador</option>
          </select>
        </label>
        <label className="block">{original ? 'Nova senha (opcional)' : 'Senha'}
          <input className={field} type="password" autoComplete="new-password" required={!original} minLength={8} maxLength={256}
            value={password} onChange={event => setPassword(event.target.value)} />
        </label>
        <div className="flex gap-2">
          <Button type="submit" size="sm">{busy ? 'Salvando…' : 'Salvar'}</Button>
          <Button type="button" size="sm" variant="outline" onClick={() => { setDraft(null); setPassword(''); setError(''); }}>Cancelar</Button>
        </div>
      </fieldset>
    </form>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {saved && <p role="status">Usuário salvo.</p>}
  </section>;
}
