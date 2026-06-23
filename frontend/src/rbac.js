export function normalizeRole(role) {
  const normalized = String(role || "").trim().toLowerCase();
  if (["super_admin", "platform_admin", "system_admin"].includes(normalized)) return "super_admin";
  if (["department_admin", "tenant_admin", "admin", "owner"].includes(normalized)) return "department_admin";
  if (["team_lead", "lead"].includes(normalized)) return "team_lead";
  if (["account_manager", "manager", "member", "staff", "customer", "viewer"].includes(normalized)) return "account_manager";
  return "account_manager";
}

export function canManageAdminSurfaces(user) {
  const role = normalizeRole(user?.role);
  return role === "super_admin" || role === "department_admin";
}

export function roleLabel(role) {
  const normalized = normalizeRole(role);
  if (normalized === "super_admin") return "Super Admin";
  if (normalized === "department_admin") return "Department Admin";
  if (normalized === "team_lead") return "Team Lead";
  return "Account Manager";
}
