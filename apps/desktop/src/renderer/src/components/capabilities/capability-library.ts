import type {
  InstalledSkill,
  McpInstalledServer,
  McpRegistryServer,
  StoreSkill
} from '../../../../shared/runtime'

export function matchesCapability(query: string, ...values: string[]): boolean {
  const needle = query.trim().toLowerCase()
  return !needle || values.some((value) => value.toLowerCase().includes(needle))
}

export function filterInstalledSkills(skills: InstalledSkill[], query: string): InstalledSkill[] {
  return skills.filter((skill) =>
    matchesCapability(query, skill.name, skill.description, skill.source)
  )
}

export function filterStoreSkills(skills: StoreSkill[], query: string): StoreSkill[] {
  return skills.filter((skill) =>
    matchesCapability(query, skill.name, skill.description, skill.source, skill.repo)
  )
}

export function skillStoreSources(skills: StoreSkill[], configuredSources: string[]): string[] {
  const sources = new Set(configuredSources.filter(Boolean))
  for (const skill of skills) {
    if (skill.repo) sources.add(skill.repo)
  }
  return [...sources]
}

export function filterInstalledServers(
  servers: McpInstalledServer[],
  query: string
): McpInstalledServer[] {
  return servers.filter((server) => matchesCapability(query, server.name, server.id, server.status))
}

export function filterRegistryServers(
  servers: McpRegistryServer[],
  installed: McpInstalledServer[],
  query: string
): McpRegistryServer[] {
  const installedNames = new Set(installed.map((server) => server.name.toLowerCase()))
  return servers.filter(
    (server) =>
      !installedNames.has(server.name.toLowerCase()) &&
      matchesCapability(query, server.name, server.qualifiedName, server.description, server.author)
  )
}
