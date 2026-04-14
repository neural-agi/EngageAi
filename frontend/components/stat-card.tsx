type StatCardProps = {
  label: string;
  value: string;
  description: string;
};

export function StatCard({ label, value, description }: StatCardProps) {
  return (
    <article>
      <h2>{label}</h2>
      <p>{value}</p>
      <p>{description}</p>
    </article>
  );
}
