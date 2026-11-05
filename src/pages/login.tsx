import { useState, type FormEvent } from 'react';
import { Redirect, useLocation } from 'wouter';
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Eye,
  EyeOff,
  Leaf,
  Loader2,
  Lock,
  Mail,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth';

const DEMO_EMAIL = 'admin@sb100.io';
const DEMO_PASSWORD = 'demo1234';
const logoUrl = `${import.meta.env.BASE_URL}CCDSB100.jpg`;

const highlights = [
  {
    icon: Leaf,
    title: 'Pesquisa agrícola com IA',
    description:
      'Dados, modelos e infraestrutura do CCD-SB100 em uma única plataforma.',
  },
  {
    icon: BarChart3,
    title: 'Inteligência de custos',
    description:
      'Acompanhe o consumo e os custos da infraestrutura de IA do projeto.',
  },
  {
    icon: ShieldCheck,
    title: 'Alertas acionáveis',
    description:
      'Sinais priorizados para a equipe agir antes que afetem a pesquisa.',
  },
];

export default function Login() {
  const { user, signIn } = useAuth();
  const [, navigate] = useLocation();
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (user) {
    return <Redirect to="/" />;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedEmail = email.trim();

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError('Informe um e-mail válido.');
      return;
    }
    if (password.length < 4) {
      setError('Sua senha precisa ter pelo menos 4 caracteres.');
      return;
    }

    setError('');
    setSubmitting(true);
    window.setTimeout(() => {
      signIn(trimmedEmail, remember);
      navigate('/', { replace: true });
    }, 400);
  }

  return (
    <main className="min-h-[100dvh] bg-[#f6f9f7] text-[#203329] lg:grid lg:grid-cols-[minmax(0,1.02fr)_minmax(0,1fr)]">
      <section className="relative hidden overflow-hidden bg-[#123d2c] px-12 py-11 text-white lg:flex lg:flex-col lg:justify-between xl:px-16 xl:py-14">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(900px 520px at 8% -8%, rgba(92,180,137,.34), transparent 62%), radial-gradient(620px 460px at 105% 105%, rgba(201,164,80,.18), transparent 60%)',
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[.09]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,.55) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.55) 1px, transparent 1px)',
            backgroundSize: '46px 46px',
            maskImage:
              'radial-gradient(circle at 30% 20%, black, transparent 74%)',
          }}
        />

        <div className="relative flex items-center gap-3">
          <div className="h-11 w-11 shrink-0 overflow-hidden rounded-xl bg-white ring-1 ring-inset ring-white/25">
            <img
              src={logoUrl}
              alt="Logo do Projeto CCD-SB100"
              className="h-full w-full object-cover"
            />
          </div>
          <div>
            <div className="font-display text-[16px] font-extrabold tracking-[-.045em]">
              CCD-SB100
            </div>
            <div className="text-[11px] font-medium text-white/55">
              Pesquisa agrícola com IA
            </div>
          </div>
        </div>

        <div className="relative max-w-[480px] py-14">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/8 px-3 py-1 font-mono text-[10px] font-medium uppercase tracking-[.16em] text-emerald-100/85 backdrop-blur-sm">
            <Sparkles className="h-3 w-3" />
            Projeto CCD-SB100 · FAPESP
          </div>
          <h1 className="font-display text-[38px] font-extrabold leading-[1.06] tracking-[-.055em] xl:text-[44px]">
            Dados e IA a serviço da agricultura.
          </h1>
          <p className="mt-4 max-w-[420px] text-[14px] leading-relaxed text-white/62">
            Dashboard DevOps do Projeto CCD-SB100, uma iniciativa de pesquisa
            em agricultura com inteligência artificial apoiada pela FAPESP.
          </p>

          <div className="mt-9 space-y-4">
            {highlights.map(({ icon: Icon, title, description }) => (
              <div key={title} className="flex items-start gap-3.5">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/12 bg-white/8 text-emerald-100">
                  <Icon className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-[13px] font-semibold text-white/92">
                    {title}
                  </div>
                  <div className="mt-0.5 text-[12px] leading-relaxed text-white/48">
                    {description}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-5 border-t border-white/10 pt-5 text-[11px] text-white/45">
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300/80" />
            99,96% de disponibilidade
          </span>
          <span className="h-3 w-px bg-white/15" />
          <span className="inline-flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-300/80" />
            Monitoramento contínuo
          </span>
        </div>
      </section>

      <section className="flex min-h-[100dvh] flex-col px-5 py-6 sm:px-8 lg:px-12">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 lg:invisible">
            <div className="h-9 w-9 shrink-0 overflow-hidden rounded-lg bg-white ring-1 ring-[#dbe5de]">
              <img
                src={logoUrl}
                alt="Logo do Projeto CCD-SB100"
                className="h-full w-full object-cover"
              />
            </div>
            <div>
              <div className="font-display text-[14px] font-extrabold tracking-[-.045em] text-[#203329]">
                CCD-SB100
              </div>
              <div className="text-[10px] font-medium text-[#7f8c85]">
                Pesquisa agrícola com IA
              </div>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[#e0e9e3] bg-white px-2.5 py-1 text-[10px] font-semibold text-[#6c7b72]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#4a9867]" />
            Ambiente seguro
          </span>
        </div>

        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[396px] animate-in fade-in slide-in-from-bottom-2 duration-500">
            <div className="mb-7">
              <div className="font-mono text-[10px] font-medium uppercase tracking-[.17em] text-[#829188]">
                Acesso ao dashboard
              </div>
              <h2 className="mt-2 font-display text-[28px] font-extrabold leading-tight tracking-[-.05em] text-[#1d3027] sm:text-[31px]">
                Bem-vindo de volta
              </h2>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#75827a]">
                Entre para acessar o dashboard do Projeto CCD-SB100.
              </p>
            </div>

            <form onSubmit={handleSubmit} noValidate className="space-y-4">
              <div>
                <label
                  htmlFor="email"
                  className="mb-1.5 block font-mono text-[10px] font-medium uppercase tracking-[.13em] text-[#65776b]"
                >
                  E-mail
                </label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#93a198]" />
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(event) => {
                      setEmail(event.target.value);
                      if (error) setError('');
                    }}
                    placeholder="voce@instituicao.br"
                    aria-invalid={Boolean(error)}
                    className="h-11 w-full rounded-lg border border-[#dbe5de] bg-white pl-10 pr-3.5 text-[13px] text-[#203329] shadow-[0_1px_2px_rgba(29,48,39,.03)] outline-none transition-colors placeholder:text-[#a6b1aa] focus:border-[#8ab7a0] focus:ring-2 focus:ring-[#1f684a]/12"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="password"
                  className="mb-1.5 block font-mono text-[10px] font-medium uppercase tracking-[.13em] text-[#65776b]"
                >
                  Senha
                </label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#93a198]" />
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      if (error) setError('');
                    }}
                    placeholder="Digite sua senha"
                    aria-invalid={Boolean(error)}
                    className="h-11 w-full rounded-lg border border-[#dbe5de] bg-white pl-10 pr-11 text-[13px] text-[#203329] shadow-[0_1px_2px_rgba(29,48,39,.03)] outline-none transition-colors placeholder:text-[#a6b1aa] focus:border-[#8ab7a0] focus:ring-2 focus:ring-[#1f684a]/12"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((value) => !value)}
                    aria-label={
                      showPassword ? 'Ocultar senha' : 'Mostrar senha'
                    }
                    className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded text-[#93a198] transition-colors hover:bg-[#f0f5f1] hover:text-[#4f6b5b]"
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between gap-3">
                <label className="inline-flex cursor-pointer items-center gap-2 text-[12px] text-[#65776b]">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(event) => setRemember(event.target.checked)}
                    className="h-3.5 w-3.5 cursor-pointer rounded border-[#c9d7ce] accent-[#1f684a]"
                  />
                  Manter conectado
                </label>
                <span className="font-mono text-[10px] uppercase tracking-[.1em] text-[#9aa69f]">
                  RBAC ativo
                </span>
              </div>

              {error && (
                <div
                  role="alert"
                  className="rounded-lg border border-[#f0c9c3] bg-[#fff4f2] px-3 py-2.5 text-[12px] font-medium text-[#a83c30]"
                >
                  {error}
                </div>
              )}

              <Button
                type="submit"
                disabled={submitting}
                className="h-11 w-full rounded-lg bg-[#1f684a] text-[13px] font-semibold text-white shadow-[0_6px_16px_rgba(31,104,74,.18)] hover:bg-[#1a5b40]"
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Entrando…
                  </>
                ) : (
                  <>
                    Entrar no dashboard
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </Button>
            </form>

            <div className="mt-6 rounded-lg border border-[#e0e9e3] bg-[#f2f7f3] px-4 py-3">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#3d6f56]">
                <Sparkles className="h-3.5 w-3.5" />
                Acesso de demonstração
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[#7a8880]">
                As credenciais já estão preenchidas. Basta clicar em{' '}
                <span className="font-semibold text-[#5b6f62]">
                  Entrar no dashboard
                </span>
                .
              </p>
            </div>

            <p className="mt-8 text-center font-mono text-[9px] uppercase tracking-[.14em] text-[#a3aea7]">
              © 2026 CCD-SB100 · Ambiente de demonstração
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}
