export const primaryNavigation = [
  { href: "/", label: "Accueil", icon: "home", paths: ["/"] },
  { href: "/projects", label: "Projets", icon: "projects", paths: ["/projects", "/tasks"] },
  { href: "/control", label: "Centre de contrôle", icon: "control", paths: ["/control", "/operator", "/activity"] },
  { href: "/environments", label: "Environnements", icon: "environments", paths: ["/environments"] },
  { href: "/settings", label: "Paramètres", icon: "settings", paths: ["/settings"] },
] as const;

export type NavigationIcon = (typeof primaryNavigation)[number]["icon"];

export function sectionForPath(pathname: string): (typeof primaryNavigation)[number]["href"] | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  const section = primaryNavigation.find((item) =>
    item.paths.some((prefix) => prefix === "/" ? path === "/" : path === prefix || path.startsWith(prefix + "/")),
  );
  return section?.href ?? null;
}
