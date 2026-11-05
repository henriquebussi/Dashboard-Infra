import { Link } from 'wouter';
import { ArrowLeft } from 'lucide-react';

const logoUrl = `${import.meta.env.BASE_URL}CCDSB100.jpg`;

export default function NotFound() {
  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-[#f6f9f7] px-4 py-10">
      <div className="w-full max-w-md rounded-xl border border-[#dfe8e2] bg-white p-8 text-center shadow-[0_4px_20px_rgba(33,64,45,.035)]">
        <div className="mx-auto h-14 w-14 overflow-hidden rounded-xl bg-white ring-1 ring-[#dfe7e1]">
          <img
            src={logoUrl}
            alt="Logo do Projeto CCD-SB100"
            className="h-full w-full object-cover"
          />
        </div>
        <div className="mt-5 font-mono text-[10px] font-medium uppercase tracking-[.16em] text-[#829188]">
          Erro 404
        </div>
        <h1 className="mt-2 font-display text-[26px] font-extrabold tracking-[-.045em] text-[#1d3027]">
          Página não encontrada
        </h1>
        <p className="mt-2 text-[13px] leading-relaxed text-[#75827a]">
          O endereço acessado não existe neste dashboard.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex h-9 items-center gap-2 rounded-md bg-[#1f684a] px-4 text-xs font-semibold text-white transition-colors hover:bg-[#1a5b40]"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Voltar ao dashboard
        </Link>
      </div>
    </main>
  );
}
