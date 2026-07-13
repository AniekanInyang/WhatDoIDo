type PageHeaderProps = {
  eyebrow: string;
  title: string;
  subtitle?: string;
};

export function PageHeader({ eyebrow, title, subtitle }: PageHeaderProps) {
  return (
    <div className="surface-card mb-4 p-5 text-center">
      <p className="text-[11px] uppercase tracking-[0.18em] text-brand-muted">{eyebrow}</p>
      <h2 className="headline mt-1 text-2xl font-semibold text-brand-text">{title}</h2>
      {subtitle ? <p className="mx-auto mt-1 max-w-2xl text-sm text-brand-muted">{subtitle}</p> : null}
    </div>
  );
}
