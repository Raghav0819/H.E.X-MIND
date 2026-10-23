import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  children?: ReactNode
}

export function EmptyState({ title, children }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <p className="empty-state__title">{title}</p>
      {children && <div className="empty-state__body">{children}</div>}
    </div>
  )
}

interface PanelHeaderProps {
  title: string
  actions?: ReactNode
}

export function PanelHeader({ title, actions }: PanelHeaderProps) {
  return (
    <div className="panel-header">
      <span className="panel-header__title">{title}</span>
      {actions && <div className="panel-header__actions">{actions}</div>}
    </div>
  )
}
