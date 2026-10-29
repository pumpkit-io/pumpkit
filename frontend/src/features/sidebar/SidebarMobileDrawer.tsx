import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useSidebar } from './useSidebar';
import { Sidebar } from './Sidebar';
import { track } from '@/lib/analytics';

export function SidebarMobileDrawer() {
  const { mobileOpen, setMobileOpen } = useSidebar();
  const { pathname } = useLocation();
  const prevOpenRef = useRef(false);
  const closeViaBackdropRef = useRef(false);
  const drawerRef = useRef<HTMLElement>(null);

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

  // A page change from outside the drawer, such as the New Post shortcut, closes it too.
  useEffect(() => setMobileOpen(false), [pathname, setMobileOpen]);

  useEffect(() => {
    if (mobileOpen) drawerRef.current?.querySelector<HTMLElement>('a[href]')?.focus();
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
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Sidebar"
            className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] md:hidden"
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            <Sidebar />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
