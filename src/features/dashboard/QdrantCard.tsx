import { fetchQdrantMetrics, type Environment } from '@/lib/api';
import { useAsyncPoll } from '@/lib/useMetrics';

export function QdrantCard({env}: {env: Environment}) {
  const {data, error, loading} = useAsyncPoll(signal => fetchQdrantMetrics(env, signal), 60000, [env]);
  return <section className="mb-4 rounded-lg border bg-white p-4">
    <p className="text-xs text-muted-foreground">Fonte · Qdrant</p>
    <h3 className="font-semibold">Coleções visíveis agora</h3>
    <p aria-live="polite">{error ? error.message.replace(/^API \d+: /, '') : data ? data.collections : loading ? 'Consultando…' : 'Indisponível'}</p>
  </section>;
}
