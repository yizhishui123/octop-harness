/** Slash-command catalogue rendered by the composer's command palette. */

export interface SlashCommand {
  name: string
  description: string
  /** Handled entirely in the frontend; otherwise sent as a normal message. */
  local: boolean
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: '/model', description: '选择模型（前端切换 activeModel）', local: true },
  { name: '/skills', description: '列出工作区已安装的 skills（由运行时拦截）', local: false },
  { name: '/stop', description: '停止当前运行 / 回复', local: false },
  { name: '/new', description: '新建会话', local: true },
  { name: '/clear', description: '清空当前会话的本地显示', local: true },
  { name: '/help', description: '显示可用命令', local: true },
]

export function filterCommands(input: string): SlashCommand[] {
  const query = input.startsWith('/') ? input.slice(1).toLowerCase() : input.toLowerCase()
  if (!query) return SLASH_COMMANDS
  return SLASH_COMMANDS.filter((command) => command.name.slice(1).startsWith(query))
}

export const HELP_TEXT = [
  '可用命令：',
  ...SLASH_COMMANDS.map((command) => `  ${command.name.padEnd(9)}${command.description}`),
].join('\n')
