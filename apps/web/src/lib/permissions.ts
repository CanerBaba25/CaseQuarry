const permissions: Record<string, readonly string[]> = {
  import: ["matter_lead", "attorney", "review_manager"],
  review: ["matter_lead", "attorney", "review_manager", "reviewer"],
  privilege: ["matter_lead", "attorney"],
  manage: ["matter_lead", "review_manager"],
  export: ["matter_lead", "attorney", "review_manager"],
  hold: ["matter_lead", "attorney"],
  audit: ["matter_lead", "attorney", "review_manager", "auditor"],
};

export function can(role: string, action: string): boolean {
  return Boolean(permissions[action]?.includes(role));
}

export function canCreateMatter(role: string): boolean {
  return ["firm_admin", "attorney", "review_manager"].includes(role);
}
