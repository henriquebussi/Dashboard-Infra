import Chart from 'react-apexcharts';
import type { ApexOptions } from 'apexcharts';

type Props = {
  labels: string[];
  series: { name: string; values: number[]; color?: string }[];
  compact?: boolean;
  type?: 'line' | 'area' | 'bar';
  stacked?: boolean;
};

export function ApexChart({ labels, series, compact = false, type = 'area', stacked = false }: Props) {
  const options: ApexOptions = {
    chart: { type, stacked, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: true, speed: 450 }, fontFamily: 'DM Sans, sans-serif', foreColor: '#87938e' },
    colors: series.map((entry) => entry.color ?? '#216b4e'),
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: type === 'bar' ? 0 : compact ? 2 : 2.5, lineCap: 'round' },
    fill: type === 'bar'
      ? { type: 'solid', opacity: 0.88 }
      : { type: 'gradient', gradient: { opacityFrom: 0.16, opacityTo: 0.015, stops: [0, 90, 100] } },
    ...(type === 'bar' ? { plotOptions: { bar: { columnWidth: '54%', borderRadius: 2 } } } : {}),
    grid: { borderColor: '#e9eeeb', strokeDashArray: 4, padding: { left: 8, right: 10, top: 0, bottom: 0 } },
    xaxis: { categories: labels, axisBorder: { show: false }, axisTicks: { show: false }, labels: { show: !compact, style: { fontSize: '10px', fontFamily: 'DM Mono, monospace' }, trim: true, hideOverlappingLabels: true } },
    yaxis: { show: !compact, labels: { style: { fontSize: '10px', fontFamily: 'DM Mono, monospace' }, formatter: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) } },
    tooltip: { theme: 'light', x: { show: true }, y: { formatter: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 }) } },
    legend: { show: false },
    markers: { size: 0, hover: { size: 4 } },
    ...(compact ? { grid: { show: false, padding: { left: 0, right: 0, top: 2, bottom: 0 } }, fill: { type: 'solid', opacity: 0.08 } } : {}),
  };
  return (
    <div data-testid="chart-infrastructure-trend" className={compact ? 'h-[72px] w-full' : 'h-[270px] w-full'}>
      <Chart
        options={options}
        series={series.map((entry) => ({ name: entry.name, data: entry.values }))}
        type={type}
        height="100%"
        width="100%"
      />
    </div>
  );
}
