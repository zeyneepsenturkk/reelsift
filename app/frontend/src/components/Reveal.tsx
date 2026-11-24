import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { EASE, staggerDelay } from '../lib/motion.ts'

// Liste öğesi ilk çizimde aşağıdan hafifçe kayarak belirir; öğeler 30 ms arayla sıralanır.
export function Reveal({ index = 0, children }: { index?: number; children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE, delay: staggerDelay(index) }}
    >
      {children}
    </motion.div>
  )
}
