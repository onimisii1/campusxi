// Event buttons per sport. Only types the server lists for the match are shown.

export type EventButton = { type: string; label: string; amount?: number; tone?: 'good' | 'bad' | 'neutral' }

const BUTTONS: Record<string, EventButton[]> = {
  football: [
    { type: 'goal', label: 'Goal', tone: 'good' },
    { type: 'assist', label: 'Assist', tone: 'good' },
    { type: 'save', label: 'Save', tone: 'good' },
    { type: 'penalty_save', label: 'Pen save', tone: 'good' },
    { type: 'yellow', label: 'Yellow', tone: 'bad' },
    { type: 'red', label: 'Red', tone: 'bad' },
    { type: 'own_goal', label: 'Own goal', tone: 'bad' },
    { type: 'penalty_miss', label: 'Pen miss', tone: 'bad' },
    { type: 'sub_on', label: 'Sub on', tone: 'neutral' },
    { type: 'sub_off', label: 'Sub off', tone: 'neutral' },
  ],
  basketball: [
    { type: 'point', label: '+1', amount: 1, tone: 'good' },
    { type: 'point', label: '+2', amount: 2, tone: 'good' },
    { type: 'point', label: '+3', amount: 3, tone: 'good' },
    { type: 'rebound', label: 'Rebound', tone: 'good' },
    { type: 'assist', label: 'Assist', tone: 'good' },
    { type: 'steal', label: 'Steal', tone: 'good' },
    { type: 'block', label: 'Block', tone: 'good' },
    { type: 'turnover', label: 'Turnover', tone: 'bad' },
    { type: 'sub_on', label: 'Sub on', tone: 'neutral' },
    { type: 'sub_off', label: 'Sub off', tone: 'neutral' },
  ],
  volleyball: [
    { type: 'kill', label: 'Kill', tone: 'good' },
    { type: 'ace', label: 'Ace', tone: 'good' },
    { type: 'block', label: 'Block', tone: 'good' },
    { type: 'dig', label: 'Dig', tone: 'good' },
    { type: 'set_assist', label: 'Set assist', tone: 'good' },
    { type: 'service_error', label: 'Serve error', tone: 'bad' },
    { type: 'attack_error', label: 'Attack error', tone: 'bad' },
    { type: 'sub_on', label: 'Sub on', tone: 'neutral' },
    { type: 'sub_off', label: 'Sub off', tone: 'neutral' },
  ],
}

export function buttonsFor(sport: string, allowed: string[]): EventButton[] {
  return (BUTTONS[sport] ?? []).filter((b) => allowed.includes(b.type))
}

export function eventLabel(type: string, amount: number): string {
  if (type === 'point') return `+${amount} pts`
  const all = Object.values(BUTTONS).flat()
  return all.find((b) => b.type === type)?.label ?? type.replace(/_/g, ' ')
}
