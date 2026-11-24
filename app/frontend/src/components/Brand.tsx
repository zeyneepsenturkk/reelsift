export function Brand({ big = false, className = '' }: { big?: boolean; className?: string }) {
  return (
    <div className={`brand${big ? ' big' : ''} ${className}`.trim()}>
      Reel<i>Sift</i>
    </div>
  )
}
