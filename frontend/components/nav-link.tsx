import Link from "next/link";


type NavLinkProps = {
  href: string;
  label: string;
};

export function NavLink({ href, label }: NavLinkProps) {
  return <Link href={href}>{label}</Link>;
}
