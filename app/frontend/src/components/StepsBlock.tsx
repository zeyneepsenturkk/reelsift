import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { splitStepDetail } from '../lib/format.ts'
import { EASE } from '../lib/motion.ts'
import type { TimelineItem } from '../state/chatReducer.ts'

function useElapsedSeconds(startedAt: number | null, running: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000))
}

function StepRow({ item, animate }: { item: TimelineItem; animate: boolean }) {
  const enter = { initial: animate ? { opacity: 0, y: 8 } : false, animate: { opacity: 1, y: 0 } } as const
  const transition = { duration: 0.35, ease: EASE }

  if (item.kind === 'notice') {
    return (
      <motion.div className="step notice" {...enter} transition={transition}>
        {item.text}
      </motion.div>
    )
  }
  const { step } = item
  const text = splitStepDetail(step.detail, step.count, step.title)
  return (
    <motion.div className={`step ${step.status}`} {...enter} transition={transition}>
      {step.status === 'done' ? (
        // Çalışırken görünen metin kesin haline yumuşak geçer.
        <motion.span
          key="done"
          initial={animate ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, ease: EASE }}
        >
          <b>{step.title}</b> {text.lead}
          {text.count !== null && <span className="n">{text.count}</span>}
          {text.rest}
        </motion.span>
      ) : (
        <span key={step.status}>{step.status === 'running' ? `${step.title}…` : step.title}</span>
      )}
    </motion.div>
  )
}

type Props = {
  timeline: TimelineItem[]
  running: boolean
  startedAt: number | null
  // Bitmiş mesajda gösterilecek süre (sn); bilinmiyorsa başlıkta süre yazılmaz.
  finalSeconds: number | null
  animate: boolean
}

export function StepsBlock({ timeline, running, startedAt, finalSeconds, animate }: Props) {
  const elapsed = useElapsedSeconds(startedAt, running)
  const seconds = running ? elapsed : finalSeconds
  const label = running ? 'arşivi tarıyorum' : 'nasıl buldum'
  return (
    <>
      <div className="steps-head">
        <span className={`dot${running ? ' live' : ''}`} />
        <span className="label">{seconds === null ? label : `${label} · ${seconds} sn`}</span>
      </div>
      {timeline.length > 0 && (
        <div className="steps">
          {timeline.map((item, index) => (
            <StepRow key={index} item={item} animate={animate} />
          ))}
        </div>
      )}
    </>
  )
}
