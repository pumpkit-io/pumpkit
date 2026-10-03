import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSidebar } from './useSidebar';
import { Sidebar } from './Sidebar';
import { track } from '@/lib/analytics';

export function SidebarMobileDrawer() {
  const { mobileOpen, setMobileOpen } = useSidebar();
  const prevOpenRef = useRef(false);
  const closeViaBackdropRef = useRef(false);

  useEffect(() => {
    if (mobileOpen && !prevOpenRef.current) {
      track('sidebar_mobile_drawer_opened');
    } else if (!mobileOpen && prevOpenRef.current) {
      track('sidebar_mobile_drawer_closed', {
        via_backdrop: closeViaBackdropRef.current,
      });
      closeViaBackdropRef.current = false;
    }
    prevOpenRef.current = mobileOpen;
  }, [mobileOpen]);

  return (
    <AnimatePresence>
      {mobileOpen && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/60 md:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={() => {
              closeViaBackdropRef.current = true;
              setMobileOpen(false);
            }}
          />
          <motion.aside
            className="fixed inset-y-0 left-0 z-50 w-72 md:hidden"
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            <Sidebar forceExpanded />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
