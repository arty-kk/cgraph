// Shared tailwind class-name constants for the projects sidebar + manage panel.
export const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
export const controlDisabled = 'disabled:opacity-50'
export const controlClass = `${controlBase} ${controlDisabled}`
export const labelRowClass = 'flex items-center gap-2 leading-none'
export const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'

export const controlSmBase = 'h-9 rounded-md bg-neutral-900 border border-neutral-800 text-sm outline-none disabled:opacity-50'
export const inputSmClass = `w-full ${controlSmBase} px-3`
export const inputSmFlexClass = `flex-1 ${controlSmBase} px-3`
export const selectSmFlexClass = `min-w-0 flex-1 ${controlSmBase} px-2`

export const buttonBase = 'h-9 rounded-md border border-neutral-800 px-3 text-sm font-semibold disabled:opacity-50'
export const buttonNeutral = `${buttonBase} bg-neutral-900 hover:bg-neutral-800`
export const buttonSoft = `${buttonBase} bg-neutral-800 hover:bg-neutral-700 border-neutral-800`
export const buttonDanger = 'h-9 rounded-md bg-neutral-900 hover:bg-red-950 border border-neutral-800 hover:border-red-800 px-3 text-sm font-semibold disabled:opacity-50'
export const buttonPrimary = 'h-9 rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 text-sm font-semibold disabled:opacity-50'
export const miniButtonClass = 'h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2.5 text-[11px] font-semibold disabled:opacity-50'
  
export const tabBase = 'flex-1 h-9 rounded-md border px-3 text-sm font-semibold transition-colors disabled:opacity-50'
export const tabActive = 'bg-neutral-900 border-neutral-700'
export const tabIdle = 'bg-neutral-950 border-neutral-900 hover:border-neutral-700'

export const loadingCardBase = 'rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-400'
export const loadingCardPulse = `${loadingCardBase} animate-pulse`
export const searchResultRowClass = 'text-left text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 hover:border-neutral-700 disabled:opacity-50'
export const confirmDangerClass = 'h-9 rounded-md bg-red-700 hover:bg-red-600 px-3 text-sm font-semibold disabled:opacity-50'
export const confirmCancelClass = 'h-9 rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 text-sm font-semibold disabled:opacity-50'
